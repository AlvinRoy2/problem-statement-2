import pytest
from skills.logic import predict_queue_wait
from skills.routing import compute_route
from skills.sensing import estimate_density
from core.state import state

# -- LOGIC TESTS --
def test_predict_queue_wait(monkeypatch):
    test_zones = {
        "zone1": {"current_headcount": 10, "service_time_sec": 30},
        "zone2": {"current_headcount": 0, "service_time_sec": 45},
        "zone3": {"current_headcount": -5, "service_time_sec": -10}, # Handled by max(0)
        "zone4": {"current_headcount": "bad_data", "service_time_sec": 30} # Handled by try/except
    }
    monkeypatch.setattr(state, 'zones', test_zones)
    
    assert predict_queue_wait("zone1") == 5.0
    assert predict_queue_wait("zone2") == 0.0
    assert predict_queue_wait("zone3") == 0.0
    assert predict_queue_wait("zone4") == 0.0
    assert predict_queue_wait("invalid_zone") == 0.0

# -- SENSING TESTS --
def test_estimate_density(monkeypatch):
    test_zones = {
        "zoneA": {"current_headcount": 50, "capacity": 100},
        "zoneB": {"current_headcount": 150, "capacity": 100}, # Clamped to 1.0 by min()
        "zoneC": {"current_headcount": "bad", "capacity": 10} # Exception guard
    }
    monkeypatch.setattr(state, '_get_zone', lambda z: test_zones.get(z))
    # State mock logic since it's a class with get_zone method
    monkeypatch.setattr(state, 'get_zone', lambda z: test_zones.get(z))
    
    # We will patch log_density so we don't need real DB
    import skills.sensing
    monkeypatch.setattr(skills.sensing, 'log_density', lambda z, d: None)
    
    assert estimate_density("zoneA") == 0.5
    assert estimate_density("zoneB") == 1.0
    assert estimate_density("zoneC") == 0.0

# -- ROUTING TESTS --
def test_routing_accessibility(monkeypatch):
    test_zones = {
        "Concourse": {},
        "Food Stand": {},
        "Stairs to VIP": {}
    }
    monkeypatch.setattr(state, 'zones', test_zones)
    
    densities = {"Concourse": 0.1, "Food Stand": 0.2, "Stairs to VIP": 0.1}
    
    # Normal route
    path_normal = compute_route("Concourse", "Stairs to VIP", False, densities)
    assert path_normal == ["Concourse", "Stairs to VIP"]
    
    # Accessible route: penalty applies but still returns path because star map enforces it
    path_access = compute_route("Concourse", "Stairs to VIP", True, densities)
    assert path_access == ["Concourse", "Stairs to VIP"]
