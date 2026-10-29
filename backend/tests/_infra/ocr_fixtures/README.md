# OCR evaluation fixtures

Each sample directory contains `input.json`, `ground_truth.json`, and, for image
providers, exactly one image.png, image.jpg, image.jpeg or image.webp.
Real receipts stay in an authorized local directory; do not commit personal data.

Use schema 2 as shown by _synthetic_bank_alert. Input and truth are separate:

- Input records sample_id, independent group_id, source_kind, split
  (diagnostic, development, holdout), authorization reference, the timezone
  and currency context actually available at capture time. Currency may be null.
- Image inputs require image_sha256. Text-only parser diagnostics use input
  raw_text. Text, currency or timezone is never taken from ground truth.
- Truth records annotator, annotation_version, and fields. Each field has
  state: present | absent | unlabeled. Only present labels have a value.
- Amount values are {minor: <integer>, currency: <ISO code>}. Time values use
  {value: <ISO datetime with offset>, precision: instant} or
  {value: <ISO date>, precision: date_only, timezone: <IANA name>}.
- An absent label scores correct only when a successful call leaves the field
  empty. Unlabeled fields do not enter accuracy. Errors count against every
  labeled field and remain in attempted and latency denominators.
- Merchant matching normalizes Unicode, case and whitespace only; substrings
  are not matches. Instants must match in full, including time and offset
  semantics. An instant is not a date-only prediction.
- All variants of an event must share a group and split. Freeze the manifest
  before tuning; retain real holdout groups untouched. The report records input,
  label and image hashes, independent groups and source/split slices.

Example from backend/:

    python scripts/ocr_benchmark.py --providers empty,mock --json-output diagnostic.json
    python scripts/ocr_benchmark.py --fixture-dir <authorized-directory> --providers rapidocr --json-output baseline.json

### 生产反馈回放

在既有 owned PostgreSQL 测试环境中运行 `python scripts/ocr_feedback_replay.py --manifest <frozen-manifest.json> --output-dir <new-output-directory>`。入口复用 real-db lane 的身份、数据库隔离和清理合同；每个对照组重建测试状态。不得连接日常安装。未显式传入 manifest 时 CI 跳过真实图片回放，不宣称执行了该材料。

manifest 使用 `schema_version: 1`，包含 `recordings` 和 `arrival_order`。每份 recording 指定原 benchmark `report`、`report_sha256`、对应事实 `snapshots`（JSONL）、`snapshots_sha256`、原 `fixtures` 目录；路径相对 manifest。report 须保留原 benchmark 的 `manifest`、`rows` 及 `source_unchanged`、`worker_closed`，snapshots 为同次真实 native 调用的 `ocr_fact_snapshot`，以 `evidence.input_sha256` 关联原图。输入、标签、图片和记录摘要必须与冻结值一致。`arrival_order` 精确列出全部 sample_id，每交易组和原图仅出现一次，development 在 holdout 前。

三组依次为 baseline、feedback、withdrawn：开发材料先调用实际详情消费者取得预测，再按 publisher 真值提交金额；feedback 仅对唯一正确、可采用的原候选提交明确反馈，保留接口返回的 selection intent；withdrawn 通过现有反馈 owner 立即撤回。所有组都用实际 PATCH、OCC、幂等回执和资格判断；最终 holdout 只读取、评分，答案从不写回。由此保留预测时可见的历史，接受已显示建议不会伪装为新的独立标签。

输出分别保存每组逐次结果、原图分组、原预测、候选、反馈资格及撤回、失败与完整分母，另按 development/holdout 和生产金额上下文的新旧分片比较修好、误伤、漏候选、弃答和再次纠错。回放复用有摘要绑定的真实 OCR 记录，不重复推理、不估算真人操作数或用时；记录原始来源、预训练排除及地域代表性的限制，时间/字符/商户质量以原图片基准单独报告。

Every requested provider is required. Invalid/empty inputs and unknown providers
exit 2; any provider failure exits 1 and remains in the report. Exit 0 means the
finite evaluation ran, never that quality or product gates passed. local_llm
is opt-in and is not part of the CPU-only core comparison.

RapidOCR and local LLM use the actual provider snapshot entry point and the same
fact parsing path as the application. Timings include snapshot acquisition and
field extraction; database queue/apply and UI latency require the full product
probe. The synthetic text fixture is a parser diagnostic, not real OCR quality
or low-resource performance evidence. JSON includes all attempts, field-specific
denominators, coverage, false fills, and success/all-outcome P50/P95.
