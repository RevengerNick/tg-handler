"""Read-only Telegram Reader subsystem for Vex."""


def get_runtime():
    from .runtime import get_runtime as resolve_runtime
    return resolve_runtime()


__all__ = ["get_runtime"]
