# Design Reference

This folder documents the two local design packs used as UI acceptance baselines.
Large zip files are intentionally not committed. Low-resolution thumbnails are kept
under `thumbnails/` so future implementation work can understand the target
direction without depending on local artifact paths.

## Source Packs

Two local design archives drive the UI acceptance baseline. They are large and
contain unreleased art; **do not commit the original zips or full-size renders**.

- `ticketbox_ui_redesign_pack.zip` — page redesigns (Pending, Edit, Ledger, Stats, Settings)
- `ticketbox_theme_ux_pack.zip` — theme proposals + UX interaction reference

Keep the zips outside the repo (downloads folder or similar). After extraction,
put the working copy under:

- `artifacts/design_packs/ui_redesign/`
- `artifacts/design_packs/theme_ux/`

`artifacts/` is gitignored — use it for large local screenshots and validation captures.

> **主题命名说明**：本目录的"松雾 / 柚光 / 港湾 / 莓果 / 夜幕"是设计稿原始命名，
> 仅作为视觉灵感参考。**v0.9 起的真值主题为 paper / mono / midnight**，详见
> [../current/V0_9_DESIGN_TOKEN_REFERENCE.md](../current/V0_9_DESIGN_TOKEN_REFERENCE.md)。

## Page Mapping

| Target screen | Reference file | Thumbnail |
| --- | --- | --- |
| Brand mood | `00_promo_poster.png` | `thumbnails/00_promo_poster.png` |
| PendingScreen | `01_pending_redesign.png` | `thumbnails/01_pending_redesign.png` |
| ExpenseEditScreen | `02_edit_confirm_redesign.png` | `thumbnails/02_edit_confirm_redesign.png` |
| LedgerScreen | `03_ledger_redesign.png` | `thumbnails/03_ledger_redesign.png` |
| StatsScreen | `04_stats_redesign.png` | `thumbnails/04_stats_redesign.png` |
| SettingsScreen | `05_settings_redesign.png` | `thumbnails/05_settings_redesign.png` |

## Theme Mapping

| Theme | Reference file | Thumbnail |
| --- | --- | --- |
| 松雾 | `主题方案_松雾.png` | `thumbnails/主题方案_松雾.png` |
| 柚光 | `主题方案_柚光.png` | `thumbnails/主题方案_柚光.png` |
| 港湾 | `主题方案_港湾.png` | `thumbnails/主题方案_港湾.png` |
| 莓果 | `主题方案_莓果.png` | `thumbnails/主题方案_莓果.png` |
| 夜幕 | `主题方案_夜幕.png` | `thumbnails/主题方案_夜幕.png` |

## UX Mapping

| UX topic | Reference file | Thumbnail |
| --- | --- | --- |
| Core flow | `UX交互_核心流程.png` | `thumbnails/UX交互_核心流程.png` |
| Key states and micro-interactions | `UX交互_关键状态与微交互.png` | `thumbnails/UX交互_关键状态与微交互.png` |

## Acceptance Use

These images define the visual target, not optional inspiration. A screen reaches
80% parity when structure, atmosphere, Hero hierarchy, cards, CTA, empty states,
bottom navigation, and readability are close enough to pass human review on a
real-device screenshot.
