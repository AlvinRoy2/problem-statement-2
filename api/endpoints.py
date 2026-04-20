from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import asyncio
import json
import re
from core.state import state
from core.events import subscribe, unsubscribe, broadcast
from core.database import cleanup_old_logs, log_staff_note, get_staff_notes
from skills.routing import compute_route
from skills.sensing import estimate_density
from skills.logic import predict_queue_wait, check_zone_thresholds
from skills.illuminate import query_ai_coordinator
from skills.reporting import generate_end_of_day_report
from skills.google_services import (
    semantic_search_notes,
    query_with_function_calling,
    analyze_report_with_gemini,
    query_with_grounding,
)

router = APIRouter()

# ── Helpers ────────────────────────────────────────────────────────────────

def _current_state_payload() -> dict:
    """Build the canonical state snapshot broadcast to all SSE clients."""
    from api.endpoints import get_dashboard_snapshot
    return get_dashboard_snapshot()


async def _broadcast_state() -> None:
    await broadcast(_current_state_payload())


# ── Request Models ─────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    # Security: Constrain input sizes
    message: str = Field(..., max_length=500)

class ZoneRegisterRequest(BaseModel):
    zone_id: str = Field(..., max_length=100)
    capacity: int = Field(..., gt=0)
    service_time_sec: int = Field(default=10, gt=0)

class ZoneThresholdRequest(BaseModel):
    """SK-11: Set per-zone density alert thresholds."""
    zone_id: str = Field(..., max_length=100)
    warning: float = Field(default=0.7, ge=0.0, le=1.0, description="Fraction (0-1) to trigger a warning alert")
    critical: float = Field(default=0.9, ge=0.0, le=1.0, description="Fraction (0-1) to trigger a critical alert")

class StaffNoteRequest(BaseModel):
    """SK-14: Log a manual staff incident note."""
    author: str = Field(..., max_length=100)
    note: str = Field(..., max_length=1000)
    zone_id: str = Field(default="general", max_length=100)


class SemanticSearchRequest(BaseModel):
    """SK-15: Semantic staff-note search query."""
    query: str = Field(..., max_length=300, description="Natural-language search query.")
    top_k: int = Field(default=5, ge=1, le=20)


class AiActionRequest(BaseModel):
    """SK-16: Structured function-calling chat request."""
    message: str = Field(..., max_length=500)


class GroundingRequest(BaseModel):
    """SK-18: Real-time grounded search query."""
    topic: str = Field(
        ...,
        max_length=400,
        description="Topic or question to answer with live Google Search context.",
    )


# ── SSE Stream ─────────────────────────────────────────────────────────────

@router.get("/stream")
async def sse_stream(request: Request):
    """
    Server-Sent Events endpoint — push state to frontend instantly on any change.
    The frontend connects once; the backend pushes whenever state mutates.
    A keepalive comment is sent every 15s to prevent proxy/browser timeouts.
    """
    q = subscribe()

    async def event_generator():
        # Send the current state immediately on connect so the UI isn't blank
        yield f"data: {json.dumps(_current_state_payload())}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive — prevents proxies / browsers from dropping idle connections
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable Nginx buffering if proxied
        },
    )


# ── Zone Management ────────────────────────────────────────────────────────

@router.post("/admin/zones")
async def register_zone(req: ZoneRegisterRequest) -> Dict[str, Any]:
    try:
        state.register_zone(req.zone_id, req.capacity, req.service_time_sec)
        await _broadcast_state()
        return {"status": "success", "zone": req.zone_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/admin/zones/{zone_id}")
async def remove_zone(zone_id: str) -> Dict[str, Any]:
    try:
        state.remove_zone(zone_id)
        await _broadcast_state()
        return {"status": "success", "zone": zone_id}
    except KeyError:
        raise HTTPException(status_code=404, detail="Zone not found.")

@router.post("/admin/set_mode")
async def set_mode(mode: str) -> Dict[str, Any]:
    try:
        state.mode = mode
        await _broadcast_state()
        return {"status": "success", "mode": state.mode}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/admin/state")
def get_state() -> Dict[str, Any]:
    return {"status": "success", "mode": state.mode, "zones": state.zones}

@router.post("/admin/simulate_crowd")
async def simulate_crowd(zone_id: str, headcount: int) -> Dict[str, Any]:
    try:
        state.update_headcount(zone_id, headcount)
        await _broadcast_state()
        return {"status": "success", "zone": zone_id, "new_headcount": state.get_zone(zone_id)["current_headcount"]}
    except KeyError:
        raise HTTPException(status_code=404, detail="Zone not found.")

@router.get("/attendee/route")
def get_route(start: str, end: str, accessible_only: bool = False) -> Dict[str, Any]:
    densities = {z: estimate_density(z) for z in state.zones.keys()}
    path = compute_route(start, end, accessible_only, densities)
    if path:
        return {"status": "success", "route": path}
    raise HTTPException(status_code=404, detail="No valid route found or nodes do not exist.")

@router.post("/admin/generate_report")
def generate_report() -> Dict[str, Any]:
    try:
        report_file = generate_end_of_day_report()
        return {"status": "success", "file": report_file}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to generate report.")


# ── AI Chat with Agentic Actions ───────────────────────────────────────────

@router.post("/admin/chat")
async def chat_with_agent(req: ChatRequest) -> Dict[str, Any]:
    valid_modes = ["PRE_EVENT", "LIVE", "EGRESS", "POST_EVENT"]
    zone_list = list(state.zones.keys())

    # Prompt Steering: AI outputs structured action tags for backend execution.
    prompt = (
        f"Current State -> Mode: {state.mode}. Known zones: {zone_list}.\n"
        f"Staff asks: {req.message}\n"
        f"Rules:\n"
        f"- If they ask to change mode to one of {valid_modes}, reply with [ACTION: SET_MODE: <MODE>].\n"
        f"- If they ask to update/set/add people or headcount for a zone, reply with [ACTION: UPDATE_HEADCOUNT: <ZONE_ID>:<COUNT>] using the exact zone_id from the known zones list."
    )

    response = query_ai_coordinator(
        prompt=prompt,
        system_prompt="You are an intelligent ops assistant for SmartVenue. You can take actions by outputting special bracket tags. Keep verbosity to 2 sentences."
    )

    has_action = False
    action_logs = []

    # Parse for mode change
    mode_match = re.search(r'\[ACTION:\s*SET_MODE:\s*(.*?)\]', response)
    if mode_match:
        new_mode = mode_match.group(1).strip().upper()
        if new_mode in valid_modes:
            state.mode = new_mode
            has_action = True
            action_logs.append(f"Mode changed to {new_mode}")

    # Parse for headcount update(s)
    for hc_match in re.finditer(r'\[ACTION:\s*UPDATE_HEADCOUNT:\s*([^:\]]+):([\d]+)\]', response):
        zone_id = hc_match.group(1).strip()
        count = int(hc_match.group(2).strip())
        try:
            state.update_headcount(zone_id, count)
            has_action = True
            action_logs.append(f"Headcount for {zone_id} updated to {count}")
        except KeyError:
            action_logs.append(f"Zone '{zone_id}' not found — headcount not updated")

    # Broadcast immediately if any action changed state
    if has_action:
        await _broadcast_state()

    # Strip all action tags from the user-facing response
    response = re.sub(r'\[ACTION:.*?\]', '', response).strip()

    if has_action:
        response += "\n\n⚙️ " + " | ".join(action_logs)

    return {"status": "success", "response": response}


# ─── SK-11: Per-Zone Threshold Configuration ───────────────────────────────

@router.post("/admin/zones/thresholds")
async def set_zone_thresholds(req: ZoneThresholdRequest) -> Dict[str, Any]:
    """
    Set custom density alert thresholds for a zone.
    warning (default 0.7 = 70%) fires a staff advisory.
    critical (default 0.9 = 90%) fires an urgent critical alert.
    """
    try:
        state.set_zone_thresholds(req.zone_id, req.warning, req.critical)
        await _broadcast_state()
        return {
            "status": "success",
            "zone": req.zone_id,
            "thresholds": {"warning": req.warning, "critical": req.critical}
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── SK-12: Manual Log Cleanup ─────────────────────────────────────────────

@router.post("/admin/cleanup_logs")
def trigger_log_cleanup(older_than_hours: int = 48) -> Dict[str, Any]:
    """
    Manually purge sensor_logs older than `older_than_hours` hours.
    The agent loop also runs this automatically every ~8 minutes.
    """
    if older_than_hours < 1 or older_than_hours > 720:
        raise HTTPException(status_code=400, detail="older_than_hours must be between 1 and 720.")
    deleted = cleanup_old_logs(older_than_hours)
    return {"status": "success", "rows_deleted": deleted, "older_than_hours": older_than_hours}


# ─── SK-13: Live Dashboard Snapshot ────────────────────────────────────────

@router.get("/attendee/dashboard")
def get_dashboard_snapshot() -> Dict[str, Any]:
    """
    Returns a computed real-time snapshot of all zones:
    density %, estimated queue wait, threshold status colour, and mode.
    Perfect for powering a React dashboard card grid with zero extra logic.
    """
    zone_snapshots = {}
    for zone_id in list(state.zones.keys()):
        density = estimate_density(zone_id)
        wait_min = predict_queue_wait(zone_id)
        thresholds = state.get_zone_thresholds(zone_id)

        if density >= thresholds["critical"]:
            status_label = "critical"
            colour = "#FF4444"
        elif density >= thresholds["warning"]:
            status_label = "warning"
            colour = "#FFA500"
        else:
            status_label = "ok"
            colour = "#44CC77"

        zone_snapshots[zone_id] = {
            "density_pct": round(density * 100, 1),
            "queue_wait_min": wait_min,
            "status": status_label,
            "colour": colour,
            "capacity": state.zones[zone_id]["capacity"],
            "current_headcount": state.zones[zone_id]["current_headcount"],
            "thresholds": thresholds,
        }

    return {"status": "success", "mode": state.mode, "zones": zone_snapshots}


# ─── SK-14: Staff Incident Notes ───────────────────────────────────────────

@router.post("/staff/notes")
async def post_staff_note(req: StaffNoteRequest) -> Dict[str, Any]:
    """
    Log a manual staff incident note from any device.
    Notes are stored in SQLite and appear in the end-of-day Markdown report.
    """
    log_staff_note(req.author, req.note, req.zone_id)
    await _broadcast_state()
    return {"status": "success", "author": req.author, "zone_id": req.zone_id}

@router.get("/staff/notes")
def list_staff_notes(limit: int = 20) -> Dict[str, Any]:
    """Retrieve the most recent staff incident notes (max 100)."""
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100.")
    notes = get_staff_notes(limit=limit)
    return {"status": "success", "count": len(notes), "notes": notes}


# ─── SK-15: Semantic Staff Note Search (Gemini Embeddings) ─────────────────

@router.post("/staff/notes/search")
def semantic_note_search(req: SemanticSearchRequest) -> Dict[str, Any]:
    """
    SK-15: Semantically search staff incident notes using Gemini text-embedding-004.
    Returns the most relevant notes ranked by cosine similarity to the query.
    No GCP project required — uses GOOGLE_API_KEY from AI Studio.
    """
    all_notes = get_staff_notes(limit=100)
    if not all_notes:
        return {"status": "success", "count": 0, "results": []}

    results = semantic_search_notes(req.query, all_notes, top_k=req.top_k)
    return {
        "status": "success",
        "query": req.query,
        "count": len(results),
        "results": results,
    }


# ─── SK-16: AI Function-Calling Chat (Gemini Function Calling) ─────────────

@router.post("/admin/ai_action")
async def ai_function_action(req: AiActionRequest) -> Dict[str, Any]:
    """
    SK-16: Send a staff request to Gemini with structured function-calling tools.
    Gemini may invoke get_zone_status, set_venue_mode, update_zone_headcount,
    or dispatch_alert as structured actions that the backend executes immediately.
    No GCP project required — uses GOOGLE_API_KEY from AI Studio.
    """
    result = query_with_function_calling(
        prompt=req.message,
        zone_data=state.zones,
        current_mode=state.mode,
    )

    # Execute parsed function-call actions against live state
    executed: list[str] = []
    for action in result.get("actions", []):
        fn   = action.get("function", "")
        args = action.get("args", {})
        try:
            if fn == "set_venue_mode" and "mode" in args:
                state.mode = args["mode"].upper()
                executed.append(f"Mode → {state.mode}")
            elif fn == "update_zone_headcount" and "zone_id" in args and "count" in args:
                state.update_headcount(args["zone_id"], int(args["count"]))
                executed.append(f"Headcount {args['zone_id']} → {args['count']}")
            elif fn == "dispatch_alert":
                executed.append(
                    f"Alert [{args.get('severity','?')}]: {args.get('message','')[:80]}"
                )
            # get_zone_status is read-only — no state mutation needed
        except (KeyError, ValueError) as e:
            executed.append(f"Action '{fn}' failed: {e}")

    if executed:
        await _broadcast_state()

    response_text = result.get("response", "")
    if executed:
        response_text += "\n\n⚙️ " + " | ".join(executed)

    return {
        "status": "success",
        "response": response_text,
        "actions_executed": executed,
        "raw_actions": result.get("actions", []),
    }


# ─── SK-17: Gemini Files API Report Analysis ───────────────────────────────

@router.post("/admin/analyze_report")
def analyze_last_report(report_filename: str) -> Dict[str, Any]:
    """
    SK-17: Upload a previously generated Markdown report to the Gemini Files API
    and receive an AI-generated executive summary with improvement recommendations.
    No GCP project required — uses GOOGLE_API_KEY from AI Studio.
    """
    import os
    report_path = os.path.join("reports", report_filename)
    if not os.path.exists(report_path):
        raise HTTPException(
            status_code=404,
            detail=f"Report '{report_filename}' not found in /reports directory.",
        )

    analysis = analyze_report_with_gemini(report_path)
    return {
        "status": "success",
        "report": report_filename,
        "ai_analysis": analysis,
    }


# ─── SK-18: Gemini Grounding with Google Search ────────────────────────────

@router.post("/admin/context/realtime")
def realtime_web_context(req: GroundingRequest) -> Dict[str, Any]:
    """
    SK-18: Use Gemini's built-in Google Search grounding to give the ops team
    real-time web intelligence — weather, transport, nearby crowd events, etc.
    No GCP project required — uses GOOGLE_API_KEY from AI Studio.
    """
    answer = query_with_grounding(req.topic)
    return {
        "status": "success",
        "topic": req.topic,
        "grounded_response": answer,
    }
