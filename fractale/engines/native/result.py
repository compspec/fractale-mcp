import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union


@dataclass
class ToolResult:
    """
    Standardized client-side view of a tool execution.
    """

    content: str  # The human-readable string (for UI and LLM context)
    data: Optional[Dict]  # The structured data (if JSON was returned)
    is_error: bool  # Success/Fail flag
    error_message: Optional[str] = None


def parse_tool_response(raw_response: Any) -> ToolResult:
    """
    Parses the raw return value from fastmcp.Client.call_tool into a robust ToolResult.
    Handles:
    1. FastMCP Protocol objects (CallToolResult)
    2. JSON Strings
    3. Python Dictionaries
    4. Plain Text
    """
    content = ""

    # 1. Unwrap FastMCP Protocol Object
    # FastMCP returns an object with a 'content' list of TextContent items
    if hasattr(raw_response, "content") and isinstance(raw_response.content, list):
        # Join multiple content blocks if present
        content = "\n".join([c.text for c in raw_response.content if hasattr(c, "text")])
    else:
        # Fallback for raw strings or other types
        content = str(raw_response)

    # 2. Attempt JSON Parsing (to get structured data)
    data = None
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass

    # 3. Determine Error Status
    is_error = False
    error_msg = None

    # Strategy A: Structured Checks (Priority)
    if isinstance(data, dict):
        # Check standard conventions for exit codes or status keys
        if data.get("returncode", 0) != 0:
            is_error = True
        elif data.get("exit_code", 0) != 0:
            is_error = True
        elif data.get("status", "").lower() in ["error", "failure", "failed"]:
            is_error = True
        elif data.get("is_error"):
            is_error = True

    # Strategy B: String Heuristics (Fallback)
    # If no structured signal found, look for visual markers in the text
    if not is_error:
        # Matches the Result.render() format we defined earlier
        if "❌" in content or "STATUS: FAILURE" in content or "CRITICAL ERROR" in content:
            is_error = True

    if is_error:
        error_msg = content  # Use the full content as the error description

    return ToolResult(content=content, data=data, is_error=is_error, error_message=error_msg)
