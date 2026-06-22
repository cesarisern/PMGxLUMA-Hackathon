import json
import re


def parse_json(text: str) -> dict | list:
    """Parse JSON from model output, stripping markdown code fences if present."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())
