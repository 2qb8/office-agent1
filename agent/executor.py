from __future__ import annotations

from pathlib import Path

from agent.dataflow import ResolutionError, resolve_arguments
from agent.logger import JobLogger
from agent.models import (
    JobPlan,
    JobState,
    PlanStep,
    StepStatus,
    ToolResult,
)
from agent.registry import ToolRegistry
from agent.state import save_state


class Executor:
    """Runs plan steps in order, resolving "$step.field" data references."""

    def __init__(
        self,
        registry: ToolRegistry,
        job_directory: Path,
    ) -> None:
        self.registry = registry

        self.job_directory = Path(job_directory)

        self.job_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.logger = JobLogger(
            self.job_directory / "run.log"
        )

        self.state_file = (
            self.job_directory / "state.json"
        )

    def execute(
        self,
        plan: JobPlan,
        job_id: str,
    ) -> JobState:

        state = JobState(
            job_id=job_id,
            status=StepStatus.RUNNING,
        )

        self._save(state)

        for step in plan.steps:

            missing_dependencies = [
                dependency
                for dependency in step.depends_on
                if dependency not in state.completed_steps
            ]

            if missing_dependencies:
                return self._fail(
                    state,
                    step,
                    "Missing dependencies: "
                    + ", ".join(missing_dependencies),
                )

            state.current_step = step.id
            step.status = StepStatus.RUNNING

            self._save(state)

            self.logger.log(
                "EXECUTOR",
                f"{step.id} started: {step.description}",
            )

            try:
                arguments = resolve_arguments(
                    step.arguments or {},
                    state.results,
                )

                tool = self.registry.get(step.tool)

                self.logger.log(
                    step.tool.upper(),
                    f"Action: {step.action}",
                )

                result: ToolResult = tool.run(
                    step.action,
                    arguments,
                )

            except ResolutionError as exc:
                return self._fail(
                    state,
                    step,
                    f"Could not resolve arguments: {exc}",
                )

            except KeyError as exc:
                return self._fail(state, step, str(exc))

            except Exception as exc:
                return self._fail(
                    state,
                    step,
                    f"{type(exc).__name__}: {exc}",
                )

            state.results[step.id] = result
            step.result = result.data

            if not result.success:
                return self._fail(
                    state,
                    step,
                    result.error
                    or result.message
                    or "Tool reported failure.",
                )

            step.status = StepStatus.SUCCESS

            state.completed_steps.append(step.id)

            self.logger.log(
                step.tool.upper(),
                f"{step.id} succeeded: {result.message}",
            )

            self._save(state)

        state.current_step = None
        state.status = StepStatus.SUCCESS

        self._save(state)

        self.logger.log(
            "ORCHESTRATOR",
            f"Job completed: {job_id}",
        )

        return state

    def _fail(
        self,
        state: JobState,
        step: PlanStep,
        error: str,
    ) -> JobState:

        step.status = StepStatus.FAILED
        step.error = error

        state.failed_steps.append(step.id)
        state.status = StepStatus.FAILED

        state.results.setdefault(
            step.id,
            ToolResult(success=False, error=error),
        )

        self.logger.log(
            "EXECUTOR",
            f"{step.id} failed: {error}",
        )

        self._save(state)

        return state

    def _save(self, state: JobState) -> None:
        save_state(state, self.state_file)
