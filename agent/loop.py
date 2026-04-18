import asyncio
import logging
from core.state import state
from core.database import cleanup_old_logs
from core.events import broadcast
from skills.sensing import estimate_density, check_anomaly
from skills.logic import predict_queue_wait, check_zone_thresholds
from skills.coordination import send_bounty_push, run_egress_announcements
from skills.illuminate import query_ai_coordinator

logger = logging.getLogger(__name__)


def _current_state_payload() -> dict:
    return {"mode": state.mode, "zones": dict(state.zones)}


async def agent_execution_loop(max_iterations: int = -1):
    logger.info("Starting SmartVenue Agent Continuous Loop...")
    loop_count = 0

    while True:
        if max_iterations > 0 and loop_count >= max_iterations:
            break

        try:
            logger.debug(f"--- Cycle Tick [{state.mode}] ---")
            loop_count += 1
            state_changed = False

            for zone_id in list(state.zones.keys()):
                # 1. SENSE — density is logged to SQLite; headcounts don't change here
                density = estimate_density(zone_id)
                check_anomaly(zone_id, density)

                # 2. INFER & DECIDE
                wait_time = predict_queue_wait(zone_id)

                # SK-11: Evaluate per-zone capacity thresholds
                check_zone_thresholds(zone_id, density)

                if wait_time > 10 and "Food_Stand" in zone_id:
                    alt = "Food_Stand_B" if zone_id == "Food_Stand_A" else "Food_Stand_A"
                    if predict_queue_wait(alt) < 5:
                        send_bounty_push(zone_id, alt)

                state_changed = True  # density logged each cycle; push snapshot

            # EGRESS MODE Action
            if state.mode == "EGRESS":
                run_egress_announcements()

            # 3. AI SUPERVISION OVERLAY — every 5th loop
            if loop_count % 5 == 0:
                logger.info("[AI SUPERVISOR HEALTH CHECK]")
                prompt = f"The venue is in mode {state.mode}. Gate/Stand status: {state.zones}. If any capacity > 300, warn us, else say 'All good'."
                response = query_ai_coordinator(prompt)
                logger.info(f"-> {response}")

            # SK-12: Purge old sensor logs every 50 cycles (~8 minutes at 10s tick)
            if loop_count % 50 == 0:
                cleanup_old_logs(older_than_hours=48)

            # Broadcast updated state to all SSE clients after every agent tick
            if state_changed:
                await broadcast(_current_state_payload())

        except Exception as e:
            # Quality & Security: prevent unhandled exception stack dumps from exiting loop
            logger.exception(f"Error in agent cycle: {e}")

        await asyncio.sleep(10)
