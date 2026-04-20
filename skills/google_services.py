"""
Google AI Services Hub — SmartVenue
SK-15 · SK-16 · SK-17 · SK-18

All services use the google-genai SDK with GOOGLE_API_KEY obtained from
https://aistudio.google.com/app/apikey — NO Google Cloud project or
service account credentials are required.

Services provided:
  SK-15  Gemini text-embedding-004      Semantic search over staff notes
  SK-16  Gemini Function Calling        Structured agentic venue decisions
  SK-17  Gemini Files API               Report upload + AI summary analysis
  SK-18  Gemini Grounding (Google Search) Real-time web context for venue ops
"""

import os
import json
import math
import logging
from typing import Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
logger = logging.getLogger(__name__)

GOOGLE_API_KEY  = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL    = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
EMBEDDING_MODEL = "text-embedding-004"   # free, API-key only


# ── Internal helpers ───────────────────────────────────────────────────────

def _client() -> Optional[genai.Client]:
    """Return a configured Gemini client, or None when the key is absent."""
    if not GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY not set; Google AI services disabled.")
        return None
    return genai.Client(api_key=GOOGLE_API_KEY)


def _cosine(v1: list[float], v2: list[float]) -> float:
    """Pure-Python cosine similarity (no numpy dependency)."""
    dot  = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    return dot / (mag1 * mag2) if mag1 and mag2 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# SK-15 · Gemini Text Embeddings — Semantic Staff-Note Search
# ─────────────────────────────────────────────────────────────────────────────

def embed_text(text: str) -> Optional[list[float]]:
    """
    SK-15: Convert a text string into a 768-dimensional semantic vector
    using Google's text-embedding-004 model (free, API-key only).
    """
    client = _client()
    if not client:
        return None
    try:
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.error(f"[SK-15] Embedding failed: {e}")
        return None


def semantic_search_notes(query: str, notes: list[dict], top_k: int = 5) -> list[dict]:
    """
    SK-15: Rank a list of staff notes by semantic similarity to the query.
    Falls back to returning the first top_k notes if embeddings are unavailable.

    Each note dict must contain keys: author, note, zone_id, timestamp.
    Returns notes augmented with a '_similarity' score field.
    """
    query_vec = embed_text(query)
    if not query_vec or not notes:
        # Graceful degradation — return unranked subset
        return notes[:top_k]

    scored: list[dict] = []
    for note in notes:
        note_text = f"{note.get('author', '')} {note.get('zone_id', '')} {note.get('note', '')}"
        note_vec = embed_text(note_text)
        score = _cosine(query_vec, note_vec) if note_vec else 0.0
        scored.append({**note, "_similarity": round(score, 4)})

    scored.sort(key=lambda x: x["_similarity"], reverse=True)
    logger.info(f"[SK-15] Semantic search top score: {scored[0]['_similarity'] if scored else 'N/A'}")
    return scored[:top_k]


# ─────────────────────────────────────────────────────────────────────────────
# SK-16 · Gemini Function Calling — Structured Agentic Venue Decisions
# ─────────────────────────────────────────────────────────────────────────────

# Declare the venue management tools Gemini may call
_VENUE_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="get_zone_status",
            description=(
                "Retrieve real-time crowd density and queue status for a specific zone."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "zone_id": types.Schema(
                        type="STRING",
                        description="The venue zone identifier to inspect.",
                    )
                },
                required=["zone_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="set_venue_mode",
            description=(
                "Transition the operational mode of the entire venue. "
                "Valid values: PRE_EVENT, LIVE, EGRESS, POST_EVENT."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "mode": types.Schema(
                        type="STRING",
                        description="Target operational mode.",
                    )
                },
                required=["mode"],
            ),
        ),
        types.FunctionDeclaration(
            name="update_zone_headcount",
            description="Update the current headcount for a venue zone.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "zone_id": types.Schema(type="STRING", description="Target zone."),
                    "count":   types.Schema(type="INTEGER", description="New headcount."),
                },
                required=["zone_id", "count"],
            ),
        ),
        types.FunctionDeclaration(
            name="dispatch_alert",
            description=(
                "Dispatch an operational alert to staff with a given severity level."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "severity": types.Schema(
                        type="STRING", description="Alert severity: info, warning, or critical."
                    ),
                    "message": types.Schema(
                        type="STRING", description="Human-readable alert message for staff."
                    ),
                },
                required=["severity", "message"],
            ),
        ),
    ]
)


def query_with_function_calling(
    prompt: str,
    zone_data: dict,
    current_mode: str,
) -> dict:
    """
    SK-16: Send a staff request to Gemini with structured function-calling tools.
    Gemini decides which functions to invoke and returns both a text response
    and a list of parsed action dicts the API layer can execute immediately.

    Returns: { "response": str, "actions": [{"function": str, "args": dict}] }
    """
    client = _client()
    if not client:
        return {"response": "[Google AI unavailable]", "actions": []}

    try:
        system_prompt = (
            "You are SmartVenue AI, an intelligent venue operations assistant. "
            "Use the provided function tools to take real actions when appropriate. "
            "Keep your text response under 3 sentences."
        )
        full_prompt = (
            f"Current venue mode: {current_mode}. "
            f"Zone data: {json.dumps(zone_data, default=str)}.\n\n"
            f"Staff request: {prompt[:1500]}"   # Safety: cap prompt size
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[_VENUE_TOOLS],
                temperature=0.2,
            ),
        )

        actions: list[dict] = []
        text_parts: list[str] = []

        for candidate in response.candidates:
            for part in candidate.content.parts:
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    actions.append({"function": fc.name, "args": dict(fc.args)})
                elif getattr(part, "text", None):
                    text_parts.append(part.text)

        logger.info(f"[SK-16] Function calling produced {len(actions)} action(s).")
        return {
            "response": " ".join(text_parts).strip() or "Action(s) dispatched.",
            "actions":  actions,
        }

    except Exception as e:
        logger.error(f"[SK-16] Gemini function calling failed: {e}")
        return {"response": f"[Function calling error: {e}]", "actions": []}


# ─────────────────────────────────────────────────────────────────────────────
# SK-17 · Gemini Files API — Report Upload & AI Analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_report_with_gemini(report_path: str) -> str:
    """
    SK-17: Upload a venue Markdown report to the Gemini Files API (free tier,
    API-key only) and request an intelligent post-event summary with
    actionable recommendations.

    The remote file is deleted immediately after analysis.
    """
    client = _client()
    if not client:
        return "[Google AI unavailable for report analysis]"

    if not os.path.exists(report_path):
        return f"[Report not found: {report_path}]"

    try:
        # 1. Upload the report file via Gemini Files API
        uploaded = client.files.upload(
            path=report_path,
            config=types.UploadFileConfig(
                display_name=os.path.basename(report_path),
                mime_type="text/plain",
            ),
        )
        logger.info(f"[SK-17] Uploaded report to Gemini Files API: {uploaded.name}")

        # 2. Request structured analysis from Gemini
        analysis_prompt = (
            "You are a venue analytics expert. Analyse this SmartVenue post-event report "
            "and provide:\n"
            "1. A one-paragraph executive summary.\n"
            "2. The three highest-severity operational incidents.\n"
            "3. Three concrete improvement recommendations for the next event.\n"
            "Be concise and actionable."
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[uploaded, analysis_prompt],
        )

        # 3. Clean up: delete the remote file immediately after use
        client.files.delete(name=uploaded.name)
        logger.info(f"[SK-17] Deleted remote file {uploaded.name} from Gemini Files API.")

        return response.text.strip()

    except Exception as e:
        logger.error(f"[SK-17] Gemini Files API analysis failed: {e}")
        return f"[Report analysis error: {e}]"


# ─────────────────────────────────────────────────────────────────────────────
# SK-18 · Gemini Grounding with Google Search — Real-Time Venue Context
# ─────────────────────────────────────────────────────────────────────────────

def query_with_grounding(topic: str) -> str:
    """
    SK-18: Use Gemini's built-in Google Search grounding tool to inject
    real-time web information into venue operations context — including weather
    alerts, local transport disruptions, or nearby event crowd spillover.

    Requires gemini-2.0-flash or later; uses GOOGLE_API_KEY only.
    """
    client = _client()
    if not client:
        return "[Google AI unavailable for grounded search]"

    try:
        grounding_tool = types.Tool(google_search=types.GoogleSearch())

        safe_topic = topic[:800]   # Safety: bound input
        response = client.models.generate_content(
            model="gemini-2.0-flash",   # Grounding requires 2.0-flash+
            contents=(
                f"You are assisting a live venue operations team. "
                f"Search the web and provide a concise, factual answer (max 4 sentences) to: {safe_topic}"
            ),
            config=types.GenerateContentConfig(
                tools=[grounding_tool],
                temperature=0.1,   # Low temp for factual grounded output
            ),
        )
        logger.info("[SK-18] Gemini grounded search completed successfully.")
        return response.text.strip()

    except Exception as e:
        logger.error(f"[SK-18] Gemini grounding search failed: {e}")
        return f"[Grounded search error: {e}]"
