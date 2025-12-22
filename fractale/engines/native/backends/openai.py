import json
import os
from typing import Any, Dict, List, Tuple

from rich import print

from fractale.core.config import ModelConfig

from .base import LLMBackend


class OpenAIBackend(LLMBackend):
    """
    Backend to use OpenAI
    """

    def __init__(self, config: ModelConfig):
        super().__init__()
        import openai

        self.client = openai.OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.model_name = config.model_name
        self.history = []
        self.tools_schema = []
        self._usage = {}

    async def initialize(self, mcp_tools: List[Any]):
        """
        Convert MCP tools to OpenAI Schema.
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

    def generate_response(
        self,
        prompt: str = None,
        tool_outputs: List[Dict] = None,
        use_tools: bool = True,
        one_off: bool = False,  # OpenAI doesn't natively support easy one-off without managing history manually
    ) -> Tuple[str, str, List[Dict]]:
        """
        Generate the response and update history.
        """
        # TODO: Implement one_off logic if needed (creating temp client or copying history)

        if prompt:
            self.history.append({"role": "user", "content": prompt})

        if tool_outputs:
            for out in tool_outputs:
                self.history.append(
                    {"role": "tool", "tool_call_id": out["id"], "content": str(out["content"])}
                )

        # Use helper from base class to get tool config
        # This handles the 'auto' vs None logic
        api_args = self.select_tools(use_tools)

        response = self.client.chat.completions.create(
            model=self.model_name, messages=self.history, **api_args
        )

        print(response)
        msg = response.choices[0].message

        # Save assistant reply to history
        self.history.append(msg)

        if response.usage:
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

        # OpenAI (via O1 or DeepSeek via compatible endpoints) might have reasoning_content
        # Standard GPT-4o does not usually expose this field directly in the message object property
        # unless using specific beta headers, but we return empty string for now.
        reasoning = getattr(msg, "reasoning_content", "")

        return msg.content or "", reasoning, tool_calls

    @property
    def token_usage(self):
        return self._usage
