import logging

from jinja2 import BaseLoader, Environment

logger = logging.getLogger(__name__)


class WorkflowStateMachine:
    """
    Dynamic State Machine execution engine.
    """

    def __init__(self, states, context, callbacks):
        self.states = states
        self.context = context

        # This is manager.run_agent and manager.run_tool
        self.current_state_name = None
        self.callbacks = callbacks
        self.set_initial_state()

    def set_initial_state(self):
        """
        Set the initial state based on finding "initial"
        """
        for s in self.states.values():
            if s.get("initial"):
                self.current_state_name = s.name
                break

        if not self.current_state_name:
            # Fallback to first key that isn't a terminal
            keys = [k for k, v in self.states.items() if v.type != "final"]
            self.current_state_name = keys[0] if keys else "failed"

    def run_cycle(self):
        """
        Executes ONE state and determines the next state.

        Returns: (step_metadata, is_finished)
        """
        current_step = self.states[self.current_state_name]

        # Are we terminal? That sounds dark...
        if current_step.type == "final":
            print("Current step is final, returning finished")
            return None, True

        # Execute via callback function
        runner = self.callbacks.get(current_step.type)
        if not runner:
            raise ValueError(f"No runner for type '{current_step.type}'")

        # TODO: vsoch: do we want Jinja inputs here?
        step_inputs = current_step.spec.get("inputs", {})
        print(step_inputs)

        # Merge into temp context for execution
        exec_context = self.context.copy()
        exec_context.update(step_inputs)
        print(f"Running {current_step}")
        result, error, meta = runner(current_step, exec_context)

        # Save previous result and last error in context
        if result:
            print("RESULT")
            print(result)
            self.context["result"] = result
            self.context[f"{current_step.name}_result"] = result
        if error:
            print("ERROR")
            print(error)
        print(meta)

        # Always set error_message in the context
        self.context["error_message"] = error

        # Determine Transition
        outcome = "success" if (result and not error) else "failure"
        print(f"outcome is {outcome}")
        next_state = current_step.transitions.get(outcome)
        print(f"next state is {next_state}")

        # If explicit transition missing, default to failed
        if not next_state:
            next_state = "failed"
            print(f"next state is {next_state}")

        logger.info(f"🔀 Transition: {current_step.name} ({outcome}) -> {next_state}")
        prev_state_name = self.current_state_name
        self.current_state_name = next_state

        return {
            "agent": prev_state_name,
            "result": result,
            "error": error,
            "metadata": meta,
            "transition": f"{outcome} -> {next_state}",
        }, False
