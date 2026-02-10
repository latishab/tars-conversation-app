# LLM Tools

This directory contains LLM callable functions organized by domain. Each tool is a function that the LLM can invoke during conversation to perform specific actions.

## Organization

Tools are grouped by domain:

| File | Domain | Functions |
|------|--------|-----------|
| `robot.py` | Robot hardware control | execute_movement, capture_camera_view |
| `persona.py` | Identity and personality | adjust_persona_parameter, set_user_identity |
| `vision.py` | Vision analysis | fetch_user_image |
| `crossword.py` | Game-specific utilities | get_crossword_hint |

## Structure

Each tool file contains:

1. **Function implementations** - Async functions that accept `FunctionCallParams`
2. **Schema creators** - Functions that return `FunctionSchema` for LLM registration
3. **Helper functions** - Domain-specific utilities

## Usage

Import tools in your bot code:

```python
from tools.robot import execute_movement, create_movement_schema
from tools.persona import adjust_persona_parameter, create_adjust_persona_schema
from tools.vision import fetch_user_image, create_fetch_image_schema

# Register with LLM
llm.register_function("execute_movement", execute_movement)
llm.register_function("adjust_persona_parameter", adjust_persona_parameter)

# Add schemas to context
tools = ToolsSchema(standard_tools=[
    create_movement_schema(),
    create_adjust_persona_schema(),
    create_fetch_image_schema(),
])
```

## Creating New Tools

When adding new LLM tools:

1. Choose the appropriate domain file (or create new one)
2. Implement async function with `FunctionCallParams` parameter
3. Create schema function returning `FunctionSchema`
4. Export from `__init__.py`
5. Document in this README

Example:

```python
async def my_new_tool(params: FunctionCallParams):
    \"\"\"Tool description.\"\"\"
    arg = params.arguments.get("arg")
    result = do_something(arg)
    await params.result_callback(result)

def create_my_tool_schema() -> FunctionSchema:
    \"\"\"Create schema for my_new_tool.\"\"\"
    return FunctionSchema(
        name="my_new_tool",
        description="When to call this tool",
        properties={
            "arg": {"type": "string", "description": "Argument description"}
        },
        required=["arg"]
    )
```

## Design Principles

1. **Domain separation** - Group related functions together
2. **Clear naming** - Function names should describe action (verb_noun)
3. **Schema clarity** - Descriptions should tell LLM when to call the function
4. **Error handling** - Always handle exceptions and provide feedback
5. **Logging** - Log important actions for debugging

## Not Tools

This directory is for LLM-callable functions only. Other code belongs in:

- `services/` - Backend services (STT, TTS, memory, robot control)
- `processors/` - Pipeline frame processors
- `transport/` - Network transport (WebRTC, gRPC)
- `character/` - Character definitions and prompts
