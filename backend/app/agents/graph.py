from copy import deepcopy
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph

from app.tools.fortyguard_tools import observe_environment
from app.tools.worker_tools import (
    create_incident,
    escalate_incident,
    get_active_workers,
    process_pending_checkins,
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
    pending_actions: list[dict]
    monitoring_active: bool


llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
)


def _cap_actions(actions: list[str], limit: int = 50) -> list[str]:
    return actions[-limit:]


def _fallback_environment(state: SafetyAgentState, reason: str) -> dict:
    temperature = state["temperature"]

    return {
        "latitude": state["latitude"],
        "longitude": state["longitude"],
        "temperature_c": temperature,
        "heat_index_c": max(temperature + 4.3, 36.8),
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


def observe(state: SafetyAgentState):
    try:
        environment = observe_environment.invoke(
            {
                "latitude": state["latitude"],
                "longitude": state["longitude"],
                "temperature": state["temperature"],
                "date": "2024-07-15",
                "start_time": "14:00",
            }
        )
    except Exception as exc:
        environment = _fallback_environment(state, str(exc))

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
                "agent_actions": state["agent_actions"],
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

    checkin_result = process_pending_checkins.invoke(
        {
            "state": {
                "workers": workers,
                "incidents": state["incidents"],
                "agent_actions": actions,
            }
        }
    )

    workers = checkin_result["workers"]
    actions.extend(checkin_result["actions"])

    heat_index = state["environment"].get("heat_index_c")

    if heat_index is None:
        risk_temperature = state["temperature"]
        actions.append("Heat index unavailable; using temperature.")
    else:
        risk_temperature = heat_index

    for worker in workers:
        if (
            worker["status"] == "working"
            and worker.get("check_in_response") != "OK"
            and risk_temperature >= 35
            and worker["exposure_minutes"] >= 45
        ):
            worker["status"] = "high_risk"

            message = f"High environmental exposure detected for {worker['name']}"

            if message not in actions:
                actions.append(message)

    return {
        "workers": workers,
        "agent_actions": _cap_actions(actions),
        "current_step": "risk_assessed",
    }


def _policy_action(state: SafetyAgentState) -> dict:
    incidents = state["incidents"]
    workers = state["workers"]

    for incident in incidents:
        if incident["status"] == "active":
            return {
                "type": "escalate_incident",
                "worker_id": incident["worker_id"],
                "incident_id": incident["id"],
                "reason": "Active incident requires supervisor escalation.",
            }

    active_worker_ids = {
        incident["worker_id"]
        for incident in incidents
        if incident["status"] != "resolved"
    }

    for worker in workers:
        if worker["status"] == "unresponsive" and worker["id"] not in active_worker_ids:
            return {
                "type": "create_incident",
                "worker_id": worker["id"],
                "incident_id": None,
                "reason": "Worker is unresponsive with no active incident.",
            }

    for worker in workers:
        if worker["status"] == "high_risk" and worker.get("check_in_response") != "OK":
            return {
                "type": "send_checkin",
                "worker_id": worker["id"],
                "incident_id": None,
                "reason": "High-risk worker requires a safety check-in.",
            }

    return {
        "type": "wait",
        "worker_id": None,
        "incident_id": None,
        "reason": "No intervention is currently required.",
    }


def _validate_action(
    state: SafetyAgentState,
    action: dict,
) -> tuple[bool, str]:

    action_type = action.get("type", "").lower()
    required = _policy_action(state)

    if action_type == "wait" and required["type"] != "wait":
        return False, f"Safety policy requires {required['type']}."

    workers = {worker["id"]: worker for worker in state["workers"]}

    incidents = {incident["id"]: incident for incident in state["incidents"]}

    if action_type == "wait":
        return True, ""

    if action_type == "send_checkin":
        worker = workers.get(action.get("worker_id"))

        if not worker:
            return False, "Worker does not exist."

        if worker["status"] != "high_risk":
            return False, "Worker is not currently high risk."

        if worker.get("check_in_response") == "OK":
            return False, "Worker already confirmed safety."

        return True, ""

    if action_type == "create_incident":
        worker = workers.get(action.get("worker_id"))

        if not worker:
            return False, "Worker does not exist."

        if worker["status"] != "unresponsive":
            return False, "Worker is not unresponsive."

        if any(
            incident["worker_id"] == worker["id"] and incident["status"] != "resolved"
            for incident in state["incidents"]
        ):
            return False, "Worker already has an active incident."

        return True, ""

    if action_type == "escalate_incident":
        incident = incidents.get(action.get("incident_id"))

        if not incident:
            return False, "Incident does not exist."

        if incident["status"] != "active":
            return False, "Incident is already escalated or resolved."

        return True, ""

    return False, "Unknown action."


def agent_decide(state: SafetyAgentState):
    worker_summary = [
        {
            "id": worker["id"],
            "name": worker["name"],
            "status": worker["status"],
            "exposure_minutes": worker["exposure_minutes"],
            "check_in_response": worker.get("check_in_response"),
        }
        for worker in state["workers"]
    ]

    incident_summary = [
        {
            "id": incident["id"],
            "worker_id": incident["worker_id"],
            "status": incident["status"],
            "type": incident["type"],
        }
        for incident in state["incidents"]
    ]

    prompt = f"""
You are Sentinel, an autonomous environmental safety operations agent.

Choose the next operational action from exactly one of:

SEND_CHECKIN
CREATE_INCIDENT
ESCALATE_INCIDENT
WAIT

Environment:
{state["environment"]}

Workers:
{worker_summary}

Incidents:
{incident_summary}

Rules:

1. An UNRESPONSIVE worker without an active incident needs CREATE_INCIDENT.
2. An ACTIVE incident needs ESCALATE_INCIDENT.
3. A HIGH_RISK worker who has not responded OK needs SEND_CHECKIN.
4. A worker who responded OK must not receive another check-in.
5. Never create duplicate incidents.
6. Never escalate an already escalated incident.
7. If no intervention is required, choose WAIT.

Return exactly:

ACTION=<action>
WORKER_ID=<worker id or NONE>
INCIDENT_ID=<incident id or NONE>
REASON=<short reason>
"""

    try:
        response = llm.invoke(
            [
                SystemMessage(
                    content=("You are a careful autonomous safety " "operations agent.")
                ),
                HumanMessage(content=prompt),
            ]
        )

        text = response.content.strip()
        llm_error = None

    except Exception as exc:
        text = ""
        llm_error = str(exc)

    parsed = {
        "type": "wait",
        "worker_id": None,
        "incident_id": None,
        "reason": "No intervention is currently required.",
    }

    for line in text.splitlines():

        if line.startswith("ACTION="):
            parsed["type"] = line.split("=", 1)[1].strip().lower()

        elif line.startswith("WORKER_ID="):
            value = line.split("=", 1)[1].strip()
            parsed["worker_id"] = None if value == "NONE" else value

        elif line.startswith("INCIDENT_ID="):
            value = line.split("=", 1)[1].strip()
            parsed["incident_id"] = None if value == "NONE" else value

        elif line.startswith("REASON="):
            parsed["reason"] = line.split("=", 1)[1].strip()

    valid, validation_reason = _validate_action(
        state,
        parsed,
    )

    if valid:
        selected = parsed
    else:
        selected = _policy_action(state)

    actions = list(state["agent_actions"])

    if llm_error:
        actions.append(f"LLM unavailable; policy fallback used: {llm_error}")

    elif not valid:
        actions.append("Policy guardrail rejected LLM action: " f"{validation_reason}")

    actions.append(
        f"Agent decision: " f"{selected['type'].upper()} — " f"{selected['reason']}"
    )

    return {
        "pending_actions": ([] if selected["type"] == "wait" else [selected]),
        "agent_actions": _cap_actions(actions),
        "current_step": "agent_decided",
    }


def execute_action(state: SafetyAgentState):
    workers = deepcopy(state["workers"])
    incidents = deepcopy(state["incidents"])
    actions = list(state["agent_actions"])
    pending = list(state["pending_actions"])

    if not pending:
        return {
            "workers": workers,
            "incidents": incidents,
            "agent_actions": actions,
            "pending_actions": [],
            "current_step": "waiting",
        }

    action = pending.pop(0)

    action_type = action["type"]
    worker_id = action.get("worker_id")
    incident_id = action.get("incident_id")

    tool_state = {
        "workers": workers,
        "incidents": incidents,
        "agent_actions": actions,
    }

    if action_type == "send_checkin" and worker_id:

        result = send_checkin.invoke(
            {
                "state": tool_state,
                "worker_id": worker_id,
            }
        )

        if result["success"]:
            workers = result["workers"]
            incidents = result["incidents"]

            actions.append(
                "Tool executed: " f"Check-in sent to {result['worker_name']}"
            )

        else:
            actions.append(
                "Tool rejected: " f"{result.get('message', result.get('error'))}"
            )

    elif action_type == "create_incident" and worker_id:

        result = create_incident.invoke(
            {
                "state": tool_state,
                "worker_id": worker_id,
                "incident_type": "environmental_safety",
            }
        )

        if result["success"]:
            workers = result["workers"]
            incidents = result["incidents"]

            actions.append(f"Tool executed: Created {result['incident_id']}")

        else:
            actions.append(f"Tool rejected: {result.get('error')}")

    elif action_type == "escalate_incident" and incident_id:

        result = escalate_incident.invoke(
            {
                "state": tool_state,
                "incident_id": incident_id,
                "escalation_level": "supervisor",
            }
        )

        if result["success"]:
            workers = result["workers"]
            incidents = result["incidents"]

            actions.append("Tool executed: " f"Escalated {incident_id} to supervisor")

        else:
            actions.append(f"Tool rejected: {result.get('error')}")

    return {
        "workers": workers,
        "incidents": incidents,
        "agent_actions": _cap_actions(actions),
        "pending_actions": pending,
        "current_step": "action_executed",
    }


def should_continue(
    state: SafetyAgentState,
) -> Literal["execute", "finish"]:

    if state["pending_actions"]:
        return "execute"

    return "finish"


def build_graph():

    graph = StateGraph(SafetyAgentState)

    graph.add_node("observe", observe)
    graph.add_node("load_workers", load_workers)
    graph.add_node("assess_workers", assess_workers)
    graph.add_node("agent_decide", agent_decide)
    graph.add_node("execute_action", execute_action)

    graph.add_edge(
        START,
        "observe",
    )

    graph.add_edge(
        "observe",
        "load_workers",
    )

    graph.add_edge(
        "load_workers",
        "assess_workers",
    )

    graph.add_edge(
        "assess_workers",
        "agent_decide",
    )

    graph.add_conditional_edges(
        "agent_decide",
        should_continue,
        {
            "execute": "execute_action",
            "finish": END,
        },
    )

    graph.add_edge(
        "execute_action",
        END,
    )

    return graph.compile()


safety_agent_graph = build_graph()
