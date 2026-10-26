"""Service observations shared by pure policy and the native SCM adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FailureAction:
    action_type: int
    delay_ms: int


@dataclass(frozen=True)
class ServiceConfiguration:
    service_type: int
    start_type: int
    error_control: int
    argv: tuple[str, ...]
    load_order_group: str
    tag_id: int
    dependencies: tuple[str, ...]
    account_sid: str
    display_name: str
    sid_type: int
    failure_reset_seconds: int
    failure_actions: tuple[FailureAction, ...]
    failure_reboot_message: str
    failure_command: str
    failure_actions_on_non_crash: bool
    delayed_auto_start: bool
    trigger_count: int


class ScmObserver(Protocol):
    def observe(self, name: str) -> ServiceConfiguration: ...


