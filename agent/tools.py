"""
Tool registry that exposes our analytical primitives to Gemini.

Design:
    - Each tool is declared once with a JSON Schema describing its arguments.
    - Gemini sees these declarations and decides which tool to call.
    - The dispatch layer executes the real Python function and returns a dict.
    - Errors are caught and returned as error dicts (not raised) so the LLM
      can recover gracefully instead of crashing the conversation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
import pandas as pd

from google.genai import types as gtypes

from analytics.primitives import (
    top_n_zones,
    compare_segments,
    trend,
    aggregate,
    multivariable_filter,
    growth_drivers,
)
from analytics.detectors import run_all_detectors
from core.metric_dictionary import all_metric_names

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dynamic enum so tool schemas always match the current metric dictionary.
# ---------------------------------------------------------------------------

METRIC_ENUM = all_metric_names()

COUNTRY_ENUM = ["AR", "BR", "CL", "CO", "CR", "EC", "MX", "PE", "UY"]
ZONE_TYPE_ENUM = ["Wealthy", "Non Wealthy"]
ZONE_PRIO_ENUM = ["High Priority", "Prioritized", "Not Prioritized"]


# ---------------------------------------------------------------------------
# Tool declarations (what Gemini sees)
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS: list[gtypes.FunctionDeclaration] = [
    gtypes.FunctionDeclaration(
        name="top_n_zones",
        description=(
            "Return the top-N zones ranked by a metric. The ranking direction "
            "is automatic based on the metric's semantic (higher-is-better vs "
            "lower-is-better). Use for filtering questions like 'which are the "
            "best/worst zones for X'."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "metric": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    enum=METRIC_ENUM,
                    description="The operational metric to rank by.",
                ),
                "n": gtypes.Schema(type=gtypes.Type.INTEGER, description="How many zones to return."),
                "week_offset": gtypes.Schema(
                    type=gtypes.Type.INTEGER,
                    description="0 = current week, 1 = last week, ..., 8 = 8 weeks ago.",
                ),
                "country": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    enum=COUNTRY_ENUM,
                    description="Optional country filter (ISO-2 code).",
                ),
                "zone_type": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    enum=ZONE_TYPE_ENUM,
                    description="Optional wealth segmentation filter.",
                ),
                "zone_prioritization": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    enum=ZONE_PRIO_ENUM,
                    description="Optional strategic prioritization filter.",
                ),
            },
            required=["metric"],
        ),
    ),
    gtypes.FunctionDeclaration(
        name="compare_segments",
        description=(
            "Compare a metric between two or more segments (e.g., Wealthy vs "
            "Non Wealthy zones, or country-to-country). Uses direction-aware "
            "aggregation from the metric dictionary. Pass weeks_window=N to "
            "average over the last N weeks (reduces noise and is often what "
            "the user actually wants when they don't specify a week)."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "metric": gtypes.Schema(type=gtypes.Type.STRING, enum=METRIC_ENUM),
                "segment_by": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    enum=["ZONE_TYPE", "ZONE_PRIORITIZATION", "COUNTRY"],
                    description="Dimension to segment on.",
                ),
                "segment_values": gtypes.Schema(
                    type=gtypes.Type.ARRAY,
                    items=gtypes.Schema(type=gtypes.Type.STRING),
                    description="Optional subset of segment values to compare.",
                ),
                "week_offset": gtypes.Schema(
                    type=gtypes.Type.INTEGER,
                    description="Single-week mode: 0=current, 1=last, ..., 8=8wks ago. Default 0.",
                ),
                "weeks_window": gtypes.Schema(
                    type=gtypes.Type.INTEGER,
                    description=(
                        "Averaging mode: compute the mean over the last N weeks. "
                        "Use this when the user asks for a comparison without "
                        "specifying a single week — it's less noisy."
                    ),
                ),
                "country": gtypes.Schema(type=gtypes.Type.STRING, enum=COUNTRY_ENUM),
            },
            required=["metric", "segment_by"],
        ),
    ),
    gtypes.FunctionDeclaration(
        name="trend",
        description=(
            "Time series of a metric over the last N weeks. Pass `zone` for a "
            "single-zone trend, `country` for a country-level aggregate, or "
            "neither for a global trend. Use for 'evolution' or 'show me the "
            "last X weeks' questions."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "metric": gtypes.Schema(type=gtypes.Type.STRING, enum=METRIC_ENUM),
                "zone": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    description="Exact zone name (e.g., 'Chapinero'). Optional.",
                ),
                "country": gtypes.Schema(type=gtypes.Type.STRING, enum=COUNTRY_ENUM),
                "n_weeks": gtypes.Schema(
                    type=gtypes.Type.INTEGER,
                    description="How many weeks back to include (1-9). Default 8.",
                ),
            },
            required=["metric"],
        ),
    ),
    gtypes.FunctionDeclaration(
        name="aggregate",
        description=(
            "Group-by aggregation of a metric, e.g., 'average Lead Penetration "
            "per country' or 'total Orders per zone type'. Aggregation strategy "
            "(mean vs weighted mean vs sum) is automatic per metric."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "metric": gtypes.Schema(type=gtypes.Type.STRING, enum=METRIC_ENUM),
                "group_by": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    enum=["COUNTRY", "CITY", "ZONE_TYPE", "ZONE_PRIORITIZATION"],
                ),
                "week_offset": gtypes.Schema(type=gtypes.Type.INTEGER),
            },
            required=["metric", "group_by"],
        ),
    ),
    gtypes.FunctionDeclaration(
        name="multivariable_filter",
        description=(
            "Find zones that are favorable on one metric AND unfavorable on "
            "another. Example: 'zones with high Lead Penetration but low "
            "Perfect Orders'. 'High' and 'low' are interpreted direction-aware "
            "(a high markdown zone is still 'unfavorable' even though higher)."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "high_metric": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    enum=METRIC_ENUM,
                    description="The metric where we want zones to perform well.",
                ),
                "low_metric": gtypes.Schema(
                    type=gtypes.Type.STRING,
                    enum=METRIC_ENUM,
                    description="The metric where we want zones to perform poorly.",
                ),
                "week_offset": gtypes.Schema(type=gtypes.Type.INTEGER),
                "country": gtypes.Schema(type=gtypes.Type.STRING, enum=COUNTRY_ENUM),
            },
            required=["high_metric", "low_metric"],
        ),
    ),
    gtypes.FunctionDeclaration(
        name="growth_drivers",
        description=(
            "Identify zones with the biggest increase in a target metric over "
            "N weeks, and for each zone, list the other metrics that moved the "
            "most in the same period as candidate explanatory drivers. Use for "
            "inference questions: 'which zones are growing most in orders and "
            "what might explain it?'"
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={
                "target_metric": gtypes.Schema(type=gtypes.Type.STRING, enum=METRIC_ENUM),
                "n_weeks": gtypes.Schema(type=gtypes.Type.INTEGER, description="Default 5."),
                "top_n_growing": gtypes.Schema(type=gtypes.Type.INTEGER, description="Default 5."),
                "country": gtypes.Schema(type=gtypes.Type.STRING, enum=COUNTRY_ENUM),
            },
            required=["target_metric"],
        ),
    ),
    gtypes.FunctionDeclaration(
        name="run_all_detectors",
        description=(
            "Run the full suite of automatic detectors (anomalies, "
            "deteriorating trends, peer divergence, correlations, "
            "opportunities) across the entire dataset. Use when the user asks "
            "for proactive insights, weekly summaries, or 'what's interesting'."
        ),
        parameters=gtypes.Schema(
            type=gtypes.Type.OBJECT,
            properties={},
        ),
    ),
]


# ---------------------------------------------------------------------------
# Dispatch table (what is actually called)
# ---------------------------------------------------------------------------

def _build_registry(df: pd.DataFrame) -> dict[str, Callable[..., Any]]:
    """Bind the loaded dataframe to each primitive so Gemini-callable tools
    only need to pass business arguments, not the dataframe."""
    return {
        "top_n_zones": lambda **kw: top_n_zones(df, **kw),
        "compare_segments": lambda **kw: compare_segments(df, **kw),
        "trend": lambda **kw: trend(df, **kw),
        "aggregate": lambda **kw: aggregate(df, **kw),
        "multivariable_filter": lambda **kw: multivariable_filter(df, **kw),
        "growth_drivers": lambda **kw: growth_drivers(df, **kw),
        "run_all_detectors": lambda **kw: run_all_detectors(df),
    }


def execute_tool(
    df: pd.DataFrame,
    tool_name: str,
    tool_args: dict,
) -> dict:
    """
    Execute a single tool call with defensive error handling.
    Returns a dict that's always serializable — either the tool's result
    or an {"error": ...} dict the LLM can see and recover from.
    """
    registry = _build_registry(df)

    if tool_name not in registry:
        return {
            "error": f"Unknown tool '{tool_name}'.",
            "available_tools": list(registry.keys()),
        }

    try:
        logger.info(f"Executing tool '{tool_name}' with args: {tool_args}")
        result = registry[tool_name](**tool_args)
        return result
    except ValueError as e:
        # Invalid argument (e.g., unknown metric). Safe to show to LLM.
        logger.warning(f"Tool '{tool_name}' rejected args: {e}")
        return {"error": str(e), "tool": tool_name, "args": tool_args}
    except Exception as e:
        # Unexpected error. Log the real trace but return a clean message.
        logger.exception(f"Tool '{tool_name}' crashed unexpectedly")
        return {
            "error": f"Internal error executing {tool_name}: {type(e).__name__}",
            "tool": tool_name,
        }
