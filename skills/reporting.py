import sqlite3
import os
import logging
from datetime import datetime
from contextlib import closing
from core.database import DB_NAME, get_staff_notes

logger = logging.getLogger(__name__)

# SK-10: Markdown Post-Event Reporter
def generate_end_of_day_report() -> str:
    """Generate a Markdown report summarizing event analytics from SQLite."""
    os.makedirs("reports", exist_ok=True)
    file_name = f"report_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md"
    report_path = f"reports/{file_name}"
    
    try:
        with sqlite3.connect(DB_NAME, timeout=5.0) as conn:
            with closing(conn.cursor()) as cursor:
                # 1. Max density
                try:
                    cursor.execute("SELECT max(density) FROM sensor_logs")
                    row = cursor.fetchone()
                    max_density = round(row[0] * 100, 1) if row and row[0] is not None else 0.0
                except sqlite3.OperationalError:
                    max_density = 0.0
                
                # 2. Total alerts
                try:
                    cursor.execute("SELECT count(*) FROM alerts")
                    row_alerts = cursor.fetchone()
                    total_alerts = row_alerts[0] if row_alerts else 0
                except sqlite3.OperationalError:
                    total_alerts = 0
                
                # 3. Highest traffic zone
                try:
                    cursor.execute("SELECT zone_id, COUNT(*) FROM sensor_logs GROUP BY zone_id ORDER BY COUNT(*) DESC LIMIT 1")
                    row_zone = cursor.fetchone()
                    busiest_zone = row_zone[0] if row_zone else "N/A"
                except sqlite3.OperationalError:
                    busiest_zone = "N/A"
                
        # Security: formatting cleanly with no arbitrary executable injection
        report_md = f"""# SmartVenue Event Post-Mortem

**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Core Analytics
- **Maximum Recorded Crowd Density:** {max_density}%
- **Total Operational Alerts Dispatched:** {total_alerts}
- **Most Active Registered Zone:** {busiest_zone}

## Staff Incident Notes
"""
        # SK-14: Append all staff notes logged today
        notes = get_staff_notes(limit=50)
        if notes:
            for n in notes:
                report_md += f"- `[{n['timestamp']}]` **{n['author']}** ({n['zone_id']}): {n['note']}\n"
        else:
            report_md += "_No staff notes logged for this event._\n"

        report_md += "\n*Generated entirely on-device from local SQLite metrics without cloud dependencies.*\n"
        with open(report_path, "w") as f:
            f.write(report_md)
            
        logger.info(f"Report generated successfully at {report_path}")
        return file_name
    
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        raise
