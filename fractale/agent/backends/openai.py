from typing import Any, Dict, List

from openai import AsyncOpenAI

from .llm import LLMBackend


class OpenAIBackend(LLMBackend):
    """
    Backend to use OpenAI (not tested yet)
    """

    def __init__(self, model_name="gpt-4o"):
        self.client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.model_name = model_name
        self.history = []
        self.tools_schema = []
        self._usage = {}

    async def initialize(self, mcp_tools: List[Any]):
        """
        Tell this jerk about all the MCP tools.
        """
        self.tools_schema = []
        for tool in mcp_tools:
            self.tools_schema.append(
                {
                    "type": "function",
                    "function": {
                        # OpenAI is fine with dashes
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
            )

    async def generate_response(self, prompt: str = None, tool_outputs: List[Dict] = None):
        """
        Generate the response and update history.
        """
        if prompt:
            self.history.append({"role": "user", "content": prompt})
        if tool_outputs:
            for out in tool_outputs:
                self.history.append(
                    {"role": "tool", "tool_call_id": out["id"], "content": str(out["content"])}
                )

        # Call API
        response = await self.client.chat.completions.create(
            model=self.model_name, messages=self.history, tools=self.tools_schema or None
        )

        msg = response.choices[0].message

        # Save assistant reply to history
        self.history.append(msg)
        self._usage = dict(response.usage)

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        # OpenAI needs IDs
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments),
                    }
                )

        return msg.content, tool_calls

    @property
    def token_usage(self):
        return self._usage
