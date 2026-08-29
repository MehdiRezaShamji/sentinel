import os
from copy import deepcopy
from fastapi import APIRouter, Request, Response

from app.agents.graph import safety_agent_graph
from app.services.monitor import (
    get_monitoring_status,
    start_monitoring,
    stop_monitoring,
    reset_monitoring_state,
    set_emergency_response,
    get_emergency_response,
)
from app.services.database import load_workers_from_db

router = APIRouter()

# Default timeout is 300 seconds (5 mins), can be overridden in env (e.g. 30s for demo)
CHECKIN_TIMEOUT = int(os.getenv("CHECKIN_TIMEOUT_SECONDS", "300"))

BASE_WORKERS = [
    {
        "id": "W001",
        "name": "Alex",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "task": "Road maintenance",
        "exposure_minutes": 60,
        "status": "working",
        "buddy_id": "W002",
        "phone": "+15550000001",
        "check_in_status": None,
        "check_in_sent_at": None,
        "check_in_timeout_seconds": CHECKIN_TIMEOUT,
        "buddy_verification_status": None,
        "buddy_notified_at": None,
    },
    {
        "id": "W002",
        "name": "Jordan",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "task": "Equipment inspection",
        "exposure_minutes": 30,
        "status": "working",
        "buddy_id": "W001",
        "phone": "+15550000002",
        "check_in_status": None,
        "check_in_sent_at": None,
        "check_in_timeout_seconds": CHECKIN_TIMEOUT,
        "buddy_verification_status": None,
        "buddy_notified_at": None,
    },
    {
        "id": "W003",
        "name": "Sam",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "task": "Heavy road work",
        "exposure_minutes": 60,
        "status": "working",
        "buddy_id": "W001",
        "phone": "+15550000003",
        "check_in_status": None,
        "check_in_sent_at": None,
        "check_in_timeout_seconds": CHECKIN_TIMEOUT,
        "buddy_verification_status": None,
        "buddy_notified_at": None,
    },
]


def build_demo_state() -> dict:
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    timeout = 20 if demo_mode else int(os.getenv("CHECKIN_TIMEOUT_SECONDS", "300"))
    
    workers = load_workers_from_db()

    from app.telegram import get_persisted_chat_id
    chat_id = get_persisted_chat_id()
    
    for w in workers:
        w["check_in_timeout_seconds"] = timeout
        if demo_mode and w["id"] == "W001":
            # Set telegram_chat_id separately from phone so routing works correctly.
            # phone remains the worker's actual phone number.
            # Alex is the live Telegram worker: only a real discovered chat ID
            # (in-memory or a valid persisted one) may be used. Always assign it
            # explicitly so stale/invalid DB values and phone-formatted numbers
            # (e.g. DEMO_PHONE_NUMBER) can never route Alex through [DEMO TELEGRAM].
            w["telegram_chat_id"] = chat_id

    return {
        "latitude": 40.7128,
        "longitude": -74.0060,
        "temperature": 32.5,
        "environment": {},
        "workers": workers,
        "incidents": [],
        "agent_actions": [],
        "current_step": "starting",
        "pending_actions": [],
        "monitoring_active": True,
        "emergency_response_enabled": get_emergency_response(),
    }


@router.post("/agent/run")
def run_agent():
    state = build_demo_state()
    result = safety_agent_graph.invoke(state)
    return {
        "status": "success",
        "current_step": result["current_step"],
        "environment": result["environment"],
        "workers": result["workers"],
        "incidents": result["incidents"],
        "agent_actions": result["agent_actions"],
    }


@router.post("/monitor/start")
def start_monitoring_endpoint():
    return start_monitoring(build_demo_state())


@router.post("/monitor/stop")
def stop_monitoring_endpoint():
    return stop_monitoring()


@router.get("/monitor/status")
def monitoring_status():
    return get_monitoring_status()



@router.post("/demo/reset")
def reset_demo():
    # Pass build_demo_state to re-initialize base values
    return reset_monitoring_state(build_demo_state())


@router.post("/demo/emergency")
@router.post("/monitor/emergency")
def set_emergency(payload: dict):
    enabled = payload.get("enabled", False)
    return set_emergency_response(enabled)

@router.get("/telegram/status")
def telegram_status():
    from app.telegram import get_telegram_status
    return get_telegram_status()

@router.post("/telegram/test")
def telegram_test(payload: dict = None):
    from app.telegram import send_telegram_message, get_persisted_chat_id
    chat_id = get_persisted_chat_id()
    if not chat_id:
        return {"success": False, "error": "No discovered chat ID. Please send /start to the bot first."}
    msg = (payload or {}).get("message", "Sentinel safety check-in: Are you safe? Reply SAFE or NOT SAFE.")
    return send_telegram_message(chat_id, msg)
