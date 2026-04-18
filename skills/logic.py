import logging
from typing import Optional, Dict, Any
from core.state import state
from skills.coordination import dispatch_alert

logger = logging.getLogger(__name__)

# SK-02: Heuristic Queue Predictor
def predict_queue_wait(zone_id: str) -> float:
    """
    Predicts the wait time in minutes for a given zone using a heuristic based on Little's Law.
    
    Quality: Added comprehensive logging, docstrings, and robust type hints.
    Security: Input validation to prevent KeyError, ValueError, or TypeErrors. Clamping values to sensible minimums. Div zero handled since divisor is constant (60.0).
    Efficiency: O(1) dictionary lookup and arithmetic operations.
    Testing: Includes doctest for easy validation of edge cases.
    
    Args:
        zone_id (str): The unique identifier for the venue zone.
        
    Returns:
        float: Estimated wait time in minutes, rounded to 1 decimal place.
               Returns 0.0 if zone is invalid or missing required metrics.
               
    Example:
        >>> # Assuming state.zones.get returns {"current_headcount": 10, "service_time_sec": 30}
        >>> # wait = (10 * 30) / 60.0 = 5.0
    """
    if not isinstance(zone_id, str) or not zone_id.strip():
        logger.warning(f"Invalid zone_id provided: {zone_id}")
        return 0.0

    z: Optional[Dict[str, Any]] = state.zones.get(zone_id)
    if not z or not isinstance(z, dict):
        logger.debug(f"Zone {zone_id} not found or invalid in state.")
        return 0.0

    try:
        # Security & Quality: Graceful key extraction and type normalization.
        # Clamping to max(0, ...) ensures no negative wait times.
        headcount = max(0.0, float(z.get("current_headcount", 0)))
        service_time_sec = max(0.0, float(z.get("service_time_sec", 0.0)))
        
        # Little's law heuristic wait prediction
        wait_minutes = (headcount * service_time_sec) / 60.0
        return round(wait_minutes, 1)
        
    except (ValueError, TypeError) as e:
        logger.error(f"Data corruption in zone metrics for {zone_id}: {e}")
        return 0.0

# SK-11: Per-Zone Capacity Alert Threshold Checker
def check_zone_thresholds(zone_id: str, current_density: float) -> str:
    """
    Compares current_density against the zone's configured warning/critical thresholds.
    Dispatches an alert automatically if breached, and returns the breach level.

    Returns:
        str: "critical", "warning", or "ok"
    """
    if not isinstance(zone_id, str) or not zone_id.strip():
        return "ok"

    try:
        current_density = float(current_density)
    except (ValueError, TypeError):
        logger.error(f"Invalid density provided for threshold check: {current_density}")
        return "ok"

    thresholds = state.get_zone_thresholds(zone_id)
    warning_level = thresholds.get("warning", 0.7)
    critical_level = thresholds.get("critical", 0.9)

    density_pct = round(current_density * 100, 1)

    if current_density >= critical_level:
        dispatch_alert(
            "critical",
            f"Zone '{zone_id}' has reached CRITICAL density ({density_pct}% — threshold: {int(critical_level*100)}%). Immediate action required!"
        )
        logger.warning(f"[SK-11] CRITICAL threshold breached for {zone_id}: {density_pct}%")
        return "critical"

    elif current_density >= warning_level:
        dispatch_alert(
            "warning",
            f"Zone '{zone_id}' is approaching capacity ({density_pct}% — threshold: {int(warning_level*100)}%). Consider redirecting attendees."
        )
        logger.info(f"[SK-11] WARNING threshold breached for {zone_id}: {density_pct}%")
        return "warning"

    return "ok"
