# OCR learning: stage diagnosis

W0 extends the existing benchmark; it does not change the product parser or learning policy.
Run `python scripts/ocr_benchmark.py --fixture-dir <local-corpus> --providers rapidocr --split development --json-output <private-report>` from `backend`.
Partition selection reads only input metadata before opening selected annotations and images.
Keep private images, annotations, predictions and reports outside Git.

Schema 2 remains supported. An input may add `app_tag`; omitted tags form the explicit `unknown` slice.
A present field annotation may add `source_region: [left, top, right, bottom]` in original image pixels and
`source_text` for an independently transcribed literal whose formatting differs from the canonical field value.
Neither reaches the provider or parser. A region is retained as annotation evidence; its presence does not imply region accuracy was measured.

Each present amount, merchant and time label receives exactly one stage: `text_missing`, `no_candidate`,
`not_first`, `first_abstained`, `correct`. The last two distinguish whether the correct first candidate was
actually selected correctly; `first_abstained` also includes the exceptional case of selecting a different,
wrong candidate while the first candidate was correct. Selected wrong values are independently counted as
`silent_errors`, including false fills against explicitly absent annotations. Unlabeled fields remain unknown.
Extraction failures remain in the denominator. Rows retain the parser's candidates, rank, role, text spans,
block indices and decision. Text presence is a literal diagnostic, not an independent OCR transcription score.

Stage intervals use a deterministic 1,000-resample percentile bootstrap over whole transaction groups.
The report includes provider and app slices. Small or dependent samples can produce wide or degenerate intervals;
these are not a release gate or an accuracy guarantee. Existing complete-denominator final-field scores remain available.

Validation: synthetic fixtures cover all five stages, silent selection errors, failed extraction, group clustering,
numeric substring rejection and development selection with unreadable sealed holdout content. These establish
evaluation behavior, not product quality.
