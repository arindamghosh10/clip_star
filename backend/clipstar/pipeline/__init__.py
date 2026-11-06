def register_all() -> None:
    from ..engage.service import register_handlers as engage
    from ..publishing.service import register_handlers as publishing
    from .stages import register_handlers

    register_handlers()
    publishing()
    engage()
