# Office automation agent

A DOCX instruction in, files out. Drop one instruction document into a job
folder, point it at your inputs, run it, and the agent builds the DOCX, XLSX,
CSV, TXT or JSON outputs the instruction describes.

The engine is deterministic: the instruction carries a small YAML/JSON job
spec, and every step names a tool action plus its arguments. Steps can pass
data to later steps with `$step.field` references, so reading a workbook,
filtering rows, summarising them and writing a report is a few declarations.

AI planning is not required. The planner modules are still present and wired
to the runtime, but they are opt-in and unconfigured (see [AI planning](#ai-planning-later)).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Quickstart

Create a job, then open its instruction:

```bash
.venv/bin/python run.py init jobs/my-job
```

Fill `jobs/my-job/inputs/`, edit the YAML block in
`jobs/my-job/instruction.docx`, and run:

```bash
.venv/bin/python run.py jobs/my-job
```

Outputs land in `jobs/my-job/output/`. `run.log` and `state.json` in the job
folder record what happened, step by step.

A complete example ships with the project:

```bash
.venv/bin/python run.py examples/sales-pack
```

It reads `examples/sales-pack/inputs/sales.xlsx`, filters large deals,
aggregates revenue by region, and produces a report DOCX, its TXT export, a
CSV of the filtered rows, a summary workbook, and a copied note file. It also
reads the table inside `inputs/summary.docx` and writes it out as both XLSX
and CSV, stamps the job's `metadata` onto every workbook and document, and
renders a PNG preview of the finished report into `evidence/`. Rebuild the
example inputs with `python examples/build_examples.py`.

List every tool and action:

```bash
.venv/bin/python run.py tools
```

## Job folder layout

```
jobs/my-job/
  instruction.docx     exactly one instruction (.docx, .txt or .md)
  inputs/              source files, read-only
  output/              every generated file
  evidence/            screenshots and other verification artefacts
  run.log, state.json  written by the runtime
  report.json          per-step status, messages and generated outputs
```

Relative paths in a spec are resolved against the job folder, so
`inputs/sales.xlsx` always means the job's own input. The validator refuses
plans that write outside `output/` (screenshots may also write to
`evidence/`), modify anything under `inputs/`, or reference a step that has
not run yet.

## Instruction format

The instruction document contains YAML or JSON. It can be the whole document
or a fenced block (```` ```yaml ```` ... ```` ``` ````) inside normal prose,
which is easier to write in Word. Word's smart quotes and non-breaking spaces
are normalized before parsing.

```yaml
title: Monthly sales pack

steps:
  - id: sales
    tool: excel
    action: read_table
    arguments:
      path: inputs/sales.xlsx
      sheet: Sales

  - id: report
    tool: word
    action: create_document
    arguments:
      output_path: output/sales-report.docx
      elements:
        - type: heading
          text: Monthly Sales Pack
          level: 1
        - type: table
          headers: $sales.headers
          rows: $sales.rows
```

Every step needs `tool` and `action`. Optional keys:

| Key | Meaning |
| --- | --- |
| `id` | Step name used by references; defaults to `step_N` |
| `description` | Human-readable label for the log |
| `arguments` | Action arguments (`args` and `with` also work) |
| `depends_on` | Step ids that must succeed first (`after` also works) |

Steps run in document order, and execution stops at the first failure.

### Passing data between steps

A `$step.field` string is replaced with that step's result before the tool
runs. It must be the whole value, not part of a longer string.

| Reference | Value |
| --- | --- |
| `$sales.headers` | Header row read from a workbook |
| `$sales.rows` | Data rows read from a workbook |
| `$summary.row_count` | Any key of that step's result data |
| `$summary.rows.0.1` | Nested list access, index `0` then `1` |
| `$step.message` | The tool's human-readable message |
| `$step.evidence` | Paths the tool recorded as evidence |

Validated at plan time: a reference to a later or unknown step is rejected
before anything executes.

## Tools

### `excel`

| Action | Arguments |
| --- | --- |
| `inspect` | `path`, optional `sheet` — workbook structure, headers, sample rows, metadata |
| `read_table` | `path`, `sheet`, optional `header_row` (default 1), `max_rows`, `data_only` |
| `create_workbook` | `output_path`, `sheets: [{name, headers, rows}]`, optional `metadata` |
| `append_rows` | `path`, `sheet`, `rows: [[...]]` — adds after the last used row |
| `set_cell` | `path`, `sheet`, `cell`, `value` |
| `set_range_values` | `path`, `sheet`, `start_cell`, `values: [[...]]` |
| `merge_cells` | `path`, `sheet`, `range` (`A1:B1`), optional `value` |
| `format_header` | `path`, `sheet`, optional `row` (default 1) |
| `autofit` | `path`, optional `sheet` (default: all sheets) |
| `add_image` | `path`, `sheet`, `image_path`, optional `cell` (default `A1`), `width`, `height` |
| `set_metadata` | `path`, `metadata` — only the fields given are changed |
| `verify_cell` | `path`, `sheet`, `cell`, `expected` |
| `verify_workbook` | `path`, `expected: {sheets: [{name, headers, rows}]}` |
| `verify_exists` | `path` |

### `word`

| Action | Arguments |
| --- | --- |
| `create_document` | `output_path`, `elements`, optional `metadata` |
| `append_elements` | `path`, `elements`, optional `output_path`, `metadata` |
| `replace_text` | `path`, `replacements: {"{{placeholder}}": "value"}`, optional `output_path` |
| `append_image` | `path`, `image_path`, optional `output_path`, `caption`, `width_inches` |
| `set_metadata` | `path`, `metadata` — only the fields given are changed |
| `read_table` | `path`, optional `table` index (default 0), `header_row` (default 1), `max_rows` |
| `inspect` | `path` — paragraphs, tables and metadata |
| `export_text` | `path`, optional `output_path` (default: same name `.txt`), `include_tables` |
| `verify_document` | `path`, `expected: {paragraphs, tables}` |

`word.read_table` returns the same `headers` / `rows` / `row_count` fields
as `excel.read_table` (both use one shared table shaper), so a DOCX table can
feed an XLSX, CSV, Markdown or Word output directly. Merged cells repeat
their text in every covered column.

Element types for `create_document` and `append_elements`:

| Element | Fields |
| --- | --- |
| `heading` | `text`, `level` |
| `paragraph` | `text` |
| `table` | `headers`, `rows` |
| `bullet_list` / `numbered_list` | `items` |
| `page_break` | — |

`replace_text` fills DOCX templates: placeholders are replaced across a
paragraph's runs, including inside table cells, so text Word split while
typing still matches. The replacement takes the first run's formatting; a
placeholder that spans two differently formatted runs loses that mixed
formatting.

### `screenshot`

Renders a DOCX or XLSX to a PNG preview. It draws from the parsed file, so it
works without Word, Excel or LibreOffice, including in the standalone
executable. Fonts and pagination are approximations, not a pixel-exact print.

| Action | Arguments |
| --- | --- |
| `document` | `path`, `output_path` (`.png`), optional `scale` (default 1) |
| `workbook` | `path`, `output_path` (`.png`), optional `sheet`, `scale`, `max_rows` (40), `max_columns` (12) |

Use it for visual evidence in a job, then attach the PNG with
`word.append_image` or `excel.add_image`:

```yaml
  - id: preview
    tool: screenshot
    action: document
    arguments:
      path: output/report.docx
      output_path: evidence/report.png

  - id: attach
    tool: word
    action: append_image
    arguments:
      path: output/report.docx
      image_path: evidence/report.png
      caption: Report preview
      width_inches: 4
```

### `text`

| Action | Arguments |
| --- | --- |
| `write` | `output_path`, plus one of `headers` + `rows`, `data`, `lines`, `content`; optional `mode: append`, `delimiter` |
| `read` | `path` |
| `verify` | `path`, optional `expected_text`, `expected_contains` |

Output format follows the extension: `.csv` (comma separated), `.tsv`/`.txt`
(tab separated), `.md` (Markdown table), `.json` (records), any other text
suffix (raw content).

### `table`

In-memory transforms; pass `headers: $step.headers` and `rows: $step.rows`.

| Action | Arguments |
| --- | --- |
| `filter` | `column`, `op`, `value` |
| `sort` | `column`, optional `descending` |
| `select` | `columns` |
| `aggregate` | `column`, `op` (`sum`, `count`, `mean`, `min`, `max`), optional `group_by` |
| `limit` | `limit`, optional `offset` |

Filter operators: `==`, `!=`, `>`, `>=`, `<`, `<=`, `contains`,
`starts_with`, `ends_with`, `in`, `not_in`, `is_empty`, `not_empty`.
Comparisons are numeric when both sides are numbers, case-insensitive text
otherwise.

### `filesystem`

| Action | Arguments |
| --- | --- |
| `list_files` | `path` |
| `copy_file` | `path`, `destination_path`, optional `overwrite` |

## Document metadata

Every DOCX and XLSX the agent creates carries document properties, so the
files are not anonymous:

| Field | Default |
| --- | --- |
| `author` | `Office Automation Agent` |
| `last_modified_by` | same as `author` |
| `title`, `subject`, `keywords`, `category`, `comments` | empty |
| `created`, `modified` | left to the file library (ISO 8601 accepted) |

Change them, from most to least specific:

1. **A step's arguments** — `metadata: {author: Ana}` inside `arguments`.
2. **A step's `metadata` key** — beside `tool` and `action`.
3. **A job-level `metadata` block** — applies to every step that supports it.
4. **`OFFICE_AGENT_AUTHOR`** — environment variable, overrides the author default.
5. **`DEFAULT_METADATA`** in `agent/metadata.py` — the built-in defaults.

```yaml
metadata:
  author: Sales Operations
  title: Monthly sales pack
  keywords: sales, report

steps:
  - id: report
    tool: word
    action: create_document
    metadata:
      title: Monthly report   # wins over the job-level title
    arguments:
      output_path: output/report.docx
      elements: []
```

`word.set_metadata` and `excel.set_metadata` update an existing file and
change only the fields you name; `word.inspect` and `excel.inspect` report
the current values. Steps that append to an existing document leave its
metadata alone unless the step supplies `metadata`.

## Tests

The suite uses the standard library `unittest` module; no extra
installation is needed.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

It covers spec parsing (fenced and plain YAML, JSON, smart quotes,
plan defaults and rejections), the validation guards (path escapes,
input modification, forward references, unknown tools), DOCX table
reading, and full job runs driven by a DOCX instruction — including
a DOCX table feeding an XLSX and a CSV output, plus a job that reads
text, appends to a document, renders a screenshot and attaches it.

`tests/test_actions.py` has one test per advertised tool action, plus a
meta-test that fails when an action has no test or is not wired into the
tool's `run()`.

## Standalone executable

`build_exe.py` freezes the agent into a single file with PyInstaller:

```bash
.venv/bin/pip install pyinstaller
.venv/bin/python build_exe.py
```

| Platform | Artifact |
| --- | --- |
| Windows | `dist/office-agent.exe` |
| Linux / macOS | `dist/office-agent` |

PyInstaller does not cross-compile, so the Windows `.exe` has to be
built on Windows. Without a Windows machine, run the
`.github/workflows/build-exe.yml` workflow on GitHub and download the
`office-agent-windows` artifact. The frozen binary needs no Python
installation on the target machine:

```bat
office-agent.exe init jobs\my-job
office-agent.exe jobs\my-job
office-agent.exe tools
```

## Project layout

```
run.py               CLI: run, init, tools
agent/
  spec.py            instruction parsing, plan building, path resolution
  dataflow.py        $step.field reference resolution
  runtime.py         job orchestration, plan validation, output reporting
  executor.py        step execution, state and logging
  instructions.py    DOCX/TXT reading
  ai_config.py       AI provider presets, config/.env writer, connection check
  planner.py, llm.py, llm_factory.py   AI planning (opt-in)
  metadata.py        document metadata defaults, resolution and application
tools/
  excel.py, word.py, text.py, table.py, filesystem.py, screenshot.py
  render.py          DOCX/XLSX to PNG rendering for screenshots
  tabular.py         shared table validation and rendering
tests/
  test_spec.py       spec parsing and plan building
  test_validation.py plan validation rejections
  test_word_table.py DOCX table reading
  test_job_run.py    full job run: DOCX instruction and table to outputs
  test_actions.py    one test per advertised action, plus an evidence job
  test_cli.py        CLI entry points and back-compatible job argument
  test_ai.py         LLM client, provider presets, config, AI planning
  test_planner_prompt.py  planner prompt covers every tool action
examples/
  build_examples.py  rebuild the example job inputs and instruction
  sales-pack/        ready-to-run example job
officeagent.spec     PyInstaller recipe
build_exe.py         build the standalone executable
```

## AI planning (optional)

The deterministic path never touches the network. A model is used only when
the instruction has no job spec:

| Instruction | `run` behaviour |
| --- | --- |
| Contains a YAML/JSON spec | Spec is used; AI is not contacted |
| Plain prose, provider configured | AI plans it |
| Plain prose, no provider | Fails with setup instructions |
| `--no-ai` | AI is never used |
| `--ai` | AI plans it, spec or not |

### One-time setup

```bash
python run.py ai setup
```

| `--provider` | Endpoint | Key needed |
| --- | --- | --- |
| `openai` | `https://api.openai.com/v1` | yes |
| `gemini` | Gemini OpenAI-compatible endpoint | yes |
| `openrouter` | `https://openrouter.ai/api/v1` | yes |
| `ollama` | `http://localhost:11434/v1` | no (local) |
| `custom` | any OpenAI-compatible URL | depends |

The key comes from `LLM_API_KEY` in the environment or a hidden prompt; it is
written to `config/.env` (gitignored), never into a job folder. `ai` status
never prints it. Providers that need no key (Ollama) are saved with an empty
key — an ambient `LLM_API_KEY` is not copied into their config. Override
presets with `--base-url` and `--model`.

### Local model, no account

```bash
ollama serve
ollama pull qwen2.5:3b
python run.py ai setup --provider ollama
```

No model weights ship with this project (they are far larger than the
executable). Local models come from Ollama, or LM Studio / llama.cpp through
`--provider custom --base-url ...`.

### Check and use

```bash
python run.py ai                        # status
python run.py ai test                   # one tiny request
python run.py run jobs/my-job           # spec if present, else AI
python run.py run jobs/my-job --ai      # force the model
python run.py run jobs/my-job --no-ai   # never use a model
```

What is sent: the instruction text plus the input inventory (file names,
sizes, worksheet headers and sample rows). Files stay on your machine.

### Model notes

Small local models (3B–8B) handle these plans well because the prompt gives
the exact tool catalogue and JSON shape. If a model returns a plan that names
an unknown tool, the validator rejects it before anything runs.
