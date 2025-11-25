import asyncio
import os
import time

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

import fractale.agent.backends as backends
import fractale.agent.logger as logger
from fractale.agent.base import Agent


class MCPAgent(Agent):
    """
    Backend-Agnostic Agent that uses MCP Tools.
    """

    def init(self):
        # 1. Setup MCP Client
        port = os.environ.get("FRACTALE_MCP_PORT", "8089")
        token = os.environ.get("FRACTALE_MCP_TOKEN")
        url = f"http://localhost:{port}/mcp"

        if token:
            transport = StreamableHttpTransport(url=url, headers={"Authorization": token})
            self.client = Client(transport)
        else:
            self.client = Client(url)

        # 2. Select Backend based on Config/Env
        provider = os.environ.get("FRACTALE_LLM_PROVIDER", "gemini").lower()
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

    async def execute_mission_async(self, prompt_text: str):
        """
        The Async Loop: Think -> Act -> Observe -> Think
        """
        start_time = time.perf_counter()

        # 1. Connect & Discover Tools
        async with self.client:
            mcp_tools = await self.client.list_tools()

            # 2. Initialize Backend with these tools
            await self.backend.initialize(mcp_tools)

            # 3. Initial Prompt
            # 'response_text' is what the LLM says to the user
            # 'calls' is a list of tools it wants to run
            response_text, calls = await self.backend.generate_response(prompt=prompt_text)

            max_loops = 15
            loops = 0

            while loops < max_loops:
                loops += 1

                # If there are tool calls, we MUST execute them and feed back results
                if calls:
                    tool_outputs = []

                    for call in calls:
                        t_name = call["name"]
                        t_args = call["args"]
                        t_id = call.get("id")  # Needed for OpenAI

                        logger.info(f"🛠️ Tool Call: {t_name} {t_args}")

                        # --- EXECUTE TOOL ---
                        try:
                            result = await self.client.call_tool(t_name, t_args)
                            # Handle FastMCP result object
                            output_str = (
                                result.content[0].text
                                if hasattr(result, "content")
                                else str(result)
                            )
                        except Exception as e:
                            output_str = f"Error: {str(e)}"

                        # Record Metadata (Your Requirement)
                        self._record_step(t_name, t_args, output_str)

                        tool_outputs.append({"name": t_name, "content": output_str, "id": t_id})

                    # --- FEEDBACK LOOP ---
                    # We pass the outputs back to the backend.
                    # It returns the NEXT thought.
                    response_text, calls = await self.backend.generate_response(
                        tool_outputs=tool_outputs
                    )

                else:
                    # No tool calls? The LLM is done thinking.
                    break

        end_time = time.perf_counter()

        # Save Summary Metadata
        self.save_mcp_metadata(end_time - start_time)

        return response_text

    def _record_step(self, tool, args, output):
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

    def save_mcp_metadata(self, duration):
        """Save token usage from backend."""
        usage = self.backend.token_usage
        if "llm_usage" not in self.metadata:
            self.metadata["llm_usage"] = []

        self.metadata["llm_usage"].append(
            {
                "duration": duration,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }
        )

    def run_step(self, context):
        """
        Bridge the sync Base Class to the async implementation.
        """
        prompt_text = self.get_prompt(context)

        try:
            # Run the loop
            final_result = asyncio.run(self.execute_mission_async(prompt_text))
            context["result"] = final_result
        except Exception as e:
            context["error_message"] = str(e)
            logger.error(f"Agent failed: {e}")
            raise  # Or handle gracefully depending on policy

        return context
