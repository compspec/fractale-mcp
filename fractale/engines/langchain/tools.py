from langchain_core.tools import StructuredTool
from pydantic import create_model


async def get_langchain_tools(client):
    """
    Fetches tools from MCP and converts them to LangChain StructuredTools.
    """
    mcp_tools = await client.list_tools()
    tools = []

    for tool in mcp_tools:
        # 1. Create Pydantic Model for args dynamically
        # LangChain requires Pydantic models for structured input
        fields = {}
        # Simple mapping: assume everything is string/any for robustness
        # In a strict implementation, we'd map JSON Schema types to Python types
        for arg_name in tool.inputSchema.get("properties", {}).keys():
            fields[arg_name] = (str, ...)  # Type, Default

        ArgsModel = create_model(f"{tool.name}_args", **fields)

        # 2. Define the Async Runner
        # We must bind the specific tool name to the closure
        async def run_tool(tool_name=tool.name, **kwargs):
            try:
                res = await client.call_tool(tool_name, kwargs)
                if hasattr(res, "content") and res.content:
                    return res.content[0].text
                return str(res)
            except Exception as e:
                return f"Error: {e}"

        # Create the Tool
        tool = StructuredTool.from_function(
            func=None,
            coroutine=run_tool,  # async
            name=tool.name,
            description=tool.description,
            args_schema=ArgsModel,
        )
        tools.append(tool)

    return tools
