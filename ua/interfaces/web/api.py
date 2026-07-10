"""FastAPI web interface for UnifiedAgent - a thin HTTP wrapper."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from ua.config.logging import configure_logging
from ua.core.factory import build_default_agent


class ChatRequest(BaseModel):
    """Request model for the chat endpoint."""

    user_id: str
    message: str


class ChatResponse(BaseModel):
    """Response model for the chat endpoint."""

    response: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: configure_logging(), build the agent ONCE via build_default_agent().

    Stores on app.state.agent. No explicit teardown needed for v1.
    """
    configure_logging()
    app.state.agent = build_default_agent()
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest) -> ChatResponse:
    """platform is fixed to 'web' for every request through this endpoint.

    Delegates to app.state.agent.chat(...).
    """
    response = await app.state.agent.chat(
        user_id=req.user_id,
        platform="web",
        message=req.message,
    )
    return ChatResponse(response=response)


@app.get("/health")
async def health() -> dict:
    """Returns {'status': 'ok'}."""
    return {"status": "ok"}
