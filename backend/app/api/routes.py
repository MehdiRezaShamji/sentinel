from fastapi import APIRouter

from app.agents.graph import heat_resource_graph
from app.models.scenario import Scenario

router = APIRouter()


@router.post("/analyze")
def analyze_scenario(scenario: Scenario):
    result = heat_resource_graph.invoke(
        {
            "area": scenario.area,
            "candidate_locations": scenario.candidate_locations,
            "available_resources": scenario.available_resources,
            "intervention_options": scenario.intervention_options,
            "heat_data": {},
            "environmental_data": {},
            "analysis": {},
            "recommendation": {},
        }
    )

    return {
        "status": "success",
        "analysis": result["analysis"],
        "recommendation": result["recommendation"],
    }
