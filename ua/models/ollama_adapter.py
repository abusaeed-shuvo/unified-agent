"""Ollama native OpenAI-incompatible adapter."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from ua.models.base import LLMAdapter, LLMAdapterError, LLMResponse, Message, ToolCall

logger = logging.getLogger(__name__)


class OllamaAdapter(LLMAdapter):
    """
    Adapter for a local Ollama server's native ``/api/chat`` endpoint.

    Ollama's wire format differs from OpenAI's in two important ways that
    this adapter normalises:

    1. The assistant message lives under a top-level ``"message"`` key
       (OpenAI nests it under ``"choices"[0]["message"]``).
    2. Tool-call ``arguments`` are returned as an already-parsed **dict**
       (OpenAI returns a JSON-encoded **string**). Ollama also does not
       provide an ``id`` on tool calls, so we synthesise one with
       :func:`uuid.uuid4` when absent.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        """
        Initialise the adapter.

        Parameters
        ----------
        base_url:
            Base URL of the Ollama server (e.g. ``"http://localhost:11434"``).
        model:
            Model identifier to send in the ``model`` field of each request.
        client:
            Optional pre-configured :class:`httpx.AsyncClient`.  When supplied
            the *timeout* parameter is ignored.  Tests should inject a client
            backed by :class:`httpx.MockTransport`.
        timeout:
            Request timeout in seconds.  Only used when *client* is ``None``.
        """
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Send messages to Ollama's ``/api/chat`` and return a normalised response.

        Parameters
        ----------
        messages:
            Conversation messages to send.
        tools:
            Optional list of tool definitions in Ollama/OpenAI format.  When
            ``None`` or empty the ``"tools"`` key is omitted from the request
            payload.
        **kwargs:
            Additional keyword arguments forwarded to
            :meth:`httpx.AsyncClient.post` (e.g. ``headers``).

        Returns
        -------
        LLMResponse
            Normalised response containing ``content``, ``tool_calls``, and
            ``raw`` (the full parsed JSON).

        Raises
        ------
        LLMAdapterError
            On network errors, non-2xx status codes, or malformed responses.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                self._serialise_message(m)
                for m in messages
            ],
            "stream": False,
        }

        if tools:
            payload["tools"] = tools

        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat",
                json=payload,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            timeout_val = self._client.timeout.read or self._client.timeout
            raise LLMAdapterError(
                f"Request to Ollama timed out after {timeout_val} seconds."
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMAdapterError(
                f"Could not connect to Ollama at {self._base_url}."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMAdapterError(
                f"Ollama returned HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMAdapterError(
                "Ollama returned invalid JSON."
            ) from exc

        try:
            message = data["message"]
            content = message.get("content") or ""
            raw_tool_calls = message.get("tool_calls", [])
        except (KeyError, TypeError) as exc:
            raise LLMAdapterError(
                f"Unexpected response shape from Ollama: missing 'message'. Got: {data!r}"
            ) from exc

        tool_calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            try:
                tc_function = tc["function"]
                tc_name = tc_function["name"]
                tc_arguments_raw = tc_function["arguments"]

                # Ollama returns arguments as an already-parsed dict, but we
                # defensively handle the case where a server (or future version)
                # returns a JSON-encoded string, to keep the shared ToolCall
                # contract (arguments must always be a dict) intact.
                if isinstance(tc_arguments_raw, str):
                    logger.debug(
                        "Ollama returned tool_call arguments as a JSON string; parsing it."
                    )
                    tc_arguments = json.loads(tc_arguments_raw)
                else:
                    tc_arguments = tc_arguments_raw

                # Ollama does not provide an id on tool calls; synthesise one
                # so the shared ToolCall contract (which requires an id) holds.
                tc_id = tc.get("id") or str(uuid.uuid4())

                tool_calls.append(
                    ToolCall(
                        id=tc_id,
                        name=tc_name,
                        arguments=tc_arguments,
                    )
                )
            except (KeyError, json.JSONDecodeError, TypeError) as exc:
                raise LLMAdapterError(
                    f"Malformed tool_call in Ollama response: {tc!r}"
                ) from exc

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            raw=data,
        )

    @staticmethod
    def _serialise_message(message: Message) -> dict[str, Any]:
        """
        Convert a :class:`Message` to Ollama's payload shape.

        Ollama uses ``tool_name`` (not ``tool_call_id``) on ``role="tool"``
        messages to identify which tool produced the result.
        """
        serialised: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.role == "tool" and message.tool_call_id is not None:
            # Ollama expects the tool's name here; we stored the tool name in
            # tool_call_id for tool-role messages (see Architecture.md §9).
            serialised["tool_name"] = message.tool_call_id
        return serialised
