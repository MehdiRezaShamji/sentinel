from datetime import datetime, timezone

from langchain_core.tools import tool

from app.models.scenario import Incident

CHECKIN_TIMEOUT_SECONDS = 5 * 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp


@tool
def get_active_workers(state: dict) -> dict:
    """Get all workers currently being monitored."""

    return {
        "workers": state.get(
            "workers",
            [],
        )
    }


@tool
def send_checkin(
    state: dict,
    worker_id: str,
) -> dict:
    """
    Start a safety check-in for a high-risk worker.

    This function records the check-in locally. Actual SMS delivery
    will be connected in the SMS-provider implementation later.

    A worker can have only one pending check-in at a time.
    """

    for worker in state["workers"]:

        if worker["id"] != worker_id:
            continue

        # Never send another check-in while one is already pending.
        if worker.get("check_in_status") == "pending":
            return {
                "success": False,
                "worker_id": worker_id,
                "worker_name": worker["name"],
                "status": worker["status"],
                "message": "Check-in already pending.",
                "workers": state["workers"],
                "incidents": state["incidents"],
            }

        if worker["status"] == "awaiting_checkin":
            return {
                "success": False,
                "worker_id": worker_id,
                "worker_name": worker["name"],
                "status": "awaiting_checkin",
                "message": "Check-in already pending.",
                "workers": state["workers"],
                "incidents": state["incidents"],
            }

        # A worker who has already confirmed safety should not receive
        # another check-in during the current safety cycle.
        if worker.get("check_in_response") == "OK":
            return {
                "success": False,
                "worker_id": worker_id,
                "worker_name": worker["name"],
                "status": worker["status"],
                "message": "Worker already confirmed safety.",
                "workers": state["workers"],
                "incidents": state["incidents"],
            }

        sent_at = _now_iso()

        worker["status"] = "awaiting_checkin"
        worker["check_in_sent"] = True
        worker["check_in_response"] = None

        # New deterministic timer state.
        worker["check_in_status"] = "pending"
        worker["check_in_sent_at"] = sent_at
        worker["check_in_timeout_seconds"] = CHECKIN_TIMEOUT_SECONDS

        return {
            "success": True,
            "worker_id": worker_id,
            "worker_name": worker["name"],
            "status": "awaiting_checkin",
            "check_in_status": "pending",
            "check_in_sent_at": sent_at,
            "timeout_seconds": CHECKIN_TIMEOUT_SECONDS,
            "message": "Safety check-in started.",
            "workers": state["workers"],
            "incidents": state["incidents"],
        }

    return {
        "success": False,
        "error": f"Worker {worker_id} not found.",
        "workers": state["workers"],
        "incidents": state["incidents"],
    }


@tool
def worker_checkin_response(
    state: dict,
    worker_id: str,
    response: str,
) -> dict:
    """
    Record a worker's response to a pending safety check-in.

    The only accepted response for the worker workflow is OK.
    """

    normalized_response = response.strip().upper()

    for worker in state["workers"]:

        if worker["id"] != worker_id:
            continue

        if worker.get("check_in_status") != "pending":
            return {
                "success": False,
                "worker_id": worker_id,
                "message": "No check-in is currently awaiting a response.",
                "workers": state["workers"],
                "incidents": state["incidents"],
            }

        if normalized_response == "OK":

            worker["status"] = "working"
            worker["check_in_response"] = "OK"
            worker["check_in_status"] = "confirmed"

            # Preserve the original sent timestamp for the UI/history,
            # but the pending timer is no longer active.
            worker["check_in_completed_at"] = _now_iso()

            return {
                "success": True,
                "worker_id": worker_id,
                "worker_name": worker["name"],
                "status": "working",
                "check_in_status": "confirmed",
                "message": "Worker confirmed they are safe.",
                "workers": state["workers"],
                "incidents": state["incidents"],
            }

        return {
            "success": False,
            "worker_id": worker_id,
            "worker_name": worker["name"],
            "status": "awaiting_checkin",
            "check_in_status": "pending",
            "message": "Unrecognized check-in response.",
            "workers": state["workers"],
            "incidents": state["incidents"],
        }

    return {
        "success": False,
        "error": f"Worker {worker_id} not found.",
        "workers": state["workers"],
        "incidents": state["incidents"],
    }


@tool
def process_checkin_timeouts(
    state: dict,
) -> dict:
    """
    Check pending worker check-ins for the five-minute timeout.

    This is deterministic and intended to be called by the local
    monitoring loop every few seconds.

    It does not:
    - call FortyGuard
    - call an LLM
    - send repeated SMS
    - create an incident
    - notify a supervisor

    Those actions belong to later Day 2 workflow steps.
    """

    now = datetime.now(timezone.utc)
    actions = []

    for worker in state["workers"]:

        if worker.get("check_in_status") != "pending":
            continue

        sent_at_value = worker.get("check_in_sent_at")

        if not sent_at_value:
            continue

        try:
            sent_at = _parse_timestamp(sent_at_value)
        except (TypeError, ValueError):
            continue

        elapsed_seconds = (now - sent_at).total_seconds()

        timeout_seconds = worker.get(
            "check_in_timeout_seconds",
            CHECKIN_TIMEOUT_SECONDS,
        )

        # Still inside the response window.
        if elapsed_seconds < timeout_seconds:
            continue

        # Five minutes have elapsed without an OK response.
        worker["status"] = "unresponsive"
        worker["check_in_status"] = "timed_out"
        worker["check_in_response"] = None
        worker["check_in_timed_out_at"] = _now_iso()

        actions.append(
            "No check-in response received "
            f"from {worker['name']} after "
            f"{timeout_seconds // 60} minutes"
        )

    return {
        "success": True,
        "workers": state["workers"],
        "incidents": state["incidents"],
        "actions": actions,
    }


@tool
def process_pending_checkins(
    state: dict,
) -> dict:
    """
    Backward-compatible wrapper for the existing LangGraph workflow.

    The autonomous monitoring system uses process_checkin_timeouts()
    instead. This function remains available so the existing graph.py
    import and agent test continue to work.
    """

    return process_checkin_timeouts.invoke(
        {
            "state": state,
        }
    )


@tool
def create_incident(
    state: dict,
    worker_id: str,
    incident_type: str,
) -> dict:
    """Create a safety incident for an unresponsive worker."""

    existing = next(
        (
            incident
            for incident in state["incidents"]
            if (incident["worker_id"] == worker_id and incident["status"] != "resolved")
        ),
        None,
    )

    if existing:
        return {
            "success": False,
            "error": (f"Active incident {existing['id']} " "already exists."),
            "incident_id": existing["id"],
            "workers": state["workers"],
            "incidents": state["incidents"],
        }

    incident_id = f"INC-{len(state['incidents']) + 1:03d}"

    incident = Incident(
        id=incident_id,
        worker_id=worker_id,
        type=incident_type,
    )

    state["incidents"].append(incident.model_dump())

    return {
        "success": True,
        "incident_id": incident_id,
        "status": "active",
        "workers": state["workers"],
        "incidents": state["incidents"],
    }


@tool
def escalate_incident(
    state: dict,
    incident_id: str,
    escalation_level: str,
) -> dict:
    """Escalate an active safety incident."""

    for incident in state["incidents"]:

        if incident["id"] != incident_id:
            continue

        if incident["status"] != "active":
            return {
                "success": False,
                "error": (f"{incident_id} is already " "escalated or resolved."),
                "workers": state["workers"],
                "incidents": state["incidents"],
            }

        incident["status"] = f"escalated_{escalation_level}"

        incident["actions_taken"].append(f"Escalated to {escalation_level}")

        return {
            "success": True,
            "incident_id": incident_id,
            "escalation_level": escalation_level,
            "workers": state["workers"],
            "incidents": state["incidents"],
        }

    return {
        "success": False,
        "error": f"Incident {incident_id} not found.",
        "workers": state["workers"],
        "incidents": state["incidents"],
    }


@tool
def resolve_incident(
    state: dict,
    incident_id: str,
) -> dict:
    """Resolve a safety incident."""

    for incident in state["incidents"]:

        if incident["id"] == incident_id:

            incident["status"] = "resolved"

            incident["actions_taken"].append("Resolved")

            return {
                "success": True,
                "incident_id": incident_id,
                "status": "resolved",
                "workers": state["workers"],
                "incidents": state["incidents"],
            }

    return {
        "success": False,
        "error": f"Incident {incident_id} not found.",
        "workers": state["workers"],
        "incidents": state["incidents"],
    }
