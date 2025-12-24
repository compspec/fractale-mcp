# fractale-mcp

> Fractale Agents with MCP Server Tools

[![PyPI version](https://badge.fury.io/py/fractale-mcp.svg)](https://badge.fury.io/py/fractale-mcp)

## Design

We create a robust and asynchronous server that can dynamically discover and load tools of interest. The project here initially contained two "buckets" of assets: tools (functions, prompts, resources) and orchestration (agent frameworks and backends paired with models). Those are now (for the most part) separated into modular projects, and tools are added as needed:

- [flux-mcp](https://github.com/converged-computing/flux-mcp): MCP tools for Flux Framework
- [hpc-mcp](https://github.com/converged-computing/hpc-mcp): HPC tools for a larger set of HPC and converged computing use cases.

### Abstractions

The library here has the following abstractions.

- **Agents** can be driven by an agent interface (engine). We support "native" (state machine), and (TBA) autogen and langchain.
- **Plan** is the YAML manifest that any agent can read and deploy.
- **Engines**: The orchestration engine (native state machine, langchain, autogen).
- **tools**: server tools, prompts, and resources
- **ui**: user interface that an engine (with a main manager) uses
- **core**: shared assets, primarily the plan/step/config definitions
- **routes**: server views not related to mcp.
- **backends**: child of an engine, these are the model services (llama, openai, gemini)
- **databases**: how to save results as we progress in a pipeline (currently we support sqlite and filesystem JSON)

For the above, the engines, tools, ui, databases, and backends are interfaces.

### Tools

There are different means to add tools here:

 - **internal** are discovered in `fractale/tools`.
 - **external modules**: externally discovered via the same mechanism.
 - **external one-off**: add a specific tool, prompt, or resource to a server (suggested)

I am suggesting a combined approach of the first and last bullet for security. E.g., when we deploy, we do not want to open a hole to add functions that are not known. In the context of a job, we likely have a specific need or use case and can select from a library. I am developed scoped tools with this aim or goal -- to be able to deploy a job and start a server within the context of the job with exactly what is needed. Here is how the module discovery works:

```python
from fractale.tools.manager import ToolManager

# Discover and register defaults
manager = ToolManager()

# The tools vendored here are automatically discovered..
manager.register("fractale.tools")

# Register a different module
manager.register("mymodule.tools")
```

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
In our [first version](https://github.com/compspec/fractale), an agent corresponded to a kind of task (e.g., build). For this refactored version, the concept of an agent is represented in a prompt or persona, which can be deployed by a generic MCP agent with some model backend (e.g., Gemini, Llama, or OpenAI). Let's test doing a build. You'll first need to define backends. Note that I'm primarily testing and developing with Gemini because it doesn't suck. But here is how you'd define, for example, openai.

```bash
# Define the model (provider and endpoints) to use.
export FRACTALE_LLM_PROVIDER=openai
export OPENAI_API_KEY=xxxxxxxxxxxxxxxx
export OPENAI_BASE_URL=https://my.custom.url/v1

# For testing I prefer to use Gemini and their API
export GEMINI_API_TOKEN=xxxxxxxxxx
```

#### Build Docker Container

Here is an example that shows usage. This first example is for a straight forward "Use these inputs to create a prompt about building containers, and choose the right tool." We first need to install the functions from [hpc-mcp](https://github.com/converged-computing/hpc-mcp):

```bash
pip install hpc-mcp --break-system-packages
```

Start the server with the functions and prompt we need:

```bash
# In one terminal (start MCP)
fractale start -t http --port 8089 \
  --prompt hpc_mcp.t.build.docker.docker_build_persona_prompt \
  --tool hpc_mcp.t.build.docker.docker_build_container
```

And then run the plan.

```bash
# In the other, run the plan
fractale agent ./examples/plans/build-lammps.yaml

# It's often easier to debug with cli mode
fractale agent ./examples/plans/build-lammps.yaml
```

This works very well in Google Cloud (Gemini). I am not confident our on-premises models will easily choose the right tool. Hence the next design. If you define a `tool` section in any step, that will limit the selection of the LLM to JUST the tool you are interested in. We hope that this will work.

The design is simple in that each agent is responding to state of error vs. success. In the [first version](https://github.com/compspec/fractale) of our library, agents formed a custom graph. In this variant, we refactor to use MCP server tools. It has the same top level design with a manager, but each step agent is like a small state machine governed by an LLM with access to MCP tools and resources.

#### Flux JobSpec Translation

To prototype with Flux, open the code in the devcontainer. Install the library and start a flux instance.

```bash
pip install -e . --break-system-packages
pip install flux-mcp IPython --break-system-packages
flux start
```

We will need to start the server and add the validation functions and prompt.

```bash
fractale start -t http --port 8089 \
  --tool flux_mcp.validate.flux_validate_jobspec \
  --tool flux_mcp.transformer.transform_jobspec
```

Note: I am currently working here. Next step is to write prompts for the jobspec translation. We need different ones for batch vs. canonical and then to use the manual endpoint vs. have the LLM figure it out.

#### TODO

- Config file to start a server (with custom set of functions).

### Design Choices

Here are a few design choices (subject to change, of course). I am starting with re-implementing our fractale agents with this framework. For that, instead of agents being tied to specific functions (as classes on their agent functions) we will have separate agents that use mcp functions, prompts, and resources.

- Tools hosted here are internal and needed for the library. E.g, we have a prompt that allows getting a final status for an output, in case a tool does not do a good job.
- For those hosted here, we don't use mcp.tool (and associated functions) directly, but instead add them to the mcp manually to allow for dynamic loading.
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
