# OCR benchmark fixtures

Each subdirectory is one fixture for `scripts/ocr_benchmark.py`:

```
<name>/
  image.png          (optional)  raw receipt screenshot
  ground_truth.json  (required)  expected extracted fields
```

`ground_truth.json` schema:

```json
{
  "amount_cents": 1851,
  "merchant": "中国建设银行",
  "expense_time": "2026-05-04T16:23:25+08:00",
  "category": "其他",
  "raw_text": "中国建设银行\n交易提醒\n交易时间：2026年5月4日 16:23:25\n交易金额：18.51（人民币）"
}
```

All fields optional individually; `raw_text` is what the `mock` provider
will parse when there's no image (lets you exercise the parse layer
without committing personal data).

Real receipt fixtures are NOT in this repo — they would leak personal
data. Add your own PNG/JPG + ground truth pairs locally to evaluate OCR
quality on real screenshots; this directory only ships the synthetic
smoke-test fixture below.

## `_synthetic_bank_alert`

Image-less fixture that lets `mock` provider parse a canonical bank
transaction alert. Drives the harness's framework test
(`tests/test_ocr_benchmark_harness.py`) without depending on real OCR
libraries or a real LLM.
