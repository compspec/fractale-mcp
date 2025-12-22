import os
import re
import time

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from rich import print

# Native Engine Imports
import fractale.engines.native.backends as backends
import fractale.utils as utils
from fractale.core.config import ModelConfig
from fractale.logger import logger


class WorkerAgent:
    """
    A standalone worker for the Native Engine.
    Executes a single step using FastMCP + LLM Backend.
    No inheritance from global base classes.
    """

    def __init__(self, name: str, step, ui=None, max_attempts=None):
        self.name = name

        # The agent is responsible for a step.
        # this is basically a config for the step
        self.step = step
        self.ui = ui
        self.max_attempts = max_attempts or 5
        self.client = None
        self.metadata = {
            "name": name,
            "status": "pending",
            "times": {},
            "steps": [],  # Tool execution history
            "llm_usage": [],
        }

    def run(self, context):
        """
        Main entry point called by the Manager.
        Synchronous wrapper around the async execution loop.
        """
        logger.info(f"▶️  '{self.name}' starting...")
        start_time = time.time()
        self.metadata["status"] = "running"

        # The manager adds the step.prmopt as source prompt here
        prompt_name = context.agent_config.get("source_prompt")
        if not prompt_name:
            raise ValueError(f"Worker {self.name} missing 'source_prompt' in context.")

        try:
            result = utils.run_sync(self.run_async(prompt_name, context))
            context.result = result
            self.metadata["status"] = "success"

        except Exception as e:
            self.metadata["status"] = "failed"
            context.error_message = str(e)
            logger.error(f"Worker '{self.name}' failed: {e}")
            raise e

        finally:
            self.metadata["times"]["execution"] = time.time() - start_time

        return context

    async def run_async(self, prompt_name: str, context):
        """
        Sets up connections and runs the async loop.
        """
        start_exec = time.time()

        # Setup fastmcp client and choose a backend
        self.init_mcp_client()
        self.init_backend(context)

        async with self.client:

            # Get tools available for running session.
            mcp_tools = await self.client.list_tools()
            await self.backend.initialize(mcp_tools)

            # Derive the persona (prompt) from mcp server.
            context_data = getattr(context, "data", context)
            prompt_args, _ = self.step.partition_inputs(context_data)
            instruction = await self._fetch_persona(prompt_name, prompt_args)

            # Once we get here, we have a specific instruction (with a persona)
            # And we want to allow the agent to work on the task in a loop
            response = await self.run_loop(instruction, context)

        self.record_usage(time.time() - start_exec)
        return response

    def init_mcp_client(self):
        """
        Setup the mcp client for the state machine. We use
        the streaming http transport from fastmcp.
        """
        port = os.environ.get("FRACTALE_MCP_PORT", "8089")
        token = os.environ.get("FRACTALE_MCP_TOKEN")
        url = f"http://127.0.0.1:{port}/mcp"

        headers = {"Authorization": token} if token else None
        transport = StreamableHttpTransport(url=url, headers=headers)
        self.client = Client(transport)

    def init_backend(self, context):
        """
        Create the backend from the model config.
        """
        cfg = ModelConfig.from_context(context)
        if cfg.provider not in backends.BACKENDS:
            raise ValueError(f"Provider '{cfg.provider}' not supported.")
        self.backend = backends.BACKENDS[cfg.provider](config=cfg)

    async def _fetch_persona(self, prompt_name, arguments):
        """
        Calls MCP Server to render the prompt string.
        """
        log_msg = f"📥 Persona: {prompt_name}"
        if self.ui:
            self.ui.log(log_msg)
        else:
            logger.info(log_msg)

        try:
            result = await self.client.get_prompt(name=prompt_name, arguments=arguments)

            msgs = [
                m.content.text if hasattr(m.content, "text") else str(m.content)
                for m in result.messages
            ]
            text = "\n\n".join(msgs)

            # Update UI Prompt Box
            if self.ui and hasattr(self.ui, "on_set_prompt"):
                self.ui.on_set_prompt(text)

            return text
        except Exception as e:
            raise RuntimeError(f"Failed to fetch persona '{prompt_name}': {e}")

    async def run_loop(self, instruction, context):
        """
        Here we are going to think -> do something -> respond.
        """
        # The user is allowed to set a one-off max attempts
        max_loops = context.get("max_attempts") or self.max_attempts
        loops = 0

        while loops < max_loops:
            loops += 1

            # Generate some initial asset.
            response, reason, calls = self.backend.generate_response(prompt=instruction)

            # Logging (reason, response with and without ui)
            if reason and self.ui:
                self.ui.log(reason)
            if response and self.ui:
                self.ui.log(response)
            elif response:
                logger.info(f"🤖 Thought: {response}")

            # TODO: vsoch: not happy with logic here. We should be able
            # to have calls WITH validation, not either OR.
            # The response will either have or not have tool calls.
            # For on-premises models, we will need better control of this.
            # If we don't have calls, we might have an implicit validation tool request
            # In which case, the response from above goes into the request
            validate_tool = context.agent_config.get("validate")
            if not calls and validate_tool:
                tool_args = self.extract_code_block(response)
                if tool_args:
                    msg = f"⚡ Auto-triggering tool: {validate_tool}"
                    if self.ui:
                        self.ui.log(msg)
                    else:
                        logger.info(msg)

                    # TODO: do we need to update args here from user config?
                    calls = [{"name": validate_tool, "args": tool_args, "id": validate_tool}]

            # If still no calls, we are done.
            elif not calls:
                logger.info("🛑 Agent finished (No tools called).")
                return response

            # Call tools - combination of user and agent selected.
            tool_outputs = []
            while calls:
                call = calls.pop(0)
                t_name = call["name"]
                t_args = call["args"]
                logger.info(f"🛠️  Calling: {t_name}")

                try:
                    res = await self.client.call_tool(t_name, t_args)
                    content = res.content[0].text if hasattr(res, "content") else str(res)
                    # Debugging for now
                    print(res)
                except Exception as e:
                    content = f"❌ ERROR: {e}"

                self.record_step(t_name, t_args, content)
                if self.ui and hasattr(self.ui, "on_step_update"):
                    self.ui.on_step_update(content)

                tool_outputs.append({"id": call.get("id"), "name": t_name, "content": content})

            # After a set of calls, check with the agent.
            response, reason, calls = self.backend.generate_response(tool_outputs=tool_outputs)

            # More debugging
            if response:
                print("💬 Response")
                print(response)
            # Gemini doesn't have a reason
            # It's OK Gemini, neither do I.
            if reason:
                print("🙋‍♀️ Reason")
                print(reason)
            if calls:
                print("☎️  Calls")
                print(calls)
            if response and self.ui:
                self.ui.log(f"🤖 Thought:\n{response}")
            if not calls:
                return response

        return response

    def extract_code_block(self, text):
        """
        Match block of code, assuming llm returns as markdown or code block.
        """
        match = re.search(r"```(?:\w+)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

    def record_step(self, tool, args, output):
        self.metadata["steps"].append(
            {
                "tool": tool,
                "args": args,
                "output_snippet": str(output)[:200],
                "timestamp": time.time(),
            }
        )

    def record_usage(self, duration):
        """
        Record token usage for the LLM.

        TODO: need to look into metrics for other backends.
        """
        if hasattr(self.backend, "token_usage"):
            self.metadata["llm_usage"].append(self.backend.token_usage)
        # TODO: vsoch what to do with duration?
