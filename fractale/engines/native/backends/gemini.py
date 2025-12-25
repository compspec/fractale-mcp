import os
from typing import Any, Dict, List, Tuple

from fractale.core.config import ModelConfig

from .base import LLMBackend

default_model = "gemini-2.5-pro"


class GeminiBackend(LLMBackend):
    def __init__(self, config: ModelConfig):
        super().__init__()
        from google import genai
        from google.genai import types

        self.genai = genai
        self.types = types

        self.api_key = config.api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")

        self.model_name = config.model_name or default_model
        self.chat = None
        self.client = None
        self.tools_config = None
        self._usage = {}

    async def initialize(self, mcp_tools: List[Any]):
        """
        Initialize the client and chat session with tools using the new SDK.
        """
        self.client = self.genai.Client(api_key=self.api_key)

        # Convert MCP tools to Gemini types...
        function_declarations = []

        for tool in mcp_tools:
            if "-" in tool.name or " " in tool.name:
                raise ValueError(
                    f"❌ Invalid Tool Name: '{tool.name}'\n"
                    f"Gemini API does not allow hyphens or spaces in function names.\n"
                    f"Please rename this tool in your MCP Server (e.g. use '{tool.name.replace('-', '_')}')."
                )

            # Deep copy and clean schema
            schema = tool.inputSchema.copy()
            self._clean_schema(schema)

            # Gemini needs specific types, probably for protobuf
            func_decl = self.types.FunctionDeclaration(
                name=tool.name, description=tool.description, parameters=schema
            )
            function_declarations.append(func_decl)

        # Again, a "Tool" container
        if function_declarations:
            self.tools_obj = [self.types.Tool(function_declarations=function_declarations)]
        else:
            self.tools_obj = None

        # In the new SDK, we create the chat via the client
        # We pass the tools configuration here so the chat session knows about them
        self.chat = self.client.chats.create(
            model=self.model_name, config=self.types.GenerateContentConfig(tools=self.tools_obj)
        )

    def _clean_schema(self, obj):
        """
        Recursive helper to fix types / remove defaults for Gemini Schema.
        """
        if isinstance(obj, dict):
            if "default" in obj:
                del obj["default"]

            # Gemini prefers uppercase types (STRING, OBJECT, etc)
            if "type" in obj and isinstance(obj["type"], str):
                obj["type"] = obj["type"].upper()
            for k, v in list(obj.items()):
                self._clean_schema(v)
        elif isinstance(obj, list):
            for item in obj:
                self._clean_schema(item)

    def generate_response(
        self,
        prompt: str = None,
        tool_outputs: List[Dict] = None,
        use_tools: bool = True,
        one_off: bool = False,
        tools: List[str] = None,
    ) -> Tuple[str, Any, List[Dict]]:
        """
        Generate response from Gemini using the new SDK patterns.
        """
        # Function calling config
        fc_config = None

        if not use_tools or not self.tools_obj:
            fc_config = self.types.FunctionCallingConfig(mode="NONE")
        elif tools:
            # Force specific tools (ANY) with allowed_function_names
            sanitized_names = [t.replace("-", "_") for t in tools if t]
            fc_config = self.types.FunctionCallingConfig(
                mode="ANY", allowed_function_names=sanitized_names
            )
        else:
            fc_config = self.types.FunctionCallingConfig(mode="AUTO")

        # function_calling_config must be wrapped in ToolConfig
        tool_config_obj = self.types.ToolConfig(function_calling_config=fc_config)

        config = self.types.GenerateContentConfig(
            tools=self.tools_obj if use_tools else None,
            tool_config=tool_config_obj,
            temperature=0.0,
        )

        response = None

        try:
            # One-off (stateless)
            if one_off:
                if not prompt:
                    return "", None, []
                response = self.client.models.generate_content(
                    model=self.model_name, contents=prompt, config=config
                )

            # Chat (memory)
            else:
                # If we have tool outputs, we are completing a turn
                if tool_outputs:
                    parts = []
                    for output in tool_outputs:
                        parts.append(
                            self.types.Part.from_function_response(
                                name=output["name"].replace("-", "_"),
                                response={"result": output["content"]},
                            )
                        )
                    # Send the tool outputs back to the chat
                    response = self.chat.send_message(parts)

                # Otherwise, it's a new user prompt
                elif prompt:
                    # Update the chat's config for this specific turn
                    response = self.chat.send_message(prompt, config=config)

        except Exception as e:
            return f"Error communicating with Gemini: {str(e)}", None, []

        if not response:
            return "", None, []

        # Usage...
        if response.usage_metadata:
            self._usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
            }

        if not response.candidates:
            return "Error: Blocked by safety filters or empty response", None, []

        # And content.
        candidate = response.candidates[0]
        text_content = ""
        tool_calls = []

        for part in candidate.content.parts:
            if part.text:
                text_content += part.text

            if part.function_call:
                tool_calls.append(
                    {"name": part.function_call.name, "args": part.function_call.args}
                )

        reasoning_content = None
        return text_content, reasoning_content, tool_calls

    @property
    def token_usage(self):
        return self._usage
