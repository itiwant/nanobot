"""Tests for the WorkflowEngine and RunWorkflowTool."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow_file(tmp_path: Path, definition: dict) -> Path:
    """Write a JSON workflow definition to a temp file and return the path."""
    wf = tmp_path / "test_workflow.json"
    wf.write_text(json.dumps(definition), encoding="utf-8")
    return wf


def _simple_chain_definition() -> dict:
    return {
        "name": "Test Chain",
        "description": "A simple two-step chain",
        "steps": [
            {
                "step_id": "step1",
                "agent_role": "Researcher",
                "mode": "chain",
                "prompt_template": "Research: {{input_topic}}",
                "timeout": 30,
            },
            {
                "step_id": "step2",
                "agent_role": "Writer",
                "mode": "chain",
                "prompt_template": "Write about: {{step1.output}}",
                "timeout": 30,
            },
        ],
    }


def _conditional_definition(condition: str = "contains: 'keyword'") -> dict:
    return {
        "name": "Conditional Test",
        "description": "Test conditional step skipping",
        "steps": [
            {
                "step_id": "first",
                "agent_role": "Worker",
                "mode": "chain",
                "prompt_template": "Do: {{input_topic}}",
                "timeout": 10,
            },
            {
                "step_id": "conditional_step",
                "agent_role": "Checker",
                "mode": "conditional",
                "condition": condition,
                "prompt_template": "Check: {{first.output}}",
                "timeout": 10,
            },
        ],
    }


def _parallel_definition() -> dict:
    return {
        "name": "Parallel Test",
        "description": "Test parallel execution",
        "steps": [
            {
                "step_id": "para1",
                "agent_role": "Worker A",
                "mode": "parallel",
                "prompt_template": "Task A: {{input_topic}}",
                "timeout": 10,
            },
            {
                "step_id": "para2",
                "agent_role": "Worker B",
                "mode": "parallel",
                "prompt_template": "Task B: {{input_topic}}",
                "timeout": 10,
            },
        ],
    }


def _error_handling_definition() -> dict:
    return {
        "name": "Error Handling Test",
        "description": "Test error_handling: continue",
        "steps": [
            {
                "step_id": "failing_step",
                "agent_role": "Faulty",
                "mode": "chain",
                "prompt_template": "Will fail: {{input_topic}}",
                "error_handling": "continue",
                "timeout": 10,
            },
            {
                "step_id": "next_step",
                "agent_role": "Worker",
                "mode": "chain",
                "prompt_template": "After failure: {{failing_step.output}}",
                "timeout": 10,
            },
        ],
    }


def _make_subagent_manager(tmp_path: Path) -> MagicMock:
    """Create a mock SubagentManager with expected attributes."""
    from nanobot.config.schema import ExecToolConfig, WebSearchConfig

    mgr = MagicMock()
    mgr.provider = MagicMock()
    mgr.provider.get_default_model.return_value = "test-model"
    mgr.workspace = tmp_path
    mgr.model = "test-model"
    mgr.web_search_config = WebSearchConfig()
    mgr.web_proxy = None
    mgr.exec_config = ExecToolConfig()
    mgr.restrict_to_workspace = False
    mgr._build_subagent_prompt.return_value = "You are a subagent."
    return mgr


# ---------------------------------------------------------------------------
# WorkflowEngine unit tests
# ---------------------------------------------------------------------------


class TestWorkflowEngineParsing:
    """Tests for JSON parsing and basic property access."""

    def test_load_workflow(self, tmp_path: Path) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        defn = _simple_chain_definition()
        wf_path = _make_workflow_file(tmp_path, defn)
        engine = WorkflowEngine(wf_path)

        assert engine.name == "Test Chain"
        assert engine.description == "A simple two-step chain"
        assert len(engine.steps) == 2

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            WorkflowEngine(bad_file)

    def test_empty_steps(self, tmp_path: Path) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        defn = {"name": "Empty", "description": "No steps", "steps": []}
        wf_path = _make_workflow_file(tmp_path, defn)
        engine = WorkflowEngine(wf_path)
        assert engine.steps == []


class TestPromptRendering:
    """Tests for template variable interpolation."""

    def test_render_simple_variable(self, tmp_path: Path) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        defn = _simple_chain_definition()
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        engine.context["input_topic"] = "AI Agents"

        result = engine.render_prompt("Research about {{input_topic}}")
        assert result == "Research about AI Agents"

    def test_render_step_output_variable(self, tmp_path: Path) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        defn = _simple_chain_definition()
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        engine.context["step1.output"] = "Detailed research results"

        result = engine.render_prompt("Write about: {{step1.output}}")
        assert result == "Write about: Detailed research results"

    def test_render_missing_variable_preserved(self, tmp_path: Path) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        defn = _simple_chain_definition()
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        # Don't set any context
        result = engine.render_prompt("Missing: {{unknown_var}}")
        assert result == "Missing: {{unknown_var}}"

    def test_render_multiple_variables(self, tmp_path: Path) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        defn = _simple_chain_definition()
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        engine.context["a"] = "X"
        engine.context["b"] = "Y"

        result = engine.render_prompt("{{a}} and {{b}}")
        assert result == "X and Y"


class TestConditionEvaluation:
    """Tests for the static _evaluate_condition method."""

    def test_contains_match(self) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        assert WorkflowEngine._evaluate_condition("contains: 'hello'", "say hello world") is True

    def test_contains_no_match(self) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        assert WorkflowEngine._evaluate_condition("contains: 'hello'", "goodbye world") is False

    def test_contains_double_quotes(self) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        assert WorkflowEngine._evaluate_condition('contains: "data"', "some data here") is True

    def test_unknown_condition_returns_true(self) -> None:
        from nanobot.agent.workflow import WorkflowEngine

        assert WorkflowEngine._evaluate_condition("unknown_op: foo", "any text") is True


# ---------------------------------------------------------------------------
# WorkflowEngine execution tests (with mocked sub-agents)
# ---------------------------------------------------------------------------


class TestWorkflowExecution:
    """Integration-style tests with mocked LLM provider."""

    @pytest.mark.asyncio
    async def test_chain_execution(self, tmp_path: Path) -> None:
        """Two chain steps should execute sequentially, passing data."""
        from nanobot.agent.workflow import WorkflowEngine
        from nanobot.providers.base import LLMResponse

        defn = _simple_chain_definition()
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        mgr = _make_subagent_manager(tmp_path)

        call_count = {"n": 0}

        async def fake_chat(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return LLMResponse(content="research output", tool_calls=[])
            return LLMResponse(content="written article", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        result = await engine.run("AI Agents", mgr)
        assert result == "written article"
        assert engine.context["step1.output"] == "research output"
        assert engine.context["step2.output"] == "written article"
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_conditional_step_skipped(self, tmp_path: Path) -> None:
        """Conditional step should be skipped when condition is not met."""
        from nanobot.agent.workflow import WorkflowEngine
        from nanobot.providers.base import LLMResponse

        defn = _conditional_definition("contains: 'keyword'")
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        mgr = _make_subagent_manager(tmp_path)

        async def fake_chat(*, messages, **kwargs):
            return LLMResponse(content="nothing special here", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        result = await engine.run("test topic", mgr)  # noqa: F841
        # Conditional step should be skipped (output is empty string)
        assert engine.context.get("conditional_step.output") == ""

    @pytest.mark.asyncio
    async def test_conditional_step_executed(self, tmp_path: Path) -> None:
        """Conditional step should execute when condition is met."""
        from nanobot.agent.workflow import WorkflowEngine
        from nanobot.providers.base import LLMResponse

        defn = _conditional_definition("contains: 'keyword'")
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        mgr = _make_subagent_manager(tmp_path)

        call_count = {"n": 0}

        async def fake_chat(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return LLMResponse(content="result with keyword inside", tool_calls=[])
            return LLMResponse(content="checked result", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        result = await engine.run("test topic", mgr)  # noqa: F841
        assert call_count["n"] == 2
        assert engine.context["conditional_step.output"] == "checked result"

    @pytest.mark.asyncio
    async def test_parallel_execution(self, tmp_path: Path) -> None:
        """Parallel steps should all execute."""
        from nanobot.agent.workflow import WorkflowEngine
        from nanobot.providers.base import LLMResponse

        defn = _parallel_definition()
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        mgr = _make_subagent_manager(tmp_path)

        results = {"para1": "result A", "para2": "result B"}
        call_order: list[str] = []

        async def fake_chat(*, messages, **kwargs):
            user_msg = messages[-1]["content"]
            if "Task A" in user_msg:
                call_order.append("para1")
                return LLMResponse(content=results["para1"], tool_calls=[])
            call_order.append("para2")
            return LLMResponse(content=results["para2"], tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        await engine.run("test", mgr)
        assert engine.context["para1.output"] == "result A"
        assert engine.context["para2.output"] == "result B"
        # Both should have been called
        assert len(call_order) == 2

    @pytest.mark.asyncio
    async def test_error_handling_continue(self, tmp_path: Path) -> None:
        """Steps with error_handling='continue' should not halt the pipeline."""
        from nanobot.agent.workflow import WorkflowEngine
        from nanobot.providers.base import LLMResponse

        defn = _error_handling_definition()
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        mgr = _make_subagent_manager(tmp_path)

        call_count = {"n": 0}

        async def fake_chat(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated failure")
            return LLMResponse(content="recovered", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        result = await engine.run("test", mgr)
        assert "Error (skipped)" in engine.context["failing_step.output"]
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_error_handling_raise(self, tmp_path: Path) -> None:
        """Steps without error_handling='continue' should propagate errors."""
        from nanobot.agent.workflow import WorkflowEngine

        defn = {
            "name": "Error Raise",
            "steps": [
                {
                    "step_id": "fail",
                    "agent_role": "Worker",
                    "mode": "chain",
                    "prompt_template": "{{input_topic}}",
                    "timeout": 10,
                },
            ],
        }
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        mgr = _make_subagent_manager(tmp_path)

        async def fake_chat(*, messages, **kwargs):
            raise RuntimeError("fatal error")

        mgr.provider.chat_with_retry = fake_chat

        with pytest.raises(RuntimeError, match="fatal error"):
            await engine.run("test", mgr)

    @pytest.mark.asyncio
    async def test_timeout_returns_message(self, tmp_path: Path) -> None:
        """Step timeout should produce a meaningful error message, not raise."""
        from nanobot.agent.workflow import WorkflowEngine
        from nanobot.providers.base import LLMResponse

        defn = {
            "name": "Timeout Test",
            "steps": [
                {
                    "step_id": "slow",
                    "agent_role": "Worker",
                    "mode": "chain",
                    "prompt_template": "{{input_topic}}",
                    "timeout": 1,
                },
            ],
        }
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        mgr = _make_subagent_manager(tmp_path)

        async def slow_chat(*, messages, **kwargs):
            await asyncio.sleep(10)
            return LLMResponse(content="late", tool_calls=[])

        mgr.provider.chat_with_retry = slow_chat

        result = await engine.run("test", mgr)
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_empty_workflow(self, tmp_path: Path) -> None:
        """A workflow with no steps should return empty string."""
        from nanobot.agent.workflow import WorkflowEngine

        defn = {"name": "Empty", "steps": []}
        engine = WorkflowEngine(_make_workflow_file(tmp_path, defn))
        mgr = _make_subagent_manager(tmp_path)

        result = await engine.run("test", mgr)
        # context has input_topic only, so the last value is input_topic
        assert result == "test"


# ---------------------------------------------------------------------------
# RunWorkflowTool tests
# ---------------------------------------------------------------------------


class TestRunWorkflowTool:
    """Tests for the run_workflow tool."""

    def test_tool_schema(self) -> None:
        from nanobot.agent.tools.workflow import RunWorkflowTool

        mgr = MagicMock()
        tool = RunWorkflowTool(manager=mgr, workflows_dir=Path("/tmp"))
        assert tool.name == "run_workflow"
        assert "workflow_name" in tool.parameters["properties"]
        assert "input" in tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_missing_workflow(self, tmp_path: Path) -> None:
        from nanobot.agent.tools.workflow import RunWorkflowTool

        mgr = MagicMock()
        tool = RunWorkflowTool(manager=mgr, workflows_dir=tmp_path)
        result = await tool.execute(workflow_name="nonexistent", input="test")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_lists_available_workflows(self, tmp_path: Path) -> None:
        from nanobot.agent.tools.workflow import RunWorkflowTool

        # Create a dummy workflow
        (tmp_path / "my_flow.json").write_text(
            json.dumps({"name": "My", "steps": []}), encoding="utf-8"
        )
        mgr = MagicMock()
        tool = RunWorkflowTool(manager=mgr, workflows_dir=tmp_path)
        result = await tool.execute(workflow_name="nonexistent", input="test")
        assert "my_flow" in result

    @pytest.mark.asyncio
    async def test_execute_workflow_success(self, tmp_path: Path) -> None:
        from nanobot.agent.tools.workflow import RunWorkflowTool
        from nanobot.providers.base import LLMResponse

        defn = {
            "name": "Quick Test",
            "steps": [
                {
                    "step_id": "only",
                    "agent_role": "Helper",
                    "mode": "chain",
                    "prompt_template": "Do: {{input_topic}}",
                    "timeout": 10,
                },
            ],
        }
        (tmp_path / "quick.json").write_text(json.dumps(defn), encoding="utf-8")

        mgr = _make_subagent_manager(tmp_path)

        async def fake_chat(*, messages, **kwargs):
            return LLMResponse(content="done!", tool_calls=[])

        mgr.provider.chat_with_retry = fake_chat

        tool = RunWorkflowTool(manager=mgr, workflows_dir=tmp_path)
        result = await tool.execute(workflow_name="quick", input="hello")
        assert "completed" in result
        assert "done!" in result

    @pytest.mark.asyncio
    async def test_execute_workflow_error(self, tmp_path: Path) -> None:
        from nanobot.agent.tools.workflow import RunWorkflowTool

        defn = {
            "name": "Bad",
            "steps": [
                {
                    "step_id": "fail",
                    "agent_role": "Worker",
                    "mode": "chain",
                    "prompt_template": "{{input_topic}}",
                    "timeout": 5,
                },
            ],
        }
        (tmp_path / "bad.json").write_text(json.dumps(defn), encoding="utf-8")

        mgr = _make_subagent_manager(tmp_path)

        async def failing_chat(*, messages, **kwargs):
            raise RuntimeError("boom")

        mgr.provider.chat_with_retry = failing_chat

        tool = RunWorkflowTool(manager=mgr, workflows_dir=tmp_path)
        result = await tool.execute(workflow_name="bad", input="test")
        assert "failed" in result
        assert "boom" in result


# ---------------------------------------------------------------------------
# Tool registration integration test
# ---------------------------------------------------------------------------


class TestWorkflowToolRegistration:
    """Verify run_workflow is registered in the default tool set."""

    def test_loop_registers_workflow_tool(self) -> None:
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        workspace = MagicMock()
        workspace.__truediv__ = MagicMock(return_value=MagicMock(exists=MagicMock(return_value=False)))

        with patch("nanobot.agent.loop.ContextBuilder"), \
             patch("nanobot.agent.loop.SessionManager"), \
             patch("nanobot.agent.loop.SubagentManager"):
            loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)

        assert loop.tools.has("run_workflow")
