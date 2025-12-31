from fractale.core.plan import Plan


def get_engine(plan, engine="native", backend="gemini", ui=None, max_attempts=5, database=None):
    """
    Get the fractale engine! 🚘

    This is new, and will allow us to support different orchestators.
    """
    # This is loading the plan path
    plan = Plan(plan)

    # State machine orchestration
    if engine == "native":
        from fractale.engines.native.engine import Manager

    elif engine == "langchain":
        from fractale.engines.langchain.engine import Manager

    elif engine == "autogen":
        from fractale.engines.autogen.engine import Manager
    return Manager(plan=plan, backend=backend, ui=ui, max_attempts=max_attempts, database=database)
