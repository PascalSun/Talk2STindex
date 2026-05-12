"""Lightweight geocoder using Mapbox Geocoding API (600 req/min, 100k/month free)."""

from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

_MAPBOX_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN", "")
_geocode_cache: Dict[str, Optional[Dict[str, Any]]] = {}


def _mapbox_geocode(query: str) -> Optional[Dict[str, Any]]:
    """Geocode via Mapbox. Cached in-memory."""
    if query in _geocode_cache:
        return _geocode_cache[query]

    token = _MAPBOX_TOKEN or os.getenv("NEXT_PUBLIC_MAPBOX_TOKEN", "")
    if not token:
        logger.warning("MAPBOX_ACCESS_TOKEN not set, skipping geocoding")
        return None

    encoded = urllib.parse.quote(query, safe="")
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{encoded}.json?access_token={token}&limit=1"

    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if features:
            coords = features[0].get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                parsed = {
                    "latitude": round(coords[1], 6),
                    "longitude": round(coords[0], 6),
                    "address": features[0].get("place_name", ""),
                }
                logger.debug(f"Geocoded '{query}' → ({parsed['latitude']}, {parsed['longitude']})")
                _geocode_cache[query] = parsed
                return parsed
        _geocode_cache[query] = None
        return None
    except Exception as e:
        logger.warning(f"Mapbox geocoding failed for '{query}': {e}")
        _geocode_cache[query] = None
        return None


def geocode(
    location: str,
    parent_region: Optional[str] = None,
    spatial_reference: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Geocode a location name to coordinates using Mapbox.

    Results are cached so repeated locations are instant.

    Args:
        location: Location name (e.g. "Kwinana").
        parent_region: Parent region from LLM (e.g. "Western Australia").
        spatial_reference: Broad spatial context (e.g. "Perth, Western Australia").

    Returns:
        Dict with latitude, longitude, address or None if failed.
    """
    query = location
    if parent_region:
        query = f"{location}, {parent_region}"
    elif spatial_reference:
        query = f"{location}, {spatial_reference}"

    result = _mapbox_geocode(query)
    if result:
        return result

    # Fallback: try without parent region
    if parent_region or spatial_reference:
        return _mapbox_geocode(location)

    return None


def geocode_entities(
    spatial_entities: List[Dict[str, Any]],
    spatial_reference: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Geocode a list of spatial entities in-place, adding lat/lon.

    Args:
        spatial_entities: List of spatial entity dicts from LLM extraction.
        spatial_reference: Broad spatial context for disambiguation.

    Returns:
        The same list with latitude/longitude/address added where resolved.
    """
    for entity in spatial_entities:
        location = entity.get("text", "")
        parent_region = entity.get("parent_region")

        coords = geocode(
            location,
            parent_region=parent_region,
            spatial_reference=spatial_reference,
        )

        if coords:
            entity["latitude"] = coords["latitude"]
            entity["longitude"] = coords["longitude"]
            entity["address"] = coords["address"]
        else:
            entity["latitude"] = None
            entity["longitude"] = None
            entity["address"] = None

    return spatial_entities
