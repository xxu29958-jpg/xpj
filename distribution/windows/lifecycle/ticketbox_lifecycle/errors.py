from __future__ import annotations


class LifecycleError(Exception):
    """Operator-visible lifecycle failure with a stable identity."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LifecycleViolation(LifecycleError):
    """A contract violation that must fail closed."""
