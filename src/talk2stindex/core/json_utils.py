"""Utilities for extracting JSON from LLM output."""

from __future__ import annotations

import json
import re
from typing import Any, Dict


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Extract the last valid JSON object from LLM output text.

    Handles markdown code blocks, extra text before/after JSON, and
    multiple JSON objects (picks the last complete one).

    Returns:
        Parsed dict.

    Raises:
        ValueError: If no valid JSON found.
    """
    # Strip markdown code fences
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)

    # Find all complete JSON objects with balanced braces
    candidates: list[str] = []
    i = 0
    while i < len(text):
        start = text.find("{", i)
        if start == -1:
            break

        depth = 0
        in_string = False
        escape = False
        end = -1

        for j in range(start, len(text)):
            char = text[j]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break

        if end != -1:
            candidates.append(text[start : end + 1])
            i = end + 1
        else:
            i = start + 1

    if not candidates:
        raise ValueError(f"No JSON object found in text: {text[:200]}")

    # Try from last to first
    last_error = None
    for json_str in reversed(candidates):
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            last_error = e
            continue

    raise ValueError(f"No valid JSON found. Last error: {last_error}")
