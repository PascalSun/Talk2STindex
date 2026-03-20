"""Standalone spatiotemporal extraction — no stindex dependency."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from loguru import logger

from talk2stindex.core.geocoder import geocode_entities
from talk2stindex.core.json_utils import extract_json_from_text
from talk2stindex.core.llm import create_client
from talk2stindex.core.prompt import build_extraction_prompt
from talk2stindex.core.temporal import resolve_relative


def extract_text(
    text: str,
    temporal_reference: Optional[str] = None,
    spatial_reference: Optional[str] = None,
    llm_provider: str = "anthropic",
    model_name: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> Dict[str, Any]:
    """Extract spatial and temporal entities from plain text.

    Args:
        text: Raw text to process.
        temporal_reference: ISO 8601 date used as reference point for
            resolving relative temporal expressions.
        spatial_reference: Geographic context for spatial disambiguation.
        llm_provider: LLM provider — "anthropic" or "openai".
        model_name: Override default model name.
        temperature: Sampling temperature.
        max_tokens: Max response tokens.

    Returns:
        Dict with extracted entities, processing time, and success flag.
    """
    start = time.time()

    try:
        # Build LLM client
        kwargs: Dict[str, Any] = {"temperature": temperature, "max_tokens": max_tokens}
        if model_name:
            kwargs["model"] = model_name
        client = create_client(provider=llm_provider, **kwargs)

        # Build prompt
        system_prompt, user_prompt = build_extraction_prompt(
            text,
            temporal_reference=temporal_reference,
            spatial_reference=spatial_reference,
        )

        # Call LLM
        logger.info(f"Extracting with {llm_provider}...")
        raw_output = client.generate(system_prompt, user_prompt)
        logger.debug(f"Raw LLM output: {raw_output[:300]}")

        # Parse JSON
        extraction = extract_json_from_text(raw_output)

        # Post-process temporal entities — resolve relative dates
        temporal_entities = extraction.get("temporal", [])
        for entity in temporal_entities:
            normalized = entity.get("normalized", "")
            if normalized:
                resolved, resolved_type = resolve_relative(
                    normalized, temporal_reference
                )
                entity["normalized"] = resolved
                entity["normalization_type"] = resolved_type

        # Post-process spatial entities — geocode to lat/lon
        spatial_entities = extraction.get("spatial", [])
        if spatial_entities:
            logger.info(f"Geocoding {len(spatial_entities)} spatial entities...")
            geocode_entities(spatial_entities, spatial_reference=spatial_reference)

        entities: Dict[str, List[Dict[str, Any]]] = {}
        if temporal_entities:
            entities["temporal"] = temporal_entities
        if spatial_entities:
            entities["spatial"] = spatial_entities

        return {
            "success": True,
            "entities": entities,
            "processing_time": round(time.time() - start, 3),
        }

    except Exception as exc:
        logger.error(f"Extraction failed: {exc}", exc_info=True)
        return {
            "success": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "processing_time": round(time.time() - start, 3),
        }
