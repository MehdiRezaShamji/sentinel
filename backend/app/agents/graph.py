from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.tools.fortyguard_tools import (
    get_environmental_data_tool,
    get_heatmap_tool,
)


class AnalysisState(TypedDict):
    area: str
    candidate_locations: list[str]
    available_resources: int
    intervention_options: list[str]

    heat_data: dict
    environmental_data: dict
    analysis: dict
    recommendation: dict


def retrieve_thermal_data(state: AnalysisState):
    heat_data = get_heatmap_tool.invoke(
        {
            "area": state["area"],
            "locations": state["candidate_locations"],
        }
    )

    return {
        "heat_data": heat_data,
    }


def retrieve_environmental_data(state: AnalysisState):
    environmental_data = get_environmental_data_tool.invoke(
        {
            "area": state["area"],
            "locations": state["candidate_locations"],
        }
    )

    return {
        "environmental_data": environmental_data,
    }


def analyze_scenario(state: AnalysisState):
    heat_data = state["heat_data"]

    ranked_locations = sorted(
        heat_data.items(),
        key=lambda item: item[1]["heat_score"],
        reverse=True,
    )

    analysis = {
        "locations_evaluated": len(ranked_locations),
        "heat_ranking": [
            {
                "location": location,
                "heat_score": data["heat_score"],
            }
            for location, data in ranked_locations
        ],
    }

    return {
        "analysis": analysis,
    }


def generate_recommendation(state: AnalysisState):
    ranked_locations = state["analysis"]["heat_ranking"]
    resources = state["available_resources"]

    selected_locations = ranked_locations[:resources]

    recommendation = {
        "priority_locations": selected_locations,
        "resources_used": len(selected_locations),
        "message": (
            f"Prioritized {len(selected_locations)} locations "
            "based on thermal severity and available resources."
        ),
    }

    return {
        "recommendation": recommendation,
    }


def build_graph():
    graph = StateGraph(AnalysisState)

    graph.add_node("retrieve_thermal_data", retrieve_thermal_data)
    graph.add_node(
        "retrieve_environmental_data",
        retrieve_environmental_data,
    )
    graph.add_node("analyze_scenario", analyze_scenario)
    graph.add_node(
        "generate_recommendation",
        generate_recommendation,
    )

    graph.add_edge(START, "retrieve_thermal_data")
    graph.add_edge(
        "retrieve_thermal_data",
        "retrieve_environmental_data",
    )
    graph.add_edge(
        "retrieve_environmental_data",
        "analyze_scenario",
    )
    graph.add_edge(
        "analyze_scenario",
        "generate_recommendation",
    )
    graph.add_edge("generate_recommendation", END)

    return graph.compile()


heat_resource_graph = build_graph()
