from __future__ import annotations

import json
from pathlib import Path

from agent.dataflow import iter_references
from agent.executor import Executor
from agent.instruction_loader import load_instruction
from agent.job import (
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
from agent.models import JobInstruction, JobPlan, JobState
from agent.registry import ToolRegistry
from agent.spec import (
    SpecError,
    build_plan_from_text,
    resolve_job_paths,
)


# Actions that create a new user-facing file.
WRITE_ACTIONS: dict[tuple[str, str], str] = {
    ("word", "create_document"): "output_path",
    ("word", "export_text"): "output_path",
    ("excel", "create_workbook"): "output_path",
    ("text", "write"): "output_path",
    ("filesystem", "copy_file"): "destination_path",
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


class PlanValidationError(RuntimeError):
    """Raised when a plan would touch files or tools it must not."""


class AgentRuntime:
    """Runs one job directory: instruction in, generated files out."""

    def __init__(
        self,
        job_path: Path,
        registry: ToolRegistry,
    ) -> None:
        self.job_path = create_job(job_path)

        self.job_id = make_job_id(self.job_path)

        self.registry = registry

        self.logger = JobLogger(
            self.job_path / "run.log"
        )

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    def find_instruction(self) -> Path:
        return find_instruction_file(self.job_path)

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

        A structured job spec in the instruction always wins. Without a
        spec, use_ai=True forces the AI planner, use_ai=False forbids it,
        and use_ai=None uses AI only when a provider is configured.
        """

        if llm is not None:
            return self._create_llm_plan(instruction, llm)

        self.logger.log(
            "SPEC",
            "Parsing job spec from the instruction document",
        )

        try:
            plan = build_plan_from_text(
                instruction.text,
                self.job_path,
                source=instruction.source_file,
            )
        except SpecError:
            if use_ai is False:
                raise

            llm = try_create_llm()

            if llm is None:
                raise

            settings = resolve_settings()

            self.logger.log(
                "PLANNER",
                "No job spec found; planning with the AI model "
                f"({settings['provider']}/"
                f"{settings['model']})",
            )

            return self._create_llm_plan(instruction, llm)

        self._log_plan(plan)

        return plan

    def _create_llm_plan(
        self,
        instruction: JobInstruction,
        llm,
    ) -> JobPlan:
        from agent.planner import Planner

        context = self._build_context()

        self.logger.log("PLANNER", "Creating plan with LLM")

        plan = Planner(llm).create_plan(
            instruction.text,
            context=context,
        )

        # Models produce job-relative paths, exactly like specs do.
        for step in plan.steps:
            step.arguments = resolve_job_paths(
                step.arguments,
                self.job_path,
            )

        self._log_plan(plan)

        return plan

    def _build_context(self) -> dict:
        """Inventory inputs for the LLM planner (AI configuration later)."""

        self.logger.log(
            "FILES",
            "Discovering job input files",
        )

        filesystem = self.registry.get("filesystem")

        inventory = filesystem.run(
            "list_files",
            {
                "path": str(self.job_path / "inputs"),
            },
        )

        if not inventory.success:
            raise RuntimeError(
                inventory.error
                or "Could not inspect job inputs."
            )

        files = inventory.data.get("files", [])

        self.logger.log(
            "FILES",
            f"Discovered {len(files)} input files",
        )

        excel_observations = []

        for file in files:
            if file["type"] != "excel":
                continue

            result = self.registry.get("excel").run(
                "inspect",
                {"path": file["path"]},
            )

            if not result.success:
                raise RuntimeError(
                    f"Could not inspect {file['name']}: "
                    f"{result.error}"
                )

            excel_observations.append(
                {
                    "file": file,
                    "inspection": result.data,
                }
            )

        return {
            "job_root": str(self.job_path),
            "inputs_dir": str(self.job_path / "inputs"),
            "output_dir": str(self.job_path / "output"),
            "evidence_dir": str(self.job_path / "evidence"),
            "input_files": files,
            "excel_observations": excel_observations,
        }

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

                if action in EVIDENCE_ACTIONS:
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

            raw_evidence = step.arguments.get("evidence_path")

            if raw_evidence:
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

    def execute(self, plan: JobPlan) -> JobState:
        self.logger.log("EXECUTOR", "Starting execution")

        state = Executor(
            self.registry,
            self.job_path,
        ).execute(plan, self.job_id)

        self.logger.log(
            "EXECUTOR",
            f"Execution finished: {state.status.value}",
        )

        return state

    def run(self, use_ai: bool | None = None) -> JobState:
        llm = None

        if use_ai is True:
            llm = create_llm()

        return self._run_with(llm, use_ai=use_ai)

    def _run_with(
        self,
        llm,
        use_ai: bool | None = None,
    ) -> JobState:

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

        state = self.execute(plan)

        for path in self.output_files(state):
            self.logger.log("OUTPUT", path)

        report = self.write_report(plan, state)

        self.logger.log("REPORT", f"Wrote {report.name}")

        self.logger.log(
            "ORCHESTRATOR",
            f"Job finished: {state.status.value}",
        )

        return state

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

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


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False

    return True
