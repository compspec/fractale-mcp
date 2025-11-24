# fractale-mcp

> Fractale Agents with MCP Server Tools

[![PyPI version](https://badge.fury.io/py/fractale-mcp.svg)](https://badge.fury.io/py/fractale-mcp)

## Design

We create a single, robust and asynchronous server that can dynamically discover and load tools of interest. Instead of multiple ports (one per tool) we serve tools on one port, given an http transport.

### Tools

The fractale-mcp library is based on discoverability. While any installed module is probably too lenient (e.g., imagine anything on the PYTHONPATH would be found), instead we automatically discover tools with a common base class in `fractale/tools`. The developer user can easily register additional tool modules that may not be a part of fractale here. E.g.,:

```python
from fractale.tools.manager import ToolManager

# Discover and register defaults
manager = ToolManager()

# The tools vendored here are automatically discovered..
manager.register("fractale.tools")

# Register a different module
manager.register("mymodule.tools")
```

Tools to add:

 - flux
   - flux-sched
   - delegation
   - submit jobs
   - validator
   - topology?
   - batch job generation
   - jobspec generation
   - translation (the transformers?)
 - helpers
   - debug
   - result parser (regular expressions)
   - timer (agent can request to wait some N time)
 - kubernetes
   - deploy job
   - deploy minicluster
 - build
   - docker

### Testing

Start the server in one terminal. Export `FRACTALE_MCP_TOKEN` if you want to require simple token auth. Here is for http.

```bash
fractale start --transport http --port 8089
```

In another terminal, check the health endpoint or do a simple tool request.

```bash
# Health check
curl -s http://0.0.0.0:8089/health  | jq

# Tool to ech back message
python3 examples/mcp/test_echo.py
```

TODO:

 - we will want to keep track of state (retries, etc.) for agents somewhere.

### Agents

**Not written yet**

The `fractale agent` command provides means to run build, job generation, and deployment agents.
This part of the library is under development. There are three kinds of agents:

 - `step` agents are experts on doing specific tasks (do hold state)
 - `manager` agents know how to orchestrate step agents and choose between them (don't hold state, but could)
 - `helper` agents are used by step agents to do small tasks (e.g., suggest a fix for an error)

The design is simple in that each agent is responding to state of error vs. success. In the [first version]() of our library, agents formed a custom graph. In this variant, we refactor to use MCP server tools. In the case of a step agent, the return code determines to continue or try again. In the case of a helper, the input is typically an erroneous response (or something that needs changing) with respect to a goal. For a manager, we are making a choice based on a previous erroneous step.

See [examples/agent](examples/agent) for an example, along with observations, research questions, ideas, and experiment brainstorming!

TODO refactor examples.

### Design Choices

Here are a few design choices (subject to change, of course). I am starting with re-implementing our fractale agents with this framework. For that, instead of agents being tied to specific functions (as classes on their agent functions) we will have separate agents that use mcp functions, prompts, and resources. I have not yet worked on the agents, but rather I'm writing our set of functions first.

- We don't use mcp.tool (and associated functions) directly, but instead add them to the mcp manually to allow for dynamic loading.
- The function docstrings are expose to the LLM (so write good ones!)
- We can use mcp.mount to extend a server to include others, or the equivalent for proxy.
- We are using mcp.run, but could also use mcp.run_async
- The backend of FastMCP is essentially starlette, so we define (and add) other routes to the server.


## License

HPCIC DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/cloud-select/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/cloud-select/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/cloud-select/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
