import asyncio
import json
import os
import time

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from rich import print

import fractale.utils as utils
import fractale.agent.backends as backends
import fractale.agent.defaults as defaults
import fractale.agent.logger as logger
import fractale.agent.prompts as prompts
from fractale.agent.base import Agent


class MCPAgent(Agent):
    """
    Backend-Agnostic Agent that uses MCP Tools.
    """

    def init(self):
        # 1. Setup MCP Client
        port = os.environ.get("FRACTALE_MCP_PORT", defaults.mcp_port)
        token = os.environ.get("FRACTALE_MCP_TOKEN")
        url = f"http://localhost:{port}/mcp"

        headers = None
        if token:
            headers = headers = {"Authorization": token}
        transport = StreamableHttpTransport(url=url, headers=headers)
        self.client = Client(transport)

        # Initialize the provider. We will do this for each step.
        self.init_provider()

    def init_provider(self):
        """
        Initialize the provider.
        """
        # select Backend based on Config/Env first, then cached version
        provider = os.environ.get("FRACTALE_LLM_PROVIDER", "gemini").lower()

        # Other envars come from provider backend
        if provider in backends.BACKENDS:
            self.backend = backends.BACKENDS[provider]()
        else:
            raise ValueError(f"Provider {provider} is not available. Did you install dependencies?")

    async def get_prompts_list(self):
        """
        Get list of prompts. A prompt is technically a persona/role
        that was previously considered an entire agent. Now we pair a prompt
        with an MCP backend and get a full agent.
        """
        async with self.client:
            prompts = await self.client.list_prompts_mcp()
        return prompts

    async def get_tools_list(self):
        """
        Get list of tools.
        """
        async with self.client:
            tools = await self.client.list_tools()
        return tools

    async def execute(self, context, step):
        """
        The Async Loop that will start with a prompt name, retrieve it,
        and then respond to it until the state is successful.
        """
        start_time = time.perf_counter()

        # We keep the client connection open for the duration of the step
        async with self.client:

            # These are tools available to agent
            # TODO need to filter these to be agent specific?
            mcp_tools = await self.client.list_tools()
            await self.backend.initialize(mcp_tools)

            # Get prompt to give goal/task/personality to agent
            args = getattr(context, "data", context)

            # This partitions inputs, adding inputs from the step and separating
            # those from extra
            args, extra = step.partition_inputs(args)
            instruction = await self.fetch_persona(step.prompt, args)
            message = json.loads(instruction)["messages"][0]["content"]["text"]
            self.ui.log(message)

            # Run the loop up to some max attempts (internal state machine with MCP tools)
            response_text = await self.run_llm_loop(instruction, step, context)

        self.record_usage(time.perf_counter() - start_time)
        return response_text

    async def manual_step_run(self, name, args):
        """
        Manually run a step (typically after a generation, like a validation).
        """
        result = await self.client.call_tool(name, args)
        if hasattr(result, "content") and isinstance(result.content, list):
            content = result.content[0].text
        else:
            content = str(result)

        # probably need to harden this more.
        was_error = True if "❌" in content or "Error" in content else False
        self.record_step(name, args, content)
        self.ui.on_step_update(content)
        return was_error, content

    async def call_tools(self, calls):
        """
        call tools.
        """
        tool_outputs = []
        for call in calls:
            t_name = call["name"]
            t_args = call["args"]
            t_id = call.get("id")
            logger.info(f"🛠️  Calling: {t_name}")
            has_error = False

            try:
                result = await self.client.call_tool(t_name, t_args)
                content = result.content[0].text if hasattr(result, "content") else str(result)
            except Exception as e:
                content = f"❌ ERROR: {e}"
                has_error = True
            self.record_step(t_name, t_args, content)
            self.ui.on_step_update(content)
            tool_outputs.append({"id": t_id, "name": t_name, "content": content})
            # Return content (with error) early if we generated one
            if has_error:
                return has_error, content, tool_outputs
        return has_error, content, tool_outputs

    async def run_llm_loop(self, instruction, step, context) -> str:
        """
        Process -> Tool -> Process loop.
        We need to return on some state of success or ultimate failure.
        """
        max_loops = context.get("max_loops", 15)
        loops = 0
        use_tools = step.validate in [None, ""]
        print(f"Using tools? {use_tools}")
        while loops < max_loops:

            loops += 1
            print(f"Calling {instruction}")
            response, reason, calls = self.backend.generate_response(
                prompt=instruction, use_tools=use_tools
            )

            # Reset tool outputs
            tool_outputs = None

            # These are here for debugging now.
            if reason:
                print("🧠 Thinking:")
                self.ui.log(reason)
            if response:
                print("🗣️  Response:")
                self.ui.log(response)
            print("🔨 Tools available:")
            self.ui.log(self.backend.tools_schema)
            if calls:
                print("📞 Calls requested:")
                self.ui.log(calls)

            # We validate OR allow it to call tools.
            # Validate is a manual approach for LLMs that suck at following instructions
            if step.validate:

                # The response may be nested in a code block.
                err, args = self.get_code_block(response)
                if err:
                    print(f" Error parsing code block from response: {err}")
                    instruction = prompts.was_format_error_prompt(response)
                    continue

                err, response = await self.manual_step_run(step.validate, args)
                if err:
                    instruction = prompts.was_error_prompt(response)
                    continue

            # Call tools - good luck.
            elif not calls:
                logger.info("🛑 Agent finished (No tools called).")
                break

            else:
                has_error, response, tool_outputs = await self.call_tools(calls)
                if has_error:
                    instruction = prompts.was_error_prompt(response)
                    continue

            # If we are successful, give back to llm to summarize (and we need to act on its response)
            print("Calling again...")
            response, reason, calls = self.backend.generate_response(tool_outputs=tool_outputs)
            if response:
                self.ui.log(f"🤖 Thought:\n{response}")

        return response

    def get_code_block(self, response, code_type=None):
        """
        Get a code block from the response.
        """
        # If we already have dict, we are good.
        if isinstance(response, dict):
            return None, response

        # Try to json load if already have string
        # Models are adding extra newlines where they shouldn't be...
        try:
            if isinstance(response, str):
                return None, json.loads(response)
        except Exception as e:
            return str(e), None
                
        # We might have a code block nested in other output
        try:
            return None, json.loads(utils.get_code_block(response, code_type))
        except Exception as e:
            return str(e), None

    async def fetch_persona(self, prompt_name: str, arguments: dict) -> str:
        """
        Asks the MCP Server to render the prompt template.

        This is akin to rendering or fetching the person. E.g., "You are X and
        here are your instructions for a task."
        """
        self.ui.log(f"📥 Persona: {prompt_name}")
        prompt_result = await self.client.get_prompt(name=prompt_name, arguments=arguments)
        # MCP Prompts return a list of messages (User/Assistant/Text).
        # We squash them into a single string for the instruction.
        msgs = []
        for m in prompt_result.messages:
            if hasattr(m.content, "text"):
                msgs.append(m.content.text)
            else:
                msgs.append(str(m.content))

        instruction = "\n\n".join(msgs)

        # Set the prompt if we have a ui for it.
        if self.ui and hasattr(self.ui, "on_set_prompt"):
            self.ui.on_set_prompt(instruction)

        return instruction

    def record_step(self, tool, args, output):
        """
        Record step metadata.
        TODO: refactor this into metadata registry (decorator)
        """
        if "steps" not in self.metadata:
            self.metadata["steps"] = []
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
        Record token usage.
        TODO: refactor this into metadata registry (decorator)
        """
        if hasattr(self.backend, "token_usage"):
            usage = self.backend.token_usage
            self.metadata["llm_usage"].append(
                {
                    "duration": duration,
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                }
            )

    def run_step(self, context, step):
        """
        Run step is called from the Agent run (base class)
        It's here so we can asyncio.run the thing!
        """
        try:
            final_result = asyncio.run(self.execute(context, step))
            print("final result")
            import IPython

            IPython.embed()
            context.result = final_result
        except Exception as e:
            context["error_message"] = str(e)
            logger.error(f"Agent failed: {e}")
            raise e
        return context
