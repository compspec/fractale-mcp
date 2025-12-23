import os
from typing import Any, Dict, List, Tuple

from fractale.core.config import ModelConfig

from .base import LLMBackend

default_model = "gemini-2.5-pro"


class GeminiBackend(LLMBackend):
    def __init__(self, config: ModelConfig):
        super().__init__()
        import google.generativeai as genai

        self.genai = genai

        # TODO: think about how fits with model config.
        # I'm not sure what best security model is
        api_key = config.api_key or os.environ.get("GEMINI_API_KEY")
        try:
            genai.configure(api_key=api_key)
        except KeyError:
            print("❌ GEMINI_API_KEY missing.")

        self.model_name = config.model_name or default_model
        self.chat = None
        self.model = None
        self.tools_schema = []
        self._usage = {}

    async def initialize(self, mcp_tools: List[Any]):
        """
        Initialize the model and chat session with tools.
        """
        self.tools_schema = []

        # Convert MCP tools to Gemini Schema
        for tool in mcp_tools:
            if "-" in tool.name or " " in tool.name:
                raise ValueError(
                    f"❌ Invalid Tool Name: '{tool.name}'\n"
                    f"Gemini API does not allow hyphens or spaces in function names.\n"
                    f"Please rename this tool in your MCP Server (e.g. use '{tool.name.replace('-', '_')}')."
                )

            schema = tool.inputSchema.copy()

            # Recursive helper to fix types / remove defaults
            def clean_schema(obj):
                if isinstance(obj, dict):
                    if "default" in obj:
                        del obj["default"]
                    if "type" in obj and isinstance(obj["type"], str):
                        obj["type"] = obj["type"].upper()
                    for k, v in list(obj.items()):
                        clean_schema(v)
                elif isinstance(obj, list):
                    for item in obj:
                        clean_schema(item)

            # Cleaning, cleaning, all I do is cleaning...
            clean_schema(schema)
            self.tools_schema.append(
                {"name": tool.name, "description": tool.description, "parameters": schema}
            )

        # Create the main stateful model and chat
        self.model = self.genai.GenerativeModel(self.model_name, tools=self.tools_schema)
        self.chat = self.model.start_chat(enable_automatic_function_calling=False)

    def generate_response(
        self,
        prompt: str = None,
        tool_outputs: List[Dict] = None,
        use_tools: bool = True,
        one_off: bool = False,
        tools: List[str] = None,
    ):
        """
        Generate response from Gemini.

        Args:
            allowed_tools: A list of tool names (e.g. ["docker-build"]) to restrict the model to.
                           If provided, the model MUST call one of these tools.
        """
        tool_config = {}

        if not use_tools:
            # Force no tools
            tool_config = {"function_calling_config": {"mode": "NONE"}}

        elif tools:
            # Force specific tools
            # We must sanitize names (docker-build -> docker_build) to match Gemini's schema
            sanitized_names = [t.replace("-", "_") for t in tools if t]

            tool_config = {
                "function_calling_config": {
                    "mode": "ANY",  # 'ANY' forces the model to call a tool
                    "allowed_function_names": sanitized_names,
                }
            }
        else:
            # Let model decide freely
            tool_config = {"function_calling_config": {"mode": "AUTO"}}

        response = None

        # Stateless one off model
        if one_off:
            if not prompt:
                return "", None, []
            response = self.model.generate_content(prompt, tool_config=tool_config)

        # Chat mode (memory)
        else:
            if tool_outputs:
                parts = []
                for output in tool_outputs:
                    parts.append(
                        self.genai.protos.Part(
                            function_response=self.genai.protos.FunctionResponse(
                                name=output["name"].replace("-", "_"),
                                response={"result": output["content"]},
                            )
                        )
                    )
                response = self.chat.send_message(
                    self.genai.protos.Content(parts=parts), tool_config=tool_config
                )
            elif prompt:
                response = self.chat.send_message(prompt, tool_config=tool_config)

        if not response:
            return "", None, []

        # Usage Metadata
        if hasattr(response, "usage_metadata"):
            self._usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
            }

        if not response.candidates:
            return "Error: Blocked by safety filters or empty response", None, []

        candidate = response.candidates[0]
        part = candidate.content.parts[0]

        # Extract Text and tool calls
        text_content = ""
        if hasattr(part, "text") and part.text:
            text_content = part.text

        tool_calls = []
        if part.function_call:
            fc = part.function_call

            def proto_to_dict(obj):
                type_name = type(obj).__name__
                if type_name == "RepeatedComposite":
                    return [proto_to_dict(x) for x in obj]
                elif type_name == "MapComposite":
                    return {k: proto_to_dict(v) for k, v in obj.items()}
                else:
                    return obj

            tool_calls.append({"name": fc.name, "args": proto_to_dict(fc.args)})

        # Gemini reasoning is mixed in text usually
        reasoning_content = None
        return text_content, reasoning_content, tool_calls

    @property
    def token_usage(self):
        return self._usage
