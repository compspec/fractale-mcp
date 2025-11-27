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

    @abstractmethod
    def generate_response(self, prompt: str = None, tool_outputs: List[Dict] = None):
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
