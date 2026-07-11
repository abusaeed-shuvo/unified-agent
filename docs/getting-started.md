# Getting Started with Unified Agent

This guide gets you from a fresh clone to a working CLI chat session.

## Prerequisites

- **Python 3.12+** (required)
- **uv** package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

## Setup

```bash
# Clone the repository (skip if already in the repo)
# git clone <repo-url>
# cd unified-agent

# Install all dependencies (core + dev + web + discord optional groups)
uv sync --all-extras

# Verify installation
uv run python -c "import ua; print('Unified Agent imported successfully')"
```

## Running the Test Suite

```bash
uv run pytest
```

All tests should pass. The suite includes ~200 tests covering the core, models, memory, conversation, and tools layers.

## Running the CLI with the Fake Provider

The fastest way to verify everything works is using the built-in fake LLM provider:

```bash
# Start the CLI (reads .env automatically)
uv run unified-agent-cli
```

Or run a minimal script that demonstrates the same:

```bash
uv run python examples/minimal_cli_chat.py
```

Expected output (the FakeAdapter echoes your message back):
```
============================================================
Minimal CLI Chat Example
============================================================

Building default agent...
Agent created successfully!

Sending message: 'Hello, agent!'
Response received:
  echo: Hello, agent!

Example completed successfully!
```

Type messages at the `You:` prompt. Press Ctrl+D (or Enter on an empty line) to exit.

## Configuring Real LLM Providers

For real LLM providers, set these environment variables in your `.env` file:

### LM Studio (local, unauthenticated)

```env
UA_LLM_PROVIDER=lmstudio
UA_LLM_BASE_URL=http://localhost:1234/v1
UA_LLM_MODEL=local-model
```

### Ollama (local)

```env
UA_LLM_PROVIDER=ollama
UA_LLM_BASE_URL=http://localhost:11434
UA_LLM_MODEL=llama3
```

### OpenAI-compatible (OpenRouter, vLLM, etc.)

```env
UA_LLM_PROVIDER=openai_compat
UA_LLM_BASE_URL=https://openrouter.ai/api/v1
UA_LLM_MODEL=openrouter/auto
```

Note: The current Settings class does not include `UA_LLM_API_KEY`. For authenticated endpoints like OpenRouter, you would need to modify `ua/config/settings.py` and `ua/models/manager.py` to add and pass the API key. LM Studio and Ollama are recommended for local development without authentication requirements.

After setting your `.env`, run `uv run unified-agent-cli` to connect to the configured provider.

## Next Steps

- Explore `examples/` for more usage patterns
- See Architecture.md for the system design overview
- See Contributing.md §5 for tool plugin conventions
- See Contributing.md §6 for personality conventions