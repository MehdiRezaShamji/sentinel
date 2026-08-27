from fastapi import APIRouter

from app.agents.graph import safety_agent_graph

from app.services.monitor import (
    start_monitoring,
    stop_monitoring,
    get_monitoring_status,
)

router = APIRouter()


@router.post("/agent/run")
def run_agent():
    initial_state = {
        "latitude": 40.7128,
        "longitude": -74.0060,
        "temperature": 32.5,
        "environment": {},
        "workers": [
            {
                "id": "W001",
                "name": "Alex",
                "latitude": 40.7128,
                "longitude": -74.0060,
                "task": "Road maintenance",
                "exposure_minutes": 60,
                "status": "unresponsive",
                "buddy_id": "W002",
            },
            {
                "id": "W002",
                "name": "Jordan",
                "latitude": 40.7128,
                "longitude": -74.0060,
                "task": "Equipment inspection",
                "exposure_minutes": 30,
                "status": "unresponsive",
                "buddy_id": "W001",
            },
            {
                "id": "W003",
                "name": "Sam",
                "latitude": 40.7128,
                "longitude": -74.0060,
                "task": "Heavy road work",
                "exposure_minutes": 60,
                "status": "unresponsive",
                "buddy_id": "W001",
            },
        ],
        "incidents": [],
        "agent_actions": [],
        "current_step": "starting",
    }

    result = safety_agent_graph.invoke(initial_state)

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
    return start_monitoring()


@router.post("/monitor/stop")
def stop_monitoring_endpoint():
    return stop_monitoring()


@router.get("/monitor/status")
def monitoring_status():
    return get_monitoring_status()
