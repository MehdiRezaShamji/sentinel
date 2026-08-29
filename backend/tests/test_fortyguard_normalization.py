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

if __name__ == "__main__":
    unittest.main()
