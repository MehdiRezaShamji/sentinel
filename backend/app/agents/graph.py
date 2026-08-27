from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.tools.fortyguard_tools import observe_environment
from app.tools.worker_tools import (
    create_incident,
    escalate_incident,
    get_active_workers,
    send_checkin,
)


class SafetyAgentState(TypedDict):
    latitude: float
    longitude: float
    temperature: float
    environment: dict
    workers: list[dict]
    incidents: list[dict]
    agent_actions: list[str]
    current_step: str


def observe(state: SafetyAgentState):
    environment = observe_environment.invoke(
        {
            "latitude": state["latitude"],
            "longitude": state["longitude"],
            "temperature": state["temperature"],
            "date": "2024-07-15",
            "start_time": "14:00",
        }
    )

    return {
        "environment": environment,
        "current_step": "environment_observed",
    }


def load_workers(state: SafetyAgentState):
    result = get_active_workers.invoke(
        {
            "state": {
                "workers": state["workers"],
                "incidents": state["incidents"],
                "agent_actions": [],
            }
        }
    )

    return {
        "workers": result["workers"],
        "current_step": "workers_loaded",
    }


def assess_workers(state: SafetyAgentState):
    workers = [dict(worker) for worker in state["workers"]]
    actions = list(state["agent_actions"])

    heat_index = state["environment"].get("heat_index_c")

    if heat_index is None:
        actions.append("Heat index unavailable; using temperature.")
        risk_temperature = state["temperature"]
    else:
        risk_temperature = heat_index

    for worker in workers:
        if worker["status"] == "working":
            if risk_temperature >= 35 and worker["exposure_minutes"] >= 45:
                worker["status"] = "high_risk"

                actions.append(
                    f"High environmental exposure detected for " f"{worker['name']}"
                )

        if worker["status"] == "unresponsive":
            actions.append(f"No response detected from {worker['name']}")

    return {
        "workers": workers,
        "agent_actions": actions,
        "current_step": "workers_assessed",
    }


def execute_response(state: SafetyAgentState):
    workers = state["workers"]
    incidents = [dict(incident) for incident in state["incidents"]]
    actions = list(state["agent_actions"])

    for worker in workers:

        if worker["status"] == "high_risk":
            result = send_checkin.invoke(
                {
                    "state": {
                        "workers": workers,
                        "incidents": incidents,
                        "agent_actions": actions,
                    },
                    "worker_id": worker["id"],
                }
            )

            if result["success"]:
                actions.append(f"Check-in sent to {worker['name']}")

        elif worker["status"] == "unresponsive":

            existing = next(
                (
                    incident
                    for incident in incidents
                    if incident["worker_id"] == worker["id"]
                    and incident["status"] != "resolved"
                ),
                None,
            )

            if existing:
                continue

            result = create_incident.invoke(
                {
                    "state": {
                        "workers": workers,
                        "incidents": incidents,
                        "agent_actions": actions,
                    },
                    "worker_id": worker["id"],
                    "incident_type": "environmental_safety",
                }
            )

            if result["success"]:
                incident = next(
                    incident
                    for incident in incidents
                    if incident["id"] == result["incident_id"]
                )

                actions.append(
                    f"Created {result['incident_id']} " f"for {worker['name']}"
                )

                escalation = escalate_incident.invoke(
                    {
                        "state": {
                            "workers": workers,
                            "incidents": incidents,
                            "agent_actions": actions,
                        },
                        "incident_id": result["incident_id"],
                        "escalation_level": "supervisor",
                    }
                )

                if escalation["success"]:
                    incident["status"] = "escalated_supervisor"

                    actions.append(
                        f"Escalated {result['incident_id']} " "to supervisor"
                    )

    return {
        "workers": workers,
        "incidents": incidents,
        "agent_actions": actions,
        "current_step": "response_executed",
    }


def build_graph():
    graph = StateGraph(SafetyAgentState)

    graph.add_node("observe", observe)
    graph.add_node("load_workers", load_workers)
    graph.add_node("assess_workers", assess_workers)
    graph.add_node("execute_response", execute_response)

    graph.add_edge(START, "observe")
    graph.add_edge("observe", "load_workers")
    graph.add_edge("load_workers", "assess_workers")
    graph.add_edge("assess_workers", "execute_response")
    graph.add_edge("execute_response", END)

    return graph.compile()


safety_agent_graph = build_graph()
