import os
from datetime import datetime

import fractale.utils as utils
from fractale.logger import logger

from .agent import WorkerAgent
from .context import get_context
from .state_machine import WorkflowStateMachine


class Manager:
    """
    The Native Engine Orchestrator.
    Executes the Plan using a local Finite State Machine.
    Standalone class (No inheritance from Agent).
    """

    def __init__(self, plan, ui=None, results_dir=None, max_attempts=10, backend="gemini"):
        self.plan = plan
        self.ui = ui

        # TODO: this is not exposed
        self.results_dir = results_dir or os.getcwd()
        self.max_attempts = max_attempts
        self.backend = backend
        self.attempts = 0
        self.metadata = {"status": "Pending"}
        self.init()

    def init(self):
        """
        Initialize the infrastructure (MCP Client for the Manager).
        """
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        port = os.environ.get("FRACTALE_MCP_PORT", "8089")
        token = os.environ.get("FRACTALE_MCP_TOKEN")
        url = f"http://127.0.0.1:{port}/mcp"

        headers = {"Authorization": token} if token else None
        transport = StreamableHttpTransport(url=url, headers=headers)
        self.client = Client(transport)

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

        # 4. Setup State Machine Engine
        sm = WorkflowStateMachine(
            states=self.plan.states,
            context=context,
            runner_callbacks={"agent": self.run_agent, "tool": self.run_tool},
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

                # Are we done?
                if finished:
                    self.metadata["status"] = sm.current_state_name
                    if self.ui:
                        self.ui.on_workflow_complete(sm.current_state_name.capitalize())
                    break

                # TODO: vsoch: clean this up.
                if step_meta and "failure" in step_meta.get("transition", ""):
                    if sm.current_state_name == "failed":
                        if self.ui:
                            action = self.ui.ask_user(
                                f"Workflow Failed at '{step_meta['agent']}'.\nError: {step_meta['error']}\nRetry?",
                                options=["retry", "quit"],
                            )
                            if action == "retry":
                                sm.current_state_name = step_meta["agent"]
                                logger.warning(
                                    f"🔄 User requested retry. Rewinding to {step_meta['agent']}"
                                )
                                continue
                            else:
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
        if self.ui:
            self.ui.on_step_start(step.name, step.description, step.spec.get("inputs", {}))
        if not hasattr(context, "agent_config"):
            context.agent_config = {}

        context.agent_config.update(
            {
                "step_ref": step,
                "source_prompt": step.prompt,
                "step_name": step.name,
                "implicit_tool": step.spec.get("implicit_tool"),
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

            if self.ui:
                self.ui.on_step_finish(step.name, result, error, agent.metadata)
            return result, error, agent.metadata

        except Exception as e:
            if self.ui:
                self.ui.on_step_finish(step.name, None, str(e), agent.metadata)
            return None, str(e), agent.metadata

    def run_tool(self, step, context):
        """
        Runs a deterministic Tool directly (no LLM).
        """
        if self.ui:
            self.ui.on_step_start(step.name, step.description, step.spec.get("args", {}))

        tool_name = step.tool
        start_time = datetime.now()
        tool_args = step.spec.get("args", {})

        try:
            logger.info(f"🛠️ Executing Tool: {tool_name}")

            async def _call():
                async with self.client:
                    res = await self.client.call_tool(tool_name, tool_args)
                    if hasattr(res, "content") and res.content:
                        return res.content[0].text
                    return str(res)

            result = utils.run_sync(_call())

            # I find this weird (I'd prefer an exit code) but agents like strings...
            error = None
            if "❌" in str(result) or "Error" in str(result) or "FAILED" in str(result):
                error = result

            if self.ui:
                if hasattr(self.ui, "on_step_update"):
                    self.ui.on_step_update(result)
                self.ui.on_step_finish(step.name, result, error, {})

            duration = (datetime.now() - start_time).total_seconds()
            meta = {"duration": duration, "tool": tool_name}
            return result, error, meta

        except Exception as e:
            if self.ui:
                self.ui.on_step_finish(step.name, None, str(e), {})
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
        Save results to local file.

        TODO: vsoch: we should have a more organized way of doing this.
        Maybe a database backend?
        """
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        results_file = os.path.join(self.results_dir, f"results-{timestamp}.json")
        data = {
            "steps": tracker,
            "plan_source": self.plan.plan_path,
            "metadata": self.metadata,
        }
        utils.write_json(data, results_file)
