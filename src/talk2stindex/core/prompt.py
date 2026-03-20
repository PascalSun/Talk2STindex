"""Prompt builder for spatiotemporal extraction."""

from __future__ import annotations

import json
from typing import Optional

SYSTEM_PROMPT = """You are a precise JSON extraction bot. Your ONLY output must be valid JSON.

CRITICAL RULES:
- Output ONLY the JSON object, nothing else
- NO explanations, NO reasoning, NO extra text
- Start your response with {{ and end with }}

{document_context}EXTRACTION TASKS:

1. Extract TEMPORAL (normalized):
   Extract temporal expressions (dates, times, durations, intervals)
   Hierarchy:
     - timestamp: Specific date and time (ISO 8601)
     - date: Calendar date (YYYY-MM-DD)
     - month: Year and month (YYYY-MM)
     - year: Calendar year (YYYY)
   - Normalize to ISO 8601 format:
     * Dates: YYYY-MM-DD
     * Datetimes: YYYY-MM-DDTHH:MM:SS
     * Durations: P1D (days), P2M (months), P3Y (years), PT2H (hours)
     * Intervals: start/end (e.g., 2025-10-27T11:00:00/2025-10-27T19:00:00)
{temporal_anchor}
2. Extract SPATIAL (geocoded):
   Extract spatial/location mentions with parent regions for disambiguation
   Hierarchy:
     - location: Specific location name, address, or point of interest
     - city: City or municipality
     - state: State, province, or region
     - country: Country name
   - Include parent region for disambiguation (state, country)
{spatial_context}
REMINDER: Return ONLY valid JSON, nothing else.

Respond only in raw JSON. Schema:
{schema}"""

SCHEMA = {
    "temporal": [
        {
            "text": "original text mention",
            "normalized": "ISO 8601 value",
            "normalization_type": "date|datetime|duration|interval|time|year|month",
            "confidence": 1.0,
        }
    ],
    "spatial": [
        {
            "text": "original text mention",
            "location_type": "city|state|country|location|region|landmark",
            "parent_region": "parent region for disambiguation",
            "confidence": 1.0,
        }
    ],
}


def build_extraction_prompt(
    text: str,
    temporal_reference: Optional[str] = None,
    spatial_reference: Optional[str] = None,
) -> tuple[str, str]:
    """Build system and user prompts for spatiotemporal extraction.

    Returns:
        (system_prompt, user_prompt) tuple.
    """
    # Document context
    context_parts: list[str] = []
    if temporal_reference:
        context_parts.append(f"- Temporal Reference: {temporal_reference}")
    if spatial_reference:
        context_parts.append(f"- Spatial Reference: {spatial_reference}")

    document_context = ""
    if context_parts:
        document_context = "DOCUMENT CONTEXT:\n" + "\n".join(context_parts) + "\n\n"

    # Temporal anchor instruction
    temporal_anchor = ""
    if temporal_reference:
        temporal_anchor = f"   - For relative dates (e.g., 'Monday', 'last week'), use document date {temporal_reference} as anchor\n"
    else:
        temporal_anchor = "   - For relative dates, use most recent occurrence\n"

    # Spatial context instruction
    spatial_context = ""
    if spatial_reference:
        spatial_context = f"   - Consider spatial reference: {spatial_reference}\n"

    system = SYSTEM_PROMPT.format(
        document_context=document_context,
        temporal_anchor=temporal_anchor,
        spatial_context=spatial_context,
        schema=json.dumps(SCHEMA, indent=2),
    )

    return system, text
