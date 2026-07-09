"""Deterministic fake adapter for tests and local development."""

from ua.models.base import LLMAdapter, LLMResponse, Message


class FakeAdapter(LLMAdapter):
    """
    Deterministic adapter for tests and local development without a real LLM server.

    Three modes:
    - **Default** (no *fixed_response* / *responses* given): echoes the last user
      message as ``content=f"echo: {last_message.content}"``, with no tool calls.
    - **Fixed** (``fixed_response=...``): always returns that same
      :class:`LLMResponse` regardless of input, across any number of calls.
    - **Scripted** (``responses=[...]``): consumes the list one element per
      :meth:`generate` call.  When the list is exhausted a :class:`RuntimeError`
      is raised.

    If both *fixed_response* and *responses* are provided, *fixed_response*
    takes precedence and *responses* is ignored.
    """

    def __init__(
        self,
        fixed_response: LLMResponse | None = None,
        responses: list[LLMResponse] | None = None,
    ) -> None:
        if fixed_response is not None:
            self._fixed = fixed_response
            self._responses: list[LLMResponse] | None = None
        elif responses is not None:
            self._fixed: LLMResponse | None = None
            self._responses = responses
        else:
            self._fixed = None
            self._responses = None
        self._index = 0

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        if self._fixed is not None:
            return self._fixed

        if self._responses is not None:
            if self._index >= len(self._responses):
                raise RuntimeError(
                    f"FakeAdapter has exhausted its {len(self._responses)} "
                    f"scripted response(s) (index={self._index})."
                )
            resp = self._responses[self._index]
            self._index += 1
            return resp

        # Default echo mode
        last = messages[-1]
        return LLMResponse(content=f"echo: {last.content}")
