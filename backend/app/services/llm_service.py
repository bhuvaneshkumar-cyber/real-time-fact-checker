import asyncio
import json
from loguru import logger
from typing import List, Dict
from openai import AsyncOpenAI
from app.config import config

# ── Global concurrency limiter ──────────────────────────────────────
# Prevents GPU saturation when multiple claims are processed in parallel.
# Without this, Ollama queues requests internally and latency skyrockets.
_llm_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init the semaphore (must be created inside a running event loop)."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(config.LLM_MAX_CONCURRENCY)
    return _llm_semaphore


class LLMService:
    """Service for interacting with the LLM — optimised for lightweight models."""

    @staticmethod
    def _get_openai_client() -> AsyncOpenAI:
        """Get configured Async OpenAI client for the selected provider."""
        if config.LLM_PROVIDER == "ollama":
            return AsyncOpenAI(
                api_key="ollama",
                base_url=config.OLLAMA_BASE_URL,
            )
        elif config.LLM_PROVIDER == "nim":
            return AsyncOpenAI(
                api_key=config.NIM_API_KEY,
                base_url=config.NIM_BASE_URL,
            )
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {config.LLM_PROVIDER}")

    @staticmethod
    def _get_model() -> str:
        return config.OLLAMA_MODEL if config.LLM_PROVIDER == "ollama" else config.NIM_MODEL

    @staticmethod
    def _build_extra_body() -> dict | None:
        """Ollama-specific request options (ignored by other providers)."""
        if config.LLM_PROVIDER == "ollama":
            return {
                "options": {
                    "num_ctx": config.OLLAMA_NUM_CTX,
                },
                "keep_alive": config.OLLAMA_KEEP_ALIVE,
            }
        return None

    # ─────────────────────────────────────────────────────────────────
    #  CLAIM EXTRACTION
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    async def extract_claims(text: str, video_title: str = None, context: str = None) -> List[str]:
        """Extract objective, verifiable claims from text."""
        max_retries = 2

        # Build compact context hint
        ctx = ""
        if video_title:
            ctx += f" (Video: {video_title})"
        if context:
            # Only keep the last 200 chars of context to save tokens
            ctx += f" Context: ...{context[-200:]}"

        prompt = (
            "Extract verifiable factual claims from the TEXT below. "
            "Return ONLY a JSON array of strings. No preamble.\n"
            "Rules: ignore opinions, filler, subjective statements. "
            "Each claim must be self-contained (resolve pronouns using context).\n"
            "If no claims exist, return []\n"
            f"{ctx}\n\nTEXT: \"{text}\""
        )

        for attempt in range(max_retries):
            try:
                async with _get_semaphore():
                    client = LLMService._get_openai_client()
                    response = await client.chat.completions.create(
                        model=LLMService._get_model(),
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0,
                        max_tokens=config.LLM_EXTRACT_MAX_TOKENS,
                        extra_body=LLMService._build_extra_body(),
                    )

                content = response.choices[0].message.content.strip()

                # Strip markdown code fences
                if content.startswith("```json"):
                    content = content[7:]
                elif content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                try:
                    claims = json.loads(content)
                    if not isinstance(claims, list):
                        claims = []
                except json.JSONDecodeError:
                    # Fallback: split lines but filter preamble
                    claims = []
                    for line in content.split('\n'):
                        line = line.strip().lstrip('-* ')
                        if not line or len(line.split()) < 4:
                            continue
                        lower = line.lower()
                        if any(lower.startswith(p) for p in ("here are", "sure", "i can", "note")):
                            continue
                        if "qualify as claims" in lower:
                            continue
                        claims.append(line)

                logger.debug(f"Extracted {len(claims)} claims")
                return [str(c) for c in claims if isinstance(c, str)]

            except Exception as e:
                logger.warning(f"Claim extraction attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    logger.error(f"Failed to extract claims after {max_retries} attempts: {e}")
                    return []

    # ─────────────────────────────────────────────────────────────────
    #  DIRECT CLAIM CLASSIFICATION (no search)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    async def classify_claim_directly(claim: str) -> Dict:
        """Classify a claim directly using LLM knowledge."""
        max_retries = 2

        prompt = (
            "Classify this statement as TRUE, FALSE, VAGUE, UNRELATED, or DISTRACTING.\n"
            "Reply in EXACTLY this format (3 lines, nothing else):\n"
            "VERDICT: <verdict>\n"
            "EXPLANATION: <one sentence>\n"
            "CONFIDENCE: <HIGH|MEDIUM|LOW>\n\n"
            f"Statement: \"{claim}\""
        )

        for attempt in range(max_retries):
            try:
                async with _get_semaphore():
                    client = LLMService._get_openai_client()
                    response = await client.chat.completions.create(
                        model=LLMService._get_model(),
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.1,
                        max_tokens=config.LLM_CLASSIFY_MAX_TOKENS,
                        extra_body=LLMService._build_extra_body(),
                    )

                content = response.choices[0].message.content.strip()
                logger.debug(f"LLM classify response: {content[:120]}")

                verdict = "VAGUE"
                explanation = "Unable to parse classification."
                confidence = "LOW"

                for line in content.split('\n'):
                    line = line.strip()
                    if line.upper().startswith("VERDICT:"):
                        v = line.split(":", 1)[1].strip().upper()
                        if v in ("TRUE", "FALSE", "VAGUE", "UNRELATED", "DISTRACTING"):
                            verdict = v
                    elif line.upper().startswith("EXPLANATION:"):
                        explanation = line.split(":", 1)[1].strip()
                    elif line.upper().startswith("CONFIDENCE:"):
                        c = line.split(":", 1)[1].strip().upper()
                        if c in ("HIGH", "MEDIUM", "LOW"):
                            confidence = c

                # Fallback keyword scan
                if verdict == "VAGUE" and explanation == "Unable to parse classification.":
                    upper = content.upper()
                    for v in ("TRUE", "FALSE", "UNRELATED", "DISTRACTING"):
                        if v in upper:
                            verdict = v
                            break
                    explanation = content[:100]

                return {"verdict": verdict, "explanation": explanation, "confidence": confidence}

            except Exception as e:
                logger.warning(f"Classify attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    return {"verdict": "VAGUE", "explanation": "Error during classification.", "confidence": "LOW"}

    # ─────────────────────────────────────────────────────────────────
    #  SEARCH-BASED VERDICT SYNTHESIS
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    async def synthesize_verdict(claim: str, search_context: str) -> dict:
        """Synthesize a verdict based on the claim and search context."""
        max_retries = 2

        # Truncate search context to keep prompt lean for small models
        if len(search_context) > 1500:
            search_context = search_context[:1500] + "\n...(truncated)"

        prompt = (
            "You are a fact-checker. Given the claim and search results, determine the verdict.\n"
            "Reply in EXACTLY this format (3 lines, nothing else):\n"
            "VERDICT: <TRUE|FALSE|LACKS CONTEXT>\n"
            "EXPLANATION: <one sentence>\n"
            "SOURCE: <best URL or N/A>\n\n"
            f"Claim: \"{claim}\"\n\n"
            f"Search Results:\n{search_context}"
        )

        for attempt in range(max_retries):
            try:
                async with _get_semaphore():
                    client = LLMService._get_openai_client()
                    response = await client.chat.completions.create(
                        model=LLMService._get_model(),
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0,
                        max_tokens=config.LLM_CLASSIFY_MAX_TOKENS,
                        extra_body=LLMService._build_extra_body(),
                    )

                content = response.choices[0].message.content.strip()

                verdict = "LACKS CONTEXT"
                explanation = "Unable to determine verdict due to parsing error."
                source = "N/A"

                for line in content.split('\n'):
                    line = line.strip()
                    if line.upper().startswith("VERDICT:"):
                        v = line.split(":", 1)[1].strip().upper()
                        if v in ("TRUE", "FALSE", "LACKS CONTEXT"):
                            verdict = v
                    elif line.upper().startswith("EXPLANATION:"):
                        explanation = line.split(":", 1)[1].strip()
                    elif line.upper().startswith("SOURCE:"):
                        s = line.split(":", 1)[1].strip()
                        # Rejoin if URL was split on ':'
                        if "://" not in s and line.count(":") > 1:
                            parts = line.split(":", 1)[1].strip()
                            s = parts
                        if not s or s.upper() == "N/A":
                            source = None
                        else:
                            source = s

                # Fallback keyword scan
                if verdict == "LACKS CONTEXT" and "parsing error" in explanation:
                    if "TRUE" in content.upper():
                        verdict = "TRUE"
                    elif "FALSE" in content.upper():
                        verdict = "FALSE"
                    explanation = content[:100]
                    source = None

                return {"verdict": verdict, "explanation": explanation, "source": source}

            except Exception as e:
                logger.warning(f"Verdict synthesis attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    return {"verdict": "LACKS CONTEXT", "explanation": "Error during verdict synthesis.", "source": None}