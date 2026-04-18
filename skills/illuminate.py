import os
import logging
from dotenv import load_dotenv
import groq
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-8b-8192")

# Define safety settings to enforce Security policies
SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
]

def query_gemini(prompt: str, system_prompt: str) -> str | None:
    """Queries Google Gemini with explicit safety and bounds via modern google-genai."""
    if not GOOGLE_API_KEY:
        return None
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                safety_settings=SAFETY_SETTINGS,
            )
        )
        # Quality & Security: Sanitize output and ensure it isn't an arbitrary object
        return str(response.text).strip()
    except Exception as e:
        logger.error(f"Gemini API failure: {e}")
        return None

def query_groq(prompt: str, system_prompt: str, max_tokens: int = 250) -> str | None:
    """Fallback query method using Groq."""
    if not GROQ_API_KEY:
        return None
    try:
        client = groq.Groq(api_key=GROQ_API_KEY)
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(prompt)}
            ],
            # Security & Efficiency: Bounding max tokens generated explicitly
            max_tokens=max(10, min(max_tokens, 1000)),
            temperature=0.3
        )
        return str(completion.choices[0].message.content).strip()
    except Exception as e:
        logger.error(f"Groq API failure: {e}")
        return None

def query_ai_coordinator(
    prompt: str, 
    system_prompt: str = "You are the AI Supervisor of the SmartVenue operations team. Be concise.", 
    max_tokens: int = 250
) -> str:
    """Primary entrypoint: prioritizes Gemini, falls back to Groq natively. Applies prompt bounds."""
    
    # Security: Limit prompt size to prevent large injection DoS
    # Cap at 2000 characters to ensure safe limits within standard ops workflows
    safe_prompt = prompt[:2000]
    safe_system = system_prompt[:1000]
    
    # 1. Try Google Gemini First
    gemini_resp = query_gemini(safe_prompt, safe_system)
    if gemini_resp:
        return gemini_resp
        
    # 2. Try Groq Fallback
    groq_resp = query_groq(safe_prompt, safe_system, max_tokens)
    if groq_resp:
        return groq_resp
        
    return "[AI Unavailable - Both API clients failed or missing keys]"
