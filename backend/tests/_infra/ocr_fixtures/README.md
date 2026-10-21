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
