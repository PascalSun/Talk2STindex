"""Lightweight geocoder using Nominatim for location → lat/lon."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from loguru import logger

# Rate limit between Nominatim requests (seconds).
# Nominatim allows max 1 req/s — use 1.5s to be safe.
_RATE_LIMIT = 1.5
_last_request_time = 0.0
_geocode_lock = threading.Lock()
_geocode_cache: Dict[str, Optional[Dict[str, Any]]] = {}


_MAX_RETRIES = 3


def _rate_limited_geocode(geolocator: Any, query: str) -> Optional[Dict[str, Any]]:
    """Geocode with process-wide lock, rate limiting, caching, and retry on 429."""
    if query in _geocode_cache:
        return _geocode_cache[query]

    global _last_request_time
    with _geocode_lock:
        if query in _geocode_cache:
            return _geocode_cache[query]

        for attempt in range(_MAX_RETRIES):
            now = time.monotonic()
            elapsed = now - _last_request_time
            if elapsed < _RATE_LIMIT:
                time.sleep(_RATE_LIMIT - elapsed)
            _last_request_time = time.monotonic()

            try:
                result = geolocator.geocode(query, exactly_one=True)
                parsed = None
                if result:
                    logger.debug(f"Geocoded '{query}' → ({result.latitude}, {result.longitude})")
                    parsed = {
                        "latitude": round(result.latitude, 6),
                        "longitude": round(result.longitude, 6),
                        "address": result.address,
                    }
                _geocode_cache[query] = parsed
                return parsed
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "too many" in err_str:
                    wait = _RATE_LIMIT * (attempt + 2)
                    logger.warning(f"Geocoding rate-limited for '{query}', waiting {wait:.0f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                    time.sleep(wait)
                    continue
                logger.warning(f"Geocoding failed for '{query}': {e}")
                _geocode_cache[query] = None
                return None

        logger.warning(f"Geocoding gave up for '{query}' after {_MAX_RETRIES} retries")
        _geocode_cache[query] = None
        return None


def geocode(
    location: str,
    parent_region: Optional[str] = None,
    spatial_reference: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Geocode a location name to coordinates.

    Process-wide lock ensures only one Nominatim request at a time.
    Results are cached so repeated locations are instant.

    Args:
        location: Location name (e.g. "Kwinana").
        parent_region: Parent region from LLM (e.g. "Western Australia").
        spatial_reference: Broad spatial context (e.g. "Perth, Western Australia").

    Returns:
        Dict with latitude, longitude, address or None if failed.
    """
    from geopy.geocoders import Nominatim

    geolocator = Nominatim(user_agent="talk2stindex/0.1.0", timeout=10)

    query = location
    if parent_region:
        query = f"{location}, {parent_region}"
    elif spatial_reference:
        query = f"{location}, {spatial_reference}"

    result = _rate_limited_geocode(geolocator, query)
    if result:
        return result

    # Fallback: try without parent region
    if parent_region or spatial_reference:
        return _rate_limited_geocode(geolocator, location)

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
