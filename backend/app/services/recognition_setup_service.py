"""Read-only setup checks use the production local vision transport and limiter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings
from app.errors import AppError
from app.recognition_config import resolve_local_llm_base_url
from app.services import runtime_settings_service as runtime
from app.services.local_llm_vision import call_local_llm_vision, list_local_llm_models


@dataclass(frozen=True)
class RecognitionCheck:
    message: str
    models: tuple[str, ...] = ()


def _test_image() -> bytes:
    image = Image.new("RGB", (240, 120), "white")
    ImageDraw.Draw(image).text((120, 60), "24", fill="black", anchor="mm", font=ImageFont.load_default(size=80))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def inspect_connection(form: runtime.RecognitionSettingsForm, *, action: str) -> RecognitionCheck:
    if action not in {"models", "test"}:
        raise runtime._invalid("请选择保存、读取模型或测试图片识别。")
    base_url = resolve_local_llm_base_url(form.local_llm_base_url)
    if not base_url:
        raise runtime._invalid("请填写本机模型地址，只允许 127.0.0.1、localhost 或 ::1 的 HTTP(S) 地址。")
    model = form.local_llm_model.strip()
    if len(model.encode("utf-8")) > 256:
        raise runtime._invalid("模型名称过长。")
    try:
        if action == "models":
            models = list_local_llm_models(base_url)
            return RecognitionCheck(f"已读取 {len(models)} 个模型，请在模型名称中选择。表单尚未保存；模型列表可读不代表支持图片识别。", models)
        settings = get_settings()
        model = model or list_local_llm_models(base_url)[0]
        result = call_local_llm_vision(_test_image(), "image/png",
            'Read the large two-digit number in this image. Return JSON only, with key "number" and its value.',
            settings=replace(settings, local_llm_base_url=base_url, local_llm_model=model,
                             local_llm_timeout_seconds=min(settings.local_llm_timeout_seconds, 20),
                             local_llm_queue_timeout_seconds=0))
    except AppError as exc:
        if exc.error == "rate_limited":
            raise
        raise AppError("dependency_unavailable", "本机模型检查失败。请确认服务已启动、地址和模型正确，并支持图片输入。表单和原设置均已保留。",
                       status_code=502) from exc
    if str(result.get("number", "")).strip() != "24":
        raise AppError("dependency_unavailable", "模型已响应，但没有正确读出测试图片。请确认选用视觉模型后重试；原设置未改变。", status_code=502)
    return RecognitionCheck(f"测试图片识别通过：{model}。本次仅发送固定测试图片，未读取账本或原件；表单尚未保存。")
