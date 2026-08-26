from langchain_core.tools import tool

from app.services.fortyguard import (
    get_environmental_data,
    get_heatmap,
)


@tool
def get_heatmap_tool(area: str, locations: list[str]) -> dict:
    """Retrieve thermal conditions for candidate locations."""

    return get_heatmap(area, locations)


@tool
def get_environmental_data_tool(
    area: str,
    locations: list[str],
) -> dict:
    """Retrieve environmental conditions for candidate locations."""

    return get_environmental_data(area, locations)