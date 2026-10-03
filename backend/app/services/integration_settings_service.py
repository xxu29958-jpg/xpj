"""Owner forms use the same durable settings and providers as product requests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import Settings, get_settings
from app.errors import AppError
from app.services import runtime_settings_service as runtime
from app.services.budget_advisor_service._models import BudgetInputs, CategorySnapshot
from app.services.budget_advisor_service._provider_names import canonical_provider_name
from app.services.budget_advisor_service._providers import (
    _validate_api_key_for_base_url,
    _validate_base_url,
    get_budget_advisor,
)
from app.services.runtime_integration_settings import AdvisorSettingsProjection, FxSettingsProjection, advisor_payload
from app.services.runtime_settings_store import (
    RuntimeSettingsMutation,
    read_runtime_settings,
)


@dataclass(frozen=True)
class AdvisorSettingsForm:
    provider: str = "empty"
    base_url: str = ""
    model: str = ""
    timeout_seconds: str = "60"
    min_interval_seconds: str = "60"
    daily_call_limit: str = "50"


@dataclass(frozen=True)
class FxSettingsForm:
    auto_enabled: bool = True
    source: str = "frankfurter"
    sync_times: str = "09:10,23:10"
    timezone: str = "Asia/Shanghai"


def advisor_form(settings: Settings | None = None) -> AdvisorSettingsForm:
    settings = settings or get_settings()
    return AdvisorSettingsForm(
        provider=canonical_provider_name(settings.budget_advisor_provider),
        base_url=display_advisor_url(settings.budget_advisor_base_url),
        model=settings.budget_advisor_model,
        timeout_seconds=str(settings.budget_advisor_timeout_seconds),
        min_interval_seconds=str(settings.budget_advisor_live_min_interval_seconds),
        daily_call_limit=str(settings.budget_advisor_live_daily_call_limit),
    )


def display_advisor_url(value: str) -> str:
    """Invalid legacy URLs can contain credentials; never echo those into HTML."""
    if not value:
        return ""
    try:
        return _validate_base_url(value)
    except AppError:
        return ""


def fx_form() -> FxSettingsForm:
    settings = get_settings()
    return FxSettingsForm(settings.fx_rate_auto_sync_enabled, settings.fx_rate_source,
                          settings.fx_rate_sync_times, settings.fx_rate_sync_timezone)


def _connection_snapshot() -> AdvisorSettingsProjection | None:
    projection = read_runtime_settings(runtime._SETTINGS_PATH, service_owned=runtime._SERVICE_OWNED)
    return projection.advisor if projection else None


def _connection_revision(value: AdvisorSettingsProjection | None) -> str:
    encoded = json.dumps(asdict(value) if value else None, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _advisor_snapshot(settings: Settings) -> AdvisorSettingsProjection:
    return AdvisorSettingsProjection(canonical_provider_name(settings.budget_advisor_provider),
        settings.budget_advisor_base_url, settings.budget_advisor_api_key, settings.budget_advisor_model,
        settings.budget_advisor_timeout_seconds, settings.budget_advisor_live_min_interval_seconds,
        settings.budget_advisor_live_daily_call_limit)


def advisor_connection_revision(settings: Settings | None = None) -> str:
    return _connection_revision(_advisor_snapshot(settings or get_settings()))


def confirm_advisor(*, confirmed: bool, revision: str) -> None:
    snapshot = _connection_snapshot()
    if revision != _connection_revision(snapshot or _advisor_snapshot(get_settings())):
        raise AppError("conflict", "模型配置已改变，请刷新页面，核对当前连接后重新确认。", status_code=409)
    runtime.save_runtime_mutation(RuntimeSettingsMutation("budget_advisor_owner_confirmed", confirmed,
                                  check_advisor=True, expected_advisor=snapshot))


def _resolve_advisor_key(form: AdvisorSettingsForm, *, api_key: str, key_action: str) -> str:
    """Keep a stored secret only when its destination remains the same."""
    if key_action not in {"keep", "replace", "clear"}:
        raise runtime._invalid("请选择保留、更换或清除密钥。")
    if key_action == "keep" and api_key:
        raise runtime._invalid("已填写新密钥，请选择更换密钥后再保存。")
    settings = get_settings()
    if form.provider == "openai_compat" and key_action == "keep" and settings.budget_advisor_api_key and form.base_url.strip().rstrip("/") != settings.budget_advisor_base_url.rstrip("/"):
        raise runtime._invalid("接口地址已改变，请重新填写密钥并选择更换，或明确清除原密钥。")
    key = settings.budget_advisor_api_key if key_action == "keep" else api_key if key_action == "replace" else ""
    if key_action == "replace" and not key:
        raise runtime._invalid("请填写新密钥；不需要密钥的本机服务可选择清除密钥。")
    return key


def save_advisor(form: AdvisorSettingsForm, *, api_key: str, key_action: str) -> None:
    if form.provider not in {"empty", "openai_compat"}:
        raise runtime._invalid("请选择关闭 AI 或兼容 OpenAI 的模型服务。")
    base_url = form.base_url.strip().rstrip("/")
    key = _resolve_advisor_key(form, api_key=api_key, key_action=key_action)
    model = form.model.strip()
    if form.provider == "openai_compat" and (not base_url or not model):
        raise runtime._invalid("请填写接口地址和模型名称；这些值由你选择的模型服务提供。")
    if base_url:
        try:
            base_url = _validate_base_url(base_url)
            if form.provider == "openai_compat":
                _validate_api_key_for_base_url(base_url, key)
        except AppError as exc:
            raise runtime._invalid("请检查接口地址和密钥。公网服务必须使用 HTTPS 和有效密钥；本机服务可不填密钥。") from exc
    value = AdvisorSettingsProjection(
        form.provider, base_url, key, model,
        runtime._bounded_int(form.timeout_seconds, label="请求超时", minimum=5, maximum=300),
        runtime._bounded_int(form.min_interval_seconds, label="调用间隔", minimum=0, maximum=86400),
        runtime._bounded_int(form.daily_call_limit, label="每日调用上限", minimum=0, maximum=10000),
    )
    try:
        advisor_payload(value)
    except ValueError as exc:
        raise runtime._invalid("地址、模型名称或密钥包含无效字符，或超过长度限制。") from exc
    runtime.save_runtime_mutation(RuntimeSettingsMutation("advisor", value))


def save_fx(form: FxSettingsForm) -> None:
    if form.source not in {"frankfurter", "ecb"}:
        raise runtime._invalid("请选择支持的汇率来源。")
    try:
        times = [time.fromisoformat(item.strip()) for item in form.sync_times.split(",")]
        if not 1 <= len(times) <= 6 or any(item.second or item.microsecond or item.tzinfo for item in times):
            raise ValueError("invalid daily schedule")
        timezone = form.timezone.strip()
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise runtime._invalid("每天可设置 1–6 个 HH:MM 时间，用逗号分隔；时区请填写 Asia/Shanghai 等有效名称。") from exc
    value = FxSettingsProjection(form.auto_enabled, form.source,
                                 ",".join(sorted({item.strftime("%H:%M") for item in times})), timezone)
    runtime.save_runtime_mutation(RuntimeSettingsMutation("fx", value))


def test_advisor_connection() -> str:
    """Explicit diagnostic call with fixed example data, never real ledger data."""
    settings = get_settings()
    if canonical_provider_name(settings.budget_advisor_provider) != "openai_compat":
        raise runtime._invalid("请先配置并保存模型服务。")
    if not settings.budget_advisor_owner_confirmed:
        raise runtime._invalid("请先允许当前模型服务接收请求，再测试连接。")
    try:
        advisor = get_budget_advisor(settings=replace(settings, budget_advisor_timeout_seconds=min(
            settings.budget_advisor_timeout_seconds, 20)))
    except AppError as exc:
        raise runtime._invalid("模型配置不完整，请检查地址、模型名称和密钥。") from exc
    result = advisor.advise(BudgetInputs(month="2026-01", home_currency="CNY",
                           category_breakdown=[CategorySnapshot("餐饮", 1000, 1)]))
    if result is None:
        raise AppError("dependency_unavailable", "测试失败：请检查服务是否启动、密钥和模型是否有效。设置已保留，可修改后重试。", status_code=502)
    return "连接测试成功：模型已返回有效建议。本次只发送固定示例，没有读取或修改你的账本。"
