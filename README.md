# Unified Agent

**One Mind. Every Interface.**

A reusable AI Core that provides a single conversational identity with memory and personality, exposed through multiple thin interfaces (CLI, Discord, Web API).

## What is this?

Unified Agent is a Python library that implements a complete AI conversation pipeline:

- **Unified identity**: One personality, one memory system, accessible from all interfaces
- **Multiple interfaces**: CLI, Discord bot, and Web API are included out of the box
- **Pluggable LLM providers**: Works with LM Studio, Ollama, OpenAI-compatible APIs, or a fake provider for testing
- **Built-in tools**: Calculator and filesystem tools for agent capabilities

## Installation

```bash
# Install with uv (recommended)
uv pip install unified-agent

# Or with pip
pip install unified-agent

# Install with extras for specific interfaces
uv pip install "unified-agent[discord]"  # For Discord bot
uv pip install "unified-agent[web]"      # For Web API
```

## Quick Start: CLI Chat

The fastest way to try Unified Agent is the built-in CLI with the fake provider (no API key required):

```bash
# Set up environment for testing
export UA_LLM_PROVIDER=fake
export UA_DATABASE_URL="sqlite+aiosqlite:///:memory:"

# Run the CLI
uv run unified-agent-cli
```

Once the CLI starts, type messages and press Enter:

```
You: Hello!
Agent: echo: Hello!

You: What is 2 + 2?
Agent: echo: What is 2 + 2?
```

Press Ctrl+D or enter an empty line to exit.

## Configuration

Unified Agent is configured via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UA_LLM_PROVIDER` | No | `lmstudio` | LLM provider: `lmstudio`, `ollama`, `openai_compat`, or `fake` |
| `UA_LLM_BASE_URL` | Depends | Provider-specific | Base URL for LM Studio or Ollama |
| `UA_LLM_MODEL` | Depends | Provider-specific | Model name to use |
| `UA_LLM_API_KEY` | For OpenAI | - | API key for OpenAI-compatible providers |
| `UA_DATABASE_URL` | No | `sqlite+aiosqlite:///./unified_agent.db` | SQLAlchemy database URL |
| `UA_DISCORD_TOKEN` | For Discord | - | Discord bot token |

## Interfaces

### CLI

```bash
uv run unified-agent-cli
```

### Web API

```bash
export UA_LLM_PROVIDER=fake
uv run python -m ua.interfaces.web.api
# Then POST to http://localhost:8000/chat
```

### Discord Bot

```bash
export UA_LLM_PROVIDER=fake
export UA_DISCORD_TOKEN=your_token_here
uv run python -m ua.interfaces.discord
```

## Project Structure

```
unified-agent/
├── ua/                    # Main package
│   ├── core/              # AI Core (agent, factory)
│   ├── interfaces/        # Thin adapters (cli, discord, web)
│   ├── memory/            # Memory system (short-term, long-term, knowledge)
│   ├── models/            # LLM adapters
│   ├── tools/             # Tool implementations
│   └── personality/       # Personality loader
├── docs/                  # Documentation
├── examples/              # Example scripts
├── tests/                 # Test suite
├── Architecture.md        # Architecture reference
├── Contributing.md        # Contribution guide
└── README.md              # This file
```

## Documentation

- **[Architecture.md](Architecture.md)** - Technical architecture and design rationale
- **[Contributing.md](Contributing.md)** - How to contribute to the project
- **[docs/getting-started.md](docs/getting-started.md)** - Detailed setup guide
- **[docs/writing-a-tool.md](docs/writing-a-tool.md)** - How to create custom tools
- **[docs/writing-a-personality.md](docs/writing-a-personality.md)** - How to create personalities

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Status

This is v1 of the project. See [Roadmap.md](Roadmap.md) for development history and completed features.