import os
from datetime import datetime

import fractale.utils as utils
from fractale.engines.native.result import parse_tool_response
from fractale.logger import logger

from .agent import AgentBase, WorkerAgent
from .context import get_context
from .state_machine import WorkflowStateMachine


class Manager(AgentBase):
    """
    The Native Engine Orchestrator.
    Executes the Plan using a local Finite State Machine.
    Standalone class (No inheritance from Agent).
    """

    def __init__(
        self, plan, ui=None, results_dir=None, max_attempts=10, backend="gemini", database=None
    ):
        self.plan = plan
        self.ui = ui

        # TODO: this is not exposed
        self.results_dir = results_dir or os.getcwd()
        self.max_attempts = max_attempts
        self.backend = backend
        self.attempts = 0
        self.database = database
        self.metadata = {"status": "Pending"}
        self.init()

    def run(self, context_input):
        """
        Main entry point.
        Merges inputs, validates against server, and starts FSM loop.
        """
        context = get_context(context_input)
        context.managed = True

        # Global inputs from plan
        for k, v in self.plan.global_inputs.items():
            if k not in context:
                context[k] = v

        # Connect and validate against server
        # We use run_sync to bridge the async validation method
        # God I hate asyncio
        utils.run_sync(self.connect_and_validate())

        # Setup State Machine Engine
        # The manager here creates a state machine
        # The state machine is given callbacks for running an agent or tool, defined here.
        sm = WorkflowStateMachine(
            states=self.plan.states,
            context=context,
            callbacks={"agent": self.run_agent, "tool": self.run_tool},
            ui=self.ui,
        )

        logger.info(
            f"State Machine Initialized: {len(self.plan.states)} states. Start {sm.current_state_name}"
        )
        self.metadata["status"] = "running"

        # Start Execution Loop
        tracker = []
        try:
            while True:
                step_meta, finished = sm.run_cycle()
                if step_meta:
                    tracker.append(step_meta)

                # Are we done? We need to break from True
                if finished:
                    self.metadata["status"] = sm.current_state_name
                    self.ui.log_workflow_complete(sm.current_state_name)
                    break

                # Ask user what to do next
                action = sm.ask_next_step(step_meta)

                # Implied action retry is a continue
                if action == "quit":
                    break

            # Save and return
            self.save_results(tracker)
            return tracker

        except Exception as e:
            self.metadata["status"] = "Failed"
            logger.error(f"Orchestration failed: {e}")
            raise e

    def run_agent(self, step, context):
        """
        Runs the WorkerAgent for an 'agent' type step.
        """
        self.ui.log_start(step.name, step.description, step.spec.get("inputs", {}))
        if not hasattr(context, "agent_config"):
            context.agent_config = {}

        context.agent_config.update(
            {
                "step_ref": step,
                "source_prompt": step.prompt,
                "step_name": step.name,
                "tool": step.spec.get("tool"),
            }
        )

        # The worker agent will work on successfully executing a step
        agent = WorkerAgent(
            name=step.name,
            step=step,
            # Prefer step limit, fallback to global manager limit
            max_attempts=step.spec.get("inputs", {}).get("max_attempts", self.max_attempts),
            ui=self.ui,
        )

        try:
            result_ctx = agent.run(context)
            result = result_ctx.get("result")
            error = result_ctx.get("error_message")
            self.ui.log_finish(step.name, result, error, agent.metadata)
            return result, error, agent.metadata

        except Exception as e:
            self.ui.log_finish(step.name, None, str(e), agent.metadata)
            return None, str(e), agent.metadata

    def run_tool(self, step, **kwargs):
        """
        Runs a deterministic Tool directly (no LLM).
        """
        self.ui.log_start(step.name, step.description, step.spec.get("args", {}))

        tool_name = step.tool
        start_time = datetime.now()
        tool_args = step.spec.get("args", {})

        try:
            logger.info(f"🛠️ Executing Tool: {tool_name}")

            async def call():
                async with self.client:
                    return await self.client.call_tool(tool_name, tool_args)

            raw_result = utils.run_sync(call())
            parsed = parse_tool_response(raw_result)
            self.ui.log_update(parsed.content)
            self.ui.log_finish(step.name, parsed.content, parsed.error_message, {})

            duration = (datetime.now() - start_time).total_seconds()
            meta = {"duration": duration, "tool": tool_name}
            return parsed.content, parsed.error_message, meta

        except Exception as e:
            self.ui.log_finish(step.name, None, str(e), {})
            return None, str(e), {}

    async def connect_and_validate(self):
        """
        Async helper to setup client and check server capabilities.
        """
        async with self.client:
            server_prompts_page = await self.client.list_prompts()

            if hasattr(server_prompts_page, "prompts"):
                prompts_list = server_prompts_page.prompts
            else:
                prompts_list = server_prompts_page

            schema_map = {}
            available_names = set()

            for p in prompts_list:
                available_names.add(p.name)
                args = {arg.name for arg in p.arguments} if p.arguments else set()
                schema_map[p.name] = args

            logger.info(f"🔎 Validating {len(self.plan.states)} states against server...")

            for step in self.plan.states.values():
                if step.type == "agent":
                    if step.prompt not in available_names:
                        raise ValueError(
                            f"❌ Plan Error: Unknown Persona '{step.prompt}' in step '{step.name}'"
                        )
                    step.set_schema(schema_map[step.prompt])

            logger.info("✅ Personas validated and schemas synced.")

    def save_results(self, tracker):
        """
        Delegates saving to the configured Database backend.
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
