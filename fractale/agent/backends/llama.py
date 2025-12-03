import json
import os
from typing import Any, Dict, List

import fractale.agent.backends.prompts as prompts

from .llm import LLMBackend


class LlamaBackend(LLMBackend):
    """
    Backend for Meta Llama 3.1+ models.
    """

    def __init__(self, model_name="meta-llama/Llama-3.3-70B-Instruct"):
        base_url = os.environ.get("LLAMA_BASE_URL", "http://localhost:11434/v1")
        api_key = os.environ.get("LLAMA_API_KEY", "ollama")
        self.disable_history = os.environ.get("LLAMA_DISABLE_HISTORY") is not None

        # self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        import openai

        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model_name = os.environ.get("LLAMA_MODEL") or model_name

        self.history = []
        self.tools_schema = []
        self._usage = {}

    async def initialize(self, mcp_tools: List[Any]):
        """
        Llama 3.1 follows the OpenAI Tool Schema standard.

        TODO: vsoch see if we can consolidate with OpenAI base when testing.
        """
        self.tools_schema = []
        for tool in mcp_tools:
            self.tools_schema.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,  # Llama handles dashes fine
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
            )

    def generate_response(
        self, prompt: str = None, tool_outputs: List[Dict] = None, use_tools=True
    ):
        """
        Manage history and call Llama.
        """
        if prompt:
            # llama does better with system prompt.
            if not self.history:
                self.history.append(
                    {
                        "role": "system",
                        "content": prompts.with_tools if use_tools else prompts.without_tools,
                    }
                )
            # We have to add this to history, the main prompt.
            self.history.append({"role": "user", "content": prompt})

        # Handle tool outputs (Function results)
        if tool_outputs and use_tools and not self.disable_history:
            for out in tool_outputs:
                self.history.append(
                    {
                        "role": "tool",
                        # Required for the conversation graph
                        "tool_call_id": out["id"],
                        "content": str(out["content"]),
                    }
                )

        # Derive choice and options - we can add additional filters here.
        tool_args = self.select_tools(use_tools)
        try:
            response = self.client.chat.completions.create(
                model=self.model_name, messages=self.history, **tool_args
            )
        except Exception as e:
            return f"LLAMA API ERROR: {str(e)}", "", []

        print(f"Response {response}")
        msg = response.choices[0].message
        if response.usage:
            self._usage = dict(response.usage)

        # Store history and get text content ONLY if not disabled.
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

        return text_content, msg.reasoning_content, tool_calls

    @property
    def token_usage(self):
        return self._usage
