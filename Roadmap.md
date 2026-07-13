# Unified Agent — Development Roadmap & Implementation Batches

This document is the execution plan for building Unified Agent. It assumes the reader has already read `ARCHITECTURE.md` and `CONTRIBUTING.md`. It is written for a coding agent (Cline running StepFun 3.7 Flash) to execute one batch at a time, in order.

---

## 1. How to Use This Document

- Work through batches **in numeric order**. Each batch lists its dependencies explicitly — never start a batch whose dependencies aren't merged and green.
- Each batch is scoped to be completable in under an hour by a coding agent.
- Each batch ends in a **working, tested state** — the app boots, `pytest` passes, `ruff check .` passes.
- After finishing a batch, commit with the suggested message (or an equally precise one), then move to the next batch.

---

## 2. Dependency Graph (batch-level)

```
01 Project Scaffold
 └─ 02 Config System
     ├─ 03 Logging Setup
     ├─ 04 Database Engine & Base Models
     │   └─ 05 Long-Term Memory (SQLite)
     ├─ 06 Personality Schema & Loader
     ├─ 07 LLM Adapter Base + Fake Adapter (for tests)
     │   ├─ 08 LM Studio Adapter
     │   ├─ 09 Ollama Adapter
     │   └─ 10 OpenAI-Compatible Adapter
     │       └─ 11 Model Manager
     ├─ 12 Short-Term Memory
     ├─ 13 Knowledge Memory
     │   └─ 14 Memory Manager (aggregates 05+12+13)
     ├─ 15 Tool Base & ToolResult
     │   ├─ 16 Calculator Tool
     │   └─ 17 Filesystem Tool
     │       └─ 18 Tool Registry / Auto-Discovery
     ├─ 19 Context Builder (needs 06 + 14)
     └─ 20 Conversation Manager (needs 04 + 14)
         └─ 21 UnifiedAgent Core (needs 11 + 14 + 18 + 19 + 20)
             ├─ 22 CLI Interface
             ├─ 23 Web API Interface (FastAPI)
             └─ 24 Discord Interface
25 Tool-Calling Loop Hardening (needs 21)
26 Retry / Error-Handling Layer for LLM calls (needs 11)
27 Memory Summarization / Compaction (needs 14)
28 Personality Hot-Switching (needs 06 + 21)
29 Structured Logging & Observability Pass (needs 03 + 21)
30 Test Suite Hardening & Fixtures Cleanup (needs 22-24)
31 Example Scripts (needs 21)
32 Documentation Pass (docs/ generation) (needs 31)
33 Packaging & Distribution Readiness (needs 32)
```

Batches within the same indentation level (e.g., 08/09/10, or 22/23/24) can be done in any order relative to each other, but all must wait for their listed parent.

---

## 3. Development Roadmap (phases)

**Phase 0 — Foundations (Batches 1–6):** project skeleton, config, logging, database, personality loading. Nothing "thinks" yet.

**Phase 1 — Model & Memory Layers (Batches 7–14):** LLM adapters + model manager; all three memory layers + the manager that unifies them. Still no conversation orchestration.

**Phase 2 — Tools (Batches 15–18):** tool interface, two real tools, auto-discovery registry.

**Phase 3 — Orchestration (Batches 19–21):** context builder, conversation manager, and finally `UnifiedAgent` — the first point where a real end-to-end `agent.chat()` call works, tool-less, memory-less integration tested with the fake adapter.

**Phase 4 — Interfaces (Batches 22–24):** CLI, Web API, Discord — each is a thin shell around the now-complete Core.

**Phase 5 — Hardening & Polish (Batches 25–33):** tool-calling loop robustness, retries, memory compaction, personality switching, observability, test cleanup, examples, docs, packaging.

This gets to a genuinely useful, multi-interface, tool-using agent by the end of Phase 4 (batch 24), with Phase 5 turning it into something production-respectable.



---

## Project Milestones (Completed / Planned)

This section provides a high-level overview of development progress for public visibility. The detailed batch specifications follow below.

### Foundations (Batches 1-6, 12) ✓
- Project scaffold and pyproject.toml setup
- Pydantic-based configuration system with env-var overrides
- Central logging setup (idempotent)
- Async SQLAlchemy engine and ORM models
- Personality schema, loader, and three personalities (assistant/tester/coding)

### Model & Memory Layers (Batches 7-14) ✓
- Four LLM adapters: Fake, LM Studio, Ollama, OpenAI-compatible
- Model Manager with provider selection via config
- Three-tier memory system: Short-Term, Long-Term, Knowledge
- Memory Manager facade unifying all layers

### Tools (Batches 15-18, 25) ✓
- Tool ABC, ToolResult, and ToolRegistry with auto-discovery
- Calculator tool (safe AST-based evaluation)
- Filesystem tool (read-only, path traversal protection)
- Web Search tool (DuckDuckGo HTML scraping, no API key)
- Web Fetch tool (URL fetching with SSRF protection — see known limitations)
- SSH Sandbox tools (execute/write) with confirmation gating (partial)

### Orchestration (Batches 19-21) ✓
- Context Builder merging personality + memory into prompts
- Conversation Manager with session/turn bookkeeping
- UnifiedAgent: the single `agent.chat()` public entrypoint

### Interfaces (Batches 22-24) ✓
- CLI interface with interactive chat loop
- Web API interface (FastAPI) with /chat endpoint
- Discord bot interface

### Hardening & Polish (Batches 25-30) ✓
- Bounded tool-calling loop with retry limits
- LLM call retry/backoff layer
- Memory summarization/compaction hooks
- Per-user personality hot-switching
- Structured logging for observability

### Examples & Docs (Batches 31-33) ✓
- Runnable example scripts demonstrating usage patterns
- Complete documentation suite in docs/
- Packaging and distribution readiness

---


### Batch 01 — Project Scaffold

**Objective:** Create the repository skeleton, `pyproject.toml`, and an empty but importable `ua` package, with `uv` managing the environment.

**Why this batch exists:** Nothing can be built without a working package structure and dependency manager in place.

**Files to create:**
- `pyproject.toml`
- `README.md` (placeholder with project name + one-line description)
- `.gitignore`
- `.env.example`
- `ua/__init__.py` (contains `__version__ = "0.1.0"`)
- `ua/config/__init__.py`
- `ua/database/__init__.py`
- `ua/personality/__init__.py`
- `ua/models/__init__.py`
- `ua/memory/__init__.py`
- `ua/conversation/__init__.py`
- `ua/tools/__init__.py`
- `ua/core/__init__.py`
- `ua/interfaces/__init__.py`
- `tests/__init__.py`
- `tests/conftest.py` (empty fixture file for now)

**Files to modify:** none.

**Public APIs to implement:** none yet — just package structure.

**Internal implementation notes:**
- `pyproject.toml` should declare Python `>=3.12`, `build-system` using `hatchling` (or `uv`'s default), core deps (`pydantic>=2`, `sqlalchemy>=2`, `httpx`, `python-dotenv`), and `[project.optional-dependencies]` groups: `discord`, `web`, `dev`.
- Use `uv init --package` conventions if helpful, but final structure must match `ARCHITECTURE.md` §5 exactly.

**Acceptance criteria:**
- `uv sync` completes without error.
- `uv run python -c "import ua; print(ua.__version__)"` prints `0.1.0`.
- `uv run pytest` runs (0 tests collected is fine) with exit code 0.
- `uv run ruff check .` passes.

**Manual testing steps:**
1. `uv sync`
2. `uv run python -c "import ua; print(ua.__version__)"`
3. `uv run pytest`
4. `uv run ruff check .`

**Suggested pytest tests:**
- `tests/test_package.py::test_version` — asserts `ua.__version__ == "0.1.0"`.

**Suggested Git commit message:** `chore: scaffold project structure and tooling`

**Dependencies on previous batches:** none.

**Common mistakes to avoid:**
- Don't add `discord.py`/`fastapi` as hard (non-optional) dependencies yet.
- Don't create `ua/interfaces/discord/bot.py` etc. yet — only `__init__.py` placeholders in this batch.

---

### Batch 02 — Config System

**Objective:** Implement `ua/config/settings.py` with a single `Settings(BaseSettings)` class, environment-variable driven, with a module-level `get_settings()` accessor.

**Why this batch exists:** Every later subsystem reads configuration from here; centralizing it now avoids scattered `os.environ` calls.

**Files to create:**
- `ua/config/settings.py`

**Files to modify:**
- `.env.example` — add all fields with example values.

**Public APIs to implement:**
```python
class Settings(BaseSettings):
    llm_provider: Literal["lmstudio", "ollama", "openai_compat", "fake"] = "fake"
    llm_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "local-model"
    database_url: str = "sqlite+aiosqlite:///./unified_agent.db"
    active_personality: str = "assistant"
    discord_token: str | None = None
    log_level: str = "INFO"
    tools_allow_destructive: bool = False

    model_config = SettingsConfigDict(env_prefix="UA_", env_file=".env")

@lru_cache
def get_settings() -> Settings: ...
```

**Internal implementation notes:**
- Use `pydantic-settings` (add as core dependency in this batch's `pyproject.toml` edit if not already present).
- `get_settings()` must be cached (`functools.lru_cache`) but tests need a way to bypass the cache — expose `get_settings.cache_clear()` usage in the test fixture, don't build a special bypass API.

**Acceptance criteria:**
- `get_settings()` returns defaults with no `.env` present.
- Setting `UA_LLM_PROVIDER=ollama` env var changes `get_settings().llm_provider`.

**Manual testing steps:**
1. `UA_LLM_PROVIDER=ollama uv run python -c "from ua.config.settings import get_settings; print(get_settings().llm_provider)"` → prints `ollama`.

**Suggested pytest tests:**
- `tests/test_config.py::test_defaults`
- `tests/test_config.py::test_env_override` (use `monkeypatch.setenv` + `get_settings.cache_clear()`)

**Suggested Git commit message:** `config: add centralized Settings with env-var overrides`

**Dependencies on previous batches:** Batch 01.

**Common mistakes to avoid:**
- Don't read `os.environ` anywhere outside this file going forward.
- Don't forget `env_prefix="UA_"` — every future env var must use this prefix.

---

### Batch 03 — Logging Setup

**Objective:** Central logging configuration used by every module; no `print()` in library code from here on.

**Files to create:**
- `ua/config/logging.py`

**Public APIs to implement:**
```python
def configure_logging(level: str | None = None) -> None: ...
def get_logger(name: str) -> logging.Logger: ...
```

**Internal implementation notes:**
- `configure_logging` reads `get_settings().log_level` if `level` not passed; sets a single `StreamHandler` with a consistent formatter (`%(asctime)s %(levelname)s %(name)s: %(message)s`).
- Idempotent — calling it twice must not duplicate handlers.

**Acceptance criteria:**
- Calling `configure_logging()` then `get_logger(__name__).info("x")` prints one formatted line, not duplicated.

**Manual testing steps:**
1. `uv run python -c "from ua.config.logging import configure_logging, get_logger; configure_logging(); get_logger('t').info('hello')"`

**Suggested pytest tests:**
- `tests/test_logging.py::test_no_duplicate_handlers` — call `configure_logging()` twice, assert `len(logging.getLogger().handlers) == 1`.

**Suggested Git commit message:** `config: add idempotent logging setup`

**Dependencies on previous batches:** Batch 02.

**Common mistakes to avoid:**
- Don't call `configure_logging()` at import time inside library modules — only interfaces/entrypoints call it.

---

### Batch 04 — Database Engine & Base Models

**Objective:** Async SQLAlchemy engine/session factory and the ORM base + core tables (`users`, `sessions`, `messages`, `facts`).

**Files to create:**
- `ua/database/engine.py`
- `ua/database/models.py`

**Public APIs to implement:**
```python
# engine.py
def get_engine() -> AsyncEngine: ...
async def get_session() -> AsyncIterator[AsyncSession]: ...
async def init_db() -> None: ...  # create_all for dev/test convenience

# models.py
class Base(DeclarativeBase): ...
class User(Base): ...        # id, platform, platform_user_id, created_at
class Session(Base): ...     # id, user_id FK, platform, started_at
class Message(Base): ...     # id, session_id FK, role, content, created_at
class Fact(Base): ...        # id, user_id FK, key, value, created_at
```

**Internal implementation notes:**
- Use `sqlalchemy[asyncio]` with `aiosqlite` driver, `database_url` from `get_settings()`.
- `init_db()` is for dev convenience only — note in a comment that a future batch may add Alembic; not required for v1.

**Acceptance criteria:**
- `init_db()` creates a SQLite file with all four tables.
- A round-trip insert+query of a `User` row works via `get_session()`.

**Manual testing steps:**
1. `uv run python -c "import asyncio; from ua.database.engine import init_db; asyncio.run(init_db())"` then inspect `unified_agent.db` with `sqlite3` and confirm tables exist.

**Suggested pytest tests:**
- `tests/test_database/test_engine.py::test_init_db_creates_tables`
- `tests/test_database/test_models.py::test_user_roundtrip`
- Use an in-memory `sqlite+aiosqlite:///:memory:` DB via a fixture override in `conftest.py`.

**Suggested Git commit message:** `database: add async engine and core ORM models`

**Dependencies on previous batches:** Batch 02.

**Common mistakes to avoid:**
- Don't hardcode a file path — always read from `settings.database_url`.
- Don't use sync SQLAlchemy sessions anywhere.

---

### Batch 05 — Long-Term Memory (SQLite-backed)

**Objective:** Implement the `MemoryStore` interface and a SQLite-backed `LongTermMemory` implementation using the `Fact` table.

**Files to create:**
- `ua/memory/base.py` (the `MemoryStore` Protocol + `MemoryItem` dataclass)
- `ua/memory/long_term.py`

**Public APIs to implement:**
```python
@dataclass
class MemoryItem:
    key: str
    value: str
    score: float = 1.0

class MemoryStore(Protocol):
    async def get(self, user_id: str, key: str) -> str | None: ...
    async def put(self, user_id: str, key: str, value: str) -> None: ...
    async def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]: ...

class LongTermMemory:
    async def get(self, user_id: str, key: str) -> str | None: ...
    async def put(self, user_id: str, key: str, value: str) -> None: ...
    async def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]: ...
```

**Internal implementation notes:**
- `search` in v1 does a naive `LIKE %query%` substring match over `Fact.value`, ordered by recency — this is intentionally simple; the docstring must say "replace with vector similarity search later, same interface."
- `put` upserts on `(user_id, key)`.

**Acceptance criteria:**
- Facts persist across `put`/`get` calls within a test DB.
- `search` returns matching facts, empty list when none match.

**Manual testing steps:**
1. Run a small script that puts 3 facts for a fake user, then searches for a keyword and prints matches.

**Suggested pytest tests:**
- `tests/test_memory/test_long_term.py::test_put_get_roundtrip`
- `tests/test_memory/test_long_term.py::test_search_substring_match`
- `tests/test_memory/test_long_term.py::test_search_no_match_returns_empty`

**Suggested Git commit message:** `memory: add SQLite-backed long-term memory store`

**Dependencies on previous batches:** Batch 04.

**Common mistakes to avoid:**
- Don't let `LongTermMemory` accept a raw SQL string from callers — only structured params.
- Don't skip the "swap for vector DB" docstring note; it's part of the architectural contract.

---

### Batch 06 — Personality Schema & Loader

**Objective:** Data-driven personality loading from `personalities/<name>/`.

**Files to create:**
- `ua/personality/schema.py`
- `ua/personality/loader.py`
- `personalities/assistant/system.md`
- `personalities/assistant/style.md`
- `personalities/assistant/rules.json`
- `personalities/assistant/greetings.txt`

**Public APIs to implement:**
```python
class PersonalityRules(BaseModel):
    allow_tools: list[str] = []
    max_response_tokens: int = 1024
    forbidden_topics: list[str] = []

class Personality(BaseModel):
    name: str
    system_prompt: str
    style: str
    rules: PersonalityRules
    greetings: list[str]

class PersonalityLoader:
    def __init__(self, base_dir: Path | None = None): ...
    def load(self, name: str) -> Personality: ...
```

**Internal implementation notes:**
- `base_dir` defaults to `<repo_root>/personalities`.
- Missing files raise a clear `PersonalityLoadError`, not a bare `FileNotFoundError`.
- `rules.json` for `assistant` should be a small real example (e.g., `allow_tools: ["calculator"]`, `max_response_tokens: 800`, `forbidden_topics: []`).

**Acceptance criteria:**
- `PersonalityLoader().load("assistant")` returns a populated `Personality`.
- Loading a nonexistent personality raises `PersonalityLoadError` with the personality name in the message.

**Manual testing steps:**
1. `uv run python -c "from ua.personality.loader import PersonalityLoader; p = PersonalityLoader().load('assistant'); print(p.system_prompt[:50])"`

**Suggested pytest tests:**
- `tests/test_personality.py::test_load_assistant_personality`
- `tests/test_personality.py::test_missing_personality_raises`

**Suggested Git commit message:** `personality: add data-driven personality schema and loader`

**Dependencies on previous batches:** Batch 01.

**Common mistakes to avoid:**
- Don't put any tone/persona text in Python — it all lives in the `.md`/`.json`/`.txt` files.

---

### Batch 07 — LLM Adapter Base + Fake Adapter

**Objective:** Define the `LLMAdapter` interface and a deterministic `FakeAdapter` used by all downstream tests (so no test ever needs a live LLM server).

**Files to create:**
- `ua/models/base.py`
- `ua/models/fake_adapter.py`

**Public APIs to implement:**
```python
@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None

class LLMAdapter(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse: ...

class FakeAdapter(LLMAdapter):
    async def generate(self, messages, tools=None, **kwargs) -> LLMResponse: ...
```

**Internal implementation notes:**
- `FakeAdapter` should be configurable with a canned response or a simple echo behavior (`content=f"echo: {messages[-1].content}"`) so tests can assert on it deterministically. Allow injecting a fixed `LLMResponse` via constructor for tests that need tool-call simulation.

**Acceptance criteria:**
- `FakeAdapter().generate([Message(role="user", content="hi")])` returns a deterministic `LLMResponse`.

**Manual testing steps:**
1. Small script instantiating `FakeAdapter`, calling `generate`, printing result.

**Suggested pytest tests:**
- `tests/test_models/test_fake_adapter.py::test_echo_behavior`
- `tests/test_models/test_fake_adapter.py::test_injected_response`

**Suggested Git commit message:** `models: add LLMAdapter interface and FakeAdapter for testing`

**Dependencies on previous batches:** Batch 01.

**Common mistakes to avoid:**
- Don't let `FakeAdapter` make any real network call — it must be fully synthetic and importable with zero external services running.

---

### Batch 08 — LM Studio Adapter

**Objective:** Real adapter for LM Studio's OpenAI-compatible local server.

**Files to create:**
- `ua/models/lmstudio_adapter.py`

**Public APIs to implement:**
```python
class LMStudioAdapter(LLMAdapter):
    def __init__(self, base_url: str, model: str, client: httpx.AsyncClient | None = None): ...
    async def generate(self, messages, tools=None, **kwargs) -> LLMResponse: ...
```

**Internal implementation notes:**
- POST to `{base_url}/chat/completions` with OpenAI-style payload; normalize response into `LLMResponse` (map `choices[0].message.tool_calls` into `ToolCall` list if present).
- Accept an injectable `httpx.AsyncClient` so tests can use `httpx.MockTransport` — never hit a real server in tests.
- Timeouts and connection errors must raise a normalized `LLMAdapterError` (define in `ua/models/base.py` in this batch), not leak raw `httpx` exceptions to callers.

**Acceptance criteria:**
- Against a mocked transport returning a canned OpenAI-shaped JSON, `generate()` returns the expected `LLMResponse`.
- A mocked connection error raises `LLMAdapterError`.

**Manual testing steps:**
1. With an actual LM Studio server running locally on the configured port, run a small script calling `LMStudioAdapter(...).generate(...)` and confirm a real response comes back.

**Suggested pytest tests:**
- `tests/test_models/test_lmstudio_adapter.py::test_generate_success` (mocked transport)
- `tests/test_models/test_lmstudio_adapter.py::test_generate_connection_error_raises`

**Suggested Git commit message:** `models: add LM Studio adapter`

**Dependencies on previous batches:** Batch 07.

**Common mistakes to avoid:**
- Don't test against a live server in the automated suite.
- Don't forget to add `LLMAdapterError` to `ua/models/base.py` (shared across all adapters, not redefined per-file).

---

### Batch 09 — Ollama Adapter

**Objective:** Real adapter for a local Ollama server.

**Files to create:**
- `ua/models/ollama_adapter.py`

**Public APIs to implement:**
```python
class OllamaAdapter(LLMAdapter):
    def __init__(self, base_url: str, model: str, client: httpx.AsyncClient | None = None): ...
    async def generate(self, messages, tools=None, **kwargs) -> LLMResponse: ...
```

**Internal implementation notes:**
- POST to `{base_url}/api/chat`; Ollama's payload/response shape differs from OpenAI's — normalize carefully into the same `LLMResponse`.
- Same injectable-client and `LLMAdapterError` pattern as Batch 08.

**Acceptance criteria:** Same shape as Batch 08, adapted to Ollama's response format.

**Manual testing steps:** Same pattern as Batch 08, against a real local Ollama instance if available.

**Suggested pytest tests:**
- `tests/test_models/test_ollama_adapter.py::test_generate_success`
- `tests/test_models/test_ollama_adapter.py::test_generate_connection_error_raises`

**Suggested Git commit message:** `models: add Ollama adapter`

**Dependencies on previous batches:** Batch 07 (and reuses `LLMAdapterError` from Batch 08's edit to `base.py` — if Batch 08 hasn't run yet, define `LLMAdapterError` in `base.py` as part of Batch 07 instead to avoid ordering ambiguity).

**Common mistakes to avoid:**
- Don't assume Ollama's tool-calling format matches OpenAI's — check the actual response shape and map explicitly.

---

### Batch 10 — OpenAI-Compatible Adapter

**Objective:** Generic adapter for any OpenAI-compatible endpoint (llama.cpp server, OpenRouter, actual OpenAI, etc.).

**Files to create:**
- `ua/models/openai_compat_adapter.py`

**Public APIs to implement:**
```python
class OpenAICompatAdapter(LLMAdapter):
    def __init__(self, base_url: str, model: str, api_key: str | None = None, client: httpx.AsyncClient | None = None): ...
    async def generate(self, messages, tools=None, **kwargs) -> LLMResponse: ...
```

**Internal implementation notes:**
- Nearly identical to `LMStudioAdapter` but adds an `Authorization: Bearer {api_key}` header when `api_key` is set — this is deliberately the "generic" fallback adapter. Consider having `LMStudioAdapter` subclass this one to avoid duplication, if that doesn't complicate testing.

**Acceptance criteria:** Same shape as Batch 08.

**Manual testing steps:** Same pattern as Batch 08, optionally against a real OpenAI-compatible endpoint with an API key from `.env`.

**Suggested pytest tests:**
- `tests/test_models/test_openai_compat_adapter.py::test_generate_success`
- `tests/test_models/test_openai_compat_adapter.py::test_auth_header_included_when_api_key_set`

**Suggested Git commit message:** `models: add generic OpenAI-compatible adapter`

**Dependencies on previous batches:** Batch 07.

**Common mistakes to avoid:**
- Don't log the API key, even at DEBUG level.

---

### Batch 11 — Model Manager

**Objective:** Single entrypoint that picks the correct adapter based on config.

**Files to create:**
- `ua/models/manager.py`

**Public APIs to implement:**
```python
class ModelManager:
    def __init__(self, settings: Settings | None = None): ...
    async def generate(self, messages: list[Message], tools: list[dict] | None = None, **kwargs) -> LLMResponse: ...
```

**Internal implementation notes:**
- Constructs the concrete adapter once (lazily, on first `generate` call or in `__init__`) based on `settings.llm_provider` (`"lmstudio" | "ollama" | "openai_compat" | "fake"`).
- This is the **only** place in the codebase allowed to branch on provider name.

**Acceptance criteria:**
- With `settings.llm_provider == "fake"`, `ModelManager().generate(...)` delegates to `FakeAdapter`.
- Unknown provider string raises a clear `ValueError` at construction time, not at first use.

**Manual testing steps:**
1. `UA_LLM_PROVIDER=fake uv run python -c "..."` calling `ModelManager().generate(...)` and printing the result.

**Suggested pytest tests:**
- `tests/test_models/test_manager.py::test_selects_fake_adapter`
- `tests/test_models/test_manager.py::test_unknown_provider_raises`

**Suggested Git commit message:** `models: add ModelManager for provider selection`

**Dependencies on previous batches:** Batches 07–10.

**Common mistakes to avoid:**
- Don't let any other module (`ua/core/agent.py` included) import a concrete adapter class directly — always go through `ModelManager`.

---

### Batch 12 — Short-Term Memory

**Objective:** In-process session memory (recent turns, active topic).

**Files to create:**
- `ua/memory/short_term.py`

**Public APIs to implement:**
```python
class ShortTermMemory:
    def __init__(self, max_turns: int = 20): ...
    async def get(self, user_id: str, key: str) -> str | None: ...
    async def put(self, user_id: str, key: str, value: str) -> None: ...
    async def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]: ...
    async def append_turn(self, user_id: str, role: str, content: str) -> None: ...
    async def recent_turns(self, user_id: str, limit: int = 10) -> list[Message]: ...
```

**Internal implementation notes:**
- Backed by `dict[str, deque[Message]]` keyed by `user_id`; `deque(maxlen=max_turns)` handles capping automatically.
- Implements the same `MemoryStore` shape as `LongTermMemory` for interchangeability where sensible, plus the two extra turn-specific methods `ConversationManager` needs.

**Acceptance criteria:**
- Appending more than `max_turns` turns drops the oldest ones.
- `recent_turns` returns turns in chronological order.

**Manual testing steps:**
1. Script appending 25 turns with `max_turns=20`, printing `len(recent_turns(..., limit=100))` — should be 20.

**Suggested pytest tests:**
- `tests/test_memory/test_short_term.py::test_cap_evicts_oldest`
- `tests/test_memory/test_short_term.py::test_recent_turns_order`

**Suggested Git commit message:** `memory: add in-process short-term memory`

**Dependencies on previous batches:** Batch 05 (for shared `MemoryItem`/`MemoryStore` types).

**Common mistakes to avoid:**
- Don't persist this to disk — it's explicitly ephemeral in v1; document that clearly in the module docstring.

---

### Batch 13 — Knowledge Memory

**Objective:** File/document store layer for uploaded knowledge (docs, notes).

**Files to create:**
- `ua/memory/knowledge.py`
- `ua/database/models.py` — add a `KnowledgeDocument` table (id, user_id, title, content, created_at)

**Public APIs to implement:**
```python
class KnowledgeMemory:
    async def add_document(self, user_id: str, title: str, content: str) -> str: ...  # returns doc id
    async def get(self, user_id: str, key: str) -> str | None: ...
    async def put(self, user_id: str, key: str, value: str) -> None: ...
    async def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]: ...
```

**Internal implementation notes:**
- `search` again uses naive substring/keyword matching over `content`, same "replace with vector search later" contract as `LongTermMemory`. Keep both implementations consistent so a future vector-memory batch can replace them with matching diffs.

**Acceptance criteria:**
- Adding a document then searching a keyword from its content returns it.

**Manual testing steps:**
1. Script adding a short doc, searching a word from it, printing matches.

**Suggested pytest tests:**
- `tests/test_memory/test_knowledge.py::test_add_and_search_document`
- `tests/test_memory/test_knowledge.py::test_search_no_match`

**Suggested Git commit message:** `memory: add knowledge document store`

**Dependencies on previous batches:** Batch 04.

**Common mistakes to avoid:**
- Don't add file-upload/parsing logic yet (PDF/docx extraction) — this batch is plain-text-in, plain-text-out only.

---

### Batch 14 — Memory Manager

**Objective:** Single facade aggregating short-term, long-term, and knowledge memory for the Conversation layer.

**Files to create:**
- `ua/memory/manager.py`

**Public APIs to implement:**
```python
class MemoryManager:
    def __init__(self, short_term: ShortTermMemory, long_term: LongTermMemory, knowledge: KnowledgeMemory): ...
    async def retrieve_context(self, user_id: str, message: str) -> RetrievedContext: ...
    async def record_turn(self, user_id: str, role: str, content: str) -> None: ...
    async def remember_fact(self, user_id: str, key: str, value: str) -> None: ...

@dataclass
class RetrievedContext:
    recent_turns: list[Message]
    relevant_facts: list[MemoryItem]
    relevant_knowledge: list[MemoryItem]
```

**Internal implementation notes:**
- `retrieve_context` calls `short_term.recent_turns`, `long_term.search`, and `knowledge.search` concurrently via `asyncio.gather`.
- This class is the **only** thing `ConversationManager`/`ContextBuilder` are allowed to depend on for memory — never the three sub-stores directly.

**Acceptance criteria:**
- `retrieve_context` returns a populated `RetrievedContext` combining all three sources.
- `record_turn` writes to short-term memory (and, per design, may also asynchronously persist to long-term summary later — not required in v1, just short-term for now).

**Manual testing steps:**
1. Script wiring up a `MemoryManager` with fake/in-memory stores, calling `record_turn` then `retrieve_context`, printing results.

**Suggested pytest tests:**
- `tests/test_memory/test_manager.py::test_retrieve_context_aggregates_all_layers`
- `tests/test_memory/test_manager.py::test_record_turn_updates_short_term`

**Suggested Git commit message:** `memory: add MemoryManager facade over all three layers`

**Dependencies on previous batches:** Batches 05, 12, 13.

**Common mistakes to avoid:**
- Don't let `ConversationManager` (next phase) reach into `self.memory.long_term` directly — always through `MemoryManager`'s public methods.

---

### Batch 15 — Tool Base & ToolResult

**Objective:** Define the `Tool` ABC and result type all plugins implement.

**Files to create:**
- `ua/tools/base.py`

**Public APIs to implement:**
```python
@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None

class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict]  # JSON schema
    enabled: ClassVar[bool] = True

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult: ...
```

**Acceptance criteria:**
- A minimal dummy `Tool` subclass can be instantiated and `run()` awaited, returning a `ToolResult`.

**Manual testing steps:**
1. Write a throwaway subclass in a scratch script confirming the ABC enforces `run` implementation (instantiating without it raises `TypeError`).

**Suggested pytest tests:**
- `tests/test_tools/test_base.py::test_cannot_instantiate_without_run`
- `tests/test_tools/test_base.py::test_tool_result_shape`

**Suggested Git commit message:** `tools: add Tool ABC and ToolResult`

**Dependencies on previous batches:** Batch 01.

**Common mistakes to avoid:**
- Don't add auto-registration logic here — that's Batch 18's job. Keep this batch purely about the interface.

---

### Batch 16 — Calculator Tool

**Objective:** First concrete tool, exercising the `Tool` interface end-to-end.

**Files to create:**
- `ua/tools/calculator.py`

**Public APIs to implement:**
```python
class CalculatorTool(Tool):
    name = "calculator"
    description = "Evaluate a basic arithmetic expression, e.g. '2 + 2 * 3'."
    parameters = {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}

    async def run(self, expression: str) -> ToolResult: ...
```

**Internal implementation notes:**
- Use Python's `ast` module to parse and evaluate only a safe numeric-expression subset (`+ - * / ** ()` and numeric literals) — **never** use bare `eval()`. Reject anything else with `ToolResult(success=False, error=...)`.

**Acceptance criteria:**
- `run(expression="2 + 2 * 3")` returns `success=True, output="8"`.
- `run(expression="__import__('os')")` returns `success=False` and does not execute anything.

**Manual testing steps:**
1. Script calling `CalculatorTool().run(expression="(2 + 3) * 4")`, confirm output `20`.
2. Try a malicious expression, confirm safe rejection.

**Suggested pytest tests:**
- `tests/test_tools/test_calculator.py::test_basic_arithmetic`
- `tests/test_tools/test_calculator.py::test_rejects_unsafe_expression`
- `tests/test_tools/test_calculator.py::test_division_by_zero_handled`

**Suggested Git commit message:** `tools: add safe calculator tool`

**Dependencies on previous batches:** Batch 15.

**Common mistakes to avoid:**
- Never use `eval()`/`exec()` directly on user input, even "just for the calculator."

---

### Batch 17 — Filesystem Tool

**Objective:** Sandboxed read-only (by default) filesystem access tool.

**Files to create:**
- `ua/tools/filesystem.py`

**Public APIs to implement:**
```python
class FilesystemTool(Tool):
    name = "filesystem"
    description = "Read files or list directories within an allowed sandbox root."
    parameters = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["read", "list"]},
        "path": {"type": "string"},
    }, "required": ["action", "path"]}

    def __init__(self, sandbox_root: Path): ...
    async def run(self, action: str, path: str) -> ToolResult: ...
```

**Internal implementation notes:**
- Resolve `path` relative to `sandbox_root` and reject any resolved path that escapes it (classic path-traversal check via `Path.resolve()` + `is_relative_to`).
- Writing/deleting is out of scope for this batch — read/list only. A future tool or batch can add guarded writes gated by `settings.tools_allow_destructive`.

**Acceptance criteria:**
- Reading a file inside the sandbox succeeds.
- Attempting `../../etc/passwd`-style traversal is rejected with `success=False`.

**Manual testing steps:**
1. Script instantiating `FilesystemTool(sandbox_root=Path("./sandbox_test"))`, reading a real file inside it, then attempting a traversal path and confirming rejection.

**Suggested pytest tests:**
- `tests/test_tools/test_filesystem.py::test_read_file_in_sandbox`
- `tests/test_tools/test_filesystem.py::test_list_directory`
- `tests/test_tools/test_filesystem.py::test_path_traversal_rejected`

**Suggested Git commit message:** `tools: add sandboxed filesystem read tool`

**Dependencies on previous batches:** Batch 15.

**Common mistakes to avoid:**
- Don't resolve symlinks naively — a symlink inside the sandbox pointing outside it is still a traversal; test for this if time allows, and at minimum document it as a known limitation.

---

### Batch 18 — Tool Registry / Auto-Discovery

**Objective:** Discover all enabled `Tool` subclasses under `ua/tools/` automatically and expose their JSON schemas to the Model layer.

**Files to create:**
- `ua/tools/registry.py`

**Public APIs to implement:**
```python
class ToolRegistry:
    def __init__(self): ...
    def discover(self, package: str = "ua.tools") -> None: ...
    def get(self, name: str) -> Tool: ...
    def all_schemas(self) -> list[dict]: ...
    async def execute(self, name: str, **kwargs) -> ToolResult: ...
```

**Internal implementation notes:**
- Use `pkgutil.iter_modules` + `importlib` to import every module in `ua/tools/` (excluding `base.py`/`registry.py`/`__init__.py`), then `inspect.getmembers` to find `Tool` subclasses with `enabled = True`.
- Instantiate tools with no required constructor args by default; tools needing config (like `FilesystemTool`'s `sandbox_root`) should be registered with a small factory mapping in this file rather than assuming a no-arg constructor works universally.

**Acceptance criteria:**
- `ToolRegistry().discover()` finds both `CalculatorTool` and `FilesystemTool`.
- `execute("calculator", expression="1+1")` returns the correct `ToolResult`.
- Requesting an unknown tool name raises a clear `ToolNotFoundError`.

**Manual testing steps:**
1. Script calling `discover()` then printing `all_schemas()` — confirm both tools appear.

**Suggested pytest tests:**
- `tests/test_tools/test_registry.py::test_discovers_known_tools`
- `tests/test_tools/test_registry.py::test_execute_known_tool`
- `tests/test_tools/test_registry.py::test_unknown_tool_raises`

**Suggested Git commit message:** `tools: add auto-discovering ToolRegistry`

**Dependencies on previous batches:** Batches 16, 17.

**Common mistakes to avoid:**
- Don't require every future tool author to manually edit this file to register a tool — discovery must be automatic for no-arg tools.

---

### Batch 19 — Context Builder

**Objective:** Assemble the final message list sent to the LLM from personality + retrieved memory + conversation history.

**Files to create:**
- `ua/conversation/context_builder.py`

**Public APIs to implement:**
```python
class ContextBuilder:
    def __init__(self, personality_loader: PersonalityLoader): ...
    def build(
        self,
        personality_name: str,
        context: RetrievedContext,
        new_user_message: str,
    ) -> list[Message]: ...
```

**Internal implementation notes:**
- Order: one `system` message = `personality.system_prompt + "\n\n" + personality.style` (+ a compact rendering of `relevant_facts`/`relevant_knowledge` appended as a "Known context" section), followed by `recent_turns` as alternating `user`/`assistant` messages, followed by the new `user` message.
- Respect `personality.rules.max_response_tokens` by passing it through as a `kwargs` hint (actual enforcement happens at the adapter/`ModelManager` call site, not here — this method only builds messages).

**Acceptance criteria:**
- `build(...)` returns a message list starting with exactly one `system` message and ending with the new user message.
- Facts/knowledge with no matches produce a clean prompt (no empty "Known context: " noise).

**Manual testing steps:**
1. Script constructing a fake `RetrievedContext`, calling `build(...)`, printing the resulting message list.

**Suggested pytest tests:**
- `tests/test_conversation/test_context_builder.py::test_system_message_first`
- `tests/test_conversation/test_context_builder.py::test_history_ordering_preserved`
- `tests/test_conversation/test_context_builder.py::test_empty_context_no_noise`

**Suggested Git commit message:** `conversation: add ContextBuilder for prompt assembly`

**Dependencies on previous batches:** Batches 06, 14.

**Common mistakes to avoid:**
- Don't hardcode any persona wording here — it must come entirely from the loaded `Personality`.

---

### Batch 20 — Conversation Manager

**Objective:** Session/turn bookkeeping — the layer that ties a `(user_id, platform)` to an ongoing conversation.

**Files to create:**
- `ua/conversation/manager.py`

**Public APIs to implement:**
```python
class ConversationManager:
    def __init__(self, memory: MemoryManager, db_session_factory: Callable[[], AsyncSession]): ...
    async def get_or_create_session(self, user_id: str, platform: str) -> str: ...  # returns session_id
    async def handle_incoming(self, user_id: str, platform: str, message: str) -> RetrievedContext: ...
    async def handle_outgoing(self, user_id: str, platform: str, response: str) -> None: ...
```

**Internal implementation notes:**
- `handle_incoming` records the user turn (via `MemoryManager.record_turn`) and returns the retrieved context for the `ContextBuilder`.
- `handle_outgoing` records the assistant turn.
- Session persistence to the `Session`/`Message` DB tables (Batch 04) can be a thin write-through here — short-term memory remains the fast path used by `ContextBuilder`; DB rows are for durability/audit, not hot-path reads, in v1.

**Acceptance criteria:**
- Calling `handle_incoming` then `handle_outgoing` results in both turns visible via `MemoryManager.retrieve_context`'s `recent_turns`.
- `get_or_create_session` returns the same session id on repeated calls for the same `(user_id, platform)`.

**Manual testing steps:**
1. Script simulating a two-turn conversation, printing `recent_turns` after each turn to confirm accumulation.

**Suggested pytest tests:**
- `tests/test_conversation/test_manager.py::test_session_id_stable_across_calls`
- `tests/test_conversation/test_manager.py::test_incoming_then_outgoing_recorded`

**Suggested Git commit message:** `conversation: add ConversationManager for session/turn bookkeeping`

**Dependencies on previous batches:** Batches 04, 14.

**Common mistakes to avoid:**
- Don't let this class call the LLM or build prompts itself — that's `UnifiedAgent`'s and `ContextBuilder`'s job respectively; this class is bookkeeping only.

---

### Batch 21 — UnifiedAgent Core

**Objective:** The single public entrypoint (`agent.chat(...)`) that wires together Conversation, Memory, Context, Model, and Tools into the full pipeline described in `ARCHITECTURE.md` §3.

**Files to create:**
- `ua/core/agent.py`

**Public APIs to implement:**
```python
class UnifiedAgent:
    def __init__(
        self,
        conversation: ConversationManager,
        context_builder: ContextBuilder,
        model_manager: ModelManager,
        tool_registry: ToolRegistry,
        personality_name: str,
    ): ...

    async def chat(self, user_id: str, platform: str, message: str) -> str: ...
```

**Internal implementation notes:**
- `chat()` implements the full pipeline: `conversation.handle_incoming` → `context_builder.build` → `model_manager.generate(messages, tools=tool_registry.all_schemas())` → if `response.tool_calls`, execute each via `tool_registry.execute`, append tool results as `role="tool"` messages, call `model_manager.generate` again (single follow-up round in v1 — no unbounded tool loop yet, that's Batch 25) → `conversation.handle_outgoing` → return final text.
- Provide a small `ua/core/factory.py`-style function `build_default_agent() -> UnifiedAgent` (in this same file or a sibling `factory.py`) that wires real (non-fake) dependencies from `get_settings()`, for interfaces to use without hand-assembling the graph themselves.

**Acceptance criteria:**
- End-to-end test using `FakeAdapter` (no tool calls) returns the fake adapter's echoed content and records both turns in memory.
- End-to-end test where the injected fake response includes one tool call correctly executes the tool and produces a final response incorporating the tool's output (verified via a second canned `FakeAdapter` response).

**Manual testing steps:**
1. `uv run python -c "..."` building a fully in-memory/fake-adapter agent, calling `await agent.chat(user_id='u1', platform='cli', message='hello')`, printing the response.
2. Repeat with `UA_LLM_PROVIDER=fake` via `build_default_agent()` to confirm the factory wiring works too.

**Suggested pytest tests:**
- `tests/test_core/test_agent.py::test_chat_simple_roundtrip`
- `tests/test_core/test_agent.py::test_chat_with_single_tool_call`
- `tests/test_core/test_agent.py::test_build_default_agent_uses_settings`

**Suggested Git commit message:** `core: add UnifiedAgent orchestrating the full chat pipeline`

**Dependencies on previous batches:** Batches 11, 14, 18, 19, 20.

**Common mistakes to avoid:**
- Don't import anything from `ua/interfaces/` here.
- Don't build an unbounded tool-call loop yet — one follow-up round is enough for v1; Batch 25 hardens this.

---

### Batch 22 — CLI Interface

**Objective:** A minimal, thin command-line chat loop calling `UnifiedAgent`.

**Files to create:**
- `ua/interfaces/cli/main.py`

**Files to modify:**
- `pyproject.toml` — add a `[project.scripts]` entry, e.g. `unified-agent-cli = "ua.interfaces.cli.main:run"`.

**Public APIs to implement:**
```python
def run() -> None: ...  # sync entrypoint, sets up asyncio loop, configure_logging(), builds agent, reads stdin in a loop
```

**Internal implementation notes:**
- `run()` is the only place in `ua/interfaces/cli/` allowed to call `configure_logging()` and `build_default_agent()`.
- `user_id` for the CLI can default to the OS username or a fixed `"local-user"` constant; `platform="cli"`.
- Handle `Ctrl+C`/`EOF` gracefully (exit code 0).

**Acceptance criteria:**
- Running the CLI, typing a message, and getting a printed response works end-to-end against `UA_LLM_PROVIDER=fake`.

**Manual testing steps:**
1. `UA_LLM_PROVIDER=fake uv run unified-agent-cli`, type a message, confirm a response prints, then `Ctrl+D` to exit cleanly.

**Suggested pytest tests:**
- `tests/test_interfaces/test_cli.py::test_run_handles_eof_gracefully` (feed empty stdin via monkeypatch, assert clean exit)

**Suggested Git commit message:** `interfaces: add CLI chat loop`

**Dependencies on previous batches:** Batch 21.

**Common mistakes to avoid:**
- Don't put any prompt-building or memory logic in this file — it's I/O only.

---

### Batch 23 — Web API Interface (FastAPI)

**Objective:** Thin HTTP wrapper exposing `POST /chat`.

**Files to create:**
- `ua/interfaces/web/api.py`

**Files to modify:**
- `pyproject.toml` — ensure `web` optional group has `fastapi` + `uvicorn`.

**Public APIs to implement:**
```python
class ChatRequest(BaseModel):
    user_id: str
    message: str

class ChatResponse(BaseModel):
    response: str

app = FastAPI()

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest) -> ChatResponse: ...

@app.get("/health")
async def health() -> dict: ...
```

**Internal implementation notes:**
- Build the `UnifiedAgent` once at app startup (`@app.on_event("startup")` or lifespan handler) via `build_default_agent()`, store on `app.state.agent`.
- `platform="web"` is fixed for all requests through this interface.

**Acceptance criteria:**
- `GET /health` returns `200 {"status": "ok"}`.
- `POST /chat` with a valid body returns `200` and a `ChatResponse`.

**Manual testing steps:**
1. `UA_LLM_PROVIDER=fake uv run uvicorn ua.interfaces.web.api:app --reload`, then `curl -X POST localhost:8000/chat -d '{"user_id":"u1","message":"hi"}' -H 'content-type: application/json'`.

**Suggested pytest tests:**
- `tests/test_interfaces/test_web_api.py::test_health_endpoint` (using `httpx.AsyncClient` + FastAPI's `ASGITransport`, `UA_LLM_PROVIDER=fake`)
- `tests/test_interfaces/test_web_api.py::test_chat_endpoint_roundtrip`

**Suggested Git commit message:** `interfaces: add FastAPI web chat endpoint`

**Dependencies on previous batches:** Batch 21.

**Common mistakes to avoid:**
- Don't build a new `UnifiedAgent` per request — build once, reuse.

---

### Batch 24 — Discord Interface

**Objective:** Thin Discord bot wrapper.

**Files to create:**
- `ua/interfaces/discord/bot.py`

**Files to modify:**
- `pyproject.toml` — ensure `discord` optional group has `discord.py`.

**Public APIs to implement:**
```python
def create_bot(agent: UnifiedAgent) -> discord.Client: ...
def run() -> None: ...  # entrypoint: configure_logging(), build_default_agent(), create_bot(...), client.run(settings.discord_token)
```

**Internal implementation notes:**
- On `on_message`, ignore messages from bots (including itself), extract `user_id=str(message.author.id)`, `platform="discord"`, `message=message.content`, call `await agent.chat(...)`, `await message.channel.send(response)`.
- If `settings.discord_token` is unset, `run()` should raise a clear, actionable error rather than a cryptic discord.py exception.

**Acceptance criteria:**
- `create_bot(agent)` returns a configured `discord.Client` with an `on_message` handler wired to the injected agent (verifiable without connecting to real Discord, by calling the handler directly with a mocked `message` object in a test).

**Manual testing steps:**
1. With a real `UA_DISCORD_TOKEN` set and `UA_LLM_PROVIDER=fake`, run `uv run python -m ua.interfaces.discord.bot`, message the bot in a test server, confirm a reply.

**Suggested pytest tests:**
- `tests/test_interfaces/test_discord_bot.py::test_on_message_calls_agent_and_replies` (using a `MagicMock`/`AsyncMock` Discord message object — no real Discord connection).
- `tests/test_interfaces/test_discord_bot.py::test_ignores_bot_messages`

**Suggested Git commit message:** `interfaces: add Discord bot interface`

**Dependencies on previous batches:** Batch 21.

**Common mistakes to avoid:**
- Don't let this file import `ua/memory`/`ua/models` directly — everything goes through `agent.chat`.
- Don't skip the bot-message-ignore check — infinite reply loops are a classic bug here.

---

### Batch 25 — Tool-Calling Loop Hardening

**Objective:** Replace the single-follow-up-round tool handling in `UnifiedAgent.chat` (Batch 21) with a bounded loop supporting multiple sequential tool calls.

**Files to modify:**
- `ua/core/agent.py`
- `ua/config/settings.py` — add `max_tool_call_rounds: int = 3`

**Internal implementation notes:**
- Loop `generate → execute any tool_calls → append results → generate again` up to `max_tool_call_rounds` times; if the limit is hit while the model still wants tools, return the best available text response plus a logged warning rather than erroring out to the user.

**Acceptance criteria:**
- A scripted `FakeAdapter` sequence with two chained tool calls resolves correctly within the loop.
- Exceeding `max_tool_call_rounds` degrades gracefully (no exception surfaced to the caller).

**Manual testing steps:**
1. Construct a `FakeAdapter` with a scripted sequence of 3 canned responses (tool call → tool call → final text) and confirm `chat()` returns the final text.

**Suggested pytest tests:**
- `tests/test_core/test_agent.py::test_multi_round_tool_calls_resolve`
- `tests/test_core/test_agent.py::test_exceeding_max_rounds_degrades_gracefully`

**Suggested Git commit message:** `core: harden tool-calling loop with bounded rounds`

**Dependencies on previous batches:** Batch 21.

**Common mistakes to avoid:**
- Don't make the loop unbounded — always respect `max_tool_call_rounds`.

---

### Batch 26 — Retry / Error-Handling Layer for LLM Calls

**Objective:** Add retry-with-backoff around `ModelManager.generate` for transient failures.

**Files to modify:**
- `ua/models/manager.py`
- `ua/config/settings.py` — add `llm_max_retries: int = 2`, `llm_retry_backoff_seconds: float = 0.5`

**Internal implementation notes:**
- Wrap the adapter call in a small retry helper (hand-rolled `for` loop with `asyncio.sleep`, or the `tenacity` library if added as a core dependency) that retries only on `LLMAdapterError` (transient), not on programmer errors (`ValueError`, etc.).
- Log each retry attempt at `WARNING` level.

**Acceptance criteria:**
- A `FakeAdapter`/mock configured to fail twice then succeed results in `ModelManager.generate` ultimately succeeding, having retried exactly twice.
- A mock that always fails exhausts retries and raises `LLMAdapterError` to the caller.

**Manual testing steps:**
1. Unit-test-style script wiring a mock adapter with a failure counter, confirming retry counts match `llm_max_retries`.

**Suggested pytest tests:**
- `tests/test_models/test_manager.py::test_retries_on_transient_failure`
- `tests/test_models/test_manager.py::test_raises_after_exhausting_retries`

**Suggested Git commit message:** `models: add retry/backoff to ModelManager`

**Dependencies on previous batches:** Batch 11.

**Common mistakes to avoid:**
- Don't retry on non-transient errors (bad request/validation) — only on the transient `LLMAdapterError` category.

---

### Batch 27 — Memory Summarization / Compaction

**Objective:** When short-term memory approaches its cap, summarize older turns into a long-term fact rather than silently dropping them.

**Files to modify:**
- `ua/memory/manager.py`
- `ua/memory/short_term.py` (expose an eviction hook/callback)

**Internal implementation notes:**
- `MemoryManager` can accept an optional summarizer callable `Callable[[list[Message]], Awaitable[str]]` (defaulting to a trivial concatenation-truncation in v1 — full LLM-based summarization can reuse `ModelManager` but is optional/pluggable here to keep this batch small); evicted turns get passed to it and the result is stored via `long_term.put(user_id, "conversation_summary", ...)`.

**Acceptance criteria:**
- Simulating enough turns to trigger eviction results in a `conversation_summary` fact appearing in long-term memory.

**Manual testing steps:**
1. Script pushing `max_turns + 5` turns through `MemoryManager.record_turn`, then reading back the `conversation_summary` fact.

**Suggested pytest tests:**
- `tests/test_memory/test_manager.py::test_eviction_triggers_summary_write`

**Suggested Git commit message:** `memory: add summarization hook on short-term eviction`

**Dependencies on previous batches:** Batch 14.

**Common mistakes to avoid:**
- Don't make the default summarizer call a real LLM by default (would break the "no network in tests" rule) — default must be a pure-Python truncation/concatenation function.

---

### Batch 28 — Personality Hot-Switching

**Objective:** Allow changing the active personality for a user mid-conversation without restarting the process.

**Files to modify:**
- `ua/core/agent.py` — `chat()` gains an optional `personality_override: str | None` parameter; also persist a per-user personality preference via `MemoryManager.remember_fact(user_id, "active_personality", name)`.

**Internal implementation notes:**
- Resolution order for which personality to use on a given call: explicit `personality_override` param > per-user stored preference > `UnifiedAgent`'s default `personality_name`.

**Acceptance criteria:**
- Calling `chat(..., personality_override="assistant")` uses that personality even if a different one was previously active for that user.
- A previously stored per-user preference is respected on subsequent calls without needing to pass the override again.

**Manual testing steps:**
1. Add a second minimal test personality directory (`personalities/tester/`) for this batch, then script two `chat()` calls for the same user switching personalities and confirm the system prompt used differs (assertable via a `FakeAdapter` that captures the messages it received).

**Suggested pytest tests:**
- `tests/test_core/test_agent.py::test_personality_override_applies`
- `tests/test_core/test_agent.py::test_stored_preference_persists_across_calls`

**Suggested Git commit message:** `core: support per-user personality overrides`

**Dependencies on previous batches:** Batches 06, 21.

**Common mistakes to avoid:**
- Don't hardcode the second test personality's content anywhere but its own directory files.

---

### Batch 29 — Structured Logging & Observability Pass

**Objective:** Add consistent, structured log lines across the pipeline (turn received, tool executed, LLM call duration, errors) without changing behavior.

**Files to modify:**
- `ua/core/agent.py`
- `ua/models/manager.py`
- `ua/tools/registry.py`

**Internal implementation notes:**
- Use `get_logger(__name__)` from Batch 03 everywhere; log at `INFO` for lifecycle events (turn start/end, tool executed) and `DEBUG` for full message payloads (never log full payloads at `INFO` — could contain sensitive user data).
- Measure and log LLM call duration (`time.monotonic()` diff) as part of the `INFO` line.

**Acceptance criteria:**
- Running the CLI against the fake adapter produces readable `INFO` log lines for each stage of a turn, with no duplicate handler output (still respecting Batch 03's idempotency guarantee).

**Manual testing steps:**
1. `UA_LLM_PROVIDER=fake UA_LOG_LEVEL=INFO uv run unified-agent-cli`, send a message, inspect the log output for clear stage markers.

**Suggested pytest tests:**
- `tests/test_core/test_agent.py::test_logs_emitted_for_chat_call` (using `caplog`)

**Suggested Git commit message:** `observability: add structured logging across core pipeline`

**Dependencies on previous batches:** Batches 03, 21.

**Common mistakes to avoid:**
- Don't log raw user message content at `INFO` — keep that at `DEBUG` to respect potential sensitivity.

---

### Batch 30 — Test Suite Hardening & Fixtures Cleanup

**Objective:** Consolidate shared fixtures (in-memory DB, fake adapter, tmp sandbox dirs) into `tests/conftest.py`, remove duplication across test modules built up in Batches 1–29.

**Files to modify:**
- `tests/conftest.py`
- Any test files with duplicated fixture setup, refactored to use the shared ones.

**Internal implementation notes:**
- Provide fixtures: `settings_fake_llm`, `in_memory_db_session`, `memory_manager_stub`, `tool_registry_with_test_tools`.
- No behavior change to production code in this batch — test-only refactor.

**Acceptance criteria:**
- Full suite still passes (`uv run pytest`) with reduced duplication and no fixture name collisions.

**Manual testing steps:**
1. `uv run pytest -q` — confirm same test count as before, all green.

**Suggested pytest tests:** (none new — this batch is about consolidating existing tests)

**Suggested Git commit message:** `tests: consolidate shared fixtures in conftest.py`

**Dependencies on previous batches:** Batches 22–24 (needs the full test surface to exist first).

**Common mistakes to avoid:**
- Don't change any production-code behavior "while I'm in there" — keep this batch strictly test-scoped.

---

### Batch 31 — Example Scripts

**Objective:** Add `examples/` scripts demonstrating common usage patterns for new contributors.

**Files to create:**
- `examples/minimal_cli_chat.py` — smallest possible script wiring `build_default_agent()` and running one `chat()` call.
- `examples/custom_tool_example.py` — shows adding a new `Tool` subclass and registering it via discovery.
- `examples/switch_personality.py` — demonstrates `personality_override` usage from Batch 28.

**Internal implementation notes:**
- Each example must run standalone with `UA_LLM_PROVIDER=fake` and no external services, so new contributors can execute them immediately after cloning.

**Acceptance criteria:**
- Each example script runs to completion with exit code 0 under `UA_LLM_PROVIDER=fake`.

**Manual testing steps:**
1. `UA_LLM_PROVIDER=fake uv run python examples/minimal_cli_chat.py` (repeat for the other two).

**Suggested pytest tests:**
- `tests/test_examples.py::test_all_examples_run_successfully` (subprocess-run each example, assert return code 0)

**Suggested Git commit message:** `docs: add runnable example scripts`

**Dependencies on previous batches:** Batch 21 (and 28 for the personality example).

**Common mistakes to avoid:**
- Don't let examples require a real LLM server to run — always default to the fake provider so CI can execute them.

---

### Batch 32 — Documentation Pass

**Objective:** Expand `docs/` with generated/curated reference material beyond `ARCHITECTURE.md`/`CONTRIBUTING.md`: a getting-started guide and a plugin-authoring guide.

**Files to create:**
- `docs/getting-started.md`
- `docs/writing-a-tool.md`
- `docs/writing-a-personality.md`
- `docs/writing-an-adapter.md`

**Internal implementation notes:**
- Each doc should be short (under ~150 lines), task-oriented, and link back to the relevant section of `ARCHITECTURE.md`/`CONTRIBUTING.md` rather than duplicating content.

**Acceptance criteria:**
- Following `docs/getting-started.md` from a clean clone results in a running CLI chat against the fake provider.

**Manual testing steps:**
1. Have a fresh contributor (or simulate one) follow `docs/getting-started.md` verbatim and confirm it works.

**Suggested pytest tests:** none (documentation-only batch).

**Suggested Git commit message:** `docs: add getting-started and plugin-authoring guides`

**Dependencies on previous batches:** Batch 31.

**Common mistakes to avoid:**
- Don't let docs drift from the actual API — cross-check every code snippet against the real current signatures before committing.

---

### Batch 33 — Packaging & Distribution Readiness

**Objective:** Final polish pass: ensure `pyproject.toml` metadata is complete, version is consistent, and the package can be built/installed cleanly, without adding Docker/Kubernetes (explicitly out of scope for v1 per `ARCHITECTURE.md` §13).

**Files to modify:**
- `pyproject.toml` — complete `[project]` metadata (description, license, authors, classifiers, `readme`).
- `README.md` — full project overview, install instructions, quickstart, links to `ARCHITECTURE.md`/`CONTRIBUTING.md`/`docs/`.

**Internal implementation notes:**
- `uv build` should produce a valid sdist/wheel with no errors.

**Acceptance criteria:**
- `uv build` succeeds.
- `uv run pytest`, `uv run ruff check .` both pass on the final tree.
- `README.md` alone is sufficient for a new user to get a working CLI chat.

**Manual testing steps:**
1. `uv build`
2. Fresh clone in a scratch directory, follow only `README.md`, confirm success.

**Suggested pytest tests:** none (packaging-only batch); optionally a smoke test invoking `uv build` via subprocess in CI.

**Suggested Git commit message:** `chore: finalize packaging metadata and README for v1`

**Dependencies on previous batches:** Batch 32.

**Common mistakes to avoid:**
- Don't scope-creep into Docker/K8s packaging — that's explicitly a future feature, not part of v1.

---

## 5. First Cline Implementation Prompt

Use this as the literal first message to Cline (StepFun 3.7 Flash) to kick off implementation. It intentionally repeats key constraints inline since the executing agent may not retain the full roadmap in context across sessions.

```
You are implementing Batch 01 of the "Unified Agent" project, exactly as specified below. Do not implement anything beyond this batch. Do not skip ahead to config, memory, models, or interfaces — those are later batches.

OBJECTIVE:
Create the repository skeleton, pyproject.toml, and an empty but importable `ua` package, managed with `uv`.

FILES TO CREATE:
- pyproject.toml
- README.md (placeholder: project name "Unified Agent" + one-line description "One Mind. Every Interface.")
- .gitignore (standard Python: __pycache__, *.pyc, .venv, .env, *.db, .pytest_cache, .ruff_cache)
- .env.example (empty for now, just a comment header — config fields come in Batch 02)
- ua/__init__.py containing: __version__ = "0.1.0"
- ua/config/__init__.py
- ua/database/__init__.py
- ua/personality/__init__.py
- ua/models/__init__.py
- ua/memory/__init__.py
- ua/conversation/__init__.py
- ua/tools/__init__.py
- ua/core/__init__.py
- ua/interfaces/__init__.py
- tests/__init__.py
- tests/conftest.py (leave empty except a module docstring for now)
- tests/test_package.py (one test, see below)

PYPROJECT.TOML REQUIREMENTS:
- Python requires-python = ">=3.12"
- Build backend: hatchling (or uv's default if simpler — your choice, but it must produce a working `uv sync`)
- Core dependencies: pydantic>=2, sqlalchemy>=2, httpx, python-dotenv
- [project.optional-dependencies] groups: discord = ["discord.py"], web = ["fastapi", "uvicorn"], dev = ["pytest", "pytest-asyncio", "ruff"]
- Do NOT add discord.py or fastapi as core (non-optional) dependencies.

TEST TO WRITE (tests/test_package.py):
    from ua import __version__

    def test_version():
        assert __version__ == "0.1.0"

ACCEPTANCE CRITERIA (verify all of these before considering the batch done):
1. `uv sync` completes without error.
2. `uv run python -c "import ua; print(ua.__version__)"` prints `0.1.0`.
3. `uv run pytest` passes (1 test collected, 1 passed).
4. `uv run ruff check .` passes with zero errors.

CONSTRAINTS:
- Do not create any files under ua/interfaces/discord/, ua/interfaces/web/, ua/interfaces/cli/, personalities/, or any file not explicitly listed above. Those come in later batches.
- Do not write any actual logic beyond the __version__ string — every other __init__.py is empty except for a one-line module docstring.
- When finished, run all four acceptance-criteria commands yourself and paste their output before declaring the batch complete.

When done, commit with the message: "chore: scaffold project structure and tooling"
```

---

## 6. Notes for Whoever Runs This Roadmap

- If StepFun 3.7 Flash produces a batch that doesn't meet its acceptance criteria, do not proceed to the next batch — feed the failing output back to it with a request to fix only that batch.
- Re-paste the relevant batch section (not the whole roadmap) as the prompt for each subsequent batch — this keeps the coding agent's context focused and reduces the chance of scope creep into future batches.
- `ARCHITECTURE.md` and `CONTRIBUTING.md` should be committed to the repo root before Batch 01 runs, so the coding agent (and any human reviewer) can reference them throughout.
