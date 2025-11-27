import os

from fractale.agent.manager import ManagerAgent


def main(args, extra, **kwargs):
    """
    Run an agent workflow.
    """
    # Prepare Context from Arguments
    context = vars(args)

    # Instantiate Manager (Headless).
    # This will by default select a headless manager, which we will update
    manager = ManagerAgent(
        results_dir=args.results,
        save_incremental=args.incremental,
        max_attempts=args.max_attempts,
        ui=None,
    )

    # 3. Select Interaction Mode
    if args.mode == "tui":
        # The App takes ownership of the Manager, I'm not sure how else to do it.
        # It creates the TextualAdapter internally and runs manager.run() in a thread.
        from fractale.ui.adapters.tui import FractaleApp

        app = FractaleApp(manager, context)
        app.run()

    # These next two are blocking for UI interactions
    elif args.mode == "web":
        from fractale.ui.adapters.web import WebAdapter

        manager.ui = WebAdapter(url="http://localhost:3000")
        manager.run(context)

    else:
        # This is the default mode (ui)
        from fractale.ui.adapters.cli import CLIAdapter

        manager.ui = CLIAdapter()
        manager.run(context)
