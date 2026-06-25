"""
Local Ollama chat client (text + vision).

Free, private, on-box inference -- used for the multimodal product-identity
verifier when no paid vision API key is configured. Subscription OAuth
(Claude Pro / ChatGPT Plus) is NOT a supported backend path, so a local Gemma
model via Ollama is the default vision backend; swap in a Claude/GPT API client
by injecting a different ``VisionChat`` into ``make_vision_verifier``.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable

import httpx

from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
# A locally-pulled multimodal Gemma tag (text+vision). Smaller = faster; override
# with a larger tag (e.g. 'gemma4:31b') for higher-quality judgments.
DEFAULT_VISION_MODEL = "gemma4:e4b"

# An async ``(prompt, images) -> raw text`` vision chat (what the verifier wants).
VisionChat = Callable[[str, list[bytes]], Awaitable[str]]


async def ollama_vision_chat(
    prompt: str,
    images: list[bytes],
    *,
    model: str = DEFAULT_VISION_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
    timeout: float = 120.0,
    client: httpx.AsyncClient | None = None,
) -> str:
    """
    Send a prompt + images to a local Ollama vision model and return its text.

    Args:
        prompt: Instruction text.
        images: Raw image bytes (base64-encoded into the request).
        model: Ollama model tag.
        host: Ollama server base URL.
        timeout: Request timeout (vision inference can be slow on CPU).
        client: Optional pre-configured httpx client (injected for testing).

    Returns:
        The assistant message content (stripped). Empty string if absent.
    """
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(b).decode("ascii") for b in images],
            }
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await client.post(f"{host}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return ((data.get("message") or {}).get("content") or "").strip()
    finally:
        if owns_client:
            await client.aclose()


def make_ollama_vision_chat(
    *,
    model: str = DEFAULT_VISION_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
    timeout: float = 120.0,
) -> VisionChat:
    """Build a ``VisionChat`` bound to a local Ollama model."""

    async def _chat(prompt: str, images: list[bytes]) -> str:
        return await ollama_vision_chat(prompt, images, model=model, host=host, timeout=timeout)

    return _chat
