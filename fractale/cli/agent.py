from fractale.agent.manager import ManagerAgent


def main(args, extra, **kwargs):
    """
    Run an agent (do with caution!)
    """
    # Get the agent and run!
    # - results determines if we want to save state to an output directory
    # - save_incremental will add a metadata section
    # - max_attempts is for the manager agent (defaults to 10)
    agent = ManagerAgent(
        results_dir=args.results,
        save_incremental=args.incremental,
        max_attempts=args.max_attempts,
    )
    # This is the context - we can remove variables not needed
    context = vars(args)
    agent.run(context)
