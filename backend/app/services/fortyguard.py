import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

FORTYGUARD_API_KEY = os.getenv("FORTYGUARD_API_KEY")
FORTYGUARD_BASE_URL = "https://api.fortyguard.com/v1"


def _headers() -> dict:
    if not FORTYGUARD_API_KEY:
        raise RuntimeError("FORTYGUARD_API_KEY is not configured in backend/.env")

    return {
        "api-key": FORTYGUARD_API_KEY,
        "Content-Type": "application/json",
    }


def _poll_activity(activity_id: str) -> dict:
    """Poll a FortyGuard activity until it completes."""

    url = f"{FORTYGUARD_BASE_URL}/status/{activity_id}"

    for _ in range(30):
        response = requests.get(
            url,
            headers=_headers(),
            timeout=30,
        )
        response.raise_for_status()

        payload = response.json()
        data = payload.get("data", {})

        status = data.get("status", "").lower()

        if status == "completed":
            return data.get("result", {})

        if status in {"failed", "error"}:
            raise RuntimeError(f"FortyGuard activity failed: {payload}")

        time.sleep(2)

    raise TimeoutError(f"FortyGuard activity {activity_id} timed out.")


def get_environmental_data(
    latitude: float,
    longitude: float,
    temperature: float,
    date: str | None = None,
    start_time: str | None = None,
) -> dict:
    """Retrieve environmental intelligence from FortyGuard."""

    if date is None:
        date = time.strftime("%Y-%m-%d")

    if start_time is None:
        start_time = time.strftime("%H:%M")

    payload = {
        "latitude": latitude,
        "longitude": longitude,
        "temperature": temperature,
        "date_time": {
            "start_date": date,
            "start_time": start_time,
            "filter_type": 1,
        },
    }

    response = requests.post(
        f"{FORTYGUARD_BASE_URL}/env_params",
        headers=_headers(),
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    submission = response.json()

    if submission.get("error"):
        raise RuntimeError(f"FortyGuard submission failed: {submission}")

    activity_id = submission["data"]["activity_id"]

    result = _poll_activity(activity_id)

    return _normalize_environment(result)


def _normalize_environment(result: dict) -> dict:
    """Convert FortyGuard's raw response into our application format."""

    locations = result.get("locations", [])

    if not locations:
        raise RuntimeError("FortyGuard returned no location data.")

    location = locations[0]
    parameters = location.get("parameters", {})
    solar = location.get("solar_irradiance", {})
    clear_sky = solar.get("clear_sky", {})

    def first_value(key: str):
        values = parameters.get(key, [])

        if not values:
            return None

        return values[0]

    return {
        "latitude": location.get("lat"),
        "longitude": location.get("lon"),
        "temperature_c": location.get("temperature"),
        "heat_index_c": first_value("heat_index_celsius"),
        "apparent_temperature_c": first_value("apparent_temperature_celsius"),
        "humidity_percent": first_value("relative_humidity_percent"),
        "wet_bulb_c": first_value("wet_bulb_temperature_celsius"),
        "precipitation_mm": first_value("precipitation_mm"),
        "cloud_cover_octas": first_value("cloud_cover_octas"),
        "air_quality_index": first_value("air_quality:idx"),
        "solar_irradiance": {
            "ghi": clear_sky.get("ghi"),
            "dni": clear_sky.get("dni"),
            "dhi": clear_sky.get("dhi"),
        },
        "metadata": result.get("metadata", {}),
    }
