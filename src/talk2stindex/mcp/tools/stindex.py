"""STIndex extraction tool for MCP."""

from __future__ import annotations

import json

import httpx
from mcp.types import TextContent

from talk2stindex.logging import get_logger

logger = get_logger(__name__)

EXTRACT_TEXT_SPEC = {
    "name": "extract_text",
    "description": (
        "Extract spatial and temporal entities from plain text. "
        "Returns structured entities with locations and dates/times found in the text.\n\n"
        "When pdf_id is provided, results are automatically submitted to the "
        "KAIA Platform via its REST API."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Raw text to extract spatial and temporal information from.",
            },
            "temporal_reference": {
                "type": "string",
                "description": (
                    "ISO 8601 date/datetime used as the reference point for resolving "
                    "relative temporal expressions (e.g. 'last week', 'yesterday'). "
                    "Defaults to the current date if not provided."
                ),
            },
            "spatial_reference": {
                "type": "string",
                "description": (
                    "Geographic context used as the reference for spatial disambiguation "
                    "(e.g. 'Perth, Western Australia'). Helps resolve ambiguous place names."
                ),
            },
            "pdf_id": {
                "type": "integer",
                "description": (
                    "PDF primary key in the KAIA Platform. When provided, extraction "
                    "results are automatically submitted to the platform."
                ),
            },
            "annotation_id": {
                "type": "string",
                "description": (
                    "Layout annotation region ID the text was extracted from. "
                    "Used to link entities back to their source annotation in the PDF."
                ),
            },
        },
        "required": ["text"],
    },
}

EXTRACT_PDF_SPEC = {
    "name": "extract_pdf",
    "description": (
        "Extract spatial and temporal entities from all annotations of a PDF. "
        "Fetches the PDF's OCR annotations from the KAIA Platform, runs extraction "
        "on each annotation's text, and submits all results back to the platform "
        "with annotation_id linked to each entity.\n\n"
        "Requires platform_api to be configured."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "pdf_id": {
                "type": "integer",
                "description": "PDF primary key in the KAIA Platform.",
            },
            "temporal_reference": {
                "type": "string",
                "description": (
                    "ISO 8601 date/datetime for resolving relative temporal "
                    "expressions. Defaults to current date."
                ),
            },
            "spatial_reference": {
                "type": "string",
                "description": (
                    "Geographic context for spatial disambiguation "
                    "(e.g. 'Perth, Western Australia')."
                ),
            },
        },
        "required": ["pdf_id"],
    },
}

ANALYZE_ERRORS_SPEC = {
    "name": "analyze_errors",
    "description": (
        "Analyze dismissed (incorrect) spatiotemporal entities and generate "
        "improved spatial/temporal context suggestions. Takes a list of "
        "incorrect extractions with their source text and returns recommended "
        "context updates to improve future extraction accuracy."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "errors": {
                "type": "array",
                "description": "List of incorrectly extracted entities.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The extracted entity text.",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["spatial", "temporal"],
                            "description": "Entity type.",
                        },
                        "source_text": {
                            "type": "string",
                            "description": "OCR source text the entity was extracted from.",
                        },
                    },
                },
            },
            "current_spatial_context": {
                "type": "string",
                "description": "Current spatial context setting for the project.",
            },
            "current_temporal_context": {
                "type": "string",
                "description": "Current temporal context setting for the project.",
            },
        },
        "required": ["errors"],
    },
}

TOOL_SPECS = [EXTRACT_TEXT_SPEC, EXTRACT_PDF_SPEC, ANALYZE_ERRORS_SPEC]


async def _submit_to_platform(
    pdf_id: int,
    annotation_id: str | None,
    result: dict,
    mode: str = "replace",
) -> dict | None:
    """POST extraction results to the Platform's submit endpoint."""
    if not _platform_config or not _platform_config.url:
        return None

    url = f"{_platform_config.url.rstrip('/')}/core/stindex_results/submit/"
    payload = {
        "pdf_id": pdf_id,
        "annotation_id": annotation_id,
        "annotations": result,
        "mode": mode,
    }
    headers = {"Content-Type": "application/json"}
    if _platform_config.token:
        headers["Authorization"] = f"Token {_platform_config.token}"

    try:
        async with httpx.AsyncClient(
            timeout=_platform_config.timeout,
            verify=_platform_config.verify_ssl,
        ) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code < 300:
                logger.info(
                    f"Submitted stindex results for pdf_id={pdf_id} "
                    f"annotation_id={annotation_id}: {resp.json()}"
                )
                return resp.json()
            else:
                logger.error(
                    f"Platform submit failed ({resp.status_code}): {resp.text}"
                )
                return {"error": True, "status": resp.status_code, "detail": resp.text}
    except Exception as e:
        logger.error(f"Failed to submit to platform: {e}")
        return {"error": True, "detail": str(e)}


# Platform config is injected at registration time
_platform_config = None


def configure_platform(platform_api_config) -> None:
    """Set the platform API config for result submission."""
    global _platform_config
    _platform_config = platform_api_config


async def handle_extract_text(arguments: dict) -> list[TextContent]:
    from talk2stindex.core.extraction import extract_text

    result = extract_text(
        text=arguments.get("text", ""),
        temporal_reference=arguments.get("temporal_reference"),
        spatial_reference=arguments.get("spatial_reference"),
    )

    pdf_id = arguments.get("pdf_id")
    annotation_id = arguments.get("annotation_id")

    # Auto-submit to platform if pdf_id is provided and platform is configured
    platform_result = None
    if pdf_id and _platform_config and _platform_config.url:
        platform_result = await _submit_to_platform(
            pdf_id=pdf_id,
            annotation_id=annotation_id,
            result=result,
        )
        result["platform_submit"] = platform_result
    elif pdf_id and (not _platform_config or not _platform_config.url):
        logger.warning(
            "pdf_id provided but platform API URL not configured — skipping submit"
        )
        result["platform_submit"] = {
            "skipped": True,
            "reason": "platform not configured",
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def _fetch_pdf_annotations(pdf_id: int) -> dict | None:
    """Fetch a PDF's OCR annotations from the Platform API."""
    if not _platform_config or not _platform_config.url:
        return None

    url = f"{_platform_config.url.rstrip('/')}/core/pdfs/{pdf_id}/"
    headers = {}
    if _platform_config.token:
        headers["Authorization"] = f"Token {_platform_config.token}"

    try:
        async with httpx.AsyncClient(
            timeout=_platform_config.timeout,
            verify=_platform_config.verify_ssl,
        ) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code < 300:
                return resp.json()
            else:
                logger.error(
                    f"Failed to fetch PDF {pdf_id} ({resp.status_code}): "
                    f"{resp.text}"
                )
                return None
    except Exception as e:
        logger.error(f"Failed to fetch PDF {pdf_id}: {e}")
        return None


async def handle_extract_pdf(arguments: dict) -> list[TextContent]:
    """Extract ST entities from all OCR annotations of a PDF."""
    from talk2stindex.core.extraction import extract_text

    pdf_id = arguments["pdf_id"]
    temporal_ref = arguments.get("temporal_reference")
    spatial_ref = arguments.get("spatial_reference")

    if not _platform_config or not _platform_config.url:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": True,
                        "detail": "platform_api not configured",
                    }
                ),
            )
        ]

    # Update status to processing
    await _submit_to_platform(
        pdf_id=pdf_id,
        annotation_id=None,
        result={"success": False, "status": "processing"},
    )

    # Fetch PDF data from platform
    pdf_data = await _fetch_pdf_annotations(pdf_id)
    if not pdf_data:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": True,
                        "detail": f"Could not fetch PDF {pdf_id} from platform",
                    }
                ),
            )
        ]

    ocr_annotations = pdf_data.get("ocr_annotations") or []
    if not ocr_annotations:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": True,
                        "detail": f"PDF {pdf_id} has no OCR annotations",
                    }
                ),
            )
        ]

    logger.info(f"Processing PDF {pdf_id}: {len(ocr_annotations)} annotations")

    # Clear existing data with an empty replace call
    await _submit_to_platform(
        pdf_id=pdf_id,
        annotation_id=None,
        result={
            "success": True,
            "entities": {"spatial": [], "temporal": []},
            "processing_time": 0,
        },
        mode="replace",
    )

    # Extract and submit per annotation (progressive)
    total_spatial = 0
    total_temporal = 0
    total_time = 0.0
    processed = 0
    errors = []

    for i, ann in enumerate(ocr_annotations):
        ann_id = ann.get("id")
        ocr_text = ann.get("ocr", "").strip()
        if not ocr_text:
            continue

        try:
            result = extract_text(
                text=ocr_text,
                temporal_reference=temporal_ref,
                spatial_reference=spatial_ref,
            )
            if result.get("success"):
                entities = result.get("entities", {})
                spatial = entities.get("spatial", [])
                temporal = entities.get("temporal", [])

                # Tag each entity with source OCR text as description
                ocr_preview = ocr_text[:500] if len(ocr_text) > 500 else ocr_text
                for ent in spatial + temporal:
                    if not ent.get("description"):
                        ent["description"] = ocr_preview

                if spatial or temporal:
                    await _submit_to_platform(
                        pdf_id=pdf_id,
                        annotation_id=ann_id,
                        result={
                            "success": True,
                            "entities": {
                                "spatial": spatial,
                                "temporal": temporal,
                            },
                            "processing_time": result.get("processing_time", 0),
                        },
                        mode="append",
                    )
                    total_spatial += len(spatial)
                    total_temporal += len(temporal)

                total_time += result.get("processing_time", 0)
            processed += 1
            logger.info(
                f"PDF {pdf_id}: [{i + 1}/{len(ocr_annotations)}] "
                f"annotation {ann_id}"
            )
        except Exception as e:
            logger.error(f"Error extracting annotation {ann_id}: {e}")
            errors.append({"annotation_id": ann_id, "error": str(e)})

    logger.info(
        f"PDF {pdf_id}: {total_spatial} spatial, "
        f"{total_temporal} temporal from {processed} annotations"
    )

    # Final status update
    self_result = {
        "success": True,
        "entities": {"spatial": [], "temporal": []},
        "processing_time": total_time,
    }
    await _submit_to_platform(
        pdf_id=pdf_id,
        annotation_id=None,
        result=self_result,
        mode="append",
    )

    summary = {
        "pdf_id": pdf_id,
        "status": "success",
        "annotations_processed": processed,
        "spatial_count": total_spatial,
        "temporal_count": total_temporal,
        "processing_time": total_time,
    }
    if errors:
        summary["errors"] = errors

    return [
        TextContent(
            type="text",
            text=json.dumps(summary, indent=2, default=str),
        )
    ]


_ANALYZE_PROMPT = """You are an expert at spatiotemporal entity extraction from documents.

A user has marked the following extracted entities as INCORRECT. Analyze the errors and suggest improved spatial and temporal context settings that would help avoid these mistakes in future extractions.

## Current Settings
Spatial context: {spatial_context}
Temporal context: {temporal_context}

## Incorrect Entities
{errors_text}

## Instructions
1. Analyze WHY each entity was likely extracted incorrectly
2. Suggest an improved **spatial context** - geographic hints that would help disambiguate locations
3. Suggest an improved **temporal context** - temporal reference points that would help resolve dates
4. Provide the suggestions in JSON format:

```json
{{
  "analysis": "Brief analysis of error patterns",
  "suggested_spatial_context": "Your improved spatial context text",
  "suggested_temporal_context": "Your improved temporal context text",
  "reasoning": "Why these changes would help"
}}
```
"""


async def handle_analyze_errors(arguments: dict) -> list[TextContent]:
    """Analyze dismissed entities and suggest improved context settings."""
    from talk2stindex.core.llm import create_client

    errors = arguments.get("errors", [])
    current_spatial = arguments.get("current_spatial_context", "(not set)")
    current_temporal = arguments.get("current_temporal_context", "(not set)")

    if not errors:
        return [TextContent(
            type="text",
            text=json.dumps({"error": "No errors provided"}),
        )]

    # Format errors for the prompt
    lines = []
    for i, err in enumerate(errors, 1):
        lines.append(
            f"{i}. [{err.get('type', 'unknown').upper()}] "
            f"Extracted: \"{err.get('text', '')}\"\n"
            f"   Source text: \"{err.get('source_text', '(not available)')[:300]}\""
        )
    errors_text = "\n".join(lines)

    prompt = _ANALYZE_PROMPT.format(
        spatial_context=current_spatial or "(not set)",
        temporal_context=current_temporal or "(not set)",
        errors_text=errors_text,
    )

    try:
        client = create_client(provider="anthropic", max_tokens=2048)
        raw = client.generate(
            "You are a helpful assistant that analyzes extraction errors.",
            prompt,
        )

        # Try to parse JSON from response
        from talk2stindex.core.json_utils import extract_json_from_text
        result = extract_json_from_text(raw)
        result["error_count"] = len(errors)
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2, default=str),
        )]
    except Exception as e:
        logger.error(f"analyze_errors failed: {e}", exc_info=True)
        return [TextContent(
            type="text",
            text=json.dumps({"error": str(e)}),
        )]
