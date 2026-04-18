import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SystemState:
    """
    Quality: Core system state class enforcing types and validations.
    """
    def __init__(self):
        self._mode = "PRE_EVENT"
        # Seed with a default main hub so the map isn't totally blank initially
        self._zones: Dict[str, Dict[str, Any]] = {
            "Main_Hub": {"capacity": 1000, "current_headcount": 0, "service_time_sec": 5}
        }
        # SK-11: Per-zone density alert thresholds {zone_id: {"warning": float, "critical": float}}
        self._thresholds: Dict[str, Dict[str, float]] = {}

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        # Security: State validation bounds
        valid_modes = ["PRE_EVENT", "LIVE", "EGRESS", "POST_EVENT"]
        if value in valid_modes:
            self._mode = value
        else:
            logger.warning(f"Attempted to set invalid mode: {value}")
            raise ValueError(f"Invalid mode. Must be one of {valid_modes}")

    @property
    def zones(self) -> Dict[str, Dict[str, Any]]:
        return self._zones
        
    def get_zone(self, zone_id: str) -> Dict[str, Any]:
        """Efficiency: Safe dictionary lookups."""
        return self._zones.get(zone_id, {})
        
    def update_headcount(self, zone_id: str, headcount: int):
        """Security: Ensuring bounds and validating existing keys natively."""
        if zone_id in self._zones:
            # Clamp headcount from going negative mathematically.
            self._zones[zone_id]["current_headcount"] = max(0, int(headcount))
            logger.debug(f"Updated {zone_id} headcount to {self._zones[zone_id]['current_headcount']}")
        else:
            logger.warning(f"Zone update failed; {zone_id} does not exist.")
            raise KeyError(f"Zone {zone_id} not found.")

    def register_zone(self, zone_id: str, capacity: int, service_time_sec: int):
        clean_id = str(zone_id).replace(" ", "_")
        if not clean_id:
            raise ValueError("Zone ID cannot be empty.")
            
        self._zones[clean_id] = {
            "capacity": max(1, int(capacity)),
            "current_headcount": 0,
            "service_time_sec": max(1, int(service_time_sec))
        }
        logger.info(f"Registered new dynamic zone: {clean_id} (Cap: {capacity})")

    def remove_zone(self, zone_id: str):
        if zone_id in self._zones:
            del self._zones[zone_id]
            self._thresholds.pop(zone_id, None)
            logger.info(f"Removed dynamic zone: {zone_id}")
        else:
            raise KeyError(f"Zone {zone_id} not found.")

    # SK-11: Per-zone threshold management
    def set_zone_thresholds(self, zone_id: str, warning: float = 0.7, critical: float = 0.9):
        """Set custom density alert thresholds for a specific zone."""
        if zone_id not in self._zones:
            raise KeyError(f"Zone {zone_id} not found.")
        warning = max(0.0, min(1.0, float(warning)))
        critical = max(0.0, min(1.0, float(critical)))
        if warning >= critical:
            raise ValueError("Warning threshold must be less than critical threshold.")
        self._thresholds[zone_id] = {"warning": warning, "critical": critical}
        logger.info(f"Set thresholds for {zone_id}: warning={warning}, critical={critical}")

    def get_zone_thresholds(self, zone_id: str) -> Dict[str, float]:
        """Return thresholds for a zone, falling back to system defaults."""
        return self._thresholds.get(zone_id, {"warning": 0.7, "critical": 0.9})

state = SystemState()
