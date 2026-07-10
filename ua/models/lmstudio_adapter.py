"""LM Studio OpenAI-compatible adapter."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ua.models.base import LLMAdapter, LLMAdapterError, LLMResponse, Message, ToolCall

logger = logging.getLogger(__name__)


class LMStudioAdapter(LLMAdapter):
    """
    Adapter for LM Studio's local OpenAI-compatible server.

    Sends requests to ``{base_url}/chat/completions`` and normalises the
    OpenAI-shaped JSON response into :class:`LLMResponse`.
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
            Base URL of the LM Studio server (e.g. ``"http://localhost:1234"``).
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
        Send messages to LM Studio and return a normalised response.

        Parameters
        ----------
        messages:
            Conversation messages to send.
        tools:
            Optional list of tool definitions in OpenAI format.  When ``None``
            or empty the ``"tools"`` key is omitted from the request payload.
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
        }

        if tools:
            payload["tools"] = tools

        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            timeout_val = self._client.timeout.read or self._client.timeout
            raise LLMAdapterError(
                f"Request to LM Studio timed out after {timeout_val} seconds."
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMAdapterError(
                f"Could not connect to LM Studio at {self._base_url}."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMAdapterError(
                f"LM Studio returned HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMAdapterError(
                "LM Studio returned invalid JSON."
            ) from exc

        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content") or ""
            raw_tool_calls = message.get("tool_calls", [])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMAdapterError(
                f"Unexpected response shape from LM Studio: missing 'choices'. Got: {data!r}"
            ) from exc

        tool_calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            try:
                tc_id = tc["id"]
                tc_function = tc["function"]
                tc_name = tc_function["name"]
                tc_arguments_raw = tc_function["arguments"]

                if isinstance(tc_arguments_raw, str):
                    tc_arguments = json.loads(tc_arguments_raw)
                else:
                    # If the server already returned a dict (non-standard),
                    # accept it but log a warning.
                    logger.warning(
                        "LM Studio returned tool_call arguments as %s instead of a JSON string.",
                        type(tc_arguments_raw).__name__,
                    )
                    tc_arguments = tc_arguments_raw

                tool_calls.append(
                    ToolCall(
                        id=tc_id,
                        name=tc_name,
                        arguments=tc_arguments,
                    )
                )
            except (KeyError, json.JSONDecodeError, TypeError) as exc:
                raise LLMAdapterError(
                    f"Malformed tool_call in LM Studio response: {tc!r}"
                ) from exc

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            raw=data,
        )

    @staticmethod
    def _serialise_message(message: Message) -> dict[str, Any]:
        """
        Convert a :class:`Message` to the OpenAI payload shape.

        Includes ``tool_call_id`` only for messages where it is set (i.e.
        ``role="tool"`` messages).
        """
        serialised: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.tool_call_id is not None:
            serialised["tool_call_id"] = message.tool_call_id
        return serialised
