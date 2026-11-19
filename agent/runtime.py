from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agent.dataflow import iter_references
from agent.executor import Executor
from agent.instruction_loader import load_instruction
from agent.job import (
    brief_candidates,
    create_job,
    find_instruction_file,
    make_job_id,
)
from agent.llm_factory import (
    create_llm,
    resolve_settings,
    try_create_llm,
)
from agent.logger import JobLogger
from agent.models import (
    JobInstruction,
    JobPlan,
    JobState,
    StepStatus,
)
from agent.planfile import fingerprint, load_plan, save_plan
from agent.profile import profile_packet
from agent.registry import ToolRegistry
from agent.spec import (
    SpecError,
    build_plan_from_text,
    relativize_job_paths,
    resolve_job_paths,
)


# Actions that create a new user-facing file.
WRITE_ACTIONS: dict[tuple[str, str], str] = {
    ("word", "create_document"): "output_path",
    ("word", "export_text"): "output_path",
    ("excel", "create_workbook"): "output_path",
    ("text", "write"): "output_path",
    ("filesystem", "copy_file"): "destination_path",
    ("filesystem", "work_on_copy"): "output_path",
    ("screenshot", "document"): "output_path",
    ("screenshot", "workbook"): "output_path",
}

# These write files that may live in either output/ or evidence/.
EVIDENCE_ACTIONS: set[tuple[str, str]] = {
    ("screenshot", "document"),
    ("screenshot", "workbook"),
}

# Actions that change an existing file. These may only touch output/.
MODIFY_ACTIONS: set[tuple[str, str]] = {
    ("excel", "set_cell"),
    ("excel", "set_range_values"),
    ("excel", "format_header"),
    ("excel", "append_rows"),
    ("excel", "merge_cells"),
    ("excel", "autofit"),
    ("excel", "add_image"),
    ("excel", "set_metadata"),
    ("word", "append_elements"),
    ("word", "replace_text"),
    ("word", "append_image"),
    ("word", "set_metadata"),
}


# The extension each writing action can produce. A plan that sends a .md
# path to the Word tool is wrong before it runs, and saying so here costs
# nothing where the same mistake costs a whole run later.
WRITE_SUFFIXES: dict[tuple[str, str], set[str]] = {
    ("word", "create_document"): {".docx"},
    ("word", "export_text"): {".txt"},
    ("excel", "create_workbook"): {".xlsx", ".xlsm"},
    ("text", "write"): {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".tsv",
        ".json",
        ".yaml",
        ".yml",
        ".log",
    },
    ("screenshot", "document"): {".png"},
    ("screenshot", "workbook"): {".png"},
}


# How many times a failed step is sent back to the planner before the run
# is left failed. Two corrections is enough for a wrong column or sheet
# name, and it bounds what one broken brief can cost.
MAX_REPAIRS = 2

# Failures worth sending back: the plan named something that is not there.
# Anything else (a permission error, a full disk, a broken file) is not a
# planning mistake, and asking again would only spend tokens.
REPAIRABLE_ERRORS = (
    "not found",
    "does not exist",
    "no such file",
    "unknown column",
    "unknown sheet",
    "unknown action",
    # A tool argument the model invented: table.filter(op="is"),
    # table.aggregate(op="empty").
    "unknown comparison",
    "unknown aggregation",
    "no such action",
    "missing required argument",
    # A tool handed the wrong file type: the plan has the wrong writer.
    "expected .xlsx",
    "expected .xlsm",
    "expected .docx",
    "expected .csv",
    "output must be",
)


class PlanValidationError(RuntimeError):
    """Raised when a plan would touch files or tools it must not."""


class AgentRuntime:
    """Runs one job directory: instruction in, generated files out."""

    def __init__(
        self,
        job_path: Path,
        registry: ToolRegistry,
        instruction_path: Path | None = None,
    ) -> None:
        self.instruction_path = (
            Path(instruction_path).expanduser().resolve()
            if instruction_path is not None
            else None
        )

        self.job_path = create_job(
            job_path,
            self.instruction_path,
        )

        self.job_id = make_job_id(self.job_path)

        self.registry = registry

        self.logger = JobLogger(
            self.job_path / "run.log"
        )

        self._profile: dict | None = None
        self._instruction: Path | None = None

        # Where the plan came from, and every correction made to it.
        self.plan_source = "unknown"
        self.revisions: list[dict] = []

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    def find_instruction(self) -> Path:
        if self.instruction_path is not None:
            return self.instruction_path

        if self._instruction is not None:
            return self._instruction

        candidates = brief_candidates(self.job_path)

        chosen = find_instruction_file(self.job_path)

        self._instruction = chosen

        if len(candidates) > 1:
            others = ", ".join(
                path.name
                for path in candidates
                if path != chosen
            )

            self.logger.log(
                "INSTRUCTION",
                f"Using {chosen.name} as the brief; "
                f"the rest of the packet: {others}",
            )

        return chosen

    def read_instruction(self) -> JobInstruction:
        instruction_file = self.find_instruction()

        self.logger.log(
            "INSTRUCTION",
            f"Reading {instruction_file.name}",
        )

        instruction = load_instruction(instruction_file)

        self.logger.log(
            "INSTRUCTION",
            (
                f"Loaded {instruction.word_count} words, "
                f"{instruction.character_count} characters"
            ),
        )

        return instruction

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def create_plan(
        self,
        instruction: JobInstruction,
        llm=None,
        use_ai: bool | None = None,
    ) -> JobPlan:
        """
        Build the plan for a job.

        A plan saved beside the brief wins for as long as the packet is
        unchanged. Otherwise a job spec written into the instruction is
        used as-is, and a prose brief is planned from its text and the
        packet profile. use_ai=True always asks the model, use_ai=False
        never does.
        """

        if llm is not None:
            return self._create_llm_plan(instruction, llm)

        profile = self.profile()

        if use_ai is not True:
            saved, note, source = load_plan(
                self.job_path,
                fingerprint(profile),
            )

            self.logger.log("PLANNER", note)

            if saved is not None:
                self.plan_source = source or "saved"
                self._log_plan(saved)

                return saved

        self.logger.log(
            "SPEC",
            "Looking for a job spec in the brief",
        )

        try:
            plan = build_plan_from_text(
                instruction.text,
                self.job_path,
                source=instruction.source_file,
            )
            self.plan_source = "spec"
            self.save_plan(plan, "spec")

        except SpecError:
            if use_ai is False:
                raise

            llm = try_create_llm()

            if llm is None:
                raise

            settings = resolve_settings()

            self.logger.log(
                "PLANNER",
                "The brief is prose; planning from it with "
                f"{settings['provider']}/{settings['model']}",
            )

            return self._create_llm_plan(
                instruction,
                llm,
                profile,
            )

        self._log_plan(plan)

        return plan

    def _create_llm_plan(
        self,
        instruction: JobInstruction,
        llm,
        profile: dict | None = None,
    ) -> JobPlan:
        from agent.planner import Planner

        context = (
            profile if profile is not None else self.profile()
        )

        self.logger.log("PLANNER", "Creating plan with LLM")

        self.plan_source = "api"

        plan = Planner(llm).create_plan(
            instruction.text,
            profile=context,
        )

        # Models produce job-relative paths, exactly like specs do.
        for step in plan.steps:
            step.arguments = resolve_job_paths(
                step.arguments,
                self.job_path,
            )

        self.save_plan(
            plan,
            "api",
            model=getattr(llm, "model", None),
        )

        self._log_plan(plan)

        return plan

    def save_plan(
        self,
        plan: JobPlan,
        source: str,
        model: str | None = None,
    ) -> None:
        """Keep the plan beside the brief so the packet can be replayed.

        A failure here only costs repeatability, so it is logged and never
        fails the run.
        """

        try:
            path = save_plan(
                self.job_path,
                plan,
                fingerprint(self.profile()),
                source=source,
                model=model,
                revisions=self.revisions,
            )
        except Exception as exc:
            self.logger.log(
                "PLANNER",
                f"Could not save the plan: {exc}",
            )
            return

        self.logger.log("PLANNER", f"Saved the plan to {path.name}")

    def profile(self) -> dict:
        """What the planner sees of the packet, and what plans are keyed on.

        Built once per run: every file in inputs/ plus any file sitting
        beside the brief, described in enough detail to name sheets,
        columns and cells without guessing.
        """

        if self._profile is None:
            self.logger.log(
                "FILES",
                "Profiling the work packet",
            )

            self._profile = profile_packet(
                self.job_path,
                self.find_instruction(),
            )

            totals = self._profile["totals"]

            # Named, not just counted: a file that ended up in the packet
            # by accident is otherwise invisible until a plan looks stale.
            names = ", ".join(
                file["path"] for file in self._profile["files"]
            )

            self.logger.log(
                "FILES",
                f"Profiled {totals['files']} packet files "
                f"({totals['characters']} characters)"
                + (f": {names}" if names else ""),
            )

        return self._profile

    def _log_plan(self, plan: JobPlan) -> None:
        self.logger.log(
            "PLANNER",
            f"Plan '{plan.goal}' has {len(plan.steps)} steps",
        )

        for step in plan.steps:
            self.logger.log(
                "PLANNER",
                f"Step {step.id}: {step.tool}.{step.action}",
            )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_plan(self, plan: JobPlan) -> None:
        """Validate a plan before any tool runs."""

        registered = set(self.registry.list_tools())

        output_dir = (self.job_path / "output").resolve()
        evidence_dir = (self.job_path / "evidence").resolve()
        inputs_dir = (self.job_path / "inputs").resolve()

        seen_ids: list[str] = []

        # Headers each step's result will have, where the plan says enough
        # to know them; used to catch a sort or filter on a column that the
        # aggregate never produced.
        known_headers: dict[str, list[str]] = {}

        for step in plan.steps:

            if not step.id.strip():
                raise PlanValidationError(
                    "Plan validation failed: a step has an empty id."
                )

            if step.id in seen_ids:
                raise PlanValidationError(
                    f"Plan validation failed: duplicate step id "
                    f"'{step.id}'."
                )

            if step.tool not in registered:
                raise PlanValidationError(
                    f"Plan validation failed: step '{step.id}' uses "
                    f"unregistered tool '{step.tool}'. Registered "
                    f"tools: {sorted(registered)}"
                )

            if not step.action.strip():
                raise PlanValidationError(
                    f"Plan validation failed: step '{step.id}' has "
                    "no action."
                )

            supported = getattr(self.registry.get(step.tool), "actions", ())

            if supported and step.action not in supported:
                raise PlanValidationError(
                    f"Plan validation failed: step '{step.id}' uses "
                    f"unknown action '{step.tool}.{step.action}'. "
                    f"{step.tool} has: {', '.join(supported)}"
                )

            if not isinstance(step.arguments, dict):
                raise PlanValidationError(
                    f"Plan validation failed: step '{step.id}' "
                    "arguments must be a mapping."
                )

            action = (step.tool, step.action)

            if action in WRITE_ACTIONS:
                key = WRITE_ACTIONS[action]

                raw_output = step.arguments.get(key)

                if not raw_output:
                    raise PlanValidationError(
                        f"Plan validation failed: step '{step.id}' "
                        f"writes a file but has no '{key}'."
                    )

                if _is_reference(raw_output):
                    # The target comes from an earlier step, whose own
                    # arguments were validated in their turn.
                    pass
                elif action in EVIDENCE_ACTIONS:
                    target = Path(str(raw_output)).resolve()

                    if not (
                        _is_relative_to(target, output_dir)
                        or _is_relative_to(target, evidence_dir)
                    ):
                        raise PlanValidationError(
                            f"Plan validation failed: step "
                            f"'{step.id}' must write inside "
                            f"output/ or evidence/ but uses: "
                            f"{target}"
                        )
                else:
                    self._require_inside(
                        raw_output,
                        output_dir,
                        step,
                        "output/",
                    )

            if action in MODIFY_ACTIONS:
                raw_target = step.arguments.get(
                    "path"
                ) or step.arguments.get("output_path")

                if not raw_target:
                    raise PlanValidationError(
                        f"Plan validation failed: step '{step.id}' "
                        "modifies a file but has no 'path'."
                    )

                if not _is_reference(raw_target):
                    target = Path(str(raw_target)).resolve()

                    self._require_inside(
                        target,
                        inputs_dir,
                        step,
                        "inputs/",
                        forbidden=True,
                    )

                    self._require_inside(
                        target,
                        output_dir,
                        step,
                        "output/",
                    )

            if action in WRITE_SUFFIXES and not _is_reference(raw_output):
                self._require_known_suffix(step, raw_output)

            problem = _unknown_table_column(step, known_headers)

            if problem:
                raise PlanValidationError(
                    f"Plan validation failed: step '{step.id}' {problem}"
                )

            produced = _headers_produced(step, known_headers)

            if produced is not None:
                known_headers[step.id] = produced

            raw_evidence = step.arguments.get("evidence_path")

            if raw_evidence and not _is_reference(raw_evidence):
                self._require_inside(
                    raw_evidence,
                    evidence_dir,
                    step,
                    "evidence/",
                )

            for reference in iter_references(step.arguments):
                if reference not in seen_ids:
                    raise PlanValidationError(
                        f"Plan validation failed: step '{step.id}' "
                        f"references '${reference}', which is not an "
                        "earlier step."
                    )

            for dependency in step.depends_on:
                if dependency not in seen_ids:
                    raise PlanValidationError(
                        f"Plan validation failed: step '{step.id}' "
                        f"depends on '{dependency}', which is not an "
                        "earlier step."
                    )

            seen_ids.append(step.id)

    @staticmethod
    def _require_known_suffix(step, raw_output) -> None:
        suffixes = WRITE_SUFFIXES[(step.tool, step.action)]
        name = Path(str(raw_output)).name

        if Path(name).suffix.lower() in suffixes:
            return

        allowed = " or ".join(sorted(suffixes))

        raise PlanValidationError(
            f"Plan validation failed: step '{step.id}' writes {name} with "
            f"{step.tool}.{step.action}, which writes {allowed}. Send the "
            f"file to the tool that writes that format."
        )

    @staticmethod
    def _require_inside(
        raw_path,
        directory: Path,
        step,
        label: str,
        forbidden: bool = False,
    ) -> None:

        path = Path(str(raw_path)).resolve()

        inside = _is_relative_to(path, directory)

        if forbidden and inside:
            raise PlanValidationError(
                f"Plan validation failed: step '{step.id}' would "
                f"modify a file inside {label}: {path}"
            )

        if not forbidden and not inside:
            raise PlanValidationError(
                f"Plan validation failed: step '{step.id}' must write "
                f"inside {label} but uses: {path}"
            )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        plan: JobPlan,
        progress=None,
        cancel=None,
        resume: JobState | None = None,
    ) -> JobState:
        self.logger.log("EXECUTOR", "Starting execution")

        state = Executor(
            self.registry,
            self.job_path,
            cancel=cancel,
            progress=progress,
        ).execute(plan, self.job_id, resume=resume)

        self.logger.log(
            "EXECUTOR",
            f"Execution finished: {state.status.value}",
        )

        return state

    def run(
        self,
        use_ai: bool | None = None,
        progress=None,
        cancel=None,
    ) -> JobState:
        llm = None

        if use_ai is True:
            llm = create_llm()

        return self._run_with(
            llm,
            use_ai=use_ai,
            progress=progress,
            cancel=cancel,
        )

    def plan(self, use_ai: bool | None = None) -> JobPlan:
        """Read the instruction and build a validated plan, running nothing.

        The window uses this to show the user what is about to happen before
        a single file is written.
        """

        llm = create_llm() if use_ai is True else None

        return self._plan_with(llm, use_ai=use_ai)

    def _plan_with(self, llm, use_ai: bool | None = None) -> JobPlan:
        self.logger.log(
            "ORCHESTRATOR",
            f"Job started: {self.job_id}",
        )

        instruction = self.read_instruction()

        plan = self.create_plan(
            instruction,
            llm=llm,
            use_ai=use_ai,
        )

        self.logger.log(
            "VALIDATOR",
            "Validating generated plan",
        )

        self.validate_plan(plan)

        self.logger.log("VALIDATOR", "Plan validation passed")

        return plan

    def execute_plan(
        self,
        plan: JobPlan,
        progress=None,
        cancel=None,
        repair: bool = True,
    ) -> JobState:
        """Run a plan already built by ``plan()`` and write the report.

        A failure caused by a name that does not exist is sent back to the
        planner for a correction, twice at most, and the run continues from
        the step that failed instead of starting over.
        """

        self.revisions = []

        state = self.execute(plan, progress=progress, cancel=cancel)

        if repair and state.failed_steps:
            plan, state = self._repair(
                plan,
                state,
                progress=progress,
                cancel=cancel,
            )

        for path in self.output_files(state):
            self.logger.log("OUTPUT", path)

        report = self.write_report(plan, state)

        self.logger.log("REPORT", f"Wrote {report.name}")

        self.logger.log(
            "ORCHESTRATOR",
            f"Job finished: {state.status.value}",
        )

        return state

    def _run_with(
        self,
        llm,
        use_ai: bool | None = None,
        progress=None,
        cancel=None,
    ) -> JobState:
        plan = self._plan_with(llm, use_ai=use_ai)

        return self.execute_plan(plan, progress=progress, cancel=cancel)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Repair
    # ------------------------------------------------------------------

    def _repair(
        self,
        plan: JobPlan,
        state: JobState,
        progress=None,
        cancel=None,
    ) -> tuple[JobPlan, JobState]:
        """Ask the planner to correct a plan that failed, then carry on."""

        if self.plan_source not in {"api", "chat"}:
            self.logger.log(
                "PLANNER",
                "Not repairing: this plan was not made by a model",
            )
            return plan, state

        llm = None
        attempts = 0

        while state.failed_steps and attempts < MAX_REPAIRS:
            failed_id = state.failed_steps[-1]
            result = state.results.get(failed_id)
            error = (
                result.error if result is not None else ""
            ) or ""

            step = next(
                (item for item in plan.steps if item.id == failed_id),
                None,
            )

            if step is None or not _is_repairable(error):
                self.logger.log(
                    "PLANNER",
                    f"Not repairing '{failed_id}': "
                    f"{error or 'no error message'}",
                )
                return plan, state

            if llm is None:
                llm = try_create_llm()

                if llm is None:
                    self.logger.log(
                        "PLANNER",
                        "Not repairing: no model is configured to "
                        "revise the plan",
                    )
                    return plan, state

            attempts += 1

            self.logger.log(
                "PLANNER",
                f"Repair attempt {attempts}/{MAX_REPAIRS} after "
                f"'{failed_id}': {error}",
            )

            try:
                revised = self._revise(plan, step, error, llm)
            except Exception as exc:
                self.logger.log(
                    "PLANNER",
                    f"The revision could not be used: {exc}",
                )
                return plan, state

            if not _keeps_completed_steps(revised, state):
                self.logger.log(
                    "PLANNER",
                    "The revision changed steps that already ran; "
                    "keeping the plan as it was",
                )
                return plan, state

            self.revisions.append(
                _revision_record(
                    attempts,
                    failed_id,
                    error,
                    plan,
                    self.job_path,
                )
            )

            self.logger.log(
                "PLANNER",
                f"Running the revised plan "
                f"({len(revised.steps)} steps, {attempts} revision(s))",
            )

            state.failed_steps.clear()
            state.status = StepStatus.RUNNING

            plan = revised

            state = self.execute(
                plan,
                progress=progress,
                cancel=cancel,
                resume=state,
            )

            if _failed_the_same_way(state, failed_id, error):
                self.logger.log(
                    "PLANNER",
                    f"Stopping repairs: the revision failed "
                    f"'{failed_id}' with the same error",
                )
                break

        if self.revisions:
            self.save_plan(plan, self.plan_source)

        return plan, state

    def _revise(
        self,
        plan: JobPlan,
        step,
        error: str,
        llm,
    ) -> JobPlan:
        from agent.planner import Planner

        instruction = self.read_instruction()

        revised = Planner(llm).revise(
            instruction.text,
            plan,
            step,
            error,
            profile=self.profile(),
        )

        for revised_step in revised.steps:
            revised_step.arguments = resolve_job_paths(
                revised_step.arguments,
                self.job_path,
            )

        self.validate_plan(revised)

        return revised

    def write_report(
        self,
        plan: JobPlan,
        state: JobState,
    ) -> Path:
        """Write a machine-readable summary of the run."""

        report_path = self.job_path / "report.json"

        steps = []

        for step in plan.steps:
            result = state.results.get(step.id)

            steps.append(
                {
                    "id": step.id,
                    "description": step.description,
                    "tool": step.tool,
                    "action": step.action,
                    "status": step.status.value,
                    "message": result.message if result else None,
                    "error": step.error,
                }
            )

        report_path.write_text(
            json.dumps(
                {
                    "job_id": state.job_id,
                    "goal": plan.goal,
                    "status": state.status.value,
                    "steps": steps,
                    "completed_steps": state.completed_steps,
                    "failed_steps": state.failed_steps,
                    "revisions": self.revisions,
                    "outputs": self.output_files(state),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        return report_path

    def output_files(self, state: JobState) -> list[str]:
        """Generated files inside output/, in creation order."""

        output_dir = (self.job_path / "output").resolve()

        paths: list[str] = []

        for result in state.results.values():
            raw_path = result.data.get("path")

            if not raw_path:
                continue

            path = Path(str(raw_path)).resolve()

            if not _is_relative_to(path, output_dir):
                continue

            resolved = str(path)

            if resolved not in paths:
                paths.append(resolved)

        return paths


def _headers_reference(value) -> str | None:
    """The step id in "$step.headers", or None for anything else."""

    if not isinstance(value, str):
        return None

    text = value.strip()

    if not text.startswith("$"):
        return None

    step_id, _, field = text[1:].partition(".")

    if field != "headers" or not step_id:
        return None

    return step_id


def _literal_headers(value) -> list[str] | None:
    """A headers argument written out in full, or None."""

    if not isinstance(value, list) or not value:
        return None

    if not all(isinstance(item, str) and not _is_reference(item) for item in value):
        return None

    return [str(item) for item in value]


def _headers_produced(
    step,
    known: dict[str, list[str]],
) -> list[str] | None:
    """The headers this step's result will have, when that is knowable.

    Only table steps are modelled. An aggregate names its own columns, so a
    later step can be checked against them exactly; everything else passes
    its input headers through unchanged.
    """

    if step.tool != "table":
        return None

    arguments = step.arguments or {}

    if step.action == "aggregate":
        column = arguments.get("column")

        if not isinstance(column, str) or _is_reference(column):
            return None

        operation = str(arguments.get("op") or "sum").lower()
        headers = [f"{operation}({column})"]
        group = arguments.get("group_by")

        if isinstance(group, str) and not _is_reference(group):
            headers.insert(0, group)

        return headers

    if step.action == "select":
        return _literal_headers(arguments.get("columns"))

    if step.action in {"filter", "sort", "limit"}:
        source = _headers_reference(arguments.get("headers"))

        if source is not None:
            return known.get(source)

        return _literal_headers(arguments.get("headers"))

    return None


def _unknown_table_column(
    step,
    known: dict[str, list[str]],
) -> str | None:
    """The complaint when a table step names a column it cannot have."""

    if step.tool != "table":
        return None

    arguments = step.arguments or {}
    headers = arguments.get("headers")
    source = _headers_reference(headers)

    if source is not None:
        available = known.get(source)
    else:
        available = _literal_headers(headers)

    if not available:
        return None

    named: list[str] = []

    column = arguments.get("column")

    if isinstance(column, str) and not _is_reference(column):
        named.append(column)

    group = arguments.get("group_by")

    if isinstance(group, str) and not _is_reference(group):
        named.append(group)

    columns = arguments.get("columns")

    if isinstance(columns, list):
        named.extend(
            item
            for item in columns
            if isinstance(item, str) and not _is_reference(item)
        )

    for name in named:
        if name not in available:
            return (
                f"uses column '{name}', which that table does not have. "
                f"Its columns are: {', '.join(available)}"
            )

    return None


def _is_repairable(error: str) -> bool:
    """Is this failure a mistake in the plan rather than in the machine?"""

    text = (error or "").lower()

    return any(hint in text for hint in REPAIRABLE_ERRORS)


def _keeps_completed_steps(plan: JobPlan, state: JobState) -> bool:
    """A revision may only change the part of the plan that has not run."""

    completed = state.completed_steps

    if len(plan.steps) < len(completed):
        return False

    return [
        step.id for step in plan.steps[: len(completed)]
    ] == completed


def _failed_the_same_way(
    state: JobState,
    step_id: str,
    error: str,
) -> bool:
    """Did the revision fail again on the same step with the same message?"""

    if not state.failed_steps or state.failed_steps[-1] != step_id:
        return False

    result = state.results.get(step_id)

    again = (result.error if result is not None else "") or ""

    return again == error


def _revision_record(
    attempt: int,
    step_id: str,
    error: str,
    plan: JobPlan,
    job_path: Path,
) -> dict:
    """What plan.json keeps about one correction."""

    return {
        "attempt": attempt,
        "step": step_id,
        "error": error,
        "created": datetime.now().isoformat(timespec="seconds"),
        "replaced": [
            {
                "id": step.id,
                "description": step.description,
                "tool": step.tool,
                "action": step.action,
                "arguments": relativize_job_paths(
                    step.arguments,
                    job_path,
                ),
                "depends_on": list(step.depends_on),
            }
            for step in plan.steps
        ],
    }


def _is_reference(value) -> bool:
    """A "$step.field" argument, resolved only while the plan runs."""

    return isinstance(value, str) and value.strip().startswith("$")


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False

    return True
