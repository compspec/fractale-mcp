import os
from typing import Any, Dict, List

from rich import print

from .llm import LLMBackend


class OpenAIBackend(LLMBackend):
    """
    Backend to use OpenAI
    """

    def __init__(self, model_name="openai/gpt-oss-120b"):
        # Needs to be tested if base url is None.
        # Switch to async if/when needed. Annoying for development
        # self.client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"), base_url=os.environ.get("OPENAI_BASE_URL"))
        import openai

        self.client = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"), base_url=os.environ.get("OPENAI_BASE_URL")
        )
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
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
            )

    def generate_response(self, prompt: str = None, tool_outputs: List[Dict] = None):
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

        # If we have a schema, force to call a tool.
        # We will need to figure out what to do when we want to finish.
        tool_choice = "auto" if self.tools_schema else None

        # Call API (this doesn't need async I don't think, unless we create an async client)
        print(tool_choice)
        print(self.tools_schema)
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=self.history,
            tools=self.tools_schema or None,
            tool_choice=tool_choice,
        )
        print(response)
        msg = response.choices[0].message

        # Save assistant reply to history
        self.history.append(msg)
        self._usage = dict(response.usage)

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments),
                    }
                )

        return msg.content, msg.reasoning_content, tool_calls

    @property
    def token_usage(self):
        return self._usage
