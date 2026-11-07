def register_all() -> None:
    from ..engage.service import register_handlers as engage
    from ..learn.measure import register_handlers as measure
    from ..learn.report import register_handlers as report
    from ..dubbing import register_handlers as dubbing
    from ..external_clippers import register_handlers as external
    from ..importer import register_handlers as importer
    from ..upload_alerts import register_handlers as upload_alerts
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
    dubbing()
    upload_alerts()
    external()
