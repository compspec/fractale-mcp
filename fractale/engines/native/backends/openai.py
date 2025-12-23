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
        one_off: bool = False,
        tools: List[str] = None,  # <--- NEW ARGUMENT
    ) -> Tuple[str, str, List[Dict]]:
        """
        Generate the response and update history.
        """
        # TODO: Implement one_off logic

        if prompt:
            self.history.append({"role": "user", "content": prompt})

        if tool_outputs:
            for out in tool_outputs:
                # Match name sanitization (docker-build -> docker_build)
                llm_name = out["name"].replace("-", "_")
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": out["id"],
                        "name": llm_name,
                        "content": str(out["content"]),
                    }
                )

        # --- TOOL CONFIGURATION LOGIC ---
        api_tools = self.tools_schema if self.tools_schema else None
        tool_choice = "auto" if api_tools else None

        if not use_tools:
            api_tools = None
            tool_choice = None
        elif tools:
            # 1. Sanitize requested names to match schema
            target_names = [t.replace("-", "_") for t in tools if t]

            # 2. Filter the schema list passed to the API
            api_tools = [t for t in self.tools_schema if t["function"]["name"] in target_names]

            # 3. Determine forcing strategy
            if len(target_names) == 1:
                # Force specific function
                tool_choice = {"type": "function", "function": {"name": target_names[0]}}
            else:
                # Force any function from the filtered list
                tool_choice = "required"

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=self.history,
            tools=api_tools,
            tool_choice=tool_choice,
        )

        print(response)
        msg = response.choices[0].message

        self.history.append(msg)

        if response.usage:
            self._usage = dict(response.usage)

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,  # Underscored name
                        "args": json.loads(tc.function.arguments),
                    }
                )

        reasoning = getattr(msg, "reasoning_content", "")
        return msg.content or "", reasoning, tool_calls

    @property
    def token_usage(self):
        return self._usage
