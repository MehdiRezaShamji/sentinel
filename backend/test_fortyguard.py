from app.services.fortyguard import get_environmental_data

result = get_environmental_data(
    latitude=40.7128,
    longitude=-74.0060,
    temperature=32.5,
    date="2024-07-15",
    start_time="14:00",
)

print("\n=== ENVIRONMENTAL OBSERVATION ===")

for key, value in result.items():
    print(f"{key}: {value}")
