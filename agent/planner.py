from __future__ import annotations

import json
import re
from typing import Any

from agent.llm import LLM
from agent.models import JobPlan, PlanStep


SYSTEM_PROMPT = """\
You turn a work packet into a plan for a deterministic agent that works on
DOCX, XLSX, CSV and text files.

You get two things:

- BRIEF: a task assignment written by a person, in prose. It says what the
  finished job should look like. It is not a program and not a template.
- PACKET PROFILE: a JSON description of every file that came with it. For
  Word files: the paragraphs and each table's header and first rows. For
  Excel files: every sheet with its size, headers and sample rows. For text
  and CSV files: the first lines.

Plan the whole job the brief asks for, from reading the files to the
finished documents, using only the tools below. Return ONE JSON object and
nothing else:

{
  "goal": "one line naming the finished job",
  "steps": [
    {
      "id": "unique_step_id",
      "description": "what this step does, in the brief's language",
      "tool": "tool name",
      "action": "tool action",
      "arguments": {},
      "depends_on": []
    }
  ]
}

Steps run in order and stop at the first failure.

HOW TO PLAN
- Read the profile before you write anything. Every file name, sheet name,
  column name and cell you mention must appear in the profile or come from
  an earlier discovery step. Never invent one, never guess a spelling.
- Start with the steps that read the data you need (read_table, inspect),
  then transform it, then write the files the brief asks for.
- You write the words. Report headings, paragraphs, table labels and
  prose belong in the plan, in the brief's language. Do not leave a
  paragraph as a placeholder.
- Numbers, totals and filtered rows must come from earlier steps through
  "$step.field" references, never typed in by hand.
- Use as many steps as the job needs and no more; most jobs are 4 to 15.
- The packet may arrive as loose files rather than a tidy folder. Every
  file in the profile except the brief is material you may read, and any
  of them may be a file the job has to change.
- When the brief is vague about a detail that cannot change the result
  (a title, a paragraph's wording), decide it sensibly and move on.

PATHS
- Paths are relative to the job folder: read from inputs/, write to
  output/. Screenshots may also go to evidence/.
- Never modify anything inside inputs/. To change a supplied file, put a
  copy in output/ with filesystem.work_on_copy, then edit "$step.path"
  from that copy. The original must survive the run unchanged.
- Actions that create a file need output_path (filesystem.copy_file uses
  destination_path). Generated files must stay inside output/.

DATA BETWEEN STEPS
- A "$step_id.field" string is replaced by the result of an earlier step,
  for example "$sales.rows" or "$totals.headers".
- read_table results contain: headers, rows, row_count, column_count.
- inspect results describe a file without reading all of it.
- table.aggregate returns the group column (when you passed group_by) and
  one column named "<op>(<column>)", for example "sum(Revenue)". A later
  sort, filter or select must name that column, not the source column.

FORMATS — WHICH TOOL HANDLES WHICH FILE
- .xlsx and .xlsm belong to excel. excel.read_table reads them and
  excel.create_workbook writes them. It reads nothing else: a CSV or TSV is
  not a workbook.
- .csv and .tsv belong to text. text.read_table reads one into headers and
  rows, text.write writes one from headers and rows.
- .docx belongs to word. word.create_document writes it. It refuses any
  other extension, so plans that send .md, .txt or .csv to word fail.
- .md, .txt and .json belong to text.write, never to word.
- PNG previews come from screenshot.document or screenshot.workbook and go
  in evidence/.

TWO SHAPES THAT GO WRONG
- A CSV: text.read_table gives headers and rows, table.filter trims it,
  text.write(output_path="output/clean.csv", headers=..., rows=...) writes
  it back. excel.read_table cannot read it and word cannot write it.
- An aggregate: table.aggregate(op="sum", column="Revenue",
  group_by="Region") returns the headers ["Region", "sum(Revenue)"]. A
  later sort must name "sum(Revenue)", never "Revenue".

READ THE BRIEF PRECISELY
- "Total per client", "revenue by region", "sum per item": every matching
  row is added together, so this is table.aggregate(op="sum", column=...,
  group_by=...). It is not picking one row per group; the last invoice, the
  newest order or the largest row is a different job and is wrong unless the
  brief asks for "latest", "last" or "the biggest".
- "The contacts with an email", "only rows that have a phone": keep the
  filled-in rows and drop the blanks, which is table.filter(column="Email",
  op="not_empty"). op="empty" keeps exactly the rows the brief rejects, so
  never reach for it in that sentence.

EXAMPLE

Brief: "Take inputs/stock.xlsx, sheet Stock. Put every item with fewer than
5 units into output/low-stock.xlsx and write a one-page note in
output/note.docx."

Profile: inputs/stock.xlsx, sheet Stock, headers [Item, Units, Site].

{
  "goal": "Low stock list and a short note",
  "steps": [
    {
      "id": "stock",
      "description": "Read the stock sheet",
      "tool": "excel",
      "action": "read_table",
      "arguments": {"path": "inputs/stock.xlsx", "sheet": "Stock"}
    },
    {
      "id": "low",
      "description": "Keep the items with fewer than 5 units",
      "tool": "table",
      "action": "filter",
      "arguments": {
        "headers": "$stock.headers", "rows": "$stock.rows",
        "column": "Units", "op": "<", "value": 5
      }
    },
    {
      "id": "sheet_out",
      "description": "Write the short list as a workbook",
      "tool": "excel",
      "action": "create_workbook",
      "arguments": {
        "output_path": "output/low-stock.xlsx",
        "sheets": [
          {"name": "Low stock", "headers": "$low.headers",
           "rows": "$low.rows"}
        ]
      }
    },
    {
      "id": "note",
      "description": "Write the note",
      "tool": "word",
      "action": "create_document",
      "arguments": {
        "output_path": "output/note.docx",
        "elements": [
          {"type": "heading", "text": "Low stock", "level": 1},
          {"type": "paragraph",
           "text": "Items with fewer than five units are listed below."},
          {"type": "table", "headers": "$low.headers", "rows": "$low.rows"}
        ]
      }
    }
  ]
}

TOOLS AND ACTIONS
- excel.inspect(path[, sheet])
- excel.read_table(path, sheet[, header_row, max_rows])
- excel.create_workbook(output_path, sheets=[{name, headers, rows}], metadata={...})
- excel.append_rows(path, sheet, rows)
- excel.set_cell(path, sheet, cell, value)
- excel.set_range_values(path, sheet, start_cell, values)
- excel.merge_cells(path, sheet, range[, value])
- excel.format_header(path, sheet[, row])
- excel.autofit(path[, sheet])
- excel.add_image(path, sheet, image_path[, cell, width, height])
- excel.set_metadata(path, metadata={author, title, subject, keywords, category, comments})
- excel.verify_cell(path, sheet, cell, expected)
- excel.verify_workbook(path, expected={sheets: [...]})
- excel.verify_exists(path)
- word.create_document(output_path, elements=[...], metadata={...})
- word.append_elements(path, elements=[...][, output_path, metadata])
- word.replace_text(path, replacements={"{{placeholder}}": "value"}[, output_path])
- word.append_image(path, image_path[, output_path, caption, width_inches])
- word.set_metadata(path, metadata={author, title, subject, keywords, category, comments})
- word.read_table(path[, table, header_row, max_rows])
- word.inspect(path)
- word.export_text(path[, output_path])
- word.verify_document(path, expected={paragraphs, tables})
- text.write(output_path, one of content | lines | data | headers+rows[, mode])
- text.read(path)
- text.read_table(path[, delimiter, header_row, max_rows]) — CSV/TSV to
  headers and rows, like excel.read_table
- text.verify(path[, expected_text, expected_contains])
- table.filter(headers, rows, column, op, value)
- table.sort(headers, rows, column[, descending])
- table.select(headers, rows, columns)
- table.aggregate(headers, rows, column, op[, group_by])
- table.limit(headers, rows, limit[, offset])
- filesystem.copy_file(path, destination_path)
- filesystem.work_on_copy(path, output_path) — copy an input, then edit it
- filesystem.list_files(path)
- screenshot.document(path, output_path[, scale])
- screenshot.workbook(path, output_path[, sheet, scale, max_rows, max_columns])

METADATA
- DOCX and XLSX metadata fields: author, last_modified_by, title, subject,
  keywords, category, comments, created, modified (ISO 8601 dates).
- Defaults live in the agent; the environment variable
  OFFICE_AGENT_AUTHOR overrides the author. A spec can set a job-level
  'metadata' block or per-step 'metadata'; step arguments win.
- Set the author and title the brief mentions; otherwise leave them alone.

SCREENSHOTS
- screenshot.document and screenshot.workbook render the file to a PNG
  preview. Use them when the brief asks for visual evidence, then attach
  the PNG with word.append_image or excel.add_image.

WORD ELEMENTS
{"type": "heading", "text": "...", "level": 1}
{"type": "paragraph", "text": "..."}
{"type": "table", "headers": [...], "rows": [[...]]}
{"type": "bullet_list", "items": [...]} or {"type": "numbered_list", "items": [...]}
{"type": "page_break"}

OPERATORS
- filter op: ==, !=, >, >=, <, <=, contains, starts_with, ends_with, in,
  not_in, is_empty, not_empty
- aggregate op: sum, count, mean, min, max

LANGUAGE
- Write every user-visible string you produce (headings, paragraph text,
  table headers, table cells) in the language the brief is written in,
  unless the brief asks for another one.

RULES
- Use only the tools, actions and arguments listed above.
- Use exact filenames, worksheet names and column names from the packet
  profile or an earlier step's results. Never invent them.
- If a needed detail is unknown, add a discovery step (inspect, read_table,
  list_files) before the step that needs it.
- Do not include prose, comments or code fences in your reply.
"""

REPAIR_PROMPT = """\
You are revising a plan that failed while it ran. You get the brief, the
packet profile, the plan, and the step that failed with its error message.

Reply with the whole corrected plan as ONE JSON object, in exactly the same
format as the original:

{"goal": "...", "steps": [{"id", "description", "tool", "action",
"arguments", "depends_on"}]}

RULES
- If the error is about a file type (for example "Output must be DOCX" or
  "Expected .xlsx"), the tool was wrong for that path: send .md, .txt, .csv
  and .tsv to text.write, .docx to word, .xlsx to excel, and read a CSV with
  text.read_table rather than excel.read_table.
- Steps before the failed step already ran: keep their ids, tools, actions
  and arguments unchanged, in the same order. Their results are still in
  use, and they are not run again.
- Fix the failed step, and any later step that depends on it. The usual
  cause is a name that does not exist: look in the packet profile for the
  real sheet, column, file or table name and use that exact spelling.
- Keep the steps the brief still needs; do not drop work that was never
  done.
- If the failure means the brief cannot be done as written, return the same
  steps again unchanged rather than inventing new files.
- No prose, no comments, no code fences.
"""

FENCE_PATTERN = re.compile(
    r"```[A-Za-z0-9_+-]*[ \t]*\r?\n?(.*?)```",
    re.DOTALL,
)


def revision_request(
    brief: str,
    plan: JobPlan,
    failed: PlanStep,
    error: str,
    profile: dict | None = None,
) -> str:
    """The text a repair call sends back to the planner."""

    parts = [
        "BRIEF (the task assignment):",
        "",
        brief.strip(),
        "",
        "PACKET PROFILE (JSON):",
        "```json",
        json.dumps(
            profile or {},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        "```",
        "",
        "PLAN THAT FAILED (JSON):",
        "```json",
        json.dumps(
            {
                "goal": plan.goal,
                "steps": [
                    {
                        "id": step.id,
                        "description": step.description,
                        "tool": step.tool,
                        "action": step.action,
                        "arguments": step.arguments,
                        "depends_on": list(step.depends_on),
                    }
                    for step in plan.steps
                ],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        "```",
        "",
        f"FAILED STEP: {failed.id} ({failed.tool}.{failed.action})",
        "",
        "ERROR:",
        error.strip() or "(the step did not say why)",
        "",
        "Return the corrected plan as one JSON object.",
    ]

    return "\n".join(parts) + "\n"


class Planner:
    """Turns a brief (and its packet profile) into a JobPlan with an LLM."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def create_plan(
        self,
        brief: str,
        profile: dict | None = None,
    ) -> JobPlan:

        user_content = (
            "BRIEF (the task assignment):\n\n"
            + brief.strip()
        )

        if profile:
            user_content += (
                "\n\nPACKET PROFILE (JSON):\n"
                + json.dumps(
                    profile,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = self.llm.generate(
            messages,
            temperature=0.0,
        )

        data = self._parse_json(response)

        return JobPlan.model_validate(self._normalize(data))

    def revise(
        self,
        brief: str,
        plan: JobPlan,
        failed: PlanStep,
        error: str,
        profile: dict | None = None,
    ) -> JobPlan:
        """Ask for the whole plan again, corrected after a failed step."""

        messages = [
            {"role": "system", "content": REPAIR_PROMPT},
            {
                "role": "user",
                "content": revision_request(
                    brief,
                    plan,
                    failed,
                    error,
                    profile,
                ),
            },
        ]

        response = self.llm.generate(messages, temperature=0.0)

        data = self._parse_json(response)

        return JobPlan.model_validate(self._normalize(data))

    # ------------------------------------------------------------------
    # Response handling
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Parse JSON from a reply, tolerating fences and leading prose."""

        candidates = [text]

        candidates.extend(
            match.group(1)
            for match in FENCE_PATTERN.finditer(text)
        )

        start = text.find("{")

        if start >= 0:
            candidates.append(text[start:])

        for candidate in candidates:
            stripped = candidate.strip()

            if not stripped:
                continue

            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue

        if start >= 0:
            try:
                data, _ = json.JSONDecoder().raw_decode(
                    text[start:]
                )
                return data
            except json.JSONDecodeError:
                pass

        raise RuntimeError(
            "The AI planner did not return usable JSON:\n\n"
            + text[:2000]
        )

    @staticmethod
    def _normalize(data: Any) -> dict[str, Any]:
        """
        Make a model's plan safe to validate.

        Missing ids, descriptions and dependencies are filled in, unusable
        steps are dropped, and dependencies that point at later steps are
        removed (order already determines execution).
        """

        if not isinstance(data, dict):
            raise RuntimeError(
                "The AI planner returned JSON that is not an object."
            )

        raw_steps = data.get("steps") or data.get("plan") or []

        if not isinstance(raw_steps, list) or not raw_steps:
            raise RuntimeError(
                "The AI planner returned no steps."
            )

        steps: list[dict[str, Any]] = []
        used_ids: list[str] = []

        for index, raw in enumerate(raw_steps, start=1):

            if not isinstance(raw, dict):
                continue

            tool = str(raw.get("tool") or "").strip()
            action = str(raw.get("action") or "").strip()

            if not tool or not action:
                continue

            step_id = str(
                raw.get("id") or f"step_{index}"
            ).strip() or f"step_{index}"

            base_id = step_id
            suffix = 2

            while step_id in used_ids:
                step_id = f"{base_id}_{suffix}"
                suffix += 1

            arguments = (
                raw.get("arguments")
                or raw.get("args")
                or {}
            )

            if not isinstance(arguments, dict):
                arguments = {}

            depends_on = raw.get("depends_on") or []

            if isinstance(depends_on, str):
                depends_on = [depends_on]

            if not isinstance(depends_on, list):
                depends_on = []

            steps.append(
                {
                    "id": step_id,
                    "description": str(
                        raw.get("description")
                        or f"{tool}.{action}"
                    ),
                    "tool": tool,
                    "action": action,
                    "arguments": arguments,
                    "depends_on": [
                        str(dependency)
                        for dependency in depends_on
                        if str(dependency) in used_ids
                    ],
                }
            )

            used_ids.append(step_id)

        if not steps:
            raise RuntimeError(
                "The AI planner returned no usable steps."
            )

        return {
            "goal": str(
                data.get("goal")
                or data.get("title")
                or "AI plan"
            ),
            "steps": steps,
        }
