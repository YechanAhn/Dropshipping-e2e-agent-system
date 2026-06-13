"""Unit tests for the multimodal product-identity verifier (no network/LLM)."""

import pytest

from dropagent.core.matching.models import NaverProductRef
from dropagent.core.matching.vision_verifier import make_vision_verifier

NAVER = NaverProductRef(title_ko="무선 이어폰", price=30_000, image_url="naver.jpg")


class FakeAli:
    def __init__(self, title: str, image_url: str) -> None:
        self.title = title
        self.image_url = image_url


def _fetcher(mapping: dict[str, bytes | None]):
    async def _fetch(url: str) -> bytes | None:
        return mapping.get(url)

    return _fetch


async def test_returns_parsed_score_and_passes_both_images():
    seen: dict = {}

    async def vision_chat(prompt: str, images: list[bytes]) -> str:
        seen["prompt"] = prompt
        seen["n_images"] = len(images)
        return "0.92|same product"

    verify = make_vision_verifier(
        vision_chat=vision_chat,
        fetch=_fetcher({"naver.jpg": b"n", "ali.jpg": b"a"}),
    )

    conf, reason = await verify(NAVER, FakeAli("wireless earbuds", "ali.jpg"))

    assert conf == pytest.approx(0.92)
    assert reason == "same product"
    assert seen["n_images"] == 2
    assert "무선 이어폰" in seen["prompt"]
    assert "wireless earbuds" in seen["prompt"]


async def test_missing_image_without_fallback_is_zero():
    async def vision_chat(prompt: str, images: list[bytes]) -> str:
        raise AssertionError("vision backend must not be called without 2 images")

    verify = make_vision_verifier(
        vision_chat=vision_chat,
        fetch=_fetcher({"naver.jpg": b"n"}),  # ali image missing
    )

    conf, reason = await verify(NAVER, FakeAli("x", "ali.jpg"))

    assert conf == 0.0
    assert "missing image" in reason


async def test_missing_image_uses_fallback_when_given():
    async def vision_chat(prompt: str, images: list[bytes]) -> str:
        raise AssertionError("vision backend must not be called")

    async def fallback(naver, ali) -> tuple[float, str]:
        return 0.5, "text fallback"

    verify = make_vision_verifier(
        vision_chat=vision_chat,
        fetch=_fetcher({}),  # both images missing
        fallback=fallback,
    )

    assert await verify(NAVER, FakeAli("x", "")) == (0.5, "text fallback")


async def test_backend_error_fails_safe_to_zero():
    async def vision_chat(prompt: str, images: list[bytes]) -> str:
        raise RuntimeError("ollama down")

    verify = make_vision_verifier(
        vision_chat=vision_chat,
        fetch=_fetcher({"naver.jpg": b"n", "ali.jpg": b"a"}),
    )

    conf, reason = await verify(NAVER, FakeAli("x", "ali.jpg"))

    assert conf == 0.0
    assert "error" in reason.lower()


async def test_backend_error_uses_fallback_when_given():
    async def vision_chat(prompt: str, images: list[bytes]) -> str:
        raise RuntimeError("ollama down")

    async def fallback(naver, ali) -> tuple[float, str]:
        return 0.7, "fb"

    verify = make_vision_verifier(
        vision_chat=vision_chat,
        fetch=_fetcher({"naver.jpg": b"n", "ali.jpg": b"a"}),
        fallback=fallback,
    )

    assert await verify(NAVER, FakeAli("x", "ali.jpg")) == (0.7, "fb")
