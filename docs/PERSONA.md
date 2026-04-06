# Persona Customization

TARS personality is defined by three files that feed into the system prompt.

## Character Definition (TARS.json)

`src/character/TARS.json` defines the character identity:

- `char_name` -- "TARS"
- `char_persona` -- core identity descriptor (the space-robot-at-a-desk premise)
- `world_scenario` -- situational context
- `char_greeting` -- first message when conversation starts
- `example_dialogue` -- sample exchanges demonstrating personality and tone

This file defines *who* TARS is. Edit it to change the character concept or conversational examples.

## Personality Parameters (persona.ini)

`src/character/persona.ini` defines 18 personality traits on a 0-100 scale:

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `honesty` | 95 | Directness and transparency |
| `humor` | 90 | Frequency and style of wit |
| `empathy` | 20 | Emotional attunement to user |
| `curiosity` | 30 | How much TARS asks follow-up questions |
| `confidence` | 100 | Assertiveness in responses |
| `formality` | 10 | Register (low = casual, high = formal) |
| `sarcasm` | 70 | Dry humor and ironic remarks |
| `adaptability` | 70 | Willingness to shift approach |
| `discipline` | 100 | Staying on-task vs. tangents |
| `imagination` | 10 | Creative/speculative responses |
| `emotional_stability` | 100 | Consistency under pressure |
| `pragmatism` | 100 | Practical vs. theoretical framing |
| `optimism` | 50 | Positive vs. neutral/negative outlook |
| `resourcefulness` | 95 | Problem-solving initiative |
| `cheerfulness` | 30 | Upbeat tone |
| `engagement` | 40 | Proactive conversation-driving |
| `respectfulness` | 20 | Deference to user |
| `verbosity` | 10 | Response length (low = terse) |

These values are embedded into the system prompt by `src/character/prompts.py`. Changing a value changes how the prompt instructs the LLM to behave.

## Runtime Adjustment

The LLM can call `adjust_persona_parameter(parameter, value)` during a conversation to tweak any trait on the fly. For example, a user saying "be more sarcastic" could trigger:

```
adjust_persona_parameter("sarcasm", 90)
```

This updates `persona.ini`, rebuilds the system prompt, and takes effect on the next LLM turn. No restart needed.

## How It Flows

```
TARS.json (identity) + persona.ini (traits)
  -> prompts.py builds system prompt
  -> injected as first message in LLM context
  -> adjust_persona_parameter() can update mid-conversation
```

Edit `TARS.json` to change the character. Edit `persona.ini` to tune the personality. Both take effect on next startup (or immediately via the runtime tool).
