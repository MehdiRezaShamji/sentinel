import requests
import json
import time

API_URL = "http://127.0.0.1:8000/api"

def test_workflow():
    print("--- SENTINEL LIVE API TEST ---")
    
    # 1. Reset state
    print("Resetting scenario state...")
    res = requests.post(f"{API_URL}/demo/reset")
    assert res.status_code == 200, f"Reset failed: {res.text}"
    print("Reset OK.")
    
    # 2. Get status (should be stopped or active from initial baseline)
    res = requests.get(f"{API_URL}/monitor/status")
    assert res.status_code == 200
    status_data = res.json()
    print(f"Monitoring active: {status_data['active']}")
    
    # 3. Start monitoring
    print("Starting monitoring...")
    res = requests.post(f"{API_URL}/monitor/start")
    assert res.status_code == 200
    print("Start monitoring response:", res.json())
    
    # 4. Set emergency response to True
    print("Enabling emergency response...")
    res = requests.post(f"{API_URL}/monitor/emergency", json={"enabled": True})
    assert res.status_code == 200
    print("Emergency response status:", res.json())
    
    # 5. Let's inspect the workers in state
    res = requests.get(f"{API_URL}/monitor/status")
    state = res.json()["state"]
    print("Workers in state:")
    for w in state["workers"]:
        print(f" - {w['name']} ({w['id']}): status={w['status']}, check_in_status={w['check_in_status']}, phone={w['phone']}")
        
    # 6. Verify Telegram endpoints
    print("\nVerifying Telegram API status endpoint...")
    res = requests.get(f"{API_URL}/telegram/status")
    assert res.status_code == 200
    print("Telegram status:", res.json())
    
    # Check status again
    res = requests.get(f"{API_URL}/monitor/status")
    state = res.json()["state"]
    print("\nState actions:")
    for act in state["agent_actions"][-5:]:
        print(f" * {act}")
        
    print("\nStop monitoring...")
    res = requests.post(f"{API_URL}/monitor/stop")
    assert res.status_code == 200
    print("Monitoring stopped.")
    
    print("\n--- LIVE API TEST SUCCESS ---")

if __name__ == "__main__":
    test_workflow()
