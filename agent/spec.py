from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from agent.metadata import METADATA_ACTIONS
from agent.models import JobPlan, PlanStep


class SpecError(ValueError):
    """Raised when an instruction document has no usable job spec."""


# A fenced block inside the instruction document, e.g. ```yaml ... ```
FENCE_PATTERN = re.compile(
    r"```[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```",
    re.DOTALL,
)

# Characters Word substitutes while typing; normalize them before parsing.
_REPLACEMENTS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u00a0": " ",
        "\u2007": " ",
        "\u202f": " ",
    }
)

SPEC_HELP = (
    "An instruction document must contain a job spec written in YAML "
    "or JSON: either the whole document, or inside a fenced block such as "
    "```yaml ... ```. The spec needs a non-empty 'steps' list where every "
    "step has 'tool' and 'action', for example:\n\n"
    "steps:\n"
    "  - id: read_source\n"
    "    tool: excel\n"
    "    action: read_table\n"
    "    arguments:\n"
    "      path: inputs/values.xlsx\n"
    "      sheet: Sheet1"
)

SPEC_TEMPLATE = """\
title: My automation job

# Steps run in order. Later steps can reuse earlier results with
# "$step_id.field" references, for example "$read_source.rows".
steps:
  - id: read_source
    tool: excel          # excel | word | text | table | filesystem
    action: read_table
    arguments:
      path: inputs/values.xlsx
      sheet: Sheet1

  - id: summary
    tool: table
    action: aggregate
    arguments:
      headers: $read_source.headers
      rows: $read_source.rows
      group_by: Region
      column: Revenue
      op: sum

  - id: workbook
    tool: excel
    action: create_workbook
    arguments:
      output_path: output/summary.xlsx
      sheets:
        - name: Summary
          headers: $summary.headers
          rows: $summary.rows

  - id: report
    tool: word
    action: create_document
    arguments:
      output_path: output/report.docx
      elements:
        - type: heading
          text: Automation report
          level: 1
        - type: paragraph
          text: Generated from inputs/values.xlsx.
        - type: table
          headers: $summary.headers
          rows: $summary.rows

  - id: report_text
    tool: word
    action: export_text
    arguments:
      path: output/report.docx
      output_path: output/report.txt

# Optional document metadata for every DOCX/XLSX this job creates.
# Fields: author, last_modified_by, title, subject, keywords, category,
# comments, created, modified (ISO 8601 dates). A step's own 'metadata'
# wins over this block; arguments win over both. Without any metadata the
# defaults apply, and OFFICE_AGENT_AUTHOR overrides the author.
# metadata:
#   author: Your Name
#   title: My automation job
"""


def parse_spec(text: str) -> dict[str, Any]:
    """
    Parse the job spec out of instruction text.

    Fenced blocks take precedence so a document can mix prose with a spec.
    Both JSON and YAML are accepted.
    """

    normalized = text.translate(_REPLACEMENTS)

    candidates = _spec_candidates(normalized)

    if not candidates:
        raise SpecError(
            "The instruction document is empty."
        )

    errors: list[str] = []

    for candidate in candidates:
        data = _load_candidate(candidate, errors)

        if data is not None:
            return data

    details = ""

    if errors:
        details = (
            "\n\nParse errors:\n- "
            + "\n- ".join(errors[-3:])
        )

    raise SpecError(SPEC_HELP + details)


def _spec_candidates(text: str) -> list[str]:
    blocks = [
        match.group(1)
        for match in FENCE_PATTERN.finditer(text)
    ]

    candidates = [
        block
        for block in blocks
        if block.strip()
    ]

    if text.strip():
        candidates.append(text)

    return candidates


def _load_candidate(
    candidate: str,
    errors: list[str],
) -> dict[str, Any] | None:
    stripped = candidate.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        errors.append(f"JSON: {exc}")

        try:
            data = yaml.safe_load(stripped)
        except yaml.YAMLError as yaml_error:
            errors.append(f"YAML: {yaml_error}")
            return None

    if isinstance(data, dict):
        return data

    return None


def resolve_job_paths(
    value: Any,
    job_root: Path,
) -> Any:
    """
    Make relative path arguments absolute against the job directory.

    Reference strings such as "$step.rows" and absolute paths are kept.
    """

    if isinstance(value, dict):
        resolved: dict[str, Any] = {}

        for key, item in value.items():
            if _is_path_key(key):
                resolved[key] = _resolve_job_path(
                    item,
                    job_root,
                )
            else:
                resolved[key] = resolve_job_paths(
                    item,
                    job_root,
                )

        return resolved

    if isinstance(value, list):
        return [
            resolve_job_paths(item, job_root)
            for item in value
        ]

    return value


def _is_path_key(key: Any) -> bool:
    name = str(key)

    return name == "path" or name.endswith("_path")


def _resolve_job_path(
    value: Any,
    job_root: Path,
) -> Any:
    if not isinstance(value, str):
        return value

    stripped = value.strip()

    if not stripped or stripped.startswith("$"):
        return value

    path = Path(stripped)

    if path.is_absolute():
        return str(path)

    return str((job_root / path).resolve())


def build_job_plan(
    spec: dict[str, Any],
    job_root: Path,
    source: str | None = None,
) -> JobPlan:
    """Turn a parsed spec into a validated JobPlan."""

    where = f"{Path(source).name}: " if source else ""

    steps_raw = spec.get("steps")

    if not isinstance(steps_raw, list) or not steps_raw:
        raise SpecError(
            where
            + "The job spec needs a non-empty 'steps' list."
        )

    goal = str(
        spec.get("title")
        or spec.get("goal")
        or "Automation job"
    )

    job_metadata = spec.get("metadata")

    if job_metadata is not None and not isinstance(job_metadata, dict):
        raise SpecError(
            where + "'metadata' must be a mapping of fields to values."
        )

    job_root = Path(job_root)

    steps: list[PlanStep] = []
    seen: set[str] = set()

    for index, raw in enumerate(steps_raw, start=1):

        if not isinstance(raw, dict):
            raise SpecError(
                where
                + f"Step {index} must be a mapping with "
                "'tool' and 'action'."
            )

        tool = str(raw.get("tool") or "").strip()
        action = str(raw.get("action") or "").strip()

        if not tool or not action:
            raise SpecError(
                where
                + f"Step {index} needs both 'tool' and 'action'."
            )

        step_id = str(
            raw.get("id") or f"step_{index}"
        ).strip()

        if step_id in seen:
            raise SpecError(
                where + f"Duplicate step id: {step_id}"
            )

        seen.add(step_id)

        arguments = (
            raw.get("arguments")
            or raw.get("args")
            or raw.get("with")
            or {}
        )

        if not isinstance(arguments, dict):
            raise SpecError(
                where
                + f"Step '{step_id}': 'arguments' must be a mapping."
            )

        arguments = resolve_job_paths(
            arguments,
            job_root,
        )

        if (tool, action) in METADATA_ACTIONS:
            metadata: dict[str, Any] = dict(job_metadata or {})

            step_metadata = raw.get("metadata")

            if step_metadata is not None:
                if not isinstance(step_metadata, dict):
                    raise SpecError(
                        where
                        + f"Step '{step_id}': 'metadata' must be "
                        "a mapping."
                    )

                metadata.update(step_metadata)

            argument_metadata = arguments.get("metadata")

            if argument_metadata is not None:
                if not isinstance(argument_metadata, dict):
                    raise SpecError(
                        where
                        + f"Step '{step_id}': 'metadata' must be "
                        "a mapping."
                    )

                metadata.update(argument_metadata)

            if metadata:
                arguments["metadata"] = metadata

        depends_on = (
            raw.get("depends_on")
            or raw.get("after")
            or []
        )

        if isinstance(depends_on, str):
            depends_on = [depends_on]

        if not isinstance(depends_on, list):
            raise SpecError(
                where
                + f"Step '{step_id}': 'depends_on' must be a list."
            )

        depends_on = [
            str(dependency)
            for dependency in depends_on
        ]

        steps.append(
            PlanStep(
                id=step_id,
                description=str(
                    raw.get("description")
                    or f"{tool}.{action}"
                ),
                tool=tool,
                action=action,
                arguments=arguments,
                depends_on=depends_on,
            )
        )

    for step in steps:
        for dependency in step.depends_on:
            if dependency not in seen:
                raise SpecError(
                    where
                    + f"Step '{step.id}' depends on unknown "
                    f"step '{dependency}'."
                )

    return JobPlan(goal=goal, steps=steps)


def build_plan_from_text(
    text: str,
    job_root: Path,
    source: str | None = None,
) -> JobPlan:
    """Parse instruction text and build its JobPlan."""

    spec = parse_spec(text)

    return build_job_plan(
        spec,
        job_root,
        source=source,
    )
