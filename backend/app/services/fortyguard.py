from app.data.mock.fortyguard_data import (
    MOCK_ENVIRONMENTAL_DATA,
    MOCK_HEAT_DATA,
)


def get_heatmap(area: str, locations: list[str]) -> dict:
    """Return thermal data for the requested candidate locations."""

    return {
        location: MOCK_HEAT_DATA.get(
            location,
            {
                "heat_score": 50,
                "surface_temperature_c": 35.0,
                "heat_exceedance": 0.0,
                "heat_persistence_hours": 0,
            },
        )
        for location in locations
    }


def get_environmental_data(area: str, locations: list[str]) -> dict:
    """Return environmental data for the requested candidate locations."""

    return {
        location: MOCK_ENVIRONMENTAL_DATA.get(
            location,
            {
                "vegetation_index": 0.5,
                "air_quality_index": 100,
                "humidity_percent": 50,
            },
        )
        for location in locations
    }
