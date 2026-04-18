from core.state import state
from core.database import log_density, get_recent_densities
from skills.coordination import dispatch_alert

# SK-01: Simple Crowd Density Estimator
def estimate_density(zone_id: str) -> float:
    z = state.get_zone(zone_id)
    if not z: 
        return 0.0
    
    try:
        # Security/Efficiency: Guard against division by zero mathematically.
        # Strict parsing of potentially malformed inputs
        capacity = max(1.0, float(z.get("capacity", 1.0)))
        headcount = max(0.0, float(z.get("current_headcount", 0.0)))
    except (ValueError, TypeError):
        return 0.0
        
    density = min(headcount / capacity, 1.0)
    density = round(density, 2)
    log_density(zone_id, density)
    return density

# SK-05: Moving-Average Anomaly Detector
def check_anomaly(zone_id: str, new_density: float):
    recent = get_recent_densities(zone_id, limit=5)
    if len(recent) >= 3:
        avg_density = sum(recent) / len(recent)
        if (new_density - avg_density) > 0.3:
            dispatch_alert("critical", f"Sudden crowd surge in {zone_id}! (Avg: {avg_density:.2f}, Now: {new_density:.2f})")
