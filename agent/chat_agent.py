"""
Main chat agent loop.

The loop follows the standard tool-calling pattern:
    1. Send user message + history + tool declarations to Gemini
    2. If Gemini responds with a function_call, execute the tool
    3. Send the tool result back to Gemini
    4. Gemini either calls another tool or produces a final text answer
    5. Return the text answer + full turn history (for the UI to store)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types as gtypes

from agent.tools import TOOL_DECLARATIONS, execute_tool
from agent.system_prompt import SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"
MAX_TOOL_ITERATIONS = 5  # Safety cap — stops runaway tool loops.


@dataclass
class AgentResponse:
    """What a chat turn returns to the caller (UI)."""
    text: str
    tool_calls: list[dict] = field(default_factory=list)  # for transparency in the UI
    iterations: int = 0  # how many tool hops happened


class ChatAgent:
    """A stateful agent that wraps Gemini + our tool registry.

    One ChatAgent instance = one conversation. The Streamlit UI creates one
    per session and reuses it across turns so memory (conversation history)
    persists naturally.
    """

    def __init__(self, df: pd.DataFrame, model: str = MODEL):
        api_key = None
        try:
            import streamlit as st
            api_key = st.secrets.get("GEMINI_API_KEY, None")
        except (ImportError, FileNotFoundError, Exception):
            pass
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")


        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.df = df
        self.history: list[gtypes.Content] = []
        self.tools = gtypes.Tool(function_declarations=TOOL_DECLARATIONS)

    def chat(self, user_message: str) -> AgentResponse:
        """Process one user message and return the agent's response."""
        # Append user message to history
        self.history.append(
            gtypes.Content(role="user", parts=[gtypes.Part(text=user_message)])
        )

        tool_calls_log: list[dict] = []

        for iteration in range(MAX_TOOL_ITERATIONS):
            logger.info(f"Agent iteration {iteration + 1}")

            response = self.client.models.generate_content(
                model=self.model,
                contents=self.history,
                config=gtypes.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[self.tools],
                    temperature=0.3,
                    max_output_tokens=2048,
                    thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
                ),
            )

            # If no candidates, something is deeply wrong
            if not response.candidates:
                return AgentResponse(
                    text="Lo siento, no recibí respuesta del modelo. Intenta de nuevo.",
                    iterations=iteration + 1,
                )

            candidate = response.candidates[0]
            content = candidate.content

            # Record the model's turn in history (its entire Content block)
            self.history.append(content)

            # Look for function calls in the parts
            function_calls = [
                part.function_call
                for part in (content.parts or [])
                if part.function_call is not None
            ]

            if not function_calls:
                # Model produced a plain text answer -> we're done
                text_parts = [
                    part.text for part in (content.parts or []) if part.text
                ]
                final_text = "\n".join(text_parts).strip()

                if not final_text:
                    # Empty response — build an informative fallback message.
                    # Possible causes: safety filter, token cutoff, empty model output.
                    finish_reason = getattr(candidate, "finish_reason", None)
                    safety_ratings = getattr(candidate, "safety_ratings", None)
                    logger.warning(
                        f"Empty model response. "
                        f"finish_reason={finish_reason}, "
                        f"safety_ratings={safety_ratings}, "
                        f"parts={content.parts}"
                    )
                    final_text = (
                        f"⚠️ El modelo no devolvió una respuesta de texto "
                        f"(finish_reason={finish_reason}). "
                        f"Intenta reformular la pregunta."
                    )

                return AgentResponse(
                    text=final_text,
                    tool_calls=tool_calls_log,
                    iterations=iteration + 1,
                )

            # Execute every function call and send results back
            function_response_parts: list[gtypes.Part] = []
            for fc in function_calls:
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}

                result = execute_tool(self.df, tool_name, tool_args)
                tool_calls_log.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result_summary": _summarize_result(result),
                })

                function_response_parts.append(
                    gtypes.Part.from_function_response(
                        name=tool_name,
                        response={"result": result},
                    )
                )

            # Append all function responses as a single user-role message
            self.history.append(
                gtypes.Content(role="user", parts=function_response_parts)
            )

        # Hit iteration cap
        return AgentResponse(
            text=(
                "Me detuve después de varios intentos de resolver la pregunta. "
                "Intenta reformularla o pedir algo más específico."
            ),
            tool_calls=tool_calls_log,
            iterations=MAX_TOOL_ITERATIONS,
        )

    def reset(self) -> None:
        """Clear conversation history (UI can call this on 'new chat')."""
        self.history = []


def _summarize_result(result: dict) -> str:
    """Short human-readable summary of a tool result, for logging/UI transparency."""
    if "error" in result:
        return f"ERROR: {result['error']}"
    if "rows" in result:
        return f"{len(result['rows'])} rows"
    if isinstance(result, dict):
        keys = list(result.keys())[:3]
        return f"dict with keys: {keys}"
    return str(type(result).__name__)
