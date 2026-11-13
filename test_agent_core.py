from agent.executor import Executor
def test_executor(self):
    from pathlib import Path
    import tempfile

    plan = JobPlan(
        goal="List files",
        steps=[
            PlanStep(
                id="step_1",
                description="List files",
                tool="filesystem",
                action="list_files",
                arguments={"path": "."},
            )
        ],
    )

    with tempfile.TemporaryDirectory() as temp_dir:

        executor = Executor(
            self.registry,
            Path(temp_dir),
        )

        state = executor.execute(
            plan,
            job_id="test-job",
        )

        self.assertEqual(
            state.status,
            StepStatus.SUCCESS,
        )

        self.assertTrue(
            (Path(temp_dir) / "state.json").exists()
        )

        self.assertTrue(
            (Path(temp_dir) / "run.log").exists()
        )