import asyncio
import json
import os
import time

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from rich import print

import fractale.agent.backends as backends
import fractale.agent.defaults as defaults
import fractale.agent.logger as logger
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

    async def run_llm_loop(self, instruction, step, context) -> str:
        """
        Process -> Tool -> Process loop.
        We need to return on some state of success or ultimate failure.
        """
        max_loops = context.get("max_loops", 15)
        loops = 0
        while loops < max_loops:
            loops += 1

            # We aren't getting calls back reliably, so we ignore them.
            # But we do allow the LLM to see functions available for signatures.
            response, reason, _ = self.backend.generate_response(prompt=instruction)
            self.ui.log(reason)

            # If we don't have a validate step, we are done.
            if not step.validate:
                self.ui.log("🎢 No request for validation, ending loop.")
                return response

            # The response text needs to be valid (load into json)
            response = self.backend.ensure_json(response)
            # TODO need to better get args for validate here

            # We next validate
            result = await self.client.call_tool(step.validate, response)
            if hasattr(result, "content") and isinstance(result.content, list):
                content = result.content[0].text
            else:
                content = str(result)

            # probably need to harden this more... want to return on 🟢 Success!
            if "❌" not in content and "Error" not in content:
                return content

            # 5. FAILURE: Update instruction and Loop
            instruction = f"The previous attempt failed:\n{content}\nPlease fix inputs and retry."
            self.ui.log(f"⚠️ Validation Failed. Retrying... ({loops}/{max_loops})")

            print("TODO need validation step to return some success / error code")
            print(content)
            # Record metadata about the step
            self.record_step(step.validate, response, content)

        # When we get here, we have validated
        return content

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
            context.result = final_result
        except Exception as e:
            context["error_message"] = str(e)
            logger.error(f"Agent failed: {e}")
            raise e
        return context
