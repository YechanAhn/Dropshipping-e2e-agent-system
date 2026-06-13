"""Unit tests for the local Ollama vision client (mocked transport, no server)."""

import base64
import json

import httpx

from dropagent.clients.llm.ollama import make_ollama_vision_chat, ollama_vision_chat


async def test_vision_chat_posts_base64_images_and_parses_content():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "0.8|looks same"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        out = await ollama_vision_chat(
            "compare these", [b"img1", b"img2"], model="gemma4:e4b", client=client
        )
    finally:
        await client.aclose()

    assert out == "0.8|looks same"
    assert captured["url"].endswith("/api/chat")
    body = captured["body"]
    assert body["model"] == "gemma4:e4b"
    assert body["stream"] is False
    message = body["messages"][0]
    assert message["images"] == [
        base64.b64encode(b"img1").decode("ascii"),
        base64.b64encode(b"img2").decode("ascii"),
    ]
    assert "compare these" in message["content"]


async def test_vision_chat_handles_missing_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        out = await ollama_vision_chat("x", [b"a"], client=client)
    finally:
        await client.aclose()

    assert out == ""


async def test_make_ollama_vision_chat_builds_callable():
    chat = make_ollama_vision_chat(model="gemma4:31b")
    assert callable(chat)
