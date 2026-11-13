from __future__ import annotations

import copy
import re
from typing import Any, Iterator

from agent.models import ToolResult


REF_PATTERN = re.compile(
    r"^\$([A-Za-z_][A-Za-z0-9_-]*)"
    r"((?:\.[A-Za-z0-9_-]+)*)$"
)

SECTIONS = {"data", "message", "evidence"}


class ResolutionError(ValueError):
    """Raised when a "$step.field" reference cannot be resolved."""


def resolve_arguments(
    arguments: dict[str, Any],
    results: dict[str, ToolResult],
) -> dict[str, Any]:
    """
    Replace "$step.field" references in step arguments with tool results.

    References must occupy a whole string value, for example:

        {"rows": "$sales.rows", "sheet": "Summary"}
    """

    return _resolve_value(arguments, results)


def _resolve_value(
    value: Any,
    results: dict[str, ToolResult],
) -> Any:
    if isinstance(value, str):
        match = REF_PATTERN.match(value)

        if match:
            return _resolve_reference(
                match,
                value,
                results,
            )

        return value

    if isinstance(value, dict):
        return {
            key: _resolve_value(item, results)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _resolve_value(item, results)
            for item in value
        ]

    return value


def _resolve_reference(
    match: re.Match[str],
    expression: str,
    results: dict[str, ToolResult],
) -> Any:
    step_id = match.group(1)

    tokens = [
        token
        for token in match.group(2).split(".")
        if token
    ]

    if step_id not in results:
        raise ResolutionError(
            f"{expression}: no result for step '{step_id}'. "
            f"Available steps: {sorted(results)}"
        )

    result = results[step_id]

    if tokens and tokens[0] in SECTIONS:
        section = tokens.pop(0)

        node: Any = {
            "data": result.data,
            "message": result.message,
            "evidence": result.evidence,
        }[section]
    else:
        node = result.data

    for token in tokens:
        node = _step_into(node, token, expression)

    return copy.deepcopy(node)


def _step_into(
    node: Any,
    token: str,
    expression: str,
) -> Any:
    if isinstance(node, dict):
        if token in node:
            return node[token]

        if token.isdigit() and int(token) in node:
            return node[int(token)]

        raise ResolutionError(
            f"{expression}: '{token}' not found. "
            f"Available keys: {sorted(str(key) for key in node)[:20]}"
        )

    if isinstance(node, (list, tuple)):
        try:
            index = int(token)
        except ValueError:
            raise ResolutionError(
                f"{expression}: '{token}' is not a list index."
            ) from None

        try:
            return node[index]
        except IndexError:
            raise ResolutionError(
                f"{expression}: index {index} is out of range "
                f"(length {len(node)})."
            ) from None

    raise ResolutionError(
        f"{expression}: cannot read '{token}' from "
        f"{type(node).__name__}."
    )


def iter_references(
    value: Any,
) -> Iterator[str]:
    """Yield step ids referenced anywhere inside a value."""

    if isinstance(value, str):
        match = REF_PATTERN.match(value)

        if match:
            yield match.group(1)

        return

    if isinstance(value, dict):
        for item in value.values():
            yield from iter_references(item)

        return

    if isinstance(value, list):
        for item in value:
            yield from iter_references(item)
