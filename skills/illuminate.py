import os
import logging
from dotenv import load_dotenv
import groq
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-8b-8192")

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# Define safety settings to enforce Security policies
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
}

def query_gemini(prompt: str, system_prompt: str) -> str | None:
    """Queries Google Gemini with explicit safety and bounds via generativeai."""
    if not GOOGLE_API_KEY:
        return None
    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=system_prompt
        )
        response = model.generate_content(
            prompt,
            safety_settings=SAFETY_SETTINGS
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
