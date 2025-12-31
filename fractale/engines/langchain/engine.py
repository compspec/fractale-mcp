import json
import logging
import re
import warnings
from typing import Any, Dict

import yaml
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

import fractale.utils as utils
from fractale.core.context import get_context
from fractale.engines.base import AgentBase
from fractale.engines.langchain.backend import create_langchain_model
from fractale.engines.langchain.tools import get_langchain_tools
from fractale.utils.timer import Timer

try:
    from langgraph.errors import LangGraphDeprecatedSinceV10

    warnings.filterwarnings("ignore", category=LangGraphDeprecatedSinceV10)
except ImportError:
    pass

logger = logging.getLogger(__name__)


class Manager(AgentBase):
    """
    Executes a Fractale Plan using LangChain / LangGraph.
    """

    def __init__(self, plan, backend=None, ui=None, max_attempts=10, database=None):
        self.plan = plan
        self.backend = backend
        self.ui = ui
        self.max_attempts = max_attempts
        self.database = database
        self.client = None
        self.metadata = {"status": "pending", "times": {}, "steps": []}

    def run(self, context_input):
        context = get_context(context_input)
        context.managed = True

        for k, v in self.plan.global_inputs.items():
            if k not in context:
                context[k] = v

        self.init()
        utils.run_sync(self.connect_and_validate())

        try:
            self.metadata["status"] = "running"
            final_state = utils.run_sync(self.build_and_run_graph(context))

            if isinstance(final_state, dict):
                context.update(final_state)

            self.metadata["status"] = "Succeeded"
            self.save_results(self.metadata["steps"])

            if self.ui:
                self.ui.on_workflow_complete("Success")
            return self.metadata["steps"]

        except Exception as e:
            self.metadata["status"] = "Failed"
            logger.error(f"LangChain Engine Failed: {e}")
            if self.ui:
                self.ui.on_workflow_complete("Failed")
            raise e

    async def connect_and_validate(self):
        async with self.client:
            prompts = await self.client.list_prompts()
            p_list = prompts.prompts if hasattr(prompts, "prompts") else prompts
            schema_map = {p.name: {a.name for a in p.arguments} for p in p_list}
            for step in self.plan.states.values():
                if step.type == "agent" and step.prompt in schema_map:
                    step.set_schema(schema_map[step.prompt])

    async def build_and_run_graph(self, context):
        async with self.client:
            lc_tools = await get_langchain_tools(self.client)
            workflow = StateGraph(Dict[str, Any])

            # Add nodes
            for step_name, step in self.plan.states.items():
                if step.type == "final":
                    continue
                node_func = self.create_node(step, lc_tools)
                workflow.add_node(step_name, node_func)

            # Add edges
            for step_name, step in self.plan.states.items():
                if step.type == "final":
                    continue

                def router(state, step_ref=step):
                    outcome = state.get("_last_outcome", "failure")
                    target = step_ref.transitions.get(outcome, "failed")
                    return str(target).strip()

                destinations = set(step.transitions.values())
                mapping = {}
                for dest in destinations:
                    key = str(dest).strip()
                    clean = key.lower()

                    target_step = self.plan.states.get(key)
                    is_terminal = (target_step and target_step.type == "final") or clean in [
                        "success",
                        "failed",
                        "finish",
                    ]

                    if is_terminal:
                        mapping[key] = END
                    else:
                        mapping[key] = key

                if "failed" not in mapping:
                    mapping["failed"] = END

                workflow.add_conditional_edges(step_name, router, mapping)

            # Run
            initial = self.plan.initial_state
            if not initial:
                raise ValueError("No initial state found in plan")

            if self.plan.states.get(initial).type == "final":
                candidates = [n for n, s in self.plan.states.items() if s.type != "final"]
                if candidates:
                    initial = candidates[0]

            workflow.set_entry_point(initial)
            app = workflow.compile()
            initial_state = dict(context)
            final_state = await app.ainvoke(initial_state)
            return final_state

    def create_node(self, step, tools):
        async def node_logic(state: dict):
            timer = Timer()
            with timer:
                if self.ui:
                    self.ui.on_step_start(step.name, step.description, step.inputs)

                resolved = utils.resolve_templates(step.inputs, state)
                state.update(resolved)

                self.ui.log(f"DEBUG [{step.name}]: Input State Keys: {list(state.keys())}")

                result = None
                error = None
                outcome = "failure"

                try:
                    if step.type == "agent":
                        result = await self.run_agent(step, state, tools)
                    elif step.type == "tool":
                        result = await self.run_tool(step, state)
                    outcome = "success"
                except Exception as e:
                    error = str(e)
                    outcome = "failure"

                # Store Results
                if result:
                    self.ui.log(f"DEBUG [{step.name}]: Raw Result: {str(result)[:100]}...")
                    state["_previous_result"] = result
                    state[f"{step.name}_result"] = result
                    state["result"] = result

                    try:
                        clean_str = ""
                        if isinstance(result, str):
                            clean_str = self.extract_code_block(result)

                        if isinstance(clean_str, str) and (
                            clean_str.startswith("{") or clean_str.startswith("[")
                        ):
                            parsed = json.loads(clean_str)
                            if isinstance(parsed, dict):
                                self.ui.log(
                                    f"DEBUG [{step.name}]: Parsed JSON Keys: {list(parsed.keys())}"
                                )
                                state.update(parsed)
                                state["result"] = parsed
                    except Exception as e:
                        self.ui.log(f"DEBUG [{step.name}]: JSON Parsing skipped: {e}")

                if error:
                    state["_last_error"] = error
                    self.ui.log(f"DEBUG [{step.name}]: Error: {error}")

                state["_last_outcome"] = outcome
                self.ui.on_step_finish(step.name, str(result), error, {})

            self.metadata["steps"].append(
                {
                    "step": step.name,
                    "result": result,
                    "error": error,
                    "duration": timer.elapsed_time,
                }
            )

            return state

        return node_logic

    def extract_code_block(self, text):
        """
        Match block of code.
        """
        if not isinstance(text, str):
            return ""

        match = re.search(r"```(?:\w+)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        return text.strip()

    def _normalize_content(self, content):
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                else:
                    parts.append(str(block))
            return "".join(parts)
        return str(content)

    async def run_agent(self, step, state, tools):
        """
        Main entry function to run an agent step.
        """
        prompt_args, background_info = step.partition_inputs(state)

        try:
            prompt_res = await self.client.get_prompt(step.prompt, arguments=prompt_args)
            system_msg = "\n".join([m.content.text for m in prompt_res.messages])
        except Exception as e:
            raise RuntimeError(f"Error rendering prompt '{step.prompt}': {e}")

        if background_info:
            try:
                ctx_str = yaml.dump({k: str(v) for k, v in background_info.items()})
                system_msg += f"\n\n### SHARED CONTEXT\n```yaml\n{ctx_str}\n```"
            except:
                pass

        if hasattr(self.ui, "on_set_prompt"):
            self.ui.on_set_prompt(system_msg)

        if "llm_provider" in state:
            self.backend = state["llm_provider"]

        model = create_langchain_model(state)

        # Filter tools if allowed_tools is specified
        bound_tools = tools
        allowed = step.spec.get("allowed_tools")
        if allowed:
            bound_tools = [t for t in tools if t.name in allowed]

        if getattr(step, "allow_tools", True):
            model = model.bind_tools(bound_tools)

        agent_executor = create_react_agent(model, bound_tools)

        inputs = {
            "messages": [SystemMessage(content=system_msg), HumanMessage(content="Begin task.")]
        }

        agent_result = await agent_executor.ainvoke(inputs)
        messages = agent_result["messages"]
        self.ui.log(f"DEBUG [{step.name}]: Total Messages: {len(messages)}")

        final_content = self._normalize_content(messages[-1].content)

        implicit_tool_name = step.tool

        if implicit_tool_name:
            code_block = self.extract_code_block(final_content)

            # If it has content, assume it's code/payload
            if code_block and len(code_block) > 0:
                self.ui.log(f"⚡ Intercepting code for implicit tool: {implicit_tool_name}")
                if hasattr(self.ui, "on_step_update"):
                    self.ui.on_step_update(f"⚡ Auto-executing {implicit_tool_name}...")

                # Default capture key content or check spec
                capture_key = step.spec.get("capture_arg", "content")
                tool_args = {capture_key: code_block}

                # Merge mapped args from the args dict in step spec
                raw_args = step.spec.get("args", {})
                extra_args = utils.resolve_templates(raw_args, state)
                tool_args.update(extra_args)

                try:
                    res = await self.client.call_tool(implicit_tool_name, tool_args)
                    tool_output = res.content[0].text if hasattr(res, "content") else str(res)
                    return tool_output
                except Exception as e:
                    return f"❌ Implicit Tool Error: {e}"

        return final_content

    async def run_tool(self, step, state):
        """
        Main entry function to run a tool directly.
        """
        raw_args = step.spec.get("args", {})
        tool_args = utils.resolve_templates(raw_args, state)

        self.ui.log(f"🛠️ LangChain Manager executing tool: {step.tool}")
        result = await self.client.call_tool(step.tool, tool_args)

        if hasattr(result, "content") and result.content:
            return result.content[0].text
        return str(result)

    def save_results(self, tracker):
        """
        Save results.
        """
        if not self.database:
            return
        data = {
            "steps": tracker,
            "plan_source": self.plan.plan_path,
            "status": self.metadata.get("status"),
            "metadata": self.metadata,
        }
        self.database.save(data)
