import asyncio
import json
import os
from datetime import datetime

from rich import print
from rich.prompt import Prompt as RichPrompt

import fractale.agent.logger as logger
import fractale.agent.manager.prompts as prompts
import fractale.utils as utils
from fractale.agent.agent import MCPAgent
from fractale.agent.context import get_context
from fractale.agent.manager.plan import Plan
from fractale.utils.timer import Timer

# The manager IS an agent itself since it needs to decide how to recover.


class ManagerAgent(MCPAgent):
    """
    An LLM-powered orchestrator that executes a plan.
    It acts as a supervisor:
    1. Validates the plan against the server.
    2. Dispatches steps to UniversalAgents.
    3. Handles failure via LLM reasoning OR Human intervention.
    """

    def init(self):
        """
        Initialize the MCPAgent infrastructure (MCP Client + Backend).
        """
        # This sets up the MCP connection and LLM Backend
        super().init()

    async def validate_personas(self, plan):
        """
        Queries the MCP server to ensure all personas in the plan exist.
        A persona == a prompt. Each step has an associated prompt (persona).
        """
        # Attempt to list prompts from server
        server_prompts = await self.client.list_prompts()
        schema_map = {}

        # FastMCP (bottom) vs Standard MCP (top) return types
        if hasattr(server_prompts, "prompts"):
            prompts_list = server_prompts.prompts
        else:
            prompts_list = server_prompts

        # We do this once so later we can call prompt functions and know args vs. context
        for p in prompts_list:
            # Store set of valid argument names
            args = {arg.name for arg in p.arguments} if p.arguments else set()
            schema_map[p.name] = args

        print(f"🔎 Validating {len(plan)} steps...")
        for step in plan.agents:
            if step.prompt not in schema_map:
                raise ValueError(
                    f"❌ Plan Validation Failed: Step '{step.name}' requests persona '{step.prompt}', "
                    f"but server only has: {schema_map.keys()}"
                )
            # Ensure we separate arguments from extra
            # This does not check to see if we have required, since they
            # might come from a previous step.
            step.set_schema(schema_map[step.prompt])

            # store in the manager metadata so steps can access it
            self.metadata["assets"]["prompt_schemas"] = schema_map
            print("✅ Personas validated and schemas cached")

    def get_recovery_step(self, context, failed_step, plan):
        """
        Uses the LLM Backend to decide which agent to call to fix an error.
        """
        # We describe each step (akin to a function) for the manager to choose
        descriptions = ""
        for step in plan.agents:
            descriptions += f"- {step.agent}: {step.description}\n"
            if step.agent == failed_step.agent:
                break

        # Build the prompt to recover from some failure.
        prompt_text = prompts.recovery_prompt % (
            descriptions,
            failed_step.agent,
            context.error_message,
        )
        logger.warning(
            f"🤔 Consulting Manager for recovery from {failed_step.agent} failure...",
            title="Error Triage",
        )

        # TODO: test and make more resilient if needed
        next_step = None
        while not next_step:

            # Use the backend directly - get back tuple (text, calls)
            # Note I'm trying to do these NOT async because it's easier to debug
            response_text = self.backend.generate_response(prompt=prompt_text)[0]
            next_step = json.loads(utils.get_code_block(response_text, "json"))

            # Validate - we require the agent name and description
            if (
                "agent_name" not in step_json
                or "task_description" not in next_step
                or "reason" not in next_step
            ):
                raise ValueError("Missing keys")
            if step_json["agent_name"] not in plan.agent_names:
                raise ValueError(f"Unknown agent {step_json['agent_name']}")

        agent_name = recovery_step["agent_name"]
        logger.warning(f"Recovering to agent: [bold cyan]{agent_name}[/bold cyan]")

        # Find index of target agent
        found_index = -1
        for idx, ag in enumerate(plan.agents):
            if ag.name == agent_name:
                found_index = idx
                break

        next_step["index"] = found_index

        # Update recovery metadata with choice.
        if failed_step.name not in self.metadata["assets"]["recovery"]:
            self.metadata["assets"]["recovery"][failed_step.name] = []
            self.metadata["assets"]["recovery"][failed_step.name].append(next_step)

        return next_step

    def check_personas(self, plan, personas):
        """
        Ensure that the prompt (persona) requested by each step is one
        known to the MCP server.
        """
        for step in plan.agents:
            if step.prompt not in persons:
                raise ValueError(
                    f"Unknown persona {step.prompt} in step {step.name}. Available: {personas}"
                )

    def run(self, context):
        """
        Executes a plan-driven workflow with intelligent error recovery.
        """
        # Ensure context is wrapped
        context = get_context(context)

        # Init metadata if needed
        if "recovery" not in self.metadata["assets"]:
            self.metadata["assets"]["recovery"] = {}

        context.managed = True
        self.max_attempts = self.max_attempts or 10

        # Plan parses the list of agent configs (prompts)
        plan_path = context.get("plan", required=True)
        plan = Plan(plan_path, save_incremental=self.save_incremental)

        # Connect and validate (don't allow connect without validate)
        asyncio.run(self.connect_and_validate(plan))

        # Still pass the shared context to all tasks
        try:
            tracker = self.run_tasks(context, plan)
            self.metadata["status"] = "Succeeded"
            self.save_results(tracker, plan)
            logger.custom(
                f"Workflow Complete. {len(tracker)} steps executed.",
                title="[bold green]Success[/bold green]",
            )
            return tracker

        except Exception as e:
            self.metadata["status"] = "Failed"
            logger.error(f"Orchestration failed: {e}", title="Failure")
            raise e

    async def connect_and_validate(self, plan):
        """
        Setup client and check prompts.
        """
        async with self.client:
            # Check if server has the prompts we need
            await self.validate_personas(plan)

            # Initialize our backend LLM with the available tools
            mcp_tools = await self.client.list_tools()
            await self.backend.initialize(mcp_tools)

    def run_tasks(self, context, plan):
        """
        Run agent tasks until stopping condition.
        """
        tracker = []
        timer = Timer()
        current_step_index = 0

        # Initialize recovery history
        if "recovery" not in self.metadata["assets"]:
            self.metadata["assets"]["recovery"] = {}

        # Global Manager Loop
        while current_step_index < len(plan):

            # This is an instance of MCPAgent
            step = plan[current_step_index]
            inputs = step.get("inputs", {})
            self.ui.on_step_start(step.name, step.description, inputs)

            # instantiate the agent here. If we need/want, we can cache the
            # initial envars (credentials) to not need to discover them again.
            agent = MCPAgent(
                name=step.name,
                save_incremental=plan.save_incremental,
                max_attempts=step.max_attempts,
                # Pass the UI down so the agent uses same interface
                ui=self.ui,
            )
            # Update step context
            context = step.update_context(context)

            # Execute the step. This is akin to a tiny state machine
            # The agent (persona prompt + LLM) is making calls to MCP tools
            # Agent -> run is a wrapper to agent.run_step.
            with timer:
                context = agent.run(context, step)

            # Results, error, and metadata
            result = context.get("result")
            error = context.get("error_message")
            metadata = agent.metadata

            # update the accordion header color and shows the result/error box
            self.ui.on_step_finish(step.name, result, error, metadata)

            # Record metrics
            # Note: step_agent.metadata is populated by the agent
            tracker.append(
                {
                    "agent": step.name,
                    "duration": timer.elapsed_time,
                    "result": result,
                    "error": error,
                    "attempts": self.attempts,
                    "metadata": metadata,
                }
            )

            # If we have a result and no error message, success.
            if result and not error:
                current_step_index += 1
                context.reset()
                continue

            # Check global manager limits
            if self.reached_max_attempts():
                self.ui.on_log("Manager reached max attempts. Aborting.", level="error")
                break
            self.attempts += 1

            # Always ask user if an entire step fails.
            action = self.ui.ask_user(
                f"Step Failed: {err}\nAction?", options=["retry", "assist", "auto", "quit"]
            )
            action = action.lower().strip() or "auto"

            # Respond to the action
            if action == "quit":
                break
            elif action == "retry":
                context = self.reset_context(context, plan, step)
                continue

            # Human in the loop! Ask for a hint and add to error message
            elif action == "assist":
                hint = self.ui.ask_user("Enter instructions for the agent")
                context["error_message"] = f"Previous Error: {error}\nUser Advice: {hint}"
                context = self.reset_context(context, plan, step)
                continue

            # If we get down here (auto) we ask the manager for a recovery step.
            elif action == "auto":

                # If we failed the first step, just try again.
                if current_step_index == 0:
                    context = self.reset_context(context, plan)
                    continue

                # Otherwise ask the manager to choose.
                recovery_step = self.get_recovery_step(context, agent, plan)
                index = recovery_step["index"]
                if not recovery_step:
                    self.ui.on_log("Manager could not determine recovery.", level="error")
                    break

                if index == -1:
                    self.ui.on_log(f"Recovery agent {target_name} not found!", level="error")
                    break

                # Reset context up to that point
                current_step_index = index
                context = self.reset_context(context, plan, plan[current_step_index])
                context["error_message"] = prompts.get_retry_prompt(
                    context, recovery_step["reason"]
                )
                continue

        if current_step_index == len(plan):
            self.metadata["status"] = "Succeeded"
            self.ui.on_workflow_complete("Success")
        else:
            self.metadata["status"] = "Failed"
            self.ui.on_workflow_complete("Failed")
        return tracker

    def save_results(self, tracker, plan):
        """
        Save results to file based on timestamp.
        """
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir)
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        results_file = os.path.join(self.results_dir, f"results-{timestamp}.json")

        # We assume plan has a .plan attribute or similar to get raw dict
        manager_meta = getattr(plan, "plan", {})

        if self.metadata["times"]:
            manager_meta["times"] = self.metadata["times"]
        if self.metadata["assets"]["recovery"]:
            manager_meta["recovery"] = self.metadata["assets"]["recovery"]

        result = {"steps": tracker, "manager": manager_meta, "status": self.metadata["status"]}
        utils.write_json(result, results_file)

    def reset_context(self, context, plan, failed_step=None):
        """
        Reset context state variables up to the failed step.
        """
        # We iterate through agents and call their reset logic
        for step in plan.agents:
            context = step.reset_context(context)

            # If we reached the step we are rolling back to, stop clearing.
            if failed_step is not None and step.name == failed_step.name:
                break
        return context

    def reached_max_attempts(self):
        return self.attempts >= self.max_attempts
