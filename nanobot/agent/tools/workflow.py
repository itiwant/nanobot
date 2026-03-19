"""Tool for running workflow pipelines from the main agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class RunWorkflowTool(Tool):
    """Tool to execute a JSON workflow pipeline via the WorkflowEngine."""

    def __init__(self, manager: "SubagentManager", workflows_dir: Path):
        self._manager = manager
        self._workflows_dir = workflows_dir

    @property
    def name(self) -> str:
        return "run_workflow"

    @property
    def description(self) -> str:
        return (
            "Run a predefined workflow pipeline. Workflows are multi-step processes "
            "defined in JSON files that orchestrate multiple sub-agents in sequence, "
            "parallel, or conditionally. "
            "Use list_dir to browse the workflows/ directory first to see available workflows."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workflow_name": {
                    "type": "string",
                    "description": (
                        "Name of the workflow file (without .json extension) "
                        "located in the workflows/ directory"
                    ),
                },
                "input": {
                    "type": "string",
                    "description": "The input/topic to feed into the workflow pipeline",
                },
            },
            "required": ["workflow_name", "input"],
        }

    async def execute(self, workflow_name: str, input: str, **kwargs: Any) -> str:
        """Load and execute the named workflow."""
        from nanobot.agent.workflow import WorkflowEngine

        # Resolve workflow file
        workflow_file = self._workflows_dir / f"{workflow_name}.json"
        if not workflow_file.exists():
            available = [
                f.stem for f in self._workflows_dir.glob("*.json") if f.is_file()
            ]
            return (
                f"Error: Workflow '{workflow_name}' not found. "
                f"Available workflows: {', '.join(available) or '(none)'}"
            )

        try:
            engine = WorkflowEngine(workflow_file)
            logger.info(
                "Starting workflow '{}' with input: {}",
                engine.name,
                input[:100],
            )
            result = await engine.run(input, self._manager)
            return f"Workflow '{engine.name}' completed.\n\nResult:\n{result}"
        except Exception as e:
            logger.error("Workflow '{}' failed: {}", workflow_name, e)
            return f"Error: Workflow '{workflow_name}' failed: {e}"
