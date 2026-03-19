"""Workflow engine for orchestrating multi-step sub-agent pipelines.

Reads JSON workflow definitions and executes steps sequentially (chain),
in parallel (parallel), or conditionally (conditional), passing data
between steps via an in-memory context dictionary.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class WorkflowEngine:
    """Parse a JSON workflow definition and execute its steps using sub-agents."""

    _MAX_SUBAGENT_ITERATIONS = 15

    def __init__(self, workflow_path: str | Path):
        path = Path(workflow_path)
        with open(path, "r", encoding="utf-8") as f:
            self.definition: dict[str, Any] = json.load(f)
        self.context: dict[str, str] = {}

    @property
    def name(self) -> str:
        return self.definition.get("name", "Unnamed Workflow")

    @property
    def description(self) -> str:
        return self.definition.get("description", "")

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self.definition.get("steps", [])

    # ------------------------------------------------------------------
    # Template rendering
    # ------------------------------------------------------------------

    _VAR_PATTERN = re.compile(r"\{\{(.+?)\}\}")

    def render_prompt(self, template: str) -> str:
        """Replace ``{{key}}`` placeholders with values from *context*."""

        def _replace(match: re.Match) -> str:
            key = match.group(1).strip()
            return str(self.context.get(key, match.group(0)))

        return self._VAR_PATTERN.sub(_replace, template)

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    async def _run_subagent_step(
        self,
        step: dict[str, Any],
        subagent_manager: "SubagentManager",
    ) -> str:
        """Spawn a sub-agent for *step* and wait for its result.

        Uses a lightweight direct execution approach: builds a temporary
        sub-agent loop that returns its final text output.
        """
        step_id = step["step_id"]
        role = step.get("agent_role", "Assistant")
        raw_prompt = step["prompt_template"]
        final_prompt = self.render_prompt(raw_prompt)
        timeout = step.get("timeout", 60)

        logger.info("Workflow step [{}] starting (role={})", step_id, role)

        role_instruction = f"You are acting as: {role}.\n\n"
        full_prompt = role_instruction + final_prompt

        result = await self._execute_subagent(
            subagent_manager, step_id, full_prompt, timeout
        )

        logger.info("Workflow step [{}] completed", step_id)
        return result

    async def _execute_subagent(
        self,
        manager: "SubagentManager",
        step_id: str,
        prompt: str,
        timeout: int,
    ) -> str:
        """Run a sub-agent directly (without the message-bus announcement).

        This gives the workflow engine synchronous control over the result
        instead of relying on an async bus message.
        """
        from nanobot.agent.skills import BUILTIN_SKILLS_DIR
        from nanobot.agent.tools.filesystem import (
            EditFileTool,
            ListDirTool,
            ReadFileTool,
            WriteFileTool,
        )
        from nanobot.agent.tools.registry import ToolRegistry
        from nanobot.agent.tools.shell import ExecTool
        from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
        from nanobot.utils.helpers import build_assistant_message

        tools = ToolRegistry()
        allowed_dir = manager.workspace if manager.restrict_to_workspace else None
        extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None
        tools.register(
            ReadFileTool(
                workspace=manager.workspace,
                allowed_dir=allowed_dir,
                extra_allowed_dirs=extra_read,
            )
        )
        tools.register(WriteFileTool(workspace=manager.workspace, allowed_dir=allowed_dir))
        tools.register(EditFileTool(workspace=manager.workspace, allowed_dir=allowed_dir))
        tools.register(ListDirTool(workspace=manager.workspace, allowed_dir=allowed_dir))
        tools.register(
            ExecTool(
                working_dir=str(manager.workspace),
                timeout=manager.exec_config.timeout,
                restrict_to_workspace=manager.restrict_to_workspace,
                path_append=manager.exec_config.path_append,
            )
        )
        tools.register(WebSearchTool(config=manager.web_search_config, proxy=manager.web_proxy))
        tools.register(WebFetchTool(proxy=manager.web_proxy))

        system_prompt = manager._build_subagent_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        max_iterations = self._MAX_SUBAGENT_ITERATIONS
        final_result: str | None = None

        async def _loop() -> str:
            nonlocal final_result
            for _ in range(max_iterations):
                response = await manager.provider.chat_with_retry(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=manager.model,
                )

                if response.has_tool_calls:
                    tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
                    messages.append(
                        build_assistant_message(
                            response.content or "",
                            tool_calls=tool_call_dicts,
                            reasoning_content=response.reasoning_content,
                            thinking_blocks=response.thinking_blocks,
                        )
                    )
                    for tool_call in response.tool_calls:
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.name,
                                "content": result,
                            }
                        )
                else:
                    final_result = response.content
                    break

            return final_result or "Step completed but no final response was generated."

        try:
            return await asyncio.wait_for(_loop(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Workflow step [{}] timed out after {}s", step_id, timeout)
            return f"Step '{step_id}' timed out after {timeout} seconds."

    # ------------------------------------------------------------------
    # Conditional evaluation
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_condition(condition: str, text: str) -> bool:
        """Evaluate a simple condition string against *text*.

        Supported forms:
        - ``contains: 'keyword'`` / ``contains: "keyword"``
        """
        if "contains:" in condition:
            keyword = condition.split("contains:", 1)[1].strip().strip("'\"")
            return keyword in text
        return True

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    async def execute_step(
        self,
        step: dict[str, Any],
        subagent_manager: "SubagentManager",
    ) -> None:
        """Execute a single workflow step, respecting its *mode*."""
        step_id = step["step_id"]
        mode = step.get("mode", "chain")

        # Conditional gate
        if mode == "conditional":
            condition = step.get("condition", "")
            if condition:
                previous_values = list(self.context.values())
                last_output = previous_values[-1] if previous_values else ""
                if not self._evaluate_condition(condition, last_output):
                    logger.info("Skipping step [{}] (condition not met)", step_id)
                    self.context[f"{step_id}.output"] = ""
                    return

        try:
            output = await self._run_subagent_step(step, subagent_manager)
            self.context[f"{step_id}.output"] = output
        except Exception as e:
            if step.get("error_handling") == "continue":
                logger.warning("Step [{}] failed but continuing: {}", step_id, e)
                self.context[f"{step_id}.output"] = f"Error (skipped): {e}"
            else:
                raise

    async def run(
        self,
        initial_input: str,
        subagent_manager: "SubagentManager",
    ) -> str:
        """Execute the full workflow pipeline.

        Args:
            initial_input: The user-supplied input injected as ``{{input_topic}}``.
            subagent_manager: A :class:`SubagentManager` used to spawn sub-agents.

        Returns:
            The output of the last step in the pipeline.
        """
        self.context = {"input_topic": initial_input}

        # Group consecutive parallel steps for fan-out
        i = 0
        steps = self.steps
        while i < len(steps):
            step = steps[i]
            if step.get("mode") == "parallel":
                # Collect consecutive parallel steps
                parallel_group: list[dict[str, Any]] = []
                while i < len(steps) and steps[i].get("mode") == "parallel":
                    parallel_group.append(steps[i])
                    i += 1
                # Execute in parallel
                await asyncio.gather(
                    *(self.execute_step(s, subagent_manager) for s in parallel_group)
                )
            else:
                await self.execute_step(step, subagent_manager)
                i += 1

        # Return the last output
        if self.context:
            values = list(self.context.values())
            return values[-1] if values else ""
        return ""
