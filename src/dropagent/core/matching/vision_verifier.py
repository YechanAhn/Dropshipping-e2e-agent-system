"""
Multimodal (image + text) product-identity verifier for ``ProductMatcher``.

Compares the Naver and AliExpress *photos* (plus titles) with a vision LLM to
judge "same physical product" -- the SKU-level identity lock the research calls
for. Provider-agnostic: the vision backend is injected (``VisionChat``); the
default runs a LOCAL Gemma model via Ollama (free, private, no API key), since
subscription OAuth is not a supported backend path. Swap in Claude/GPT vision by
injecting a different ``VisionChat``.

Drop-in for ``ProductMatcher(verifier=...)``. Fails safe: missing images or a
backend error yield a 0.0 confidence (routes to human review / reject) rather
than crashing the matching run.
"""

from __future__ import annotations

from dropagent.clients.llm.ollama import VisionChat, make_ollama_vision_chat
from dropagent.core.image_processor import ImageFetcher, fetch_image_bytes
from dropagent.core.matching.matcher import Verifier, _parse_verifier_response
from dropagent.core.matching.models import NaverProductRef
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

_VISION_PROMPT = (
    "You compare two e-commerce listings to judge whether they are the SAME "
    "physical product. The FIRST image + Korean title are the Naver listing; the "
    "SECOND image + English title are the AliExpress listing. Consider shape, "
    "color, parts, branding, and model. Reply EXACTLY as '<score>|<reason>' where "
    "score is a number 0..1 (1 = certainly the same product).\n"
    "Naver (Korean): {naver_title}\n"
    "AliExpress (English): {ali_title}"
)


def make_vision_verifier(
    *,
    vision_chat: VisionChat | None = None,
    fetch: ImageFetcher = fetch_image_bytes,
    fallback: Verifier | None = None,
) -> Verifier:
    """
    Build a multimodal ``Verifier`` (image + title) for ``ProductMatcher``.

    Args:
        vision_chat: Async ``(prompt, images) -> raw text`` backend. Defaults to a
            local Ollama Gemma model.
        fetch: Async image fetcher (injected for testing).
        fallback: Optional text verifier used when fewer than two images are
            available; if ``None``, missing images yield a 0.0 confidence.

    Returns:
        A ``(naver, ali_product) -> (confidence, reason)`` coroutine.
    """
    chat = vision_chat if vision_chat is not None else make_ollama_vision_chat()

    async def _verify(naver: NaverProductRef, ali_product: object) -> tuple[float, str]:
        ali_title = getattr(ali_product, "title", "")
        ali_image = getattr(ali_product, "image_url", "")

        images: list[bytes] = []
        for url in (naver.image_url, ali_image):
            data = await fetch(url) if url else None
            if data is not None:
                images.append(data)

        if len(images) < 2:
            if fallback is not None:
                return await fallback(naver, ali_product)
            return 0.0, "vision_verifier: missing image(s) for comparison"

        prompt = _VISION_PROMPT.format(naver_title=naver.title_ko, ali_title=ali_title)
        try:
            raw = await chat(prompt, images)
        except Exception as exc:  # noqa: BLE001 - backend errors must not kill the run
            logger.warning("vision_verifier_failed", error=str(exc))
            if fallback is not None:
                return await fallback(naver, ali_product)
            return 0.0, f"vision_verifier error: {exc}"

        return _parse_verifier_response(raw)

    return _verify
