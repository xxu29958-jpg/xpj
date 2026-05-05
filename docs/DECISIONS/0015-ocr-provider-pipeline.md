# 0015. OCR Provider Pipeline

## Status

Accepted.

## Context

小票夹已经跑通 iPhone 上传、Windows 后端保存、Android 待确认和人工确认入账。下一步需要 OCR，但不能让 OCR 破坏上传稳定性，也不能让某个模型或云服务绑死在 route 层。

## Decision

OCR 落地为三层：

```text
ocr_service.py
  -> provider 读取图片或已有文本
  -> receipt_parse_service.py 从 raw_text 抽取金额、商家、时间、分类
  -> expense_service.py 只写 pending 草稿字段
```

第一批 provider：

```text
empty      默认，不识别
mock       测试用
rapidocr   本地 OCR，可选依赖
local_llm  本地 OpenAI 兼容视觉模型服务
```

上传自动识别由 `OCR_AUTO_RUN` 控制，默认关闭。自动 OCR 失败不得影响上传和 pending 创建。手动 `/ocr/retry` 可以暴露 provider 错误，便于调试。

OCR 写入规则：

- 可以更新 `raw_text` 和 `confidence`。
- 只能填空的 `amount_cents`、`merchant`、`expense_time`。
- 只能在分类为 `其他` 时自动分类。
- 永远不自动确认入账。

## Consequences

- 后端可以先用 RapidOCR，本地模型可作为 fallback。
- 未来接 PaddleOCR、PaddleOCR-VL、PaliGemma 或其他模型只需要新增 provider。
- Android 不需要知道具体 OCR 模型，只展示识别草稿和原文。
- 上传稳定性优先于 OCR 成功率。
