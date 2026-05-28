"""Budget advisor provider implementations + factory.

ADR-0036 pins these provider shapes:

- ``EmptyBudgetAdvisor`` — default; never calls an AI service; returns
  ``None``. Core budgeting must still produce a usable result with this
  provider in place (AI is suggestion-only, not authoritative).
- ``MockBudgetAdvisor`` — deterministic dev / test provider, never calls
  out; required by ENGINEERING_RULES §8 (every provider needs at least
  empty + mock).
- ``OpenAiCompatBudgetAdvisor`` — production provider speaking the
  OpenAI Chat Completions protocol (covers ollama / vLLM / llama.cpp /
  LM Studio locally + OpenAI / DeepSeek / SiliconFlow / Together / Groq
  in the cloud — same base_url + api_key + model triple).

All providers honour the same contract: never raise on transport / parse
failures; return ``None`` so the caller falls back to local rules per
ADR-0036 ("AI does not write budgets, only suggests").
"""

from __future__ import annotations

import json
import logging
import re
from ipaddress import ip_address
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from app.config import get_settings
from app.errors import AppError, DataIntegrityError
from app.services.budget_advisor_service._models import (
    BudgetAdvice,
    BudgetAdvisorProvider,
    BudgetInputs,
    BudgetSuggestion,
)
from app.services.budget_advisor_service._outbound_guard import to_outbound_dict
from app.services.budget_advisor_service._provider_names import (
    EMPTY_PROVIDER_NAME,
    MOCK_PROVIDER_NAME,
    OPENAI_COMPAT_PROVIDER_NAMES,
    canonical_provider_name,
    clean_provider_name,
    is_known_provider,
)
from app.services.category_common import DEFAULT_CATEGORIES, normalize_category

logger = logging.getLogger(__name__)

MAX_PROVIDER_RESPONSE_BYTES = 512 * 1024
MAX_ADVICE_SUMMARY_CHARS = 800
MAX_ADVICE_RATIONALE_CHARS = 600
MAX_ADVICE_SUGGESTIONS = 20
_SECRETISH_DETAIL_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|token)\b\s*[:=]\s*['\"]?[^,\s'\"]+"
)

_SYSTEM_PROMPT = (
    "你是家庭预算助手。给定结构化预算数据 JSON（仅含分类聚合和匿名占位，绝无真实商户名 / 姓名 / 路径），"
    "用中文给出建议。只返回 JSON 对象，不要解释，不要 markdown 代码块。字段："
    "summary(string, 一句总结), "
    "suggestions(array of {category(string|null, null=整体建议; category must be one of "
    + "/".join(DEFAULT_CATEGORIES)
    + " or a category present in the input), suggested_amount_cents(int), rationale(string)}), "
    "confidence(number 0-1)。"
    "不要写预算 / 不要承诺修改账本——你只给建议，最终落盘由用户在 UI 确认。"
)


class EmptyBudgetAdvisor:
    """No-op provider. Returns None — caller treats absence of advice as
    "use local rules only", which is the documented zero-config path."""

    def advise(self, inputs: BudgetInputs) -> BudgetAdvice | None:
        return None


class MockBudgetAdvisor:
    """Deterministic test / dev provider — never calls an AI service.

    Synthesises a ``BudgetAdvice`` directly from ``inputs`` so callers can
    exercise the suggestion-render pipeline (UI, audit log, "采纳/手改"
    flow) without standing up a model. Required by ENGINEERING_RULES §8
    ("at least empty / mock implementations" for every provider).
    """

    def advise(self, inputs: BudgetInputs) -> BudgetAdvice | None:
        if not inputs.category_breakdown:
            return BudgetAdvice(summary="本月暂无消费数据可供建议。", confidence=0.0)
        top = max(inputs.category_breakdown, key=lambda row: row.amount_cents)
        return BudgetAdvice(
            summary=f"模拟建议：{top.category} 是本月占比最高的分类。",
            suggestions=[
                BudgetSuggestion(
                    category=top.category,
                    suggested_amount_cents=top.amount_cents,
                    rationale="mock 建议＝当前实际值（dev / test 用，无 AI 调用）",
                ),
            ],
            confidence=0.5,
        )


class OpenAiCompatBudgetAdvisor:
    """ADR-0036 production provider. Single class for local + cloud LLM
    via the OpenAI Chat Completions protocol.

    Failure semantics: any error (transport, HTTP, parse) is logged and
    swallowed; ``advise`` returns ``None``. The budget pipeline must keep
    working on local rules alone — per ADR-0036 and ENGINEERING_RULES §8
    (provider failure must not break the main loop).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds

    def advise(self, inputs: BudgetInputs) -> BudgetAdvice | None:
        try:
            payload = to_outbound_dict(inputs)
        except DataIntegrityError:
            # Payload schema drift — outbound guard fails closed. Log
            # without the payload itself (could contain inputs sized data
            # even if anonymised) and refuse the call.
            logger.exception("budget_advisor_openai_compat: outbound guard rejected payload")
            return None

        request_body = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        }

        try:
            response_json = self._post_chat_completion(request_body)
        except AppError:
            logger.exception("budget_advisor_openai_compat: HTTP call failed")
            return None
        except Exception:  # noqa: BLE001 - surface anything else as no-advice
            logger.exception("budget_advisor_openai_compat: unexpected transport error")
            return None

        try:
            content = _extract_message_content(response_json)
            allowed_categories = {
                normalize_category(row.category)
                for row in inputs.category_breakdown
                if row.category
            }
            return _parse_advice_json(content, allowed_categories=allowed_categories)
        except AppError:
            logger.exception("budget_advisor_openai_compat: response parse failed")
            return None
        except Exception:  # noqa: BLE001
            logger.exception("budget_advisor_openai_compat: unexpected parse error")
            return None

    def _post_chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        endpoint = f"{self._base_url}/chat/completions"
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            # Bearer header for OpenAI / DeepSeek / etc. Local self-hosted
            # endpoints typically ignore the header; harmless to send.
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = request.Request(endpoint, data=encoded, method="POST", headers=headers)
        try:
            with request.urlopen(req, timeout=self._timeout) as response:
                raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
                    logger.warning(
                        "budget_advisor_openai_compat: provider response too large bytes=%s",
                        len(raw),
                    )
                    raise AppError("server_error", "AI 服务暂时不可用。", status_code=500)
                return json.loads(raw.decode("utf-8"))
        except error.HTTPError as exc:
            detail = _sanitize_provider_error_detail(
                exc.read(4096).decode("utf-8", errors="replace")
            )
            logger.warning(
                "budget_advisor_openai_compat: provider HTTP error status=%s reason=%s detail=%s",
                exc.code,
                exc.reason,
                detail,
            )
            raise AppError(
                "server_error",
                "AI 服务暂时不可用。",
                status_code=500,
            ) from exc
        except (OSError, error.URLError, json.JSONDecodeError) as exc:
            raise AppError("server_error", "AI 服务暂时不可用。", status_code=500) from exc


def get_budget_advisor(provider_name: str | None = None) -> BudgetAdvisorProvider:
    """Resolve a provider by name. Defaults to ``empty`` per ADR-0036."""

    raw_name = clean_provider_name(provider_name or get_settings().budget_advisor_provider)
    name = canonical_provider_name(raw_name)
    if name == MOCK_PROVIDER_NAME:
        return MockBudgetAdvisor()
    if raw_name in OPENAI_COMPAT_PROVIDER_NAMES or name in OPENAI_COMPAT_PROVIDER_NAMES:
        settings = get_settings()
        if not settings.budget_advisor_base_url:
            raise AppError(
                "server_error",
                "未配置 BUDGET_ADVISOR_BASE_URL；无法启用 AI 预算助手。",
                status_code=500,
            )
        if not settings.budget_advisor_model:
            raise AppError(
                "server_error",
                "未配置 BUDGET_ADVISOR_MODEL；无法启用 AI 预算助手。",
                status_code=500,
            )
        base_url = _validate_base_url(settings.budget_advisor_base_url)
        api_key = settings.budget_advisor_api_key
        _validate_api_key_for_base_url(base_url, api_key)
        return OpenAiCompatBudgetAdvisor(
            base_url=base_url,
            api_key=api_key,
            model=settings.budget_advisor_model,
            timeout_seconds=settings.budget_advisor_timeout_seconds,
        )
    if name != EMPTY_PROVIDER_NAME or not is_known_provider(raw_name):
        logger.warning("budget_advisor: unsupported provider configured: %s", raw_name)
        raise AppError(
            "server_error",
            "BUDGET_ADVISOR_PROVIDER is not supported.",
            status_code=500,
        )
    return EmptyBudgetAdvisor()


def _extract_message_content(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AppError("server_error", "AI 返回格式不正确。", status_code=500)
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    raise AppError("server_error", "AI 没有返回文本。", status_code=500)


def _parse_advice_json(
    content: str, *, allowed_categories: set[str] | None = None
) -> BudgetAdvice:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise AppError("server_error", "AI 没有返回 JSON。", status_code=500)
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError("server_error", "AI 返回的 JSON 无法解析。", status_code=500) from exc
    if not isinstance(payload, dict):
        raise AppError("server_error", "AI 返回的 JSON 不是对象。", status_code=500)

    summary = _cap_text(payload.get("summary"), MAX_ADVICE_SUMMARY_CHARS)
    raw_confidence = payload.get("confidence")
    confidence: float | None = (
        max(0.0, min(1.0, float(raw_confidence)))
        if isinstance(raw_confidence, (int, float))
        else None
    )

    suggestions: list[BudgetSuggestion] = []
    accepted_categories = set(DEFAULT_CATEGORIES)
    accepted_categories.update(allowed_categories or set())
    raw_suggestions = payload.get("suggestions")
    if isinstance(raw_suggestions, list):
        for raw in raw_suggestions[:MAX_ADVICE_SUGGESTIONS]:
            if not isinstance(raw, dict):
                continue
            category = raw.get("category")
            category_str = normalize_category(str(category)) if category is not None else None
            if category is not None and category_str not in accepted_categories:
                continue
            try:
                amount = int(raw.get("suggested_amount_cents"))
            except (TypeError, ValueError):
                continue
            if amount < 0 or amount > 100_000_000:
                continue
            rationale = _cap_text(raw.get("rationale"), MAX_ADVICE_RATIONALE_CHARS)
            suggestions.append(
                BudgetSuggestion(
                    category=category_str,
                    suggested_amount_cents=amount,
                    rationale=rationale,
                )
            )
    return BudgetAdvice(summary=summary, suggestions=suggestions, confidence=confidence)


def _validate_base_url(value: str) -> str:
    cleaned = (value or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise AppError(
            "server_error",
            "BUDGET_ADVISOR_BASE_URL is invalid.",
            status_code=500,
        ) from exc
    host = parsed.hostname or ""
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(ch.isspace() for ch in host)
    ):
        raise AppError(
            "server_error",
            "BUDGET_ADVISOR_BASE_URL is invalid.",
            status_code=500,
        )
    return cleaned


def _is_local_or_private_host(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        parsed = ip_address(lowered)
    except ValueError:
        return False
    return parsed.is_loopback or parsed.is_private or parsed.is_link_local


def _validate_api_key_for_base_url(base_url: str, api_key: str) -> None:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if _is_local_or_private_host(host):
        return
    if parsed.scheme != "https":
        raise AppError(
            "server_error",
            "Public BUDGET_ADVISOR_BASE_URL must use HTTPS.",
            status_code=500,
        )
    if not api_key.strip():
        raise AppError(
            "server_error",
            "BUDGET_ADVISOR_API_KEY is required for public AI providers.",
            status_code=500,
        )


def _sanitize_provider_error_detail(value: str) -> str:
    collapsed = " ".join((value or "").split())
    return _SECRETISH_DETAIL_RE.sub(r"\1=***", collapsed)[:160]


def _cap_text(value: object, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit]
