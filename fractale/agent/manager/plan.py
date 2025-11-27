import jsonschema
from jsonschema import validators
from rich import print

import fractale.utils as utils


def set_defaults(validator, properties, instance, schema):
    """
    Fill in default values for properties that are missing.
    """
    for prop, sub_schema in properties.items():
        if "default" in sub_schema:
            instance.setdefault(prop, sub_schema["default"])


# Extend validator to apply defaults
plan_validator = validators.extend(
    jsonschema.Draft7Validator,
    {"properties": set_defaults},
)

plan_schema = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "inputs": {"type": "object", "default": {}},
        "plan": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    # This defines the (previous) agent or persona/role
                    "prompt": {"type": "string"},
                    "description": {"type": "string"},
                    "inputs": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
                "required": ["name", "prompt"],
            },
        },
    },
    "required": ["name", "plan"],
}


class Plan:
    """
    A plan for a manager includes one or more steps, each defined by a Prompt Persona.
    """

    def __init__(self, plan, save_incremental=False):
        if isinstance(plan, dict):
            self.plan = plan
            self.plan_path = "memory"
        else:
            self.plan_path = plan
            self.plan = utils.read_yaml(self.plan_path)

        self.step_names = set()
        self.save_incremental = save_incremental

        # Validate structure...
        self.validate_schema()

        # And create steps. Personas validated outside of here with manager.
        self.load()

    def validate_schema(self):
        """
        Validate against JSON schema.
        """
        validator = plan_validator(plan_schema)
        try:
            validator.validate(self.plan)
            print("✅ Plan schema is valid.")
        except Exception as e:
            raise ValueError(f"❌ Plan YAML invalid: {e}!")

    def load(self):
        """
        Initialize the steps in the plan.
        """
        print(f"Loading plan from [bold magenta]{self.plan_path}[/bold magenta]...")
        self.agents = []  # We refer to steps as agents (v1 of this library)

        for spec in self.plan.get("plan", []):
            step_name = spec["name"]

            if step_name in self.step_names:
                raise ValueError(f"Duplicate step name: '{step_name}'")
            self.step_names.add(step_name)

            step = Step(spec, save_incremental=self.save_incremental)
            self.agents.append(step)

    def __len__(self):
        return len(self.agents)

    def __getitem__(self, key):
        """
        Allows indexing plan[0]
        """
        return self.agents[key]

    @property
    def agent_names(self):
        """
        Used by Manager for recovery lookup.
        """
        return [step.name for step in self.agents]


class Step:
    """
    Wraps a specific execution step.
    Holds configuration + schema.
    """

    def __init__(self, spec, save_incremental=False):
        self.spec = spec
        self.save_incremental = save_incremental
        self._prompt_args = set()
        self.attempts = 0

    def set_schema(self, valid_args: set):
        """
        Called by Manager to define which arguments the Server Prompt accepts.
        """
        self._prompt_args = valid_args

    def partition_inputs(self, full_context: dict) -> tuple[dict, dict]:
        """
        Splits context into:
        1. Direct Arguments for the MCP Prompt function.
        2. Supplemental Context for the LLM.
        """
        # Only update inputs that aren't already defined for the context
        full_context = self.update_context(full_context)

        # Fallback if schema missing
        if self._prompt_args is None:
            return full_context, {}

        prompt_args = {}
        background_info = {}

        ignored = {
            "managed",
            "max_loops",
            "max_attempts",
            "result",
            "error_message",
        }

        for key, value in full_context.items():
            if key in self._prompt_args:
                prompt_args[key] = value
            elif key not in ignored:
                background_info[key] = value

        # TODO: we may want to supplement prompt with other "background info"
        print(prompt_args)
        return prompt_args, background_info

    def update_context(self, context):
        """
        Merge step-specific inputs into the context.
        """
        overrides = ["max_attempts", "llm_provider", "llm_model"]
        inputs = self.spec.get("inputs", {})

        for k, v in inputs.items():
            if k not in overrides:
                context[k] = v
        return context

    @property
    def name(self):
        return self.spec["name"]

    @property
    def max_attempts(self):
        return self.spec.get("max_attempts")

    @property
    def agent(self):
        return self.name

    @property
    def prompt(self):
        return self.spec["prompt"]

    @property
    def validate(self):
        return self.spec.get("validate")

    @property
    def description(self):
        return self.spec.get("description", f"Executes persona: {self.prompt}")

    def get(self, name, default=None):
        return self.spec.get(name, default)
