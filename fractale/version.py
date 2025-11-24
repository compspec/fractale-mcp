__version__ = "0.0.1"
AUTHOR = "Vanessa Sochat"
AUTHOR_EMAIL = "vsoch@users.noreply.github.com"
NAME = "fractale-mcp"
PACKAGE_URL = "https://github.com/compspec/fractale-mcp"
KEYWORDS = "cluster, orchestration, transformer, jobspec, flux"
DESCRIPTION = "Agentic framework and MCP tools for HPC orchestration"
LICENSE = "LICENSE"


################################################################################
# Global requirements

# Note that the spack / environment modules plugins are installed automatically.
# This doesn't need to be the case.
INSTALL_REQUIRES = (
    ("jsonschema", {"min_version": None}),
    ("Jinja2", {"min_version": None}),
    ("uvicorn", {"min_version": None}),
    ("mcp", {"min_version": None}),
    ("fastmcp", {"min_version": None}),
    # Yeah, probably overkill, just being used for printing the scripts
    ("rich", {"min_version": None}),
)

GOOGLE_REQUIRES = (("google-generativeai", {"min_version": None}),)
TESTS_REQUIRES = (("pytest", {"min_version": "4.6.2"}),)
INSTALL_REQUIRES_ALL = INSTALL_REQUIRES + TESTS_REQUIRES + GOOGLE_REQUIRES
