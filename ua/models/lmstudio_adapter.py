"""LM Studio OpenAI-compatible adapter."""

from __future__ import annotations

import httpx

from ua.models.openai_compat_adapter import OpenAICompatAdapter


class LMStudioAdapter(OpenAICompatAdapter):
    """
    Adapter for LM Studio's local OpenAI-compatible server.

    Inherits all request/response logic from :class:`OpenAICompatAdapter`.
    Does not expose an ``api_key`` parameter because LM Studio is a local,
    unauthenticated server.
    """

    _provider_name: str = "LM Studio"

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
        # Pass api_key=None explicitly to parent; LM Studio is local/unauthenticated.
        super().__init__(
            base_url=base_url,
            model=model,
            api_key=None,
            client=client,
            timeout=timeout,
        )
