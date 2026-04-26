"""
Shared LLM client — single place to manage all LLM providers.

Two model families, both via Groq:
  - Llama 3.3 70B:  Hot-path interview loop (grader, question_gen, planner).
  - Qwen3 32B:      Cold-path prep tasks (resume parsing, question file gen, evaluation).

All services import from here.
"""

import os
import time
import logging
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("interviewer.llm")

# ── Groq client (shared for both model families) ──────────────────────────
_groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Hot-path: fast interview loop
GROQ_PRIMARY = "llama-3.3-70b-versatile"
GROQ_FALLBACK = "llama-3.1-8b-instant"

# Cold-path: one-time prep tasks (resume, questions, evaluation)
QWEN_PRIMARY = "qwen/qwen3-32b"
QWEN_FALLBACK = "llama-3.3-70b-versatile"  # Fall back to Llama if Qwen fails


def _call_groq(
    user_prompt: str,
    system_prompt: str = "",
    json_mode: bool = True,
    temperature: float = 0.7,
    max_tokens: int = 500,
    models: list = None,
    tag: str = "Groq",
) -> str:
    """
    Internal helper: Call Groq with retry (3x) + model cascade.
    """
    if models is None:
        models = [GROQ_PRIMARY, GROQ_FALLBACK]

    # Safety guard: truncate extremely long prompts to avoid wasting tokens
    total_chars = len(system_prompt) + len(user_prompt)
    if total_chars > 8000:
        logger.warning(f"[LLM/{tag}] Prompt too large ({total_chars} chars), truncating user_prompt")
        user_prompt = user_prompt[:7000 - len(system_prompt)] + "\n...(truncated)"

    for model in models:
        for attempt in range(3):
            try:
                if attempt == 0:
                    logger.info(f"[LLM/{tag}] Calling model={model} attempt=1/3 temp={temperature} prompt={len(system_prompt)+len(user_prompt)} chars")
                else:
                    logger.info(f"[LLM/{tag}] Calling model={model} attempt={attempt + 1}/3 temp={temperature}")
                t0 = time.time()

                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": user_prompt})

                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                response = _groq_client.chat.completions.create(**kwargs)
                result = response.choices[0].message.content.strip() if response.choices else ""

                elapsed = round(time.time() - t0, 2)
                if not result:
                    logger.warning(f"[LLM/{tag}] {model} returned empty text after {elapsed}s")
                    continue

                logger.info(f"[LLM/{tag}] OK model={model} elapsed={elapsed}s | {result[:120]}...")
                return result

            except Exception as e:
                error_msg = str(e)
                is_quota = any(k in error_msg for k in ["rate_limit", "quota", "429", "Too Many Requests"])
                logger.warning(f"[LLM/{tag}] ERROR {type(e).__name__} | model={model} | attempt={attempt+1} | quota={is_quota}")
                if is_quota and attempt < 2:
                    wait = 2 ** (attempt + 1)
                    logger.info(f"[LLM/{tag}] Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    break

    logger.error(f"[LLM/{tag}] CRITICAL: All models exhausted. Returning fallback.")
    return ""


def call_llm(
    user_prompt: str,
    system_prompt: str = "",
    json_mode: bool = True,
    temperature: float = 0.7,
    max_tokens: int = 500,
) -> str:
    """
    Call Groq Llama for the hot-path interview loop.
    Used by: grader, question_gen, planner nodes.
    """
    return _call_groq(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        json_mode=json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
        models=[GROQ_PRIMARY, GROQ_FALLBACK],
        tag="Groq/Llama",
    )


def call_gemini(
    user_prompt: str,
    system_prompt: str = "",
    json_mode: bool = True,
    temperature: float = 0.5,
    max_tokens: int = 500,
) -> str:
    """
    Call Groq Qwen3-32B for cold-path prep tasks.
    Replaces the old Gemini calls — same interface, now powered by Qwen via Groq.
    Used by: resume_parser, question_file_generator, evaluation_service.
    """
    return _call_groq(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        json_mode=json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
        models=[QWEN_PRIMARY, QWEN_FALLBACK],
        tag="Groq/Qwen",
    )
