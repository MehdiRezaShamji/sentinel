from langchain_core.tools import tool

from app.services.fortyguard import get_environmental_data


@tool
def observe_environment(
    latitude: float,
    longitude: float,
    temperature: float,
    date: str | None = None,
    start_time: str | None = None,
) -> dict:
    """
    Observe environmental conditions at a specific location.

    Uses FortyGuard to retrieve temperature, heat index,
    apparent temperature, humidity, wet-bulb temperature,
    precipitation, air quality, and solar conditions.
    """

    return get_environmental_data(
        latitude=latitude,
        longitude=longitude,
        temperature=temperature,
        date=date,
        start_time=start_time,
    )
