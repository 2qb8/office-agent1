"""The JSON shape a plan must have, for servers that can enforce it.

A local llama.cpp server turns a JSON schema into a grammar, so the model
cannot emit a malformed plan: no prose before the object, no code fence, no
missing step field, no invented tool, and no action the chosen tool does not
have. Hosted providers ignore the schema and keep the prompt plus the
validator, which is all they offer.

``arguments`` is deliberately left free-form. Naming the operators there was
tried and measured: listing any properties in it made the 1.5B model omit the
rest of the arguments as well — ``headers`` and ``rows`` on a filter,
``output_path`` on a writer — so a plan that used to run merely wrongly
stopped running at all. The shape is what this grammar guarantees; argument
vocabulary stays the tools' and the validator's job.

The schema is built from the registry, so a tool that gains an action is
allowed through without a second list to keep in step.
"""

from __future__ import annotations

from typing import Any

from agent.registry import ToolRegistry, build_registry


def _step_schema(name: str, actions: list[str]) -> dict[str, Any]:
    """One step, with the action list belonging to this one tool.

    Each tool gets its own branch instead of one shared action enum: a
    grammar built from a union would still let the model write
    ``filesystem.create_document``, which no tool can run.
    """

    return {
        "type": "object",
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "tool": {"type": "string", "enum": [name]},
            "action": {"type": "string", "enum": actions},
            # Free-form on purpose: see the module docstring.
            "arguments": {"type": "object"},
            "depends_on": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "id",
            "description",
            "tool",
            "action",
            "arguments",
            "depends_on",
        ],
        "additionalProperties": False,
    }


def plan_schema(registry: ToolRegistry | None = None) -> dict[str, Any]:
    """The plan object the planner must return, tool by tool."""

    registry = registry or build_registry()

    branches = []

    for name in registry.list_tools():
        supported = sorted(getattr(registry.get(name), "actions", ()) or ())

        if supported:
            branches.append(_step_schema(name, supported))

    item: dict[str, Any]

    if len(branches) == 1:
        item = branches[0]
    else:
        item = {"oneOf": branches}

    return {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": item,
            },
        },
        "required": ["goal", "steps"],
        "additionalProperties": False,
    }


def response_format(registry: ToolRegistry | None = None) -> dict[str, Any]:
    """What an OpenAI-compatible request needs to ask for that shape."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "plan",
            "schema": plan_schema(registry),
        },
    }
