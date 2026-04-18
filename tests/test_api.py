from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_api_state():
    """Test getting the current venue state."""
    response = client.get("/api/admin/state")
    assert response.status_code == 200
    assert "status" in response.json()
    assert "zones" in response.json()

def test_api_set_mode():
    """Test changing the semantic mode of the venue."""
    response = client.post("/api/admin/set_mode", params={"mode": "LIVE"})
    assert response.status_code == 200
    assert response.json()["mode"] == "LIVE"

def test_api_register_and_simulate_zone():
    """Test the full workflow of registering a zone and simulating crowd."""
    # 1. Register Action
    res_reg = client.post("/api/admin/zones", json={
        "zone_id": "Test_Zone_API",
        "capacity": 500,
        "service_time_sec": 30
    })
    assert res_reg.status_code == 200
    
    # 2. Simulate Action
    res_sim = client.post("/api/admin/simulate_crowd", params={
        "zone_id": "Test_Zone_API",
        "headcount": 100
    })
    assert res_sim.status_code == 200
    assert res_sim.json()["new_headcount"] == 100
    
    # 3. Request Dynamic Dashboard Route
    res_dash = client.get("/api/attendee/dashboard")
    assert res_dash.status_code == 200
    assert "Test_Zone_API" in res_dash.json()["zones"]
