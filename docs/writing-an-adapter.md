# Writing an LLM Adapter

An adapter translates provider-specific responses into Unified Agent's normalized format.

## The LLMAdapter Contract

Every adapter extends `ua/models/base.py::LLMAdapter`:

```python
from abc import ABC, abstractmethod
from ua.models.base import LLMResponse, Message, ToolCall

class LLMAdapter(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Send messages to the LLM and return a normalised response."""
```

The normalized types:

```python
# ua/models/base.py lines 8-14
@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None

# ua/models/base.py lines 17-23
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

# ua/models/base.py lines 26-32
@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None  # Provider-specific raw response
```

Errors must raise `LLMAdapterError` (`ua/models/base.py` line 35) for timeouts, connection errors, and malformed responses.

## Canonical Template: LMStudioAdapter

The simplest adapter is `LMStudioAdapter` (`ua/models/lmstudio_adapter.py`), which inherits from `OpenAICompatAdapter`:

```python
# ua/models/lmstudio_adapter.py lines 10-51
class LMStudioAdapter(OpenAICompatAdapter):
    _provider_name: str = "LM Studio"

    def __init__(
        self,
        base_url: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        # Pass api_key=None explicitly; LM Studio is local/unauthenticated
        super().__init__(
            base_url=base_url,
            model=model,
            api_key=None,
            client=client,
            timeout=timeout,
        )
```

The heavy lifting is in `OpenAICompatAdapter` (`ua/models/openai_compat_adapter.py`):
- `generate()` method (lines 61-186) sends HTTP requests and parses JSON responses
- `_serialise_message()` (lines 188-201) converts `Message` to OpenAI format
- Error handling for timeouts, connection errors, and malformed responses

If your provider speaks OpenAI's chat-completions wire format (most do), subclass `OpenAICompatAdapter` and only override the constructor (like `LMStudioAdapter` does).

## Adding a New Provider

Currently, adding a new provider requires a small code change to `ModelManager` (`ua/models/manager.py` lines 45-69):

```python
if provider == "fake":
    self._adapter = FakeAdapter()
elif provider == "lmstudio":
    self._adapter = LMStudioAdapter(...)
elif provider == "ollama":
    self._adapter = OllamaAdapter(...)
elif provider == "openai_compat":
    self._adapter = OpenAICompatAdapter(...)
else:
    raise ValueError(f"Unrecognised LLM provider: {provider!r}...")
```

**Known limitation:** Switching among already-supported providers (fake, lmstudio, ollama, openai_compat) requires only configuration change via `UA_LLM_PROVIDER`. However, adding a *wholly new* provider type currently requires editing `ModelManager`'s provider-selection branch above. This is a code change, not just configuration. Architecture.md §9 states that provider switching should "only" need configuration but that applies to the four already-supported providers; new provider types are not yet fully decoupled.

## Provider Selection Flow

At agent startup:
1. `Settings.llm_provider` (from `.env` or environment) determines which adapter to instantiate
2. `ModelManager.__init__()` creates the matching adapter with `base_url` and `model`
3. All higher-level code calls only `ModelManager.generate()` — no direct adapter imports

The settings fields come from `ua/config/settings.py`:
```python
# settings.py lines 8-10
llm_provider: Literal["lmstudio", "ollama", "openai_compat", "fake"] = "fake"
llm_base_url: str = "http://localhost:1234/v1"
llm_model: str = "local-model"