"""Lightweight geocoder using Nominatim for location → lat/lon."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from loguru import logger

# Rate limit between Nominatim requests (seconds)
_RATE_LIMIT = 1.1
_last_request_time = 0.0


def _rate_limit() -> None:
    """Enforce Nominatim rate limit."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _RATE_LIMIT:
        time.sleep(_RATE_LIMIT - elapsed)
    _last_request_time = time.monotonic()


def geocode(
    location: str,
    parent_region: Optional[str] = None,
    spatial_reference: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Geocode a location name to coordinates.

    Args:
        location: Location name (e.g. "Kwinana").
        parent_region: Parent region from LLM (e.g. "Western Australia").
        spatial_reference: Broad spatial context (e.g. "Perth, Western Australia").

    Returns:
        Dict with latitude, longitude, address or None if failed.
    """
    from geopy.exc import GeocoderServiceError, GeocoderTimedOut
    from geopy.geocoders import Nominatim

    geolocator = Nominatim(
        user_agent="talk2stindex/0.1.0",
        timeout=10,
    )

    # Build query with disambiguation
    query = location
    if parent_region:
        query = f"{location}, {parent_region}"
    elif spatial_reference:
        query = f"{location}, {spatial_reference}"

    try:
        _rate_limit()
        result = geolocator.geocode(query, exactly_one=True)
        if result:
            logger.debug(
                f"Geocoded '{location}' → ({result.latitude}, {result.longitude})"
            )
            return {
                "latitude": round(result.latitude, 6),
                "longitude": round(result.longitude, 6),
                "address": result.address,
            }

        # Fallback: try without parent region
        if parent_region or spatial_reference:
            _rate_limit()
            result = geolocator.geocode(location, exactly_one=True)
            if result:
                logger.debug(
                    f"Geocoded '{location}' (fallback) → ({result.latitude}, {result.longitude})"
                )
                return {
                    "latitude": round(result.latitude, 6),
                    "longitude": round(result.longitude, 6),
                    "address": result.address,
                }

    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.warning(f"Geocoding failed for '{location}': {e}")
    except Exception as e:
        logger.warning(f"Geocoding error for '{location}': {e}")

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
