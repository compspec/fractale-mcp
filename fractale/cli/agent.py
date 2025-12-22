from fractale.engines import get_engine


def main(args, extra, **kwargs):
    """
    Run an agent workflow using the configured engine.
    """
    # Prepare Context from Arguments
    context = vars(args)

    # Instantiate the Engine (native state machine, autogen, langchain)
    engine = get_engine(
        engine=args.engine, plan=args.plan, backend=args.backend, max_attempts=args.max_attempts
    )

    # 3. Select Interaction Mode & Attach UI
    if args.mode == "tui":
        from fractale.ui.adapters.tui import FractaleApp

        # The App takes ownership of the Engine.
        # It will instantiate TextualAdapter and assign it to engine.ui
        app = FractaleApp(engine, context)
        app.run()

    elif args.mode == "web":
        from fractale.ui.adapters.web import WebAdapter

        engine.ui = WebAdapter(url="http://localhost:3000")
        engine.run(context)

    else:
        from fractale.ui.adapters.cli import CLIAdapter

        engine.ui = CLIAdapter()
        engine.run(context)
