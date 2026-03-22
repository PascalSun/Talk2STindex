"""Tests for Talk2STIndex."""

import pytest


def test_version():
    """Test that the package version is set."""
    from talk2stindex import __version__

    assert __version__ == "0.1.0"


def test_tool_specs():
    """Test that tool specifications are properly defined."""
    from talk2stindex.mcp.tools.stindex import TOOL_SPECS

    assert len(TOOL_SPECS) == 2
    assert TOOL_SPECS[0]["name"] == "extract_text"
    assert TOOL_SPECS[1]["name"] == "extract_pdf"


def test_extract_text_spec_schema():
    """Test extract_text tool spec has correct input schema."""
    from talk2stindex.mcp.tools.stindex import EXTRACT_TEXT_SPEC

    props = EXTRACT_TEXT_SPEC["inputSchema"]["properties"]
    assert "text" in props
    assert "temporal_reference" in props
    assert "spatial_reference" in props
    assert EXTRACT_TEXT_SPEC["inputSchema"]["required"] == ["text"]


def test_json_utils_valid():
    """Test JSON extraction from clean output."""
    from talk2stindex.core.json_utils import extract_json_from_text

    raw = '{"temporal": [], "spatial": []}'
    result = extract_json_from_text(raw)
    assert result == {"temporal": [], "spatial": []}


def test_json_utils_markdown():
    """Test JSON extraction from markdown-wrapped output."""
    from talk2stindex.core.json_utils import extract_json_from_text

    raw = '```json\n{"temporal": [{"text": "Monday"}]}\n```'
    result = extract_json_from_text(raw)
    assert result["temporal"][0]["text"] == "Monday"


def test_json_utils_extra_text():
    """Test JSON extraction with surrounding text."""
    from talk2stindex.core.json_utils import extract_json_from_text

    raw = 'Here is the result: {"a": 1} Hope that helps!'
    result = extract_json_from_text(raw)
    assert result == {"a": 1}


def test_json_utils_no_json():
    """Test JSON extraction raises on no JSON."""
    from talk2stindex.core.json_utils import extract_json_from_text

    with pytest.raises(ValueError, match="No JSON"):
        extract_json_from_text("no json here")


def test_temporal_resolve_iso8601_passthrough():
    """Test that ISO 8601 dates pass through unchanged."""
    from talk2stindex.core.temporal import resolve_relative

    resolved, typ = resolve_relative("2024-03-15", "2024-06-01")
    assert resolved == "2024-03-15"
    assert typ == "date"


def test_temporal_resolve_weekday():
    """Test resolving a weekday name."""
    from talk2stindex.core.temporal import resolve_relative

    resolved, typ = resolve_relative("Monday", "2024-06-05")  # Wed
    assert resolved == "2024-06-10"  # next Monday
    assert typ == "date"


def test_temporal_resolve_last_week():
    """Test resolving 'last week'."""
    from talk2stindex.core.temporal import resolve_relative

    resolved, typ = resolve_relative("last week", "2024-06-10")
    assert resolved == "2024-06-03"
    assert typ == "date"


def test_temporal_resolve_last_month():
    """Test resolving 'last month'."""
    from talk2stindex.core.temporal import resolve_relative

    resolved, typ = resolve_relative("last month", "2024-06-10")
    assert resolved == "2024-05"
    assert typ == "month"


def test_temporal_resolve_last_year():
    """Test resolving 'last year'."""
    from talk2stindex.core.temporal import resolve_relative

    resolved, typ = resolve_relative("last year", "2024-06-10")
    assert resolved == "2023"
    assert typ == "year"


def test_temporal_resolve_next_quarter():
    """Test resolving 'next quarter'."""
    from talk2stindex.core.temporal import resolve_relative

    resolved, typ = resolve_relative("next quarter", "2024-03-15")  # Q1 → Q2
    assert resolved == "2024-04"
    assert typ == "month"


def test_temporal_resolve_n_days_ago():
    """Test resolving 'N days ago'."""
    from talk2stindex.core.temporal import resolve_relative

    resolved, typ = resolve_relative("3 days ago", "2024-06-10")
    assert resolved == "2024-06-07"
    assert typ == "date"


def test_temporal_resolve_no_anchor():
    """Test resolving relative text without anchor returns as-is."""
    from talk2stindex.core.temporal import resolve_relative

    resolved, typ = resolve_relative("last week", None)
    assert resolved == "last week"
    assert typ == "relative"


def test_prompt_builder():
    """Test prompt builder produces valid prompts."""
    from talk2stindex.core.prompt import build_extraction_prompt

    system, user = build_extraction_prompt(
        "Test text",
        temporal_reference="2024-06-01",
        spatial_reference="Perth, WA",
    )
    assert "TEMPORAL" in system
    assert "SPATIAL" in system
    assert "2024-06-01" in system
    assert "Perth, WA" in system
    assert user == "Test text"


def test_prompt_builder_no_context():
    """Test prompt builder works without reference context."""
    from talk2stindex.core.prompt import build_extraction_prompt

    system, user = build_extraction_prompt("Hello world")
    assert "TEMPORAL" in system
    assert "SPATIAL" in system
    assert "DOCUMENT CONTEXT" not in system


def test_llm_client_factory_unknown():
    """Test that unknown provider raises ValueError."""
    from talk2stindex.core.llm import create_client

    with pytest.raises(ValueError, match="Unknown"):
        create_client(provider="foobar")


def test_config_load_defaults():
    """Test MCPConfig loads with defaults."""
    from talk2stindex.mcp.config import MCPConfig

    config = MCPConfig()
    assert config.server.port == 8016
    assert config.server.host == "0.0.0.0"
    assert config.oauth.protect_mcp is True
    assert config.llm.anthropic_api_key is None
