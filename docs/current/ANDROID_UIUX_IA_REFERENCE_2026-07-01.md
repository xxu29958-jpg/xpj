# Android UIUX / IA Reference - 2026-07-01

This note captures the product-design reference pass for the Android IA/UIUX
refactor. It is a working contract for implementation and QA, not a marketing
deck.

## References Reviewed

Official product/help pages were re-checked on 2026-07-01 as product
organization references only. Do not copy their brand assets, visual identity,
or proprietary copy.

- YNAB Reporting / Reflect:
  https://www.ynab.com/blog/ynab-reports-and-data and
  https://www.ynab.com/whats-new/spending-breakdown-on-mobile
- Monarch Reports / Cash Flow / Monthly Progress:
  https://help.monarchmoney.com/hc/en-us/articles/21846787088916-Using-Reports,
  https://help.monarchmoney.com/hc/en-us/articles/20504904768020-Cash-Flow,
  https://help.monarchmoney.com/hc/en-us/articles/4402543752468-Monthly-Progress-Report
- Lunch Money feature map:
  https://lunchmoney.app/features
- Qianji product and guide:
  https://docs.qianjiapp.com/ and its App Store listing
- Shark Accounting:
  https://www.shayujizhang.com/
- Suishouji App Store listing:
  https://apps.apple.com/us/app/id372353614
- Material Design references:
  https://m3.material.io/blog/data-visualization-accessibility and
  https://m3.material.io/foundations/design-tokens

## Reference Synthesis

| Reference group | What matters for XiaoPiaoJia Android | Product implication |
| --- | --- | --- |
| YNAB / Monarch | Reporting is framed around user questions such as spending, cash flow, progress, and reflection instead of a raw gallery of charts. | Insights should lead with a conclusion and a reason, then offer drill paths. |
| Lunch Money | Transactions, rules, recurring items, analytics, and account context are treated as connected workflows. | Today, Pending, Ledger, Insights, and Settings should share state language, not feel like separate tools. |
| Qianji / Shark Accounting / Suishouji | Domestic mobile bookkeeping products optimize quick entry, ledger scanning, category summaries, and repeated daily use. | Android must keep first-screen density high but readable; controls should not push the financial answer away. |
| Material Design | Charts need accessible data expression, token discipline, and text-backed meaning. | Do not add chart shapes or dependencies unless they improve comparison, variation, selection, or accessibility. |

## Product-Level IA

- Today is the daily cockpit: upload, manual entry, current ledger summary, and
  what needs attention now.
- Pending is the inbox: unconfirmed screenshots enter, real pending state is
  shown, and no duplicate/available counts are invented.
- Ledger is the source list for confirmed records: find, inspect, edit, export,
  and drill into relationship money flows. It should not look like a filter lab.
- Insights is the answer page: what happened this month, why it happened, what
  changed, and where to act next. Charts are allowed only when they make the
  answer easier to read.
- Settings is governance: account, family, rules, sync, safety, appearance, and
  data tools. It should read like an admin console, not a stack of cards.

## Layout And Interaction Rules

- Keep one shared shell language: page eyebrow, large title, restrained actions,
  one source/status strip, and bottom-safe scroll padding.
- Prefer open sections and dividers over nested cards. Cards are for repeated
  items, modal content, or a single bounded object.
- Put primary content before controls. Month/tag/view filters are context, not
  the first thing the eye should fight through.
- Use menus or sheets for secondary controls: tags, report presets, export,
  search, view mode, and planning destinations should not all occupy first
  viewport real estate.
- Use product copy, not engineering copy. Backend/local/cache should surface as
  user states such as updated, offline data, syncing, or not current.
- Avoid god objects: screen files compose page flow; dense control clusters,
  chart bodies, and row systems live in focused components.

## Insights Rules

- Lead with a sentence-like conclusion and the confirmed spend, then show the
  reason: biggest change, top category, top merchant, active days, or budget
  risk.
- If data is sparse, replace decorative line/bar charts with factual breakdowns:
  occurrence rows, peak share, active days, merchant ranking, and category
  contribution.
- Only show trend charts when there is enough variation to read. A flat or
  single-bucket month should not pretend to be a trend.
- Trend views need comparison, not just shape: current vs previous period,
  peak vs average, current month vs last month/year, or merchant/category
  concentration.
- Every chart section needs a drill path to the ledger when the user wants to
  inspect the actual bills behind the number.

## Registered Feature Gaps

- Insights lacks saved report presets. Monarch-style saved reports are useful
  once users repeatedly check the same merchant/category/timeframe.
- Insight charts do not yet support direct point/bar selection with transaction
  drill-down. This blocks the full "read insight -> inspect bills" loop.
- Monthly review is not a first-class flow yet. Monarch and YNAB both package
  financial reflection as a review/reflect surface, not only raw charts.
- Recurring/subscription insight is present as data, but the interaction is not
  yet strong enough to guide cancellation, confirmation, or rule creation.
- Settings secondary pages still need the same visual QA pass as the five root
  pages: density, copy, hierarchy, and bottom-safe scrolling.
