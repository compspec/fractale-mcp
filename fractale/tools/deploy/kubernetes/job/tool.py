from typing import Annotated

from fractale.tools.base import BaseTool
from fractale.tools.decorator import mcp

# @mcp.tool
# def process_image(
#    image_url: Annotated[str, "URL of the image to process"],
#    resize: Annotated[bool, "Whether to resize the image"] = False,
#    width: Annotated[int, "Target width in pixels"] = 800,
#    format: Annotated[str, "Output image format"] = "jpeg"
# ) -> dict:
#    """Process an image with optional resizing."""
#    # Implementation...


# No @register decorator needed! The file path defines the identity.
class K8sJobTool(BaseTool):

    def setup(self):
        pass

    @mcp.tool(name="kubernetes-status")
    def get_status(self, job_id: str):
        """Checks job status."""
        return "Running"
