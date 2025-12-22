import json
import os
from typing import Any, Dict, List, Tuple

import fractale.engines.native.prompts as prompts
from fractale.core.config import ModelConfig

from .base import LLMBackend


class LlamaBackend(LLMBackend):
    """
    Backend for Meta Llama 3.1+ models via OpenAI-Compatible endpoints (Ollama, Groq, vLLM).
    """

    def __init__(self, config: ModelConfig):
        super().__init__()

        # Use config for connection, fallback to defaults for local Ollama
        base_url = config.base_url or "http://localhost:11434/v1"
        api_key = config.api_key or "ollama"

        import openai

        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model_name = config.model_name or "llama3.1"

        self.disable_history = os.environ.get("LLAMA_DISABLE_HISTORY") is not None
        self.history = []
        self.tools_schema = []
        self._usage = {}

    async def initialize(self, mcp_tools: List[Any]):
        """
        Llama 3.1 follows the OpenAI Tool Schema standard.
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
    ) -> Tuple[str, str, List[Dict]]:
        """
        Manage history and call Llama.
        """
        # TODO: Implement one_off support

        if prompt:
            # Llama does better with a system prompt if history is empty
            if not self.history:
                self.history.append(
                    {
                        "role": "system",
                        "content": prompts.with_tools if use_tools else prompts.without_tools,
                    }
                )
            self.history.append({"role": "user", "content": prompt})

        # Handle tool outputs
        if tool_outputs and use_tools and not self.disable_history:
            for out in tool_outputs:
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": out["id"],
                        "content": str(out["content"]),
                    }
                )

        # Get tool args from base helper
        api_args = self.select_tools(use_tools)

        try:
            response = self.client.chat.completions.create(
                model=self.model_name, messages=self.history, **api_args
            )
        except Exception as e:
            return f"LLAMA API ERROR: {str(e)}", "", []

        print(f"Response {response}")
        msg = response.choices[0].message

        if response.usage:
            self._usage = dict(response.usage)

        # Store history if not disabled
        if not self.disable_history:
            self.history.append(msg)

        text_content = msg.content or ""

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

        return text_content, getattr(msg, "reasoning_content", ""), tool_calls

    @property
    def token_usage(self):
        return self._usage
