"""Ticketbox Windows vNext lifecycle coordinator.

This package is the only elevated mutation owner for fresh install.
It must not import ``backend.packaging`` or execute old receipt/handoff/CURRENT owners.
"""

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation

__all__ = ["LifecycleError", "LifecycleViolation"]
