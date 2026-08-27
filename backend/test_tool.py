from app.tools.fortyguard_tools import observe_environment

result = observe_environment.invoke(
    {
        "latitude": 40.7128,
        "longitude": -74.0060,
        "temperature": 32.5,
        "date": "2024-07-15",
        "start_time": "14:00",
    }
)

print("\n=== AGENT ENVIRONMENT TOOL ===")

for key, value in result.items():
    print(f"{key}: {value}")
