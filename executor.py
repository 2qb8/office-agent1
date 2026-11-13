from __future__ import annotations

from pathlib import Path

from agent.logger import JobLogger
from agent.models import (
    JobPlan,
    JobState,
    StepStatus,
    ToolResult,
)
from agent.registry import ToolRegistry
from agent.state import save_state


class Executor:

    def __init__(
        self,
        registry: ToolRegistry,
        job_directory: Path,
    ):
        self.registry = registry
        self.job_directory = job_directory

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

        save_state(
            state,
            self.state_file,
        )


        for step in plan.steps:

            missing_dependencies = [
                dependency
                for dependency in step.depends_on
                if dependency not in state.completed_steps
            ]

            if missing_dependencies:

                error = (
                    "Missing dependencies: "
                    + ", ".join(
                        missing_dependencies
                    )
                )

                step.status = StepStatus.FAILED
                step.error = error

                state.failed_steps.append(
                    step.id
                )

                state.status = StepStatus.FAILED

                self.logger.log(
                    "EXECUTOR",
                    f"{step.id} failed: {error}",
                )

                save_state(
                    state,
                    self.state_file,
                )

                return state

            state.current_step = step.id
            step.status = StepStatus.RUNNING

            save_state(
                state,
                self.state_file,
            )

            self.logger.log(
                "EXECUTOR",
                f"{step.id} started: "
                f"{step.description}",
            )

            try:

                tool = self.registry.get(
                    step.tool
                )

                self.logger.log(
                    step.tool.upper(),
                    f"Action: {step.action}",
                )

                result: ToolResult = tool.run(
                    step.action,
                    step.arguments,
                )

                state.results[
                    step.id
                ] = result

                step.result = result.data

                if result.success:

                    step.status = StepStatus.SUCCESS

                    state.completed_steps.append(
                        step.id
                    )

                    self.logger.log(
                        step.tool.upper(),
                        f"{step.id} succeeded: "
                        f"{result.message}",
                    )

                else:

                    step.status = StepStatus.FAILED
                    step.error = result.error

                    state.failed_steps.append(
                        step.id
                    )

                    state.status = StepStatus.FAILED

                    self.logger.log(
                        step.tool.upper(),
                        f"{step.id} failed: "
                        f"{result.error}",
                    )

                    save_state(
                        state,
                        self.state_file,
                    )

                    return state

            except Exception as exc:

                error = str(exc)

                step.status = StepStatus.FAILED
                step.error = error

                state.failed_steps.append(
                    step.id
                )

                state.results[
                    step.id
                ] = ToolResult(
                    success=False,
                    error=error,
                )

                state.status = StepStatus.FAILED

                self.logger.log(
                    "EXECUTOR",
                    f"{step.id} crashed: {error}",
                )

                save_state(
                    state,
                    self.state_file,
                )

                return state

            save_state(
                state,
                self.state_file,
            )

        state.current_step = None
        state.status = StepStatus.SUCCESS

        save_state(
            state,
            self.state_file,
        )

        self.logger.log(
            "ORCHESTRATOR",
            f"Job completed: {job_id}",
        )

        return state