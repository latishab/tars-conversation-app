"""Crossword helper module - TARS knows the answers!"""

from pipecat.adapters.schemas.function_schema import FunctionSchema

# Crossword puzzle answers that TARS can reference
CROSSWORD_ANSWERS = {
    1: {"clue": "Opposite of hot", "answer": "COLD", "direction": "across"},
    2: {"clue": "Large body of water", "answer": "OCEAN", "direction": "across"},
    3: {"clue": "Flying mammal", "answer": "BAT", "direction": "down"},
    4: {"clue": "Yellow citrus fruit", "answer": "LEMON", "direction": "across"},
    5: {"clue": "Feline pet", "answer": "CAT", "direction": "down"},
    6: {"clue": "Frozen water", "answer": "ICE", "direction": "down"},
    7: {"clue": "King of the jungle", "answer": "LION", "direction": "across"},
}


def get_crossword_hint(clue_number: int, hint_type: str = "letter") -> dict:
    """
    Get a hint for a crossword clue.

    Args:
        clue_number: The clue number
        hint_type: Type of hint - "letter" (first letter), "length", or "full"

    Returns:
        dict with hint information
    """
    if clue_number not in CROSSWORD_ANSWERS:
        return {"error": f"No clue #{clue_number} found"}

    clue_data = CROSSWORD_ANSWERS[clue_number]
    answer = clue_data["answer"]

    if hint_type == "letter":
        return {
            "hint": f"The first letter is '{answer[0]}'",
            "clue": clue_data["clue"],
            "direction": clue_data["direction"]
        }
    elif hint_type == "length":
        return {
            "hint": f"The answer has {len(answer)} letters",
            "clue": clue_data["clue"],
            "direction": clue_data["direction"]
        }
    elif hint_type == "full":
        return {
            "hint": f"The answer is '{answer}'",
            "clue": clue_data["clue"],
            "direction": clue_data["direction"]
        }
    else:
        return {"error": "Invalid hint type. Use 'letter', 'length', or 'full'"}


def get_all_answers() -> dict:
    """Get all crossword answers (for TARS internal use)"""
    return CROSSWORD_ANSWERS


def create_crossword_hint_schema():
    """Create the tool schema for crossword hints"""
    return FunctionSchema(
        name="get_crossword_hint",
        description=(
            "Get a hint for a crossword puzzle clue. Use this when the user asks for help "
            "with the crossword puzzle or seems stuck on a particular clue. "
            "TARS knows all the answers!"
        ),
        properties={
            "clue_number": {
                "type": "integer",
                "description": "The clue number (1-7)"
            },
            "hint_type": {
                "type": "string",
                "enum": ["letter", "length", "full"],
                "description": (
                    "Type of hint to give: "
                    "'letter' gives the first letter, "
                    "'length' gives the word length, "
                    "'full' gives the complete answer"
                )
            }
        },
        required=["clue_number", "hint_type"]
    )
