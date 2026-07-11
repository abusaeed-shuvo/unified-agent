# Writing a Personality

A personality defines the agent's voice and behavior. Each personality is pure data in a directory.

## Required Files

Create `personalities/<name>/` with exactly four files:

```
personalities/<name>/
├── system.md        # System prompt (core identity)
├── style.md         # Tone/voice guidance
├── rules.json       # Structured constraints
└── greetings.txt    # One greeting per line
```

### system.md

The system prompt defines core identity. From `personalities/assistant/system.md`:

> You are a helpful, honest, and direct AI assistant. Your purpose is to provide accurate, well-reasoned responses to the user's questions and requests.

### style.md

Tone guidance appended to the system prompt. From `personalities/assistant/style.md`:

> Prefer concise, direct answers. Use plain language and avoid unnecessary jargon. Be specific and precise rather than vague.

### rules.json

Structured constraints. From `personalities/assistant/rules.json`:

```json
{
    "allow_tools": ["calculator"],
    "max_response_tokens": 800,
    "forbidden_topics": []
}
```

The `tester` personality (`personalities/tester/rules.json`) shows a different set:

```json
{
    "allow_tools": ["calculator", "filesystem"],
    "max_response_tokens": 256,
    "forbidden_topics": ["casual_chat", "opinions"]
}
```

### greetings.txt

One greeting per line, picked contextualy. From `personalities/assistant/greetings.txt`:

```
Hello! How can I help you today?
Hi there! What's on your mind?
Welcome! I'm ready to assist with whatever you need.
```

The `tester` personality (`personalities/tester/greetings.txt`) keeps it minimal:

```
ready.
system online.
awaiting input.
```

## Using a Personality

There are two ways to activate a personality:

### Default Personality (via environment)

```env
UA_ACTIVE_PERSONALITY=my_new_personality
```

This is read at agent construction and used for all calls unless overridden.

### Per-Call Override

Pass `personality_override` to `chat()` (see `ua/core/agent.py` lines 64, 81-92):

```python
response = await agent.chat(
    user_id="user123",
    platform="cli",
    message="Hello!",
    personality_override="tester",  # Override for this call only
)
```

The override is also persisted as the user's stored preference — subsequent calls without an override continue using the chosen personality (sticky behavior).

See `examples/switch_personality.py` for a complete demonstration.

## Validation

The `PersonalityLoader.load()` method validates `rules.json` against the Pydantic schema in `ua/personality/schema.py`. If the schema fails, a `PersonalityLoadError` is raised. You can test a personality by attempting to load it:

```python
from ua.personality.loader import PersonalityLoader
loader = PersonalityLoader()
personality = loader.load("my_personality")  # Raises on invalid
```

## Personality Rules

Refer to Contributing.md §6 for complete personality conventions:
- Personality name must be filesystem-safe
- Rules must be valid JSON matching schema
- Never reference personalities in Python code directly