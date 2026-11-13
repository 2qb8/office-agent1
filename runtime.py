from __future__ import annotations

from pathlib import Path

from agent.executor import Executor
from agent.instruction_loader import load_instruction
from agent.job import create_job, make_job_id
from agent.llm_factory import create_llm
from agent.logger import JobLogger
from agent.models import JobState, JobInstruction
from agent.planner import Planner
from agent.registry import ToolRegistry


class AgentRuntime:

    def __init__(
        self,
        job_path: Path,
        registry: ToolRegistry,
    ):
        self.job_path = create_job(
            job_path
        )

        self.job_id = make_job_id(
            self.job_path
        )

        self.registry = registry

        self.logger = JobLogger(
            self.job_path / "run.log"
        )

    def find_instruction(self) -> Path:

        files = [
            path
            for path in self.job_path.iterdir()
            if (
                path.is_file()
                and path.suffix.lower() == ".docx"
                and path.name.lower()
                != "instruction_template.docx"
            )
        ]

        if len(files) != 1:
            raise RuntimeError(
                "Expected exactly one instruction DOCX, "
                f"found {len(files)}."
            )

        return files[0]

    def read_instruction(
        self,
    ) -> JobInstruction:

        instruction_file = (
            self.find_instruction()
        )

        self.logger.log(
            "INSTRUCTION",
            f"Reading {instruction_file.name}",
        )

        instruction = load_instruction(
            instruction_file
        )

        self.logger.log(
            "INSTRUCTION",
            (
                f"Loaded {instruction.word_count} "
                f"words"
            ),
        )

        return instruction

    def create_plan(
    self,
    instruction: JobInstruction,
    llm=None,
):
        self.logger.log(
            "FILES",
            "Discovering job input files",
        )

        filesystem = self.registry.get("filesystem")

        inventory_result = filesystem.run(
            "list_files",
            {
                "path": str(
                    self.job_path / "inputs"
                )
            },
        )

        if not inventory_result.success:
            raise RuntimeError(
                inventory_result.error
                or "Could not inspect job inputs."
            )

        files = inventory_result.data.get(
            "files",
            [],
        )

        self.logger.log(
            "FILES",
            f"Discovered {len(files)} input files",
        )

        for file in files:
            self.logger.log(
                "FILES",
                f"{file['type']}: {file['name']}",
            )

        excel_observations = []

        for file in files:
            if file["type"] != "excel":
                continue

            self.logger.log(
                "EXCEL",
                f"Inspecting {file['name']} before planning",
            )

            excel_tool = self.registry.get("excel")

            result = excel_tool.run(
                "inspect",
                {
                    "path": file["path"],
                },
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

        context = {
            "job_root": str(self.job_path),
            "inputs_dir": str(self.job_path / "inputs"),
            "output_dir": str(self.job_path / "output"),
            "evidence_dir": str(self.job_path / "evidence"),
            "input_files": files,
            "excel_observations": excel_observations,
        }

        self.logger.log(
            "PLANNER",
            "Creating plan",
        )

        if llm is None:
            llm = create_llm()

        planner = Planner(llm)

        plan = planner.create_plan(
            instruction.text,
            context=context,
        )

        self.logger.log(
            "PLANNER",
            f"Created plan with {len(plan.steps)} steps",
        )

        for step in plan.steps:
            self.logger.log(
                "PLANNER",
                f"Step {step.id}: "
                f"{step.tool}.{step.action}",
            )

        return plan

    def execute(
        self,
        plan,
    ) -> JobState:

        self.logger.log(
            "EXECUTOR",
            "Starting execution",
        )

        executor = Executor(
            self.registry,
            self.job_path,
        )

        state = executor.execute(
            plan,
            self.job_id,
        )

        self.logger.log(
            "EXECUTOR",
            f"Execution finished: {state.status.value}",
        )

        return state

    def validate_plan(self, plan) -> None:
        """Validate an LLM-generated plan before execution."""

        registered_tools = set(self.registry.list_tools())

        output_dir = (self.job_path / "output").resolve()
        evidence_dir = (self.job_path / "evidence").resolve()
        inputs_dir = (self.job_path / "inputs").resolve()

        write_actions = {
            ("word", "create_document"),
            ("excel", "create_workbook"),
            ("excel", "write"),
            ("excel", "modify"),
            ("excel", "set_cell"),
            ("excel", "set_range_values"),
            ("excel", "format_header"),
            }

        for step in plan.steps:

            # 1. Tool must actually exist.
            if step.tool not in registered_tools:
                raise RuntimeError(
                    f"Plan validation failed: "
                    f"step '{step.id}' requires unregistered "
                    f"tool '{step.tool}'. "
                    f"Registered tools: "
                    f"{sorted(registered_tools)}"
                )

            # 2. Basic step requirements.
            if not step.id.strip():
                raise RuntimeError(
                    "Plan validation failed: step has empty id."
                )

            if not step.action.strip():
                raise RuntimeError(
                    f"Plan validation failed: "
                    f"step '{step.id}' has no action."
                )

            # 3. Protect input files.
            arguments = step.arguments or {}

            for key in ("path", "input_path"):
                raw_path = arguments.get(key)

                if not raw_path:
                    continue

                path = Path(str(raw_path)).resolve()

                try:
                    path.relative_to(inputs_dir)
                except ValueError:
                    continue

                if step.action in {
                    "write",
                    "modify",
                    "delete",
                    "create_document",
                    "create_workbook",
                }:
                    raise RuntimeError(
                        f"Plan validation failed: "
                        f"step '{step.id}' attempts to modify "
                        f"an input file: {path}"
                    )

            # 4. User-facing generated files must stay in output/.
            if (step.tool, step.action) in write_actions:

                raw_output = arguments.get("output_path")

                if not raw_output:
                    raise RuntimeError(
                        f"Plan validation failed: "
                        f"step '{step.id}' writes a file but "
                        f"has no output_path."
                    )

                output_path = Path(
                    str(raw_output)
                ).resolve()

                try:
                    output_path.relative_to(output_dir)
                except ValueError:
                    raise RuntimeError(
                        f"Plan validation failed: "
                        f"step '{step.id}' attempts to write "
                        f"outside output/: {output_path}"
                    )

            # 5. Evidence must stay in evidence/.
            if "evidence_path" in arguments:

                evidence_path = Path(
                    str(arguments["evidence_path"])
                ).resolve()

                try:
                    evidence_path.relative_to(evidence_dir)
                except ValueError:
                    raise RuntimeError(
                        f"Plan validation failed: "
                        f"step '{step.id}' attempts to write "
                        f"evidence outside evidence/: "
                        f"{evidence_path}"
                    )

        # 6. Dependencies must refer to real steps.
        step_ids = {step.id for step in plan.steps}

        for step in plan.steps:
            for dependency in step.depends_on:
                if dependency not in step_ids:
                    raise RuntimeError(
                        f"Plan validation failed: "
                        f"step '{step.id}' depends on "
                        f"unknown step '{dependency}'."
                    )

    def run(self) -> JobState:

        self.logger.log(
            "ORCHESTRATOR",
            f"Job started: {self.job_id}",
        )

        instruction = (
            self.read_instruction()
        )

        plan = self.create_plan(instruction)

        self.logger.log(
            "VALIDATOR",
            "Validating generated plan",
        )

        self.validate_plan(plan)

        self.logger.log(
            "VALIDATOR",
            "Plan validation passed",
        )

        state = self.execute(plan)

        self.logger.log(
            "ORCHESTRATOR",
            f"Job finished: {state.status.value}",
        )

        return state
    
    def run_with_llm(
    self,
    llm,
) -> JobState:

        self.logger.log(
            "ORCHESTRATOR",
            f"Job started: {self.job_id}",
        )

        instruction = (
            self.read_instruction()
        )

        plan = self.create_plan(instruction, llm=llm)

        self.logger.log(
            "VALIDATOR",
            "Validating generated plan",
        )

        self.validate_plan(plan)

        self.logger.log(
            "VALIDATOR",
            "Plan validation passed",
        )

        state = self.execute(plan)

        self.logger.log(
            "ORCHESTRATOR",
            (
                f"Job finished: "
                f"{state.status.value}"
            ),
        )

        return state