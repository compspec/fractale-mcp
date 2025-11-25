import os
from typing import Any, Dict, List

import google.generativeai as genai

from .llm import LLMBackend


class GeminiBackend(LLMBackend):
    def __init__(self, model_name="gemini-1.5-pro"):
        """
        Init Gemini! We can try the newer one (3.0) when we test.
        """
        try:
            genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        # I'm allowing this for now because I don't have a working one...
        except KeyError:
            print("❌ GEMINI_API_KEY missing.")
        self.model_name = model_name
        self.chat = None
        self._usage = {}

    async def initialize(self, mcp_tools: List[Any]):
        """
        Convert MCP tools to Gemini Format
        """
        gemini_tools = []
        for tool in mcp_tools:
            gemini_tools.append(
                {
                    "name": tool.name.replace("-", "_"),  # Gemini hates dashes
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                }
            )

        model = genai.GenerativeModel(self.model_name, tools=gemini_tools)
        self.chat = model.start_chat(enable_automatic_function_calling=False)

    async def generate_response(self, prompt: str = None, tool_outputs: List[Dict] = None):
        """
        Generate Gemini response.

        This is currently setup as a chat - we need to make sure we can do a one-off
        message (no memory or bias).
        """
        response = None

        # Sending tool outputs (previous turn was a function call)
        if tool_outputs:
            parts = []
            for output in tool_outputs:
                parts.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=output["name"].replace("-", "_"),
                            response={"result": output["content"]},
                        )
                    )
                )
            response = await self.chat.send_message_async(genai.protos.Content(parts=parts))

        # Sending new text
        elif prompt:
            response = await self.chat.send_message_async(prompt)

        # Extract Logic
        self._usage = {
            "prompt_tokens": response.usage_metadata.prompt_token_count,
            "completion_tokens": response.usage_metadata.candidates_token_count,
        }

        part = response.candidates[0].content.parts[0]
        text_content = response.text if not part.function_call else ""

        tool_calls = []
        if part.function_call:
            fc = part.function_call
            tool_calls.append(
                {"name": fc.name.replace("_", "-"), "args": dict(fc.args)}  # Map back to MCP
            )

        return text_content, tool_calls

    @property
    def token_usage(self):
        return self._usage
