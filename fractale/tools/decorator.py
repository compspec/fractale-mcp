import functools
import time
from typing import List

from fractale.metrics import DurationMetric, metrics


class McpProxy:
    """
    Looks like FastMCP. It just marks functions so we can find them later.
    We want to do this so we can dynamically define / add functions.
    We also might want to allow extended attributes to be added.
    """

    def tool(self, name: str = None, description: str = None, tags: List[str] = None):
        """
        MCP tool decorator as proxy to mcp.tool()
        """

        def decorator(func):

            def record_timing(start_time, error=None):
                """
                Wrapper to record timing of tool.
                """
                end_time = time.perf_counter()
                tool_id = name or func.__name__

                # Create the specific Metric object
                metric = DurationMetric(
                    name=tool_id,
                    start_time=start_time,
                    end_time=end_time,
                    duration=end_time - start_time,
                    success=(error is None),
                    metadata={"error": str(error)} if error else {},
                )

                # Push to generic registry
                metrics.record(metric)
                return metric.duration

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.perf_counter()
                result = func(*args, **kwargs)
                dur = record_timing(start)
                # Add the duration to the result for the LLM
                result += f"\n\n[⏱️ {dur:.2f}s]"
                return result

            wrapper = sync_wrapper
            default_name = (func.__module__.lower() + "-" + func.__name__.lower()).replace(".", "-")
            wrapper._mcp_name = name or default_name
            wrapper._mcp_desc = description
            wrapper._mcp_tags = tags
            wrapper._is_mcp_tool = True
            return wrapper

        return decorator

    def prompt(self, name=None, description=None, meta=None, tags: List[str] = None):
        """
        MCP prompt decorator as proxy to mcp.prompt()
        """

        def decorator(func):
            func._mcp_description = description
            func._is_mcp_prompt = True
            func._mcp_name = name
            func._mcp_meta = meta
            func._mcp_tags = tags

            return func

        return decorator

    def resource(self, uri: str, tags: List[str] = None):
        """
        MCP resource decorator as proxy to mcp.resource()
        """

        def decorator(func):
            func._is_mcp_resource = True
            func._mcp_uri = uri
            func._mcp_tags = tags
            return func

        return decorator


mcp = McpProxy()
