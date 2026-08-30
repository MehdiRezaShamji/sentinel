import copy
import os
import threading
import time
from datetime import datetime, timezone, timedelta

from app.services.fortyguard import get_environmental_data
from app.telegram import send_telegram_message

# ---------------------------------------------------------------------------
# Monitoring configuration
# ---------------------------------------------------------------------------

# Local monitoring remains responsive without making external API calls.
POLL_SECONDS = 10

# FortyGuard is refreshed periodically rather than every monitoring cycle.
# Default: 4 hours.
FORTYGUARD_REFRESH_SECONDS = int(os.getenv("FORTYGUARD_REFRESH_SECONDS", "14400"))

MAX_ACTIONS = 50

# Existing risk policy from the Sentinel prototype.
HIGH_RISK_HEAT_INDEX_C = 35
HIGH_RISK_EXPOSURE_MINUTES = 45

# Configurable check-in response timeout (default 300s / 5 minutes)
def _get_checkin_timeout() -> int:
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    return 20 if demo_mode else int(os.getenv("CHECKIN_TIMEOUT_SECONDS", "300"))

CHECKIN_TIMEOUT_SECONDS = _get_checkin_timeout()

SUPERVISOR_PHONE = os.getenv("SUPERVISOR_PHONE", "+15550000999")

def _send_msg(to: str, message: str) -> dict:
    return send_telegram_message(to, message)

def _get_worker_telegram_destination(worker: dict) -> str:
    """
    Return the correct Telegram destination for a worker.
    Prefers telegram_chat_id (real numeric chat ID) over phone (which may be
    a phone number for simulated actors, routed through [DEMO TELEGRAM]).
    """
    chat_id = worker.get("telegram_chat_id")
    if chat_id:
        return str(chat_id).strip()
    return worker.get("phone", "")

# ---------------------------------------------------------------------------
# Global monitoring state
# ---------------------------------------------------------------------------

monitoring_active = False
monitoring_thread = None
monitoring_state = None

state_lock = threading.Lock()
monitoring_stop_event = threading.Event()

# Emergency response toggle (demonstration purposes only)
emergency_response_enabled = False

# Lock and active flag for the FortyGuard async refresh worker
refresh_thread_active = False
refresh_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_timestamp() -> str:
    return _utc_now().isoformat()


def deduplicate_workers(
    workers: list[dict],
) -> list[dict]:
    """
    Keep exactly one state entry per worker ID.
    """
    unique = {}

    for worker in workers:
        worker_id = worker.get("id")

        if worker_id is None:
            continue

        unique[worker_id] = worker

    return list(unique.values())


def _cap_actions(
    actions: list[str],
    limit: int = MAX_ACTIONS,
) -> list[str]:
    return actions[-limit:]


def _fallback_environment(
    state: dict,
    reason: str,
) -> dict:
    """
    Keep the demo operational if FortyGuard temporarily fails.
    """
    temperature = state.get(
        "temperature",
        32.5,
    )

    return {
        "latitude": state["latitude"],
        "longitude": state["longitude"],
        "temperature_c": temperature,
        "heat_index_c": max(
            temperature + 4.3,
            36.8,
        ),
        "apparent_temperature_c": None,
        "humidity_percent": None,
        "wet_bulb_c": None,
        "precipitation_mm": None,
        "cloud_cover_octas": None,
        "air_quality_index": None,
        "solar_irradiance": {
            "ghi": None,
            "dni": None,
            "dhi": None,
        },
        "metadata": {
            "source": "fallback_demo",
            "reason": reason,
        },
    }


def _clean_state(
    state: dict,
) -> dict:
    """
    Normalize monitoring state without invoking LangGraph.
    """
    cleaned = copy.deepcopy(state)

    cleaned["workers"] = deduplicate_workers(cleaned.get("workers", []))

    cleaned["incidents"] = list(cleaned.get("incidents", []))

    cleaned["agent_actions"] = _cap_actions(list(cleaned.get("agent_actions", [])))

    # The autonomous monitor no longer uses graph pending actions.
    cleaned["pending_actions"] = []

    cleaned.setdefault(
        "environment",
        {},
    )

    cleaned.setdefault(
        "current_step",
        "starting",
    )

    cleaned.setdefault(
        "monitoring_active",
        False,
    )

    cleaned.setdefault(
        "environment_last_updated",
        None,
    )

    cleaned.setdefault(
        "environment_refresh_interval_seconds",
        FORTYGUARD_REFRESH_SECONDS,
    )

    cleaned.setdefault(
        "environment_next_refresh",
        None,
    )
    
    cleaned["emergency_response_enabled"] = emergency_response_enabled

    return cleaned


def _append_action(
    state: dict,
    message: str,
) -> None:
    """
    Add an activity-log entry only if the exact message is not
    already present in the current action history.
    """
    actions = list(state.get("agent_actions", []))

    if message not in actions:
        actions.append(message)

    state["agent_actions"] = _cap_actions(actions)


def _async_refresh_worker(state_copy: dict):
    """
    Thread function that polls FortyGuard synchronously.
    Once finished, it updates the global monitoring state thread-safely.
    """
    global monitoring_state
    global refresh_thread_active

    print("[FORTYGUARD] Refresh thread started")
    
    try:
        latitude = state_copy["latitude"]
        longitude = state_copy["longitude"]
        temperature = state_copy.get("temperature", 32.5)

        environment = get_environmental_data(
            latitude=latitude,
            longitude=longitude,
            temperature=temperature,
        )

        with state_lock:
            if monitoring_state is not None:
                monitoring_state["environment"] = environment
                monitoring_state["environment_last_updated"] = _utc_timestamp()
                monitoring_state["environment_next_refresh"] = (
                    _utc_now() + timedelta(seconds=FORTYGUARD_REFRESH_SECONDS)
                ).isoformat()

                fortyguard_temperature = environment.get("temperature_c")
                if fortyguard_temperature is not None:
                    monitoring_state["temperature"] = fortyguard_temperature

                monitoring_state["current_step"] = "environment_refreshed"
                
                _append_action(
                    monitoring_state,
                    (
                        "FortyGuard environment refreshed "
                        f"({FORTYGUARD_REFRESH_SECONDS // 3600}h interval)"
                    ),
                )
                print("[FORTYGUARD] Environment refreshed successfully")

    except Exception as exc:
        print(f"[FORTYGUARD] Refresh thread failed: {exc}")
        with state_lock:
            if monitoring_state is not None:
                current_env = monitoring_state.get("environment", {})
                has_valid_env = bool(current_env) and current_env.get("metadata", {}).get("source") != "fallback_demo"

                if not has_valid_env:
                    # Initial refresh failed. Set environment to a fallback but do not treat as valid for risk evaluation.
                    monitoring_state["environment"] = _fallback_environment(
                        monitoring_state,
                        str(exc),
                    )
                    monitoring_state["current_step"] = "environment_refresh_failed"
                    _append_action(
                        monitoring_state,
                        f"FortyGuard initial refresh failed: {exc}",
                    )
                else:
                    # Preserving existing valid environment on failure.
                    monitoring_state["current_step"] = "environment_refresh_failed"
                    _append_action(
                        monitoring_state,
                        f"FortyGuard refresh failed; using last known environment: {exc}",
                    )

                monitoring_state["environment_last_updated"] = (
                    monitoring_state.get("environment_last_updated") or _utc_timestamp()
                )
                monitoring_state["environment_next_refresh"] = (
                    _utc_now() + timedelta(seconds=FORTYGUARD_REFRESH_SECONDS)
                ).isoformat()
    finally:
        with refresh_lock:
            refresh_thread_active = False


def _start_async_refresh(state: dict) -> None:
    """
    Start FortyGuard environment refresh in a separate daemon thread
    to prevent blocking local monitoring cycles.
    """
    global refresh_thread_active

    with refresh_lock:
        if refresh_thread_active:
            print("[FORTYGUARD] Refresh already in progress; skipping trigger")
            return
        refresh_thread_active = True

    print("[FORTYGUARD] Triggering environment refresh asynchronously")
    state_copy = copy.deepcopy(state)
    thread = threading.Thread(
        target=_async_refresh_worker,
        args=(state_copy,),
        daemon=True,
        name="fortyguard-refresh-worker",
    )
    thread.start()


def _environment_refresh_due(
    state: dict,
) -> bool:
    """
    Determine whether the periodic FortyGuard refresh is due.
    """
    last_updated = state.get("environment_last_updated")

    if not last_updated:
        return True

    try:
        last_refresh = datetime.fromisoformat(last_updated)

        if last_refresh.tzinfo is None:
            last_refresh = last_refresh.replace(tzinfo=timezone.utc)

        elapsed = (_utc_now() - last_refresh).total_seconds()

        return elapsed >= FORTYGUARD_REFRESH_SECONDS

    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Local worker monitoring and timeout tracking
# ---------------------------------------------------------------------------


def _assess_workers_locally(
    state: dict,
) -> dict:
    """
    Evaluate workers locally using cached environmental data.
    If workers are high risk and working, transitions their status to high_risk.
    """
    workers = state.get("workers", [])
    environment = state.get("environment", {})

    # Check if we have valid environmental data (i.e. not empty and not fallback)
    has_valid_env = bool(environment) and environment.get("metadata", {}).get("source") != "fallback_demo"

    if not has_valid_env:
        # DO NOT evaluate worker environmental risk until valid environmental data exists.
        return state

    heat_index = environment.get("heat_index_c")
    if heat_index is None:
        heat_index = state.get("temperature")

    if heat_index is None:
        return state

    is_env_high_risk = heat_index >= HIGH_RISK_HEAT_INDEX_C

    for worker in workers:
        worker_high_risk_condition = (
            is_env_high_risk
            and worker.get("exposure_minutes", 0) >= HIGH_RISK_EXPOSURE_MINUTES
        )

        # If the continuous high risk condition is resolved, reset check-in state
        if not worker_high_risk_condition:
            if worker.get("check_in_status") == "confirmed":
                worker["check_in_status"] = None
                worker["check_in_sent_at"] = None

        # Evaluate only workers currently in normal working status
        if worker.get("status") != "working":
            continue

        # If they already confirmed safety for this continuous high risk condition, keep them working
        if worker.get("check_in_status") == "confirmed":
            continue

        if worker_high_risk_condition:
            worker["status"] = "high_risk"
            message = f"High environmental exposure detected for {worker['name']}"
            _append_action(state, message)

    return state


def _check_timeouts_locally(
    state: dict,
) -> dict:
    """
    Deterministic state machine updates:
    - Send SMS check-ins to high-risk workers.
    - Check for check-in response timeouts (300 seconds default).
    - Send buddy notifications on timeout.
    """
    workers = state.get("workers", [])
    incidents = state.get("incidents", [])
    now = _utc_now()

    for worker in workers:
        # A. Trigger worker safety check-in if high risk
        if worker.get("status") == "high_risk":
            if worker.get("check_in_status") not in ("pending", "confirmed"):
                worker["status"] = "awaiting_checkin"
                worker["check_in_status"] = "pending"
                worker["check_in_sent_at"] = _utc_timestamp()
                
                check_in_msg = "Sentinel safety check-in: Are you safe? Reply SAFE or NOT SAFE."
                send_result = _send_msg(_get_worker_telegram_destination(worker), check_in_msg)

                # Only report success if Telegram actually confirmed delivery.
                if send_result.get("success"):
                    _append_action(
                        state,
                        f"[TELEGRAM] Sentinel safety check-in sent to {worker['name']}."
                    )
                else:
                    _append_action(
                        state,
                        f"[TELEGRAM ERROR] Failed to send safety check-in to {worker['name']}: "
                        f"{send_result.get('error', 'unknown error')}"
                    )

        # B. Check for check-in response timeout
        elif worker.get("status") == "awaiting_checkin" and worker.get("check_in_status") == "pending":
            sent_at_value = worker.get("check_in_sent_at")
            if sent_at_value:
                try:
                    sent_at = datetime.fromisoformat(sent_at_value)
                    if sent_at.tzinfo is None:
                        sent_at = sent_at.replace(tzinfo=timezone.utc)

                    elapsed_seconds = (now - sent_at).total_seconds()
                    timeout_seconds = worker.get("check_in_timeout_seconds")
                    if timeout_seconds is None:
                        timeout_seconds = _get_checkin_timeout()

                    if elapsed_seconds >= timeout_seconds:
                        worker["status"] = "unresponsive"
                        worker["check_in_status"] = "timed_out"
                        
                        _append_action(
                            state,
                            f"[CHECK-IN] Worker {worker['name']} check-in timed out."
                        )

                        # Find buddy and notify
                        buddy = next((w for w in workers if w["id"] == worker.get("buddy_id")), None)
                        if buddy:
                            worker["buddy_verification_status"] = "pending"
                            worker["buddy_notified_at"] = _utc_timestamp()

                            buddy_msg = (
                                f"Sentinel alert: {worker['name']} has not responded to a safety check-in. "
                                f"Please check on {worker['name']} and reply SAFE or NOT SAFE."
                            )
                            send_result = _send_msg(_get_worker_telegram_destination(buddy), buddy_msg)

                            if send_result.get("success"):
                                _append_action(
                                    state,
                                    f"[TELEGRAM] Buddy verification alert sent to {buddy['name']} for {worker['name']}."
                                )
                            else:
                                _append_action(
                                    state,
                                    f"[TELEGRAM ERROR] Failed to send buddy verification alert to {buddy['name']} "
                                    f"for {worker['name']}: {send_result.get('error', 'unknown error')}"
                                )
                        else:
                            # Direct supervisor escalation fallback if no buddy is found
                            worker["buddy_verification_status"] = "no_buddy"
                            worker["status"] = "supervisor_notified"
                            
                            _append_action(
                                state,
                                f"[TELEGRAM] Warning: No buddy found for {worker['name']}. Escalating directly."
                            )

                            # Create Incident if one doesn't exist
                            active_incident = next(
                                (inc for inc in incidents if inc["worker_id"] == worker["id"] and inc["status"] != "resolved"),
                                None
                            )
                            incident_id = ""
                            if not active_incident:
                                incident_id = f"INC-{len(incidents) + 1:03d}"
                                new_incident = {
                                    "id": incident_id,
                                    "worker_id": worker["id"],
                                    "type": "environmental_safety",
                                    "status": "active",
                                    "actions_taken": ["No buddy configured for unresponsive worker"]
                                }
                                incidents.append(new_incident)
                                _append_action(state, f"[INCIDENT] Created {incident_id} for {worker['name']}.")
                            else:
                                incident_id = active_incident["id"]

                            # Escalate incident
                            for inc in incidents:
                                if inc["id"] == incident_id:
                                    if inc["status"] == "active":
                                        inc["status"] = "escalated_supervisor"
                                        inc["actions_taken"].append("Escalated to supervisor")
                                        _append_action(state, f"[INCIDENT] Escalated {incident_id} to supervisor.")

                            # Notify supervisor
                            supervisor_msg = (
                                f"SENTINEL ALERT: {worker['name']} has not responded to a safety check-in. "
                                f"Buddy verification unavailable. Incident {incident_id}."
                            )
                            send_result = _send_msg(SUPERVISOR_PHONE, supervisor_msg)

                            if send_result.get("success"):
                                _append_action(
                                    state,
                                    f"[TELEGRAM] Supervisor notified for {worker['name']}. Incident {incident_id}."
                                )
                            else:
                                _append_action(
                                    state,
                                    f"[TELEGRAM ERROR] Failed to notify supervisor for {worker['name']}. "
                                    f"Incident {incident_id}: {send_result.get('error', 'unknown error')}"
                                )

                            # Emergency action
                            if emergency_response_enabled:
                                _append_action(state, "[EMERGENCY DEMO] Emergency response initiated — DEMO")

                except Exception as ex:
                    print(f"[TIMEOUT CHECK ERROR] {ex}")

    return state


def _run_local_monitoring_cycle(
    state: dict,
) -> dict:
    """
    One cheap local monitoring cycle.
    """
    state = _clean_state(state)

    # 1. Trigger environmental intelligence refresh asynchronously when due
    if _environment_refresh_due(state):
        _start_async_refresh(state)

    # 2. Evaluate workers using cached environmental data
    state = _assess_workers_locally(state)

    # 3. Check timeouts and trigger buddy notifications
    state = _check_timeouts_locally(state)

    state["monitoring_active"] = True
    return state


def _get_poll_seconds() -> int:
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    return 1 if demo_mode else 10


def monitoring_loop():
    """
    Autonomous Sentinel monitoring loop.
    Runs every _get_poll_seconds(), executing only local evaluations.
    """
    global monitoring_active
    global monitoring_thread
    global monitoring_state

    print("[SENTINEL MONITOR] Monitoring loop started")

    try:
        while not monitoring_stop_event.is_set():
            with state_lock:
                if not monitoring_active:
                    break

            # Poll and process Telegram safety replies autonomously before cycle evaluation.
            try:
                from app.telegram import process_telegram_replies
                process_telegram_replies()
            except Exception as tg_err:
                print(f"[SENTINEL MONITOR] Error processing Telegram replies: {tg_err}")

            if monitoring_stop_event.is_set():
                break

            with state_lock:
                if not monitoring_active:
                    break
                state = copy.deepcopy(monitoring_state)

            if state is None:
                monitoring_stop_event.wait(_get_poll_seconds())
                continue

            try:
                result = _run_local_monitoring_cycle(state)

                if monitoring_stop_event.is_set():
                    break

                with state_lock:
                    if monitoring_active:
                        monitoring_state = _clean_state(result)

                print(
                    "[SENTINEL MONITOR] "
                    "Local monitoring cycle completed "
                    f"({len(result['workers'])} workers, "
                    f"{len(result['incidents'])} incidents)"
                )

            except Exception as exc:
                if monitoring_stop_event.is_set():
                    break
                with state_lock:
                    if monitoring_active:
                        monitoring_state = _clean_state(state)
                        _append_action(
                            monitoring_state,
                            f"Monitoring error: {exc}",
                        )
                print("[SENTINEL MONITOR] Error: f{exc}")

            monitoring_stop_event.wait(_get_poll_seconds())
    finally:
        with state_lock:
            # Clean up the thread reference if it is still pointing to us
            if threading.current_thread() == monitoring_thread:
                monitoring_thread = None
                monitoring_active = False
        print("[SENTINEL MONITOR] Monitoring loop stopped")


# ---------------------------------------------------------------------------
# Public monitoring API
# ---------------------------------------------------------------------------


def start_monitoring(
    initial_state: dict | None = None,
):
    """
    Start autonomous Sentinel monitoring.
    Idempotent.
    """
    global monitoring_active
    global monitoring_thread
    global monitoring_state

    with state_lock:
        if monitoring_active:
            # Already active. If a new initial state is passed, reset state.
            if initial_state is not None:
                monitoring_state = _clean_state(initial_state)
                monitoring_state["monitoring_active"] = True
                monitoring_state["environment_last_updated"] = None
                monitoring_state["environment_next_refresh"] = None
                monitoring_state["emergency_response_enabled"] = emergency_response_enabled
            return {
                "active": True,
                "refresh_interval_seconds": FORTYGUARD_REFRESH_SECONDS,
                "message": "Monitoring already active."
            }

    # Join any active thread to prevent duplicates
    thread_to_join = None
    with state_lock:
        if monitoring_thread is not None and monitoring_thread.is_alive():
            monitoring_stop_event.set()
            thread_to_join = monitoring_thread

    if thread_to_join and thread_to_join is not threading.current_thread():
        thread_to_join.join()

    with state_lock:
        if monitoring_active:
            return {
                "active": True,
                "refresh_interval_seconds": FORTYGUARD_REFRESH_SECONDS,
                "message": "Monitoring already active."
            }

        if initial_state is not None:
            monitoring_state = _clean_state(initial_state)
            monitoring_state["emergency_response_enabled"] = emergency_response_enabled

        if monitoring_state is None:
            raise RuntimeError("Cannot start monitoring without an initial state.")

        monitoring_stop_event.clear()
        monitoring_active = True
        monitoring_state["monitoring_active"] = True
        monitoring_state["current_step"] = "starting"
        monitoring_state["environment_last_updated"] = None
        monitoring_state["environment_next_refresh"] = None

        monitoring_thread = threading.Thread(
            target=monitoring_loop,
            daemon=True,
            name="sentinel-monitor",
        )
        monitoring_thread.start()

    return {
        "active": True,
        "refresh_interval_seconds": FORTYGUARD_REFRESH_SECONDS,
    }


def stop_monitoring():
    """
    Stop the local monitoring loop.
    """
    global monitoring_active
    global monitoring_thread

    monitoring_stop_event.set()

    thread_to_join = None
    with state_lock:
        monitoring_active = False

        if monitoring_state is not None:
            monitoring_state["monitoring_active"] = False
            monitoring_state["current_step"] = "stopped"

        thread_to_join = monitoring_thread

    if thread_to_join and thread_to_join.is_alive() and thread_to_join is not threading.current_thread():
        thread_to_join.join()

    return {"active": False}


def get_monitoring_status():
    """
    Return a snapshot of the current monitoring state.
    """
    with state_lock:
        return {
            "active": monitoring_active,
            "state": copy.deepcopy(monitoring_state),
        }


def reset_monitoring_state(base_state: dict) -> dict:
    """
    Reset monitoring state to the base demo state.
    """
    global monitoring_state
    global refresh_thread_active
    global emergency_response_enabled
    
    stop_monitoring()

    with refresh_lock:
        refresh_thread_active = False

    with state_lock:
        emergency_response_enabled = False
        monitoring_state = copy.deepcopy(base_state)
        monitoring_state["emergency_response_enabled"] = False
        _append_action(monitoring_state, "Sentinel monitoring state reset.")
        return {
            "status": "success",
            "message": "Monitoring state reset successfully.",
            "state": copy.deepcopy(monitoring_state),
        }


def set_emergency_response(enabled: bool) -> dict:
    """
    Toggle simulated emergency dispatch actions on incident escalation.
    """
    global emergency_response_enabled
    global monitoring_state
    
    emergency_response_enabled = enabled
    with state_lock:
        if monitoring_state is not None:
            monitoring_state["emergency_response_enabled"] = enabled
            _append_action(
                monitoring_state,
                f"Emergency response toggled {'ON' if enabled else 'OFF'}."
            )
            
    print(f"[SENTINEL] Emergency response set to: {enabled}")
    return {
        "status": "success",
        "emergency_response_enabled": enabled,
    }


def get_emergency_response() -> bool:
    """
    Get current emergency response toggle state.
    """
    return emergency_response_enabled


def handle_sms_response(sender: str, body: str) -> dict:
    """
    Receive, normalize, and process SMS updates from workers or buddies.
    """
    global monitoring_state
    normalized_body = body.strip().upper()
    normalized_sender = sender.strip()

    print(f"[TELEGRAM] Received message from '{normalized_sender}': '{normalized_body}'")

    with state_lock:
        if monitoring_state is None:
            return {"success": False, "message": "Sentinel monitoring is currently inactive."}

        workers = monitoring_state.get("workers", [])
        incidents = monitoring_state.get("incidents", [])

        # 1. Identify if sender is a worker replying to safety check-in
        for worker in workers:
            # Match on telegram_chat_id first (real Telegram user), then fall back to phone
            worker_dest = _get_worker_telegram_destination(worker)
            if worker_dest == normalized_sender:
                if worker.get("status") == "awaiting_checkin" and worker.get("check_in_status") == "pending":
                    if normalized_body in ("OK", "SAFE"):
                        worker["status"] = "working"
                        worker["check_in_status"] = "confirmed"
                        worker["check_in_response"] = normalized_body
                        worker["check_in_completed_at"] = _utc_timestamp()
                        worker["buddy_verification_status"] = None
                        
                        _append_action(
                            monitoring_state,
                            f"[CHECK-IN] {worker['name']} confirmed safety."
                        )
                        return {
                            "success": True,
                            "message": f"Sentinel: Safety confirmed for {worker['name']}. Stay safe!"
                        }
                    elif normalized_body == "NOT SAFE":
                        worker["status"] = "supervisor_notified"
                        worker["check_in_status"] = "not_safe"
                        worker["check_in_response"] = "NOT SAFE"
                        worker["check_in_completed_at"] = _utc_timestamp()
                        
                        _append_action(
                            monitoring_state,
                            f"[CHECK-IN] Worker {worker['name']} reported NOT SAFE."
                        )

                        # Create Incident if one doesn't exist
                        active_incident = next(
                            (inc for inc in incidents if inc["worker_id"] == worker["id"] and inc["status"] != "resolved"),
                            None
                        )
                        incident_id = ""
                        if not active_incident:
                            incident_id = f"INC-{len(incidents) + 1:03d}"
                            new_incident = {
                                "id": incident_id,
                                "worker_id": worker["id"],
                                "type": "environmental_safety",
                                "status": "active",
                                "actions_taken": ["Reported not safe by worker"]
                            }
                            incidents.append(new_incident)
                            _append_action(
                                monitoring_state,
                                f"[INCIDENT] Created safety incident {incident_id} for {worker['name']}."
                            )
                        else:
                            incident_id = active_incident["id"]

                        # Escalate incident
                        for inc in incidents:
                            if inc["id"] == incident_id:
                                if inc["status"] == "active":
                                    inc["status"] = "escalated_supervisor"
                                    inc["actions_taken"].append("Escalated to supervisor")
                                    _append_action(
                                        monitoring_state,
                                        f"[INCIDENT] Escalated {incident_id} to supervisor."
                                    )

                        # Notify supervisor
                        supervisor_msg = (
                            f"SENTINEL ALERT: Worker {worker['name']} reported NOT SAFE in response to a safety check-in. "
                            f"Incident {incident_id}."
                        )
                        send_result = _send_msg(SUPERVISOR_PHONE, supervisor_msg)

                        if send_result.get("success"):
                            _append_action(
                                monitoring_state,
                                f"[TELEGRAM] Supervisor notified for {worker['name']}. Incident {incident_id}."
                            )
                        else:
                            _append_action(
                                monitoring_state,
                                f"[TELEGRAM ERROR] Failed to notify supervisor for {worker['name']}. "
                                f"Incident {incident_id}: {send_result.get('error', 'unknown error')}"
                            )

                        # Simulated Emergency Dispatch
                        if emergency_response_enabled:
                            _append_action(
                                monitoring_state,
                                "[EMERGENCY DEMO] Emergency response initiated — DEMO"
                            )

                        return {
                            "success": True,
                            "message": f"Sentinel: Alert escalated to supervisor for {worker['name']}."
                        }
                    else:
                        _append_action(
                            monitoring_state,
                            f"[CHECK-IN] Unrecognized worker response '{body}' from {worker['name']}."
                        )
                        return {
                            "success": False,
                            "message": "Sentinel: Unrecognized response. Please reply OK if you are safe."
                        }

        # 2. Identify if sender is a buddy replying to verification alert
        for buddy in workers:
            # Match on telegram_chat_id first, then phone
            buddy_dest = _get_worker_telegram_destination(buddy)
            if buddy_dest == normalized_sender:
                # Find worker associated with this buddy
                for worker in workers:
                    if worker.get("buddy_id") == buddy["id"] and worker.get("buddy_verification_status") == "pending":
                        if normalized_body == "SAFE":
                            worker["status"] = "working"
                            worker["check_in_status"] = "confirmed"
                            worker["check_in_response"] = "OK"
                            worker["buddy_verification_status"] = "confirmed_safe"
                            
                            _append_action(
                                monitoring_state,
                                f"[BUDDY] {worker['name']} verified SAFE by buddy {buddy['name']}."
                            )
                            return {
                                "success": True,
                                "message": f"Sentinel: Thank you. {worker['name']}'s safety has been confirmed."
                            }
                        elif normalized_body == "NOT SAFE":
                            worker["status"] = "supervisor_notified"
                            worker["buddy_verification_status"] = "confirmed_not_safe"
                            
                            _append_action(
                                monitoring_state,
                                f"[BUDDY] Buddy {buddy['name']} reported {worker['name']} is NOT SAFE."
                            )

                            # Create Incident if one doesn't exist
                            active_incident = next(
                                (inc for inc in incidents if inc["worker_id"] == worker["id"] and inc["status"] != "resolved"),
                                None
                            )
                            incident_id = ""
                            if not active_incident:
                                incident_id = f"INC-{len(incidents) + 1:03d}"
                                new_incident = {
                                    "id": incident_id,
                                    "worker_id": worker["id"],
                                    "type": "environmental_safety",
                                    "status": "active",
                                    "actions_taken": ["Reported not safe by buddy"]
                                }
                                incidents.append(new_incident)
                                _append_action(
                                    monitoring_state,
                                    f"[INCIDENT] Created safety incident {incident_id} for {worker['name']}."
                                )
                            else:
                                incident_id = active_incident["id"]

                            # Escalate incident
                            for inc in incidents:
                                if inc["id"] == incident_id:
                                    if inc["status"] == "active":
                                        inc["status"] = "escalated_supervisor"
                                        inc["actions_taken"].append("Escalated to supervisor")
                                        _append_action(
                                            monitoring_state,
                                            f"[INCIDENT] Escalated {incident_id} to supervisor."
                                        )

                            # Notify supervisor
                            supervisor_msg = (
                                f"SENTINEL ALERT: {worker['name']} has not responded to a safety check-in. "
                                f"Buddy verification indicates the worker may need assistance. Incident {incident_id}."
                            )
                            send_result = _send_msg(SUPERVISOR_PHONE, supervisor_msg)

                            if send_result.get("success"):
                                _append_action(
                                    monitoring_state,
                                    f"[TELEGRAM] Supervisor notified for {worker['name']}. Incident {incident_id}."
                                )
                            else:
                                _append_action(
                                    monitoring_state,
                                    f"[TELEGRAM ERROR] Failed to notify supervisor for {worker['name']}. "
                                    f"Incident {incident_id}: {send_result.get('error', 'unknown error')}"
                                )

                            # Simulated Emergency Dispatch
                            if emergency_response_enabled:
                                _append_action(
                                    monitoring_state,
                                    "[EMERGENCY DEMO] Emergency response initiated — DEMO"
                                )

                            return {
                                "success": True,
                                "message": f"Sentinel: Alert escalated to supervisor for {worker['name']}."
                            }
                        else:
                            _append_action(
                                monitoring_state,
                                f"[BUDDY] Unrecognized buddy response '{body}' from {buddy['name']}."
                            )
                            return {
                                "success": False,
                                "message": "Sentinel: Unrecognized response. Please reply SAFE or NOT SAFE."
                            }

        # If phone mapping is not found
        return {
            "success": False,
            "message": "Sentinel: Phone number not recognized or no pending safety check-ins found."
        }
