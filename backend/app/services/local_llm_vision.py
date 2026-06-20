"""Shared local-LLM vision engine (provider-agnostic).

Both the receipt OCR provider (``ocr_service``) and the debt-bill parser
(``debt_bill_parse_service``) drive the SAME self-hosted, OpenAI-compatible
vision model: encode the image, resolve the model, POST one chat-completion
carrying a task-specific prompt, then decode the single JSON object the model
returns. Only the prompt + the JSON→domain mapping differ per caller; the
transport, the loopback-URL guard, the concurrency slot limiter, and the JSON
envelope parsing live here so neither caller re-implements them.

ADR-0015 pins the receipt provider/parse architecture; this module is the
engine those providers share. It is a leaf — depends only on ``app.config`` +
``app.errors``. The ``call_local_llm_vision`` entry point takes raw image bytes
(not an ORM row), so a transient parse (an uploaded image that is never stored)
can drive it exactly like the stored-receipt path.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from contextlib import contextmanager
from time import monotonic
from typing import Any
from urllib import error, request

from app.config import get_settings
from app.errors import AppError

logger = logging.getLogger(__name__)


class _LocalLlmSlotLimiter:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active_slots = 0

    def acquire(self, max_concurrent: int, queue_timeout_seconds: float) -> None:
        limit = max(1, int(max_concurrent or 1))
        timeout = max(0.0, float(queue_timeout_seconds))
        deadline = monotonic() + timeout
        with self._condition:
            while limit <= self._active_slots:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise AppError(
                        "rate_limited",
                        "本地大模型识别队列繁忙，请稍后再试。",
                        status_code=429,
                    )
                self._condition.wait(remaining)
            self._active_slots += 1

    def release(self) -> None:
        with self._condition:
            if self._active_slots > 0:
                self._active_slots -= 1
            self._condition.notify_all()


# Process-wide slot limiter: a single-GPU local vision model cannot serve many
# concurrent generations, so all callers (receipt OCR + debt-bill parse) share
# ONE limiter — they contend for the same model.
_LOCAL_LLM_SLOT_LIMITER = _LocalLlmSlotLimiter()


@contextmanager
def local_llm_slot(max_concurrent: int, queue_timeout_seconds: float):
    _LOCAL_LLM_SLOT_LIMITER.acquire(max_concurrent, queue_timeout_seconds)
    try:
        yield
    finally:
        _LOCAL_LLM_SLOT_LIMITER.release()


def require_local_llm_base_url(base_url: str) -> None:
    """Refuse to call the local LLM when config rejected the URL.

    Empty value here means ``_resolve_local_llm_base_url`` (in app.config)
    treated the configured URL as non-loopback and dropped it. We surface that
    as a clear, actionable error rather than silently sending uploaded images
    (receipts / debt bills — both sensitive) to whatever the env variable
    pointed at.
    """

    if not base_url:
        raise AppError(
            "server_error",
            "LOCAL_LLM_BASE_URL 必须是本机回环地址（127.0.0.1 / ::1 / localhost）。",
            status_code=500,
        )


def resolve_local_llm_model(base_url: str) -> str:
    """Return the first model id the endpoint advertises (when no model is pinned)."""

    endpoint = f"{base_url}/models"
    req = request.Request(endpoint, method="GET")
    try:
        with request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, error.URLError, json.JSONDecodeError) as exc:
        raise AppError("server_error", "本地大模型服务不可用。", status_code=500) from exc

    models = payload.get("data") if isinstance(payload, dict) else None
    if not models:
        raise AppError("server_error", "本地大模型服务没有可用模型。", status_code=500)
    model_id = models[0].get("id") if isinstance(models[0], dict) else None
    if not model_id:
        raise AppError("server_error", "本地大模型服务模型列表格式不正确。", status_code=500)
    return str(model_id)


def post_chat_completion(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    endpoint = f"{settings.local_llm_base_url}/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=settings.local_llm_timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail_bytes = exc.read(4096)
        logger.warning(
            "local_llm_vision: HTTP error status=%s reason=%s detail_bytes=%s",
            exc.code,
            exc.reason,
            len(detail_bytes),
        )
        raise AppError("server_error", "本地大模型识别失败。", status_code=500) from exc
    except (OSError, error.URLError, json.JSONDecodeError) as exc:
        raise AppError("server_error", "本地大模型服务不可用。", status_code=500) from exc


def extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AppError("server_error", "本地大模型返回格式不正确。", status_code=500)
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    raise AppError("server_error", "本地大模型没有返回文本内容。", status_code=500)


def rewrap_code_fence(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = rewrap_code_fence(cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise AppError("server_error", "本地大模型没有返回 JSON。", status_code=500)
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError("server_error", "本地大模型返回的 JSON 无法解析。", status_code=500) from exc
    if not isinstance(payload, dict):
        raise AppError("server_error", "本地大模型返回的 JSON 不是对象。", status_code=500)
    return payload


def call_local_llm_vision(
    image_bytes: bytes, media_type: str | None, prompt_text: str
) -> dict[str, Any]:
    """Run one image through the local vision model and return its JSON object.

    Encodes ``image_bytes`` inline as a data URL, resolves the model (pinned or
    first-available), POSTs a single deterministic (``temperature=0``)
    chat-completion under the shared concurrency slot, and decodes the one JSON
    object the model returns. The caller owns the prompt and the JSON→domain
    mapping; everything between is identical for every vision task.
    """

    settings = get_settings()
    require_local_llm_base_url(settings.local_llm_base_url)
    media = media_type or "image/jpeg"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    model = settings.local_llm_model or resolve_local_llm_model(settings.local_llm_base_url)
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media};base64,{encoded}"},
                    },
                ],
            }
        ],
    }
    with local_llm_slot(
        settings.local_llm_max_concurrent,
        settings.local_llm_queue_timeout_seconds,
    ):
        response = post_chat_completion(payload)
    content = extract_message_content(response)
    return parse_json_object(content)
