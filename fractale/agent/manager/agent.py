import asyncio
import json
import os
from datetime import datetime

from rich import print

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
    It can perform error recovery by asking the backend LLM.
    """

    def init(self):
        """
        Initialize the MCPAgent infrastructure (MCP Client + Backend).
        """
        # This sets up the MCP connection and LLM Backend
        super().init()

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

        # Build the Prompt to recover from some failure.
        prompt_text = prompts.recovery_prompt % (
            descriptions,
            failed_step.agent,
            context.error_message,
        )
        logger.warning(
            f"🤔 Consulting Manager for recovery from {failed_step.agent} failure...",
            title="Error Triage",
        )

        step_json = None
        attempts = 0

        while not step_json and attempts < 3:
            attempts += 1
            try:
                # Use the Backend directly - get back tuple (text, calls)
                # We ask the backend to generate a response based on this prompt.
                response_text = asyncio.run(self.backend.generate_response(prompt=prompt_text))[0]
                step_json = json.loads(utils.get_code_block(response_text, "json"))

                # Validate
                if "agent_name" not in step_json or "task_description" not in step_json:
                    raise ValueError("Missing keys")
                if step_json["agent_name"] not in plan.agent_names:
                    raise ValueError(f"Unknown agent {step_json['agent_name']}")

            except Exception as e:
                step_json = None

                # Tell agent what it did wrong :)
                prompt_text = prompts.recovery_error_prompt % (
                    descriptions,
                    failed_step.agent,
                    context.error_message,
                    str(e),
                )
                logger.warning(f"Manager failed to parse recovery plan, retrying: {e}")

        return step_json

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

        # STOPPED HERE - need working token to run!
        import IPython

        IPython.embed()

        # Ensure that persons in plan exist at API.
        print(f"🔎 Validating personas. Available: {len(valid_personas)}")

        # These are personas / roles available for agents
        # 1. Connect & Discover Tools
        prompts = asyncio.run(self.get_prompts_list())

        # 2. Initialize Backend with these tools

    #            await self.backend.initialize(mcp_tools)

    # 3. Initial Prompt
    # 'response_text' is what the LLM says to the user
    # 'calls' is a list of tools it wants to run
    #           response_text, calls = await self.backend.generate_response(prompt=prompt_text)

    #        for step in plan.agents:
    #            if step.prompt not in valid_persons:

    #                if prompt_name not in valid_personas:
    #                    raise ValueError(
    #                        f"❌ Plan Error: Unknown Persona '{prompt_name}' in step '{step['name']}'.\n"
    #                        f"Available Personas: {list(valid_personas)}"
    #                    )
    #        except ImportError:
    # Fallback if registry module isn't ready or circular import issues persist
    #            print("⚠️ Warning: Skipping persona validation (registry not available)")

    #        import IPython
    #        IPython.embed()

    #        logger.custom(
    #            f"Manager Initialized with Agents: [bold cyan]{plan.agent_names}[/bold cyan]",
    #            title="[green]Manager Status[/green]",
    #        )

    #        try:
    #            tracker = self.run_tasks(context, plan)
    #            logger.custom(
    #                f"Tasks complete: [bold magenta]{len(tracker)} steps[/bold magenta]",
    #                title="[green]Manager Status[/green]",
    #            )
    #            self.save_results(tracker, plan)
    #            return tracker # Return tracker as result

    #        except Exception as e:
    #            logger.error(f"Orchestration failed:\n{str(e)}", title="Orchestration Failed", expand=False)
    #            raise e

    # NOTE from vsoch: stuff below here is old (from v1) and I'll refactor it when I can keep testing above.

    def run_tasks(self, context, plan):
        """
        Run agent tasks until stopping condition.
        """
        tracker = []
        timer = Timer()
        current_step_index = 0

        # Global Manager Loop
        while current_step_index < len(plan):
            step_agent = plan[
                current_step_index
            ]  # This is an instance of MCPAgent (e.g. UniversalAgent)

            logger.custom(
                f"Executing step {current_step_index + 1}/{len(plan)}: [bold cyan]{step_agent.name}[/bold cyan]",
                title=f"[blue]Attempt {self.attempts}[/blue]",
            )

            # --- EXECUTE AGENT ---
            # Using the new .run() interface from BaseAgent
            with timer:
                # The agent updates the context in place and returns it
                context = step_agent.run(context)

            # Record metrics
            # Note: step_agent.metadata is populated by BaseAgent
            tracker.append(
                {
                    "agent": step_agent.name,
                    "total_seconds": timer.elapsed_time,
                    "result": context.get("result"),
                    "error": context.get("error_message"),
                    "attempts": step_agent.attempts + 1,
                    "metadata": step_agent.metadata,  # Detailed logs
                }
            )

            # --- CHECK SUCCESS ---
            # If we have a result and no error message, success.
            if context.get("result") and not context.get("error_message"):
                current_step_index += 1
                context.reset()  # Clear temp results for next step
                continue  # Move to next step

            # --- FAILURE & RECOVERY ---
            else:
                logger.error(f"Step {step_agent.name} Failed: {context.get('error_message')}")

                # Check global manager limits
                if self.reached_max_attempts():
                    logger.error("Manager reached max attempts. Aborting.")
                    break

                self.attempts += 1

                # If first step fails, just hard reset
                if current_step_index == 0:
                    context = self.reset_context(context, plan=plan)
                    continue

                # RECOVERY LOGIC
                # Ask the Manager (Self) to pick a previous step to retry from
                recovery_step = self.get_recovery_step(context, step_agent, plan)

                if not recovery_step:
                    logger.error("Manager could not determine a recovery plan. Aborting.")
                    break

                if step_agent.name not in self.metadata["assets"]["recovery"]:
                    self.metadata["assets"]["recovery"][step_agent.name] = []
                self.metadata["assets"]["recovery"][step_agent.name].append(recovery_step)

                target_agent_name = recovery_step["agent_name"]
                logger.warning(f"Rolling back to agent: [bold cyan]{target_agent_name}[/bold cyan]")

                # Find index of target agent
                # (Assuming plan object allows finding index by name)
                # Simple linear search logic:
                found_index = -1
                for idx, ag in enumerate(plan.agents):
                    if ag.name == target_agent_name:
                        found_index = idx
                        break

                if found_index == -1:
                    logger.error(f"Recovery agent {target_agent_name} not found in plan!")
                    break

                current_step_index = found_index

                # Reset context up to that point
                # (We rely on the step.reset_context implementation from BaseAgent)
                context = self.reset_context(context, plan, plan[current_step_index])

                # Inject advice so it doesn't repeat the mistake
                issues = self.assemble_issues(step_agent.name)
                # Update context with a hint for the next run
                context["error_message"] = prompts.get_retry_prompt(context, issues)

                continue

        # Final Status
        if current_step_index == len(plan):
            self.metadata["status"] = "Succeeded"
        else:
            self.metadata["status"] = "Failed"

        return tracker

    def save_results(self, tracker, plan):
        """Save results to file based on timestamp."""
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
            # (We want to KEEP the state generated BY this step's previous successful run?
            #  Actually, usually if we roll back TO a step, we want to clear THAT step's output
            #  so it runs fresh.)
            if failed_step is not None and step.name == failed_step.name:
                break
        return context

    def assemble_issues(self, agent_name):
        """
        Get list of previous issues for context injection.
        """
        if agent_name not in self.metadata["assets"]["recovery"]:
            return []
        issues = []
        for issue in self.metadata["assets"]["recovery"][agent_name]:
            issues.append(issue["task_description"])
        return issues
