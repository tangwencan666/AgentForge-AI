"""Process-local readiness notification installed only by the trusted bootstrap.

There is no environment switch, network command or credential access here.
"""
_notify = None
_role = None


def install(role, callback):
    global _notify, _role
    if _notify is not None or role not in {"backend", "worker"}:
        raise RuntimeError("LIFECYCLE_RUNTIME_ALREADY_BOUND")
    _role, _notify = role, callback


def ready(role):
    if _notify is None or role != _role:
        raise RuntimeError("LIFECYCLE_RUNTIME_UNBOUND")
    _notify()
