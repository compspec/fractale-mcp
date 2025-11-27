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

### Environment

The following variables can be set in the environment.

| Name | Description | Default       |
|-------|------------|---------------|
| `FRACTALE_MCP_PORT` | Port to run MCP server on, if using http variant | 8089 |
| `FRACTALE_MCP_TOKEN` | Token to use for testing | unset |
| `FRACTALE_LLM_PROVIDER` | LLM Backend to use (gemini, openai, llama) | gemini |

### Testing

Start the server in one terminal. Export `FRACTALE_MCP_TOKEN` if you want to require simple token auth. Here is for http.

```bash
export FRACTALE_TOKEN_AUTH=dudewheresmycar
fractale start --transport http --port 8089
```

In another terminal, check the health endpoint or do a simple tool request.

```bash
# Health check
curl -s http://0.0.0.0:8089/health  | jq

# Tool to ech back message
python3 examples/mcp/test_echo.py
```

### Agents

The `fractale agent` command provides means to run build, job generation, and deployment agents.
In our [first version](https://github.com/compspec/fractale), an agent corresponded to a kind of task (e.g., build). For this refactored version, the concept of an agent is represented in a prompt or persona, which can be deployed by a generic MCP agent with some model backend (e.g., Gemini, Llama, or OpenAI). Let's test
doing a build:

```bash
# In both terminals
export FRACTALE_MCP_TOKEN=dude

# In one terminal (start MCP)
fractale start -t http --port 8089

# Define the model (provider and endpoints) to use.
export FRACTALE_LLM_PROVIDER=openai
export OPENAI_API_KEY=xxxxxxxxxxxxxxxx
export OPENAI_BASE_URL=https://my.custom.url/v1

# In the other, run the plan
fractale agent ./examples/plans/docker-build-lammps.yaml
```

 - `manager` agents know how to orchestrate step agents and choose between them (don't hold state, but could)
 - `step` agents are experts on doing specific tasks. This originally was an agent with specific functions to do something (e.g., docker build) and now is a generic MCP agent with a prompt that gives it context and a goal.

The initial design of `helper` agents from the first fractale is subsumed by the idea of an MCP function. A helper agent _is_ an MCP tool.

The design is simple in that each agent is responding to state of error vs. success. In the [first version](https://github.com/compspec/fractale) of our library, agents formed a custom graph. In this variant, we refactor to use MCP server tools. It has the same top level design with a manager, but each step agent is like a small state machine governed by an LLM with access to MCP tools and resources.

See [examples/agent](examples/agent) for an example, along with observations, research questions, ideas, and experiment brainstorming!

#### TODO

- refactor examples
- debug why the startup is so slow.

### Design Choices

Here are a few design choices (subject to change, of course). I am starting with re-implementing our fractale agents with this framework. For that, instead of agents being tied to specific functions (as classes on their agent functions) we will have separate agents that use mcp functions, prompts, and resources. I have not yet worked on the agents, but rather I'm writing our set of functions first.

- We don't use mcp.tool (and associated functions) directly, but instead add them to the mcp manually to allow for dynamic loading.
- The function docstrings are expose to the LLM (so write good ones!)
- We can use mcp.mount to extend a server to include others, or the equivalent for proxy.
- We are using mcp.run, but could also use mcp.run_async
- The backend of FastMCP is essentially starlette, so we define (and add) other routes to the server.


### Job Specifications

#### Simple

We provide a simple translation layer between job specifications. We take the assumption that although each manager has many options, the actual options a user would use is a much smaller set, and it's relatively straight forward to translate (and have better accuracy).

See [examples/transform](examples/transform) for an example.

#### Complex

We want to:

1. Generate software graphs for some cluster (fluxion JGF) (this is done with [compspec](https://github.com/compspec/compspec)
2. Register N clusters to a tool (should be written as a python module)
3. Tool would have ability to select clusters from resources known, return
4. Need graphical representation (json) of each cluster - this will be used with the LLM inference

See [examples/fractale](examples/fractale) for a detailed walk-through of the above.

For graph tool:

```bash
conda install -c conda-forge graph-tool
```

<!-- ⭐️ [Documentation](https://compspec.github.io/fractale) ⭐️ -->

## License

HPCIC DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/cloud-select/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/cloud-select/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/cloud-select/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
