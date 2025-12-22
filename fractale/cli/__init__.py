#!/usr/bin/env python

import argparse
import os
import sys

# This will pretty print all exceptions in rich
from rich.traceback import install

install()

import fractale
from fractale.logger import setup_logger


def get_parser():
    parser = argparse.ArgumentParser(
        description="Fractale",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Global Variables
    parser.add_argument(
        "--debug",
        dest="debug",
        help="use verbose logging to debug.",
        default=False,
        action="store_true",
    )

    parser.add_argument(
        "--quiet",
        dest="quiet",
        help="suppress additional output.",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--config-dir",
        dest="config_dir",
        help="Fractale configuration directory to store subsystems. Defaults to ~/.fractale",
    )
    parser.add_argument(
        "--version",
        dest="version",
        help="show software version.",
        default=False,
        action="store_true",
    )

    subparsers = parser.add_subparsers(
        help="actions",
        title="actions",
        description="actions",
        dest="command",
    )
    subparsers.add_parser("version", description="show software version")

    # Start MCP workers
    start = subparsers.add_parser(
        "start",
        formatter_class=argparse.RawTextHelpFormatter,
        description="generate subsystem metadata for a cluster",
    )
    start.add_argument("tools", help="tools to start", nargs="*")
    start.add_argument("--port", default=8000, type=int, help="port to run the agent gateway")

    # Note from V: SSE is considered deprecated (don't use it...)
    start.add_argument(
        "-t",
        "--transport",
        default="stdio",
        help="Transport to use (defaults to stdin)",
        choices=["stdio", "http", "sse", "streamable-http"],
    )
    start.add_argument("--host", default="0.0.0.0", help="Host (defaults to 0.0.0.0)")
    start.add_argument(
        "--tool", action="append", help="Additional tool module paths to discover from.", default=[]
    )
    start.add_argument("--include", help="Include tags", action="append", default=None)
    start.add_argument("--exclude", help="Exclude tag", action="append", default=None)
    start.add_argument(
        "--mask-error_details",
        help="Mask error details (for higher security deployments)",
        action="store_true",
        default=False,
    )

    # Run an agent
    agent = subparsers.add_parser(
        "agent",
        formatter_class=argparse.RawTextHelpFormatter,
        description="run an agent",
    )
    agent.add_argument(
        "plan",
        help="provide a plan to a manager",
    )
    agent.add_argument("--mode", choices=["cli", "tui", "web"], default="tui")
    agent.add_argument("--engine", choices=["native", "langchain", "autogen"], default="native")
    agent.add_argument("--backend", choices=["openai", "gemini", "llama"], default="gemini")
    agent.add_argument("--database", help="URI for result storage (file://path or sqlite://path)")
    agent.add_argument(
        "--max-attempts",
        help="Maximum attempts for a manager or individual agent",
        default=None,
        type=int,
    )
    return parser


def run_fractale():
    """
    this is the main entrypoint.
    """
    parser = get_parser()

    def help(return_code=0):
        version = fractale.__version__

        print("\nFractale v%s" % version)
        parser.print_help()
        sys.exit(return_code)

    # If the user didn't provide any arguments, show the full help
    if len(sys.argv) == 1:
        help()

    # If an error occurs while parsing the arguments, the interpreter will exit with value 2
    args, extra = parser.parse_known_args()

    if args.debug is True:
        os.environ["MESSAGELEVEL"] = "DEBUG"

    # Show the version and exit
    if args.command == "version" or args.version:
        print(fractale.__version__)
        sys.exit(0)

    setup_logger(quiet=args.quiet, debug=args.debug)

    # Here we can assume instantiated to get args
    if args.command == "agent":
        from .agent import main
    elif args.command == "start":
        from .start import main
    else:
        help(1)
    main(args, extra)


if __name__ == "__main__":
    run_fractale()
