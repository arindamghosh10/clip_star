def register_all() -> None:
    from ..engage.service import register_handlers as engage
    from ..learn.measure import register_handlers as measure
    from ..learn.report import register_handlers as report
    from ..publishing.service import register_handlers as publishing
    from .stages import register_handlers

    register_handlers()
    publishing()
    engage()
    measure()
    report()
