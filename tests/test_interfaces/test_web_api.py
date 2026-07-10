"""Tests for the FastAPI web interface."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Test: Health endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok():
    """GET /health returns HTTP 200 with body {'status': 'ok'}."""
    from ua.interfaces.web.api import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Test: Chat endpoint returns valid response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_endpoint_returns_valid_response(monkeypatch):
    """POST /chat with valid body returns HTTP 200 with ChatResponse body."""
    from ua.interfaces.web.api import app, lifespan

    # Create a mock agent
    mock_agent = MagicMock()

    async def mock_chat(user_id, platform, message):
        return f"echo: {message}"

    mock_agent.chat = mock_chat

    # Override the agent in app.state
    async with lifespan(app):
        monkeypatch.setattr(app.state, "agent", mock_agent)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/chat",
                json={"user_id": "test_user", "message": "Hello via HTTP"},
            )

    assert response.status_code == 200
    assert response.json() == {"response": "echo: Hello via HTTP"}


# ---------------------------------------------------------------------------
# Test: Chat endpoint uses web platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_endpoint_uses_web_platform(monkeypatch):
    """POST /chat passes platform='web' to agent.chat."""
    from ua.interfaces.web.api import app, lifespan

    # Track calls to agent.chat
    calls_made = []

    async def mock_chat(user_id, platform, message):
        calls_made.append({"user_id": user_id, "platform": platform, "message": message})
        return "response"

    mock_agent = MagicMock()
    mock_agent.chat = mock_chat

    async with lifespan(app):
        monkeypatch.setattr(app.state, "agent", mock_agent)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/chat",
                json={"user_id": "test_user", "message": "test message"},
            )

    assert len(calls_made) == 1
    assert calls_made[0]["platform"] == "web"


# ---------------------------------------------------------------------------
# Test: Agent built once, not per request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_built_once_not_per_request(monkeypatch):
    """Agent is built once at startup, not per-request.

    We verify this by making two sequential /chat calls and checking
    that conversation state persists (same agent instance used).
    """
    from ua.interfaces.web.api import app, lifespan

    # Track calls to agent.chat
    calls_made = []

    async def mock_chat(user_id, platform, message):
        calls_made.append({"user_id": user_id, "platform": platform, "message": message})
        return f"echo: {message}"

    mock_agent = MagicMock()
    mock_agent.chat = mock_chat

    async with lifespan(app):
        monkeypatch.setattr(app.state, "agent", mock_agent)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # First request
            await client.post(
                "/chat",
                json={"user_id": "same_user", "message": "first message"},
            )
            # Second request
            await client.post(
                "/chat",
                json={"user_id": "same_user", "message": "second message"},
            )

    # Both calls should have been made to the same mock agent
    assert len(calls_made) == 2
    assert calls_made[0]["message"] == "first message"
    assert calls_made[1]["message"] == "second message"


# ---------------------------------------------------------------------------
# Test: Missing fields returns 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_endpoint_missing_fields_returns_422():
    """POST /chat with missing 'message' field returns 422 (Pydantic validation)."""
    from ua.interfaces.web.api import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Missing 'message' field
        response = await client.post(
            "/chat",
            json={"user_id": "test_user"},
        )

    assert response.status_code == 422

    # Missing 'user_id' field
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/chat",
            json={"message": "test message"},
        )

    assert response.status_code == 422
