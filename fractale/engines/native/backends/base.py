import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple


class LLMBackend(ABC):
    """
    Abstract interface for any LLM provider (Gemini, OpenAI, Llama, Local).
    """

    def __init__(self):
        self.tools_schema = []

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
        # TODO: Add a max_retries counter here to prevent infinite recursion
        try:
            return json.loads(response)
        except Exception as e:
            prompt = f"Your response {response} was not valid json: {e}. Please return valid JSON."
            # Call self, not self.backend
            response, _, _ = self.generate_response(prompt=prompt)
            return self.ensure_json(response)

    def select_tools(self, use_tools=True):
        """
        Clean logic to decide to use a tool or not for OpenAI-compatible endpoints.
        """
        if not use_tools or not self.tools_schema:
            return {"tools": None, "tool_choice": None}

        # OpenAI expects auto, none, or required (or specific tool)
        # We default to auto if tools are allowed and present.
        return {"tools": self.tools_schema, "tool_choice": "auto"}

    @abstractmethod
    def generate_response(
        self,
        prompt: str = None,
        tool_outputs: List[Dict] = None,
        use_tools: bool = True,
        one_off: bool = False,
        tools: List[str] = None,
    ):
        """
        Returns a tuple: (text_content, reasoning_content, tool_calls)
        """
        pass

    @property
    @abstractmethod
    def token_usage(self) -> Dict:
        """
        Return token stats for metadata stuffs.
        """
        pass
