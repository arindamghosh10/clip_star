def register_all() -> None:
    from .stages import register_handlers

    register_handlers()
