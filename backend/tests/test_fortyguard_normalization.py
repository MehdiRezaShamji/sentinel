import os
import sys
import unittest

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from app.services.fortyguard import _normalize_environment

class TestFortyGuardNormalization(unittest.TestCase):
    def test_normalize_valid_response(self):
        raw_response = {
            "metadata": {
                "timezone": "GMT-5"
            },
            "locations": [
                {
                    "lat": 40.7128,
                    "lon": -74.006,
                    "temperature": 32.5,
                    "parameters": {
                        "heat_index_celsius": [36.8],
                        "apparent_temperature_celsius": [38.4],
                        "relative_humidity_percent": [55.3],
                        "precipitation_mm": [0.0],
                        "cloud_cover_octas": [31.0],
                        "wet_bulb_temperature_celsius": [26.6],
                        "air_quality:idx": [121.5]
                    },
                    "solar_irradiance": {
                        "clear_sky": {
                            "ghi": 820.64,
                            "dni": 808.81,
                            "dhi": 131.41
                        }
                    }
                }
            ]
        }
        
        normalized = _normalize_environment(raw_response)
        
        self.assertEqual(normalized["latitude"], 40.7128)
        self.assertEqual(normalized["longitude"], -74.006)
        self.assertEqual(normalized["temperature_c"], 32.5)
        self.assertEqual(normalized["heat_index_c"], 36.8)
        self.assertEqual(normalized["apparent_temperature_c"], 38.4)
        self.assertEqual(normalized["humidity_percent"], 55.3)
        self.assertEqual(normalized["wet_bulb_c"], 26.6)
        self.assertEqual(normalized["precipitation_mm"], 0.0)
        self.assertEqual(normalized["cloud_cover_octas"], 31.0)
        self.assertEqual(normalized["air_quality_index"], 121.5)
        self.assertEqual(normalized["solar_irradiance"]["ghi"], 820.64)
        self.assertEqual(normalized["metadata"]["timezone"], "GMT-5")

    def test_normalize_empty_parameters(self):
        raw_response = {
            "metadata": {},
            "locations": [
                {
                    "lat": 40.7128,
                    "lon": -74.006,
                    "temperature": 32.5,
                    "parameters": {
                        "heat_index_celsius": [],
                        "apparent_temperature_celsius": [],
                        "relative_humidity_percent": [],
                        "precipitation_mm": [],
                        "cloud_cover_octas": [],
                        "wet_bulb_temperature_celsius": [],
                        "air_quality:idx": []
                    },
                    "solar_irradiance": {
                        "clear_sky": {
                            "ghi": 0.0,
                            "dni": 0.0,
                            "dhi": 0.0
                        }
                    }
                }
            ]
        }
        
        normalized = _normalize_environment(raw_response)
        
        self.assertEqual(normalized["latitude"], 40.7128)
        self.assertEqual(normalized["temperature_c"], 32.5)
        self.assertIsNone(normalized["heat_index_c"])
        self.assertIsNone(normalized["apparent_temperature_c"])
        self.assertIsNone(normalized["humidity_percent"])
        self.assertIsNone(normalized["wet_bulb_c"])
        self.assertIsNone(normalized["precipitation_mm"])
        self.assertIsNone(normalized["cloud_cover_octas"])
        self.assertIsNone(normalized["air_quality_index"])

    def test_normalize_scalar_and_null_parameters(self):
        raw_response = {
            "metadata": {},
            "locations": [
                {
                    "lat": 40.7128,
                    "lon": -74.006,
                    "temperature": 32.5,
                    "parameters": {
                        "heat_index_celsius": 36.8,
                        "apparent_temperature_celsius": None,
                        "relative_humidity_percent": [55.3],
                        "precipitation_mm": None,
                        "cloud_cover_octas": 31,
                        "wet_bulb_temperature_celsius": [],
                        "air_quality:idx": None
                    },
                    "solar_irradiance": {
                        "clear_sky": {
                            "ghi": 0.0,
                            "dni": 0.0,
                            "dhi": 0.0
                        }
                    }
                }
            ]
        }
        
        normalized = _normalize_environment(raw_response)
        
        self.assertEqual(normalized["heat_index_c"], 36.8)
        self.assertIsNone(normalized["apparent_temperature_c"])
        self.assertEqual(normalized["humidity_percent"], 55.3)
        self.assertIsNone(normalized["precipitation_mm"])
        self.assertEqual(normalized["cloud_cover_octas"], 31)
        self.assertIsNone(normalized["wet_bulb_c"])
        self.assertIsNone(normalized["air_quality_index"])

class TestFortyGuardDemoPollingBound(unittest.TestCase):
    """Regression: in DEMO_MODE the FortyGuard activity poll must be bounded
    (~12s) so a slow activity falls back instead of stalling the demo for up
    to 10 minutes. Production polling must remain unchanged."""

    def _run_with_mocks(self, demo_mode_env):
        import time
        import requests as req
        import app.services.fortyguard as fg

        original_env = os.environ.get("DEMO_MODE")
        orig_get, orig_post, orig_sleep = req.get, req.post, time.sleep
        attempts = {"count": 0}

        class FakeResponse:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return {"data": {"status": "processing"}}

        class FakeSubmission:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return {"data": {"activity_id": "act-1"}}

        def fake_get(*args, **kwargs):
            attempts["count"] += 1
            return FakeResponse()

        def fake_post(*args, **kwargs):
            return FakeSubmission()

        req.get = fake_get
        req.post = fake_post
        time.sleep = lambda seconds: None
        if demo_mode_env is None:
            os.environ.pop("DEMO_MODE", None)
        else:
            os.environ["DEMO_MODE"] = demo_mode_env
        try:
            with self.assertRaises(fg.FortyGuardTimeout):
                fg.get_environmental_data(40.7128, -74.006, 32.5)
        finally:
            req.get = orig_get
            req.post = orig_post
            time.sleep = orig_sleep
            if original_env is None:
                os.environ.pop("DEMO_MODE", None)
            else:
                os.environ["DEMO_MODE"] = original_env
        return attempts["count"]

    def test_demo_mode_polling_is_bounded(self):
        attempts = self._run_with_mocks("true")
        self.assertLessEqual(attempts, 5, f"Demo polling made {attempts} attempts; expected demo bound (~3)")

    def test_production_polling_bounds_unchanged(self):
        attempts = self._run_with_mocks(None)
        self.assertEqual(attempts, 120, "Production polling bound must remain 120 attempts")


if __name__ == "__main__":
    unittest.main()
