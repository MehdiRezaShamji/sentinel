import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

FORTYGUARD_API_KEY = os.getenv("FORTYGUARD_API_KEY")

FORTYGUARD_BASE_URL = "https://api.fortyguard.com/v1"


class FortyGuardTimeout(RuntimeError):
    pass


def _headers() -> dict:

    if not FORTYGUARD_API_KEY:
        raise RuntimeError("FORTYGUARD_API_KEY is not configured " "in backend/.env")

    return {
        "api-key": FORTYGUARD_API_KEY,
        "Content-Type": "application/json",
    }


def _poll_activity(activity_id: str) -> dict:
    url = f"{FORTYGUARD_BASE_URL}/status/{activity_id}"

    max_attempts = 120
    poll_interval_seconds = 5

    for attempt in range(max_attempts):

        response = requests.get(
            url,
            headers=_headers(),
            timeout=10,
        )

        response.raise_for_status()

        payload = response.json()
        data = payload.get("data", {})

        status = data.get(
            "status",
            "",
        ).lower()

        if status in {
            "completed",
            "succeeded",
        }:
            return data.get(
                "result",
                {},
            )

        if status in {
            "failed",
            "error",
        }:
            raise RuntimeError(f"FortyGuard activity failed: {payload}")

        # Still processing.
        if attempt < max_attempts - 1:
            time.sleep(poll_interval_seconds)

    raise FortyGuardTimeout(
        f"FortyGuard activity {activity_id} "
        f"did not complete within "
        f"{max_attempts * poll_interval_seconds} seconds."
    )


def get_environmental_data(
    latitude: float,
    longitude: float,
    temperature: float,
    date: str | None = None,
    start_time: str | None = None,
) -> dict:

    if date is None:
        date = "2024-07-15"

    if start_time is None:
        start_time = "14:00"

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
        timeout=5,
    )

    response.raise_for_status()

    submission = response.json()

    if submission.get("error"):
        raise RuntimeError("FortyGuard submission failed: " f"{submission}")

    activity_id = submission["data"]["activity_id"]

    result = _poll_activity(activity_id)

    return _normalize_environment(result)


def _normalize_environment(
    result: dict,
) -> dict:

    locations = result.get(
        "locations",
        [],
    )

    if not locations:
        raise RuntimeError("FortyGuard returned no " "location data.")

    location = locations[0]

    parameters = location.get(
        "parameters",
        {},
    )

    solar = location.get(
        "solar_irradiance",
        {},
    )

    clear_sky = solar.get(
        "clear_sky",
        {},
    )

    def first_value(key: str):
        values = parameters.get(key)
        if values is None:
            return None
        if isinstance(values, list):
            return values[0] if values else None
        return values

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
        "metadata": result.get(
            "metadata",
            {},
        ),
    }
