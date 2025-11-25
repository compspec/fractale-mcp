import json
import os
from typing import Any, Dict, List

from openai import AsyncOpenAI

from .llm import LLMBackend


class LlamaBackend(LLMBackend):
    """
    Backend for Meta Llama 3.1+ models.
    """

    def __init__(self, model_name=None):
        # This should be provided by LLAMAME but I haven't tested.
        # Why is a llama trying to call me that's not OK. Not sure if I need ollama
        base_url = os.environ.get("LLAMA_BASE_URL", "http://localhost:11434/v1")
        api_key = os.environ.get("LLAMA_API_KEY", "ollama")

        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)

        # Default to Llama 3.1 8B if not specified
        self.model_name = model_name or os.environ.get("LLAMA_MODEL", "llama3.1")

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

    async def generate_response(self, prompt: str = None, tool_outputs: List[Dict] = None):
        """
        Manage history and call Llama.
        """
        if prompt:
            # Check if we have a System Prompt set (usually the first message).
            # If not, Llama often behaves better with one.
            if not self.history:
                self.history.append(
                    {
                        "role": "system",
                        "content": "You are a helpful assistant with access to tools. You must use them to answer questions.",
                    }
                )
            self.history.append({"role": "user", "content": prompt})

        # Handle tool outputs (Function results)
        if tool_outputs:
            for out in tool_outputs:
                self.history.append(
                    {
                        "role": "tool",
                        # Required for the conversation graph
                        "tool_call_id": out["id"],
                        "content": str(out["content"]),
                    }
                )

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=self.history,
                tools=self.tools_schema or None,
                tool_choice="auto" if self.tools_schema else None,
            )
        except Exception as e:
            return f"LLAMA API ERROR: {str(e)}", []

        msg = response.choices[0].message
        if response.usage:
            self._usage = dict(response.usage)
        # Store history and get text content
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

        return text_content, tool_calls

    @property
    def token_usage(self):
        return self._usage
