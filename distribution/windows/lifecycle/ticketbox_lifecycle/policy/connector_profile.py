"""The single supported native Cloudflare service contract."""

from __future__ import annotations

from pathlib import Path

from ticketbox_lifecycle.runtime.windows_scm_observation import FailureAction, ServiceConfiguration

SERVICE_NAME = "TicketboxCloudflared"
SERVICE_ACCOUNT = "NT SERVICE\\" + SERVICE_NAME
METRICS_HOST = "127.0.0.1"
METRICS_PORT = 20241
# SCM maps GENERIC_ALL to service-specific rights. Pin the mapped mask so
# readback compares actual permissions rather than a generic spelling.
SERVICE_DACL = "D:P(A;;0xF01FF;;;SY)(A;;0xF01FF;;;BA)(A;;CCLCRC;;;IU)"
FAILURE_ACTIONS = (FailureAction(1, 5000), FailureAction(1, 15000), FailureAction(0, 0))


def service_argv(release_root: Path, secret_root: Path, generation: int) -> tuple[str, ...]:
    if type(generation) is not int or generation <= 0:
        raise ValueError("a connector credential generation is required")
    connector = release_root / "connector"
    return (str(connector / "cloudflared.exe"), "--config", str(connector / "config.json"),
        "tunnel", "--no-autoupdate", "--metrics", f"{METRICS_HOST}:{METRICS_PORT}",
        "--loglevel", "warn", "--transport-loglevel", "warn", "--protocol", "auto", "--retries", "5",
        "run", "--token-file", str(secret_root / f"credential-g{generation}.token"))


def expected_service(argv: tuple[str, ...], service_sid: str, start_type: int) -> ServiceConfiguration:
    return ServiceConfiguration(service_type=16, start_type=start_type, error_control=1, argv=argv,
        load_order_group="", tag_id=0, dependencies=(), account_sid=service_sid, display_name=SERVICE_NAME,
        sid_type=1, failure_reset_seconds=0xFFFFFFFF, failure_actions=FAILURE_ACTIONS,
        failure_reboot_message="", failure_command="", failure_actions_on_non_crash=True,
        delayed_auto_start=False, trigger_count=0)
