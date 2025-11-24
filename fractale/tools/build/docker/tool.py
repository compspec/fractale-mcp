from fractale.tools.base import BaseTool
from fractale.tools.decorator import mcp
import fractale.agent.logger as logger
import fractale.utils as utils
import shutil
import re
import os
import sys
import shutil
import tempfile
import subprocess
import textwrap

from rich import print
from rich.syntax import Syntax

name = "docker-build"


class DockerBuildTool(BaseTool):

    def setup(self):
        """
        Setup ensures we have docker or podman installed.
        """
        self.docker = shutil.which("docker")
        if not self.docker:
            self.docker = shutil.which("podman")
        if not self.docker:
            raise ValueError("docker and podman are not present on the system.")

    @mcp.tool(name="docker-push")
    def push_container(self, uri: str, all_tags: bool = False):
        """
        Push a docker container. Accepts an optional unique resource identifier (URI).

        uri: the unique resource identifier.
        all_tags: push to the registry all tags. The URI should NOT have an associated tag.
        """
        # Manual fix if the agent gets it wrong.
        if all_tags:
            uri = uri.split(":", 1)[0]

        # Prepare command to push (docker or podman)
        command = [self.docker, "push", uri]
        if all_tags:
            command.append("--all-tags")

        logger.info(f"Pushing to {uri}...")
        p = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode != 0:
            output = "ERROR: " + p.stdout + p.stderr
            logger.warning(f"Issue with docker push: {output}")
            return logger.failure(output)
        return logger.success(output)

    @mcp.tool(name=name)
    def build_container(self, dockerfile: str, uri: str, platforms: str = None):
        """
        Build a docker container. Accepts an optional unique resource identifier (URI).
        The build is always done in a protected temporary directory.

        dockerfile: the dockerfile to write and build
        uri: the unique resource identifier.
        platforms: Custom list of platforms (e.g., linux/amd64,linux/arm64) for a multi-stage build
        push: push to the registry. Requires that the docker agent is authenticated.
        load: load into a kubernetes in docker (kind) cluster.
        """
        # TODO need a way for agent to keep track of retries. Context session id could work as key

        # This ensures that we aren't given a code block, etc.
        pattern = "```(?:docker|dockerfile)?\n(.*?)```"
        match = re.search(pattern, dockerfile, re.DOTALL)
        if match:
            dockerfile = match.group(1).strip()
        else:
            dockerfile = utils.get_code_block(dockerfile, "dockerfile")

        # Not sure if this can happen, assume it can
        if not dockerfile:
            raise ValueError("No dockerfile content provided.")

        logger.custom(dockerfile, title="[green]Dockerfile Build[/green]", border_style="green")

        build_dir = tempfile.mkdtemp()
        print(f"[dim]Created temporary build context: {build_dir}[/dim]")

        # Write the Dockerfile to the temporary directory
        utils.write_file(dockerfile, os.path.join(build_dir, "Dockerfile"))

        prefix = [self.docker, "build"]
        if platforms is not None:
            # Note that buildx for multiple platforms must be used with push
            prefix = ["docker", "buildx", "build", "--platform", platforms, "--push"]

        # Run the build process using the temporary directory as context
        p = subprocess.run(
            prefix + ["--network", "host", "-t", uri, "."],
            capture_output=True,
            text=True,
            cwd=build_dir,
            check=False,
        )
        # Clean up after we finish
        shutil.rmtree(build_dir, ignore_errors=True)
        output = logger.success(p.stdout + p.stderr)
        output = self.filter_output(output)

        if p.returncode == 0:
            return logger.success(output)
        return logger.failed(output)

    def filter_output(self, output):
        """
        Remove standard lines (e.g., apt install stuff) that likely won't help but
        add many thousands of tokens... (in testing, from 272K down to 2k)
        """
        skips = [
            "Get:",
            "Preparing to unpack",
            "Unpacking ",
            "Selecting previously ",
            "Setting up ",
            "update-alternatives",
            "Reading database ...",
        ]
        regex = "(%s)" % "|".join(skips)
        output = "\n".join([x for x in output.split("\n") if not re.search(regex, x)])
        # Try to match lines that start with #<number>
        return "\n".join([x for x in output.split("\n") if not re.search(r"^#(\d)+ ", x)])

    @mcp.tool(name="kind-docker-load")
    def load_kind(self, uri: str):
        """
        Load a Docker URI into Kind (Kubernetes in Docker)

        uri: the unique resource identifier.
        """
        kind = shutil.which("kind")
        if not kind:
            return logger.failure("Kind is not installed on the system.")

        logger.info("Loading into kind...")
        p = subprocess.run(
            [kind, "load", "docker-image", uri],
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode != 0:
            output = p.stdout + p.stderr
            logger.warning(f"Issue with kind load: {output}")
            return logger.failure(output)
        return logger.success(output)

    def print_result(self, dockerfile):
        """
        Print Dockerfile with highlighted Syntax
        """
        highlighted_syntax = Syntax(dockerfile, "docker", theme="monokai", line_numbers=True)
        logger.custom(
            highlighted_syntax, title="Final Dockerfile", border_style="green", expand=True
        )
