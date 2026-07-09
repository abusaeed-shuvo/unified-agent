# Contributing to Unified Agent

Thanks for working on **Unified Agent**. This document is the practical rulebook — read `ARCHITECTURE.md` first for the *why*, this file for the *how*.

---

## 1. Core Design Principles (non-negotiable)

1. **One Core, Many Interfaces.** All reasoning, memory, prompt-building, and tool logic lives in `ua/core/`, `ua/memory/`, `ua/conversation/`, `ua/models/`, `ua/tools/`. Interfaces (`ua/interfaces/*`) only translate platform events into `agent.chat(...)` calls and render the result. If you find yourself writing an `if` statement about memory or prompts inside an interface file, stop and move it into the Core.
2. **No upward imports.** `ua/core/` must never import from `ua/interfaces/`. Run `python -c "import ua.core"` mentally before you commit — it should never need Discord/FastAPI installed to work.
3. **Interfaces are dependency-optional.** `discord.py` should not be a hard dependency of the whole package — someone using only the CLI shouldn't need to install it. Use optional dependency groups in `pyproject.toml` (see §7).
4. **Personality is data, not code.** Never hardcode tone, greetings, or persona rules in `.py` files. They live under `personalities/<name>/`.
5. **Providers are swappable by config, not by code edits.** Adding a new LLM provider means adding a new adapter file that implements `LLMAdapter`; it must never require changes to `ua/core/agent.py`.
6. **Memory layers stay behind `MemoryStore`.** Never let `ConversationManager` or `ContextBuilder` talk directly to SQLite, a vector DB, or the filesystem — always through `MemoryManager`.
7. **Small, incremental changes.** No PR should refactor more than one subsystem. If a change touches `ua/memory/` and `ua/interfaces/discord/` in the same PR, split it.

---

## 2. Coding Standards

- **Python 3.12+**, `uv` for environment/dependency management (`uv sync`, `uv run pytest`, etc.).
- **Type hints everywhere.** Every function signature must be fully typed, including return type. `Any` is allowed only at true I/O boundaries (raw LLM API responses, JSON parsing) and must be narrowed immediately after.
- **Async first.** Anything that does I/O (LLM calls, DB, filesystem, network) is `async def`. Sync wrappers are only allowed at interface entrypoints where the platform SDK demands it.
- **Pydantic v2** for anything that crosses a boundary (config, API request/response bodies, personality schema, LLM response normalization). Use plain `@dataclass` for internal-only value objects that never get serialized.
- **Ruff** for linting and formatting (`ruff check .`, `ruff format .`). CI fails on any lint error — no warnings-only mode.
- **Logging, not print().** Use the standard `logging` module via a shared `ua/config/logging.py` setup. Never `print()` in library code (`ua/`); `print()` is acceptable only inside `interfaces/cli/`.
- **No magic values.** Any constant that could plausibly change (timeouts, token limits, model names, file paths) belongs in `ua/config/settings.py`, not inline.
- **Docstrings** on every public class and function: one-line summary, then `Args`/`Returns`/`Raises` as needed. Private helpers (`_foo`) can skip this.

---

## 3. Naming Conventions

- Modules: `snake_case.py`.
- Classes: `PascalCase` (`MemoryManager`, `LLMAdapter`).
- Functions/variables: `snake_case`.
- Abstract base classes suffixed with nothing special (`Tool`, `LLMAdapter`, `MemoryStore`) — not `ToolBase` or `IMemoryStore`.
- Concrete adapters/implementations prefixed by what they are (`LMStudioAdapter`, `SQLiteLongTermMemory`, `DiscordInterface`).
- Test files mirror source paths: `ua/memory/short_term.py` → `tests/test_memory/test_short_term.py`.
- Environment variables: `UA_` prefix + `SCREAMING_SNAKE_CASE` (`UA_LLM_PROVIDER`, `UA_DATABASE_URL`).

---

## 4. Testing Requirements

- **Framework:** `pytest` + `pytest-asyncio` for async tests.
- Every batch that adds a public class/function must add tests covering:
  - The expected/happy path.
  - At least one edge case or failure mode (empty input, missing config, adapter timeout, etc.).
- **No network calls in unit tests.** LLM adapters must be tested against a fake/mock HTTP layer (e.g., `httpx.MockTransport` or a local stub server), never a live LM Studio/Ollama instance.
- **Database tests** use an in-memory or temp-file SQLite DB created fresh per test via a `conftest.py` fixture — never a shared/real DB file.
- Target: every PR keeps `pytest` green and does not lower coverage on the module it touches. There is no hard coverage percentage gate in v1, but untested public APIs will be requested in review.
- Manual testing steps (given in each batch) must also be run and confirmed before marking a batch complete — automated tests do not replace them for interface-level work (Discord/CLI/Web).

---

## 5. Plugin (Tool) Conventions

To add a new tool:

1. Create `ua/tools/<tool_name>.py`.
2. Subclass `Tool` (from `ua/tools/base.py`), setting `name`, `description`, and a JSON-schema `parameters` dict.
3. Implement `async def run(self, **kwargs) -> ToolResult`.
4. Do **not** register it manually anywhere — `ToolRegistry` auto-discovers all `Tool` subclasses under `ua/tools/` at startup. If your tool needs to opt out of auto-registration (e.g., experimental/incomplete), set `enabled = False` as a class attribute.
5. Add `tests/test_tools/test_<tool_name>.py` covering at least one successful call and one invalid-input call.
6. Tools must be side-effect-safe by default — anything destructive (filesystem writes, shell execution) must require an explicit `confirm=True`-style parameter or a config flag (`UA_TOOLS_ALLOW_DESTRUCTIVE`), defaulting to off.
7. Tool docstrings/`description` fields are sent to the LLM — write them for a language model audience: concise, unambiguous, example-bearing where useful.

---

## 6. Personality Conventions

To add a new personality:

1. Create `personalities/<name>/` with all four files: `system.md`, `style.md`, `rules.json`, `greetings.txt`.
2. `rules.json` must validate against `ua/personality/schema.py`'s Pydantic model — run `uv run python -m ua.personality.loader --validate <name>` (added in the personality batch) before committing.
3. Never reference a personality name from Python control flow (`if personality == "assistant": ...`). If personality-specific *behavior* (not just tone) seems necessary, that's a sign the behavior belongs in `rules.json` as data the Core reads generically.

---

## 7. Dependency Management

- Managed via `uv` and `pyproject.toml`.
- Core dependencies (always installed): `pydantic`, `sqlalchemy`, `httpx`, `python-dotenv`.
- Interface-specific dependencies go in optional groups:
  ```toml
  [project.optional-dependencies]
  discord = ["discord.py"]
  web = ["fastapi", "uvicorn"]
  dev = ["pytest", "pytest-asyncio", "ruff"]
  ```
- Keep the dependency list minimal — before adding a new third-party package, check whether the standard library or an existing dependency already covers it.

---

## 8. Git Workflow

- One batch (from the roadmap) = one commit (or small commit series if the batch is naturally sub-splittable), using the commit message suggested in that batch's spec.
- Commit message format: `<area>: <imperative summary>` (e.g., `memory: add SQLite-backed long-term store`).
- Every commit must leave the repo in a working state: `uv run pytest` passes, `ruff check .` passes, and the app still boots (`uv run python -m ua.interfaces.cli.main` or the relevant smoke command from the batch).
- Do not squash multiple unrelated batches into one commit.
- Do not start a batch whose declared dependencies (previous batches) aren't done and merged.

---

## 9. Review Checklist (use before marking a batch complete)

- [ ] No interface file imports from `ua/memory`, `ua/models`, `ua/tools`, or `ua/personality` directly.
- [ ] No hardcoded personality text or magic constants introduced.
- [ ] All new public functions/classes are fully typed and documented.
- [ ] Tests added and passing (`uv run pytest`).
- [ ] Lint clean (`uv run ruff check .`).
- [ ] Manual testing steps from the batch spec were actually performed.
- [ ] Acceptance criteria from the batch spec are all met.
- [ ] Commit message matches the suggested one (or is an equally clear improvement).

---

## 10. When In Doubt

Prefer the boring, explicit, small-diff option over the clever one. This project is designed to be implemented incrementally by an automated coding agent working batch-by-batch — anything that requires holding a lot of context in your head to understand is a smell, even if it's "better architecture" in the abstract. Optimize for the next contributor (human or AI) reading one file in isolation.
