"""Preserve explicit pickle-state hooks across slotted dataclass transformations."""

from dataclasses import dataclass


def stateful_dataclass(**options):
    """Apply dataclass without replacing class-defined state hooks.

    Python 3.10's frozen/slots transformation overwrites even explicit
    __getstate__/__setstate__ methods. Capture only those defined on the input
    class and restore them on the returned class, without touching generated
    attribute guards or the class's validated __reduce__ reconstruction path.
    """

    def decorate(cls):
        hooks = {
            name: cls.__dict__[name]
            for name in ("__getstate__", "__setstate__")
            if name in cls.__dict__
        }
        result = dataclass(**options)(cls)
        for name, hook in hooks.items():
            setattr(result, name, hook)
        return result

    return decorate
