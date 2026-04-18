import requests
import logging
from core.database import log_alert
from skills.illuminate import query_ai_coordinator
from core.state import state

logger = logging.getLogger(__name__)

# SK-04: Notification Bounty Push
def send_bounty_push(overloaded: str, alternative: str):
    msg = f"Queue at {overloaded} is long! Try {alternative} instead for a faster wait."
    logger.info(f"[NTFY PUSH] {msg}")
    try:
        # Security: explicit 5s timeout and narrow exception handling
        requests.post("https://ntfy.sh/smartvenue_alerts", data=msg.encode('utf-8'), timeout=5)
    except requests.RequestException as e:
        logger.warning(f"Failed to send bounty push due to network error: {e}")

# SK-06: Scheduled Egress Announcer (AI Enhanced)
def run_egress_announcements():
    # Security: state._zones representation is local and strict, safe for prompt passing.
    prompt = f"The event has triggered EGRESS mode. Here are the current gate crowds: {state.zones}. Write a 2-sentence public announcement script directing people away from crowded food stands and towards the exits with the lowest headcount capacity."
    script = query_ai_coordinator(
        prompt=prompt,
        system_prompt="You are a stadium PA Announcer. Output ONLY the speech script you would read."
    )
    
    logger.info(f"[PA SYSTEM AUDIO GENERATED] -> {script}")

# SK-07: FOSS Alert Dispatcher (AI Enhanced)
def dispatch_alert(severity: str, raw_event_message: str):
    # Instead of robotic alerts, have the AI synthesize the context
    prompt = f"An operation alert was triggered. Raw log: {str(severity).upper()} - {str(raw_event_message)}. Turn this into a concise Slack/Discord ping for the steward team and suggest one immediate physical action they should take."
    
    refined_alert = query_ai_coordinator(
        prompt=prompt,
        system_prompt="You are the Ops AI Supervisor. Be helpful and clear."
    )
    
    # If API is missing, fallback to raw message
    if refined_alert.startswith("[AI"):
        refined_alert = raw_event_message
        
    logger.critical(f"[ALERT DISPATCH] {severity.upper()}:\n{refined_alert}")
    log_alert(severity, refined_alert)
