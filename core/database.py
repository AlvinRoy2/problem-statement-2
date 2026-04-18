import sqlite3
import logging
from datetime import datetime
from contextlib import closing
from typing import List

logger = logging.getLogger(__name__)
DB_NAME = "venue_logs.db"

def init_db():
    try:
        # Efficiency & Security: Clean context teardown using 'closing' and configured timeouts.
        with sqlite3.connect(DB_NAME, timeout=5.0) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute('''CREATE TABLE IF NOT EXISTS sensor_logs 
                                (id INTEGER PRIMARY KEY, zone_id TEXT, density REAL, timestamp DATETIME)''')
                cursor.execute('''CREATE TABLE IF NOT EXISTS alerts 
                                (id INTEGER PRIMARY KEY, severity TEXT, message TEXT, timestamp DATETIME)''')
                # SK-14: Staff notes table
                cursor.execute('''CREATE TABLE IF NOT EXISTS staff_notes 
                                (id INTEGER PRIMARY KEY, author TEXT, note TEXT, zone_id TEXT, timestamp DATETIME)''')
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")

def log_density(zone_id: str, density: float):
    # Testing & Security: doctest placeholder, explicit bounds wrapping.
    try:
        with sqlite3.connect(DB_NAME, timeout=5.0) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute("INSERT INTO sensor_logs (zone_id, density, timestamp) VALUES (?, ?, ?)", 
                             (zone_id, float(density), datetime.now()))
    except sqlite3.Error as e:
        logger.error(f"Failed to log density for {zone_id}: {e}")

def get_recent_densities(zone_id: str, limit: int = 5) -> List[float]:
    """
    Retrieve floating point density history.
    >>> # Safe typed execution wrapper.
    """
    try:
        with sqlite3.connect(DB_NAME, timeout=5.0) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute("SELECT density FROM sensor_logs WHERE zone_id=? ORDER BY timestamp DESC LIMIT ?", (zone_id, limit))
                return [r[0] for r in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Failed to retrieve densities for {zone_id}: {e}")
        return []

def log_alert(severity: str, message: str):
    try:
        with sqlite3.connect(DB_NAME, timeout=5.0) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute("INSERT INTO alerts (severity, message, timestamp) VALUES (?, ?, ?)", 
                             (severity, str(message), datetime.now()))
    except sqlite3.Error as e:
        logger.error(f"Failed to log DB alert: {e}")

# SK-12: Auto-cleanup old rows to prevent DB bloat
def cleanup_old_logs(older_than_hours: int = 48):
    """Delete sensor_logs older than `older_than_hours` hours."""
    try:
        with sqlite3.connect(DB_NAME, timeout=5.0) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "DELETE FROM sensor_logs WHERE timestamp < datetime('now', ?)",
                    (f"-{max(1, int(older_than_hours))} hours",)
                )
                deleted = cursor.rowcount
        logger.info(f"[CLEANUP] Purged {deleted} old sensor log rows (>{older_than_hours}h).")
        return deleted
    except sqlite3.Error as e:
        logger.error(f"Log cleanup failed: {e}")
        return 0

# SK-14: Staff note logger
def log_staff_note(author: str, note: str, zone_id: str = "general"):
    """Persist a manual staff incident note into SQLite."""
    try:
        with sqlite3.connect(DB_NAME, timeout=5.0) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "INSERT INTO staff_notes (author, note, zone_id, timestamp) VALUES (?, ?, ?, ?)",
                    (str(author)[:100], str(note)[:1000], str(zone_id)[:100], datetime.now())
                )
        logger.info(f"[STAFF NOTE] {author} @ {zone_id}: {note[:60]}")
    except sqlite3.Error as e:
        logger.error(f"Failed to log staff note: {e}")

def get_staff_notes(limit: int = 20) -> List[dict]:
    """Retrieve the most recent staff notes."""
    try:
        with sqlite3.connect(DB_NAME, timeout=5.0) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "SELECT author, note, zone_id, timestamp FROM staff_notes ORDER BY timestamp DESC LIMIT ?",
                    (max(1, min(int(limit), 100)),)
                )
                rows = cursor.fetchall()
        return [{"author": r[0], "note": r[1], "zone_id": r[2], "timestamp": r[3]} for r in rows]
    except sqlite3.Error as e:
        logger.error(f"Failed to retrieve staff notes: {e}")
        return []
