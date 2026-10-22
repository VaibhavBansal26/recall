"""Step-by-step position diagrams for algorithm notes: an array and pointer positions per step."""

import json

from app.agent.schemas import WalkthroughDraft

MAX_CELLS = 24
MAX_STEPS = 16


class WalkthroughError(ValueError):
    """A walkthrough that cannot be drawn; the message goes back to the model for one retry."""


def validate_walkthrough(draft: WalkthroughDraft) -> str:
    """Check a draft and return the JSON stored as the diagram source."""
    array = [str(a).strip() for a in draft.array]
    if not draft.applicable:
        raise WalkthroughError("not applicable")
    if not 2 <= len(array) <= MAX_CELLS or any(not a for a in array):
        raise WalkthroughError(f"array must have 2 to {MAX_CELLS} non-empty elements")
    if not 2 <= len(draft.steps) <= MAX_STEPS:
        raise WalkthroughError(f"need 2 to {MAX_STEPS} steps")

    steps = []
    for number, step in enumerate(draft.steps, 1):
        caption = step.caption.strip()
        if not caption or len(caption) > 200:
            raise WalkthroughError(f"step {number}: caption must be 1 to 200 characters")
        cells = step.array if step.array is not None else None
        if cells is not None and len(cells) != len(array):
            raise WalkthroughError(f"step {number}: array must keep the same length")
        size = len(array)
        for name, index in step.pointers.items():
            if not name.strip() or len(name) > 8:
                raise WalkthroughError(f"step {number}: pointer names are 1 to 8 characters")
            if not 0 <= index < size:
                raise WalkthroughError(
                    f"step {number}: pointer {name!r} index {index} is outside 0..{size - 1}"
                )
        if any(not 0 <= i < size for i in step.highlight):
            raise WalkthroughError(f"step {number}: highlight index outside 0..{size - 1}")
        steps.append(
            {
                "caption": caption,
                "pointers": {k.strip(): v for k, v in step.pointers.items()},
                "highlight": sorted(set(step.highlight)),
                **({"array": [str(c).strip() for c in cells]} if cells is not None else {}),
            }
        )
    return json.dumps({"array": array, "steps": steps})
