def register_all() -> None:
    from ..engage.service import register_handlers as engage
    from ..learn.measure import register_handlers as measure
    from ..learn.report import register_handlers as report
    from ..importer import register_handlers as importer
    from ..maintenance import register_handlers as maintenance
    from ..notify import register_handlers as notify
    from ..push import register_handlers as push
    from ..webhooks import register_handlers as webhooks
    from ..publishing.service import register_handlers as publishing
    from .stages import register_handlers

    register_handlers()
    publishing()
    engage()
    measure()
    report()
    notify()
    maintenance()
    webhooks()
    push()
    importer()
