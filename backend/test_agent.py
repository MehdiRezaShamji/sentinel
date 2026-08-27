from app.agents.graph import safety_agent_graph

initial_state = {
    "latitude": 40.7128,
    "longitude": -74.0060,
    "temperature": 32.5,
    "environment": {},
    "workers": [
        {
            "id": "W001",
            "name": "Alex",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "task": "Road maintenance",
            "exposure_minutes": 45,
            "status": "unresponsive",
            "buddy_id": "W002",
        },
        {
            "id": "W002",
            "name": "Jordan",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "task": "Equipment inspection",
            "exposure_minutes": 30,
            "status": "unresponsive",
            "buddy_id": "W001",
        },
        {
            "id": "W003",
            "name": "Sam",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "task": "Heavy road work",
            "exposure_minutes": 60,
            "status": "unresponsive",
            "buddy_id": "W001",
        },
    ],
    "incidents": [],
    "agent_actions": [],
    "current_step": "starting",
}


result = safety_agent_graph.invoke(initial_state)

print("\n=== AGENT RESULT ===")
print("Step:", result["current_step"])

print("\nActions:")
for action in result["agent_actions"]:
    print("-", action)

print("\nIncidents:")
for incident in result["incidents"]:
    print("-", incident)
