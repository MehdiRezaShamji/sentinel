from langchain_core.tools import tool

from app.models.scenario import Incident


@tool
def get_active_workers(state: dict) -> dict:
    """Get all workers currently being monitored."""

    return {"workers": state.get("workers", [])}


@tool
def send_checkin(state: dict, worker_id: str) -> dict:
    """Send a safety check-in to a worker."""

    for worker in state["workers"]:
        if worker["id"] == worker_id:
            worker["status"] = "awaiting_checkin"

            return {
                "success": True,
                "worker_id": worker_id,
                "worker_name": worker["name"],
                "status": "awaiting_checkin",
            }

    return {
        "success": False,
        "error": f"Worker {worker_id} not found",
    }


@tool
def create_incident(
    state: dict,
    worker_id: str,
    incident_type: str,
) -> dict:
    """Create a safety incident for a worker."""

    existing = next(
        (
            incident
            for incident in state["incidents"]
            if incident["worker_id"] == worker_id and incident["status"] != "resolved"
        ),
        None,
    )

    if existing:
        return {
            "success": False,
            "error": f"Active incident {existing['id']} already exists",
            "incident_id": existing["id"],
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
    }


@tool
def escalate_incident(
    state: dict,
    incident_id: str,
    escalation_level: str,
) -> dict:
    """Escalate an active safety incident."""

    for incident in state["incidents"]:
        if incident["id"] == incident_id:

            new_status = f"escalated_{escalation_level}"

            if incident["status"] == new_status:
                return {
                    "success": False,
                    "error": f"{incident_id} is already escalated",
                }

            incident["status"] = new_status

            return {
                "success": True,
                "incident_id": incident_id,
                "escalation_level": escalation_level,
            }

    return {
        "success": False,
        "error": f"Incident {incident_id} not found",
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

            return {
                "success": True,
                "incident_id": incident_id,
                "status": "resolved",
            }

    return {
        "success": False,
        "error": f"Incident {incident_id} not found",
    }
