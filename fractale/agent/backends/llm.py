import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List


class LLMBackend(ABC):
    """
    Abstract interface for any LLM provider (Gemini, OpenAI, Llama, Local).
    """

    @abstractmethod
    async def initialize(self, mcp_tools: List[Any]):
        """
        Convert MCP tools to provider-specific format and setup session.
        """
        pass

    def ensure_json(self, response):
        """
        Require an LLM to return json.
        """
        while True:
            try:
                return json.loads(response)
            except Exception as e:
                prompt = f"Your response {response} was not valid json: {e}"
                response, _, _ = self.backend.generate_response(prompt=prompt)

    def select_tools(self, use_tools=True):
        """
        Clean logic to decide to use a tool or not.
        """
        if not use_tools:
            return {}

        # TODO: we could apply more filters here.
        tool_schema = self.tool_schema
        tool_choice = "auto"
        print(f"Tool choice: {tool_choice}")
        print(f"Tool schema: {tools_schema}")
        return {"tool_choice": tool_choice, "tools": tool_schema}

    @abstractmethod
    def generate_response(
        self, prompt: str = None, tool_outputs: List[Dict] = None, use_tools=True
    ):
        """
        Returns a text_response, tool_calls
        """
        pass

    @property
    @abstractmethod
    def token_usage(self) -> Dict:
        """
        Return token stats for metadata stuffs.

        Note from V: we need a more robust provenance tracking thing.
        """
        pass
