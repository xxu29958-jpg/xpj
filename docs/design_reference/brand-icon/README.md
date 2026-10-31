# 小票夹 app icon · 票根 Pair

Design reference for the shipped launcher, Windows and Web icons. Like the rest of
`docs/design_reference/`, this is construction guidance and evidence, not product
authority; the Owner decides the identity.

## Direction

Two ticket stubs, fanned. The front stub is paper with a coral tail below a
perforated tear line; the second stub behind it is leaf green.

- **Kept record.** A stub is the part you keep after a transaction. The coral
  tail takes over the job of the old coral side clip: it marks what is kept.
- **Collection, and more than one person.** The second stub turns one record into
  a collection and reads as a pair, which suits a family ledger.
- **Trust.** The perforation is a clean, verified tear rather than a torn scrap.
- **Small sizes.** The silhouette is a two-tone block with side notches. It
  survives at 16 px, where the old receipt's zig-zag, outline and sleepy face
  all disappeared, and where the old mark read as a mug with a handle.

Palette comes straight from `backend/app/static/shared/tokens.css`: plate
`#0D3D38` (brand-primary-strong), paper `#F7F1E3`, coral `#E0583B`, leaf `#2B6E5C`.

## Concepts reviewed

`concepts/` keeps all three masters; `review/concepts-board.png` shows each under
launcher masks, themed icons and at 16/24/32/48 px.

| | A · 票根 Pair (chosen) | B · 票夹 Clipped Receipt | C · 印 Seal Monogram |
|---|---|---|---|
| 16–24 px | Two-tone block with notches stays legible | Clip shrinks to a coral dot; zig-zag vanishes | Glyph turns into a red square |
| Distinctiveness | Unusual in finance; palette is ours | Receipt-with-zig-zag is the stock finance glyph | Text-in-a-square is the common CJK app pattern |
| Meaning | Kept record, collection, verified tear | Literal name (receipt + clip) | Seal = confirmed record |
| Brand continuity | Keeps palette and the coral "kept" role | Highest: evolves the current mark | Drops paper and evergreen for vermilion |
| Themed / mono | Tear gap and half-tone back stub survive | Works | Works |
| Main risk | "Ticket" can suggest events; the receipt-paper colour and finance context counter it | Torn-bottom silhouettes slide into a ghost reading | Vermilion collides with the overspend/danger red in a finance UI |

## Where each file goes

| File | Consumer |
|---|---|
| `android/.../drawable/ic_launcher_foreground.xml` | Adaptive foreground (108 dp, front stub inside the 33 dp safe zone) |
| `android/.../drawable/ic_launcher_monochrome.xml` | Android 13+ themed icon (new; there was no monochrome layer) |
| `android/.../mipmap-anydpi/ic_launcher*.xml` | Adaptive icon; background `@color/ic_launcher_background` |
| `android/.../drawable/ic_notification_receipt.xml` | Status-bar icon: one upright stub |
| `backend/packaging/ticketbox.ico` | Manager and lifecycle exe (PyInstaller), Start-menu shortcut, installer `SetupIconFile` |
| `desktop/backend_manager/ui.html` inline icon | Desktop Manager Edge app window: title bar and taskbar |
| `backend/app/static/web/product/brand/*.png` | Web favicon, PWA icons (any and maskable), sidebar mark (paper and midnight) |

The ICO holds 16, 20, 24, 32, 40, 48, 64, 96, 128 and 256. Sizes 16, 20 and 24
are pixel-grid drawings (`masters/ticketbox-icon-{16,20,24}px.svg`): upright
stub, whole-pixel edges. Entries up to 128 px are 32-bit BMP for older tools;
256 is PNG. The perforation dots appear from 64 px up, because at 48 px they
render as grey specks.

minSdk is 28, so the legacy `mipmap-*dpi` PNGs were never loaded and are removed.

## Illustrations

`render_art.py` draws two scenes from the same stub geometry and replaces the
clay-rendered `receipt_clip` / `receipt_tray` art (the green top clip and gold
coin that PRODUCT.md rejects):

- **pair**: the mark without its plate, for capture and connect moments
  (inbox capture, file pickers, Web login, Android bind).
- **box (票盒)**: stubs filed upright with the newest pulled up to show its
  tear and coral tail, for genuine empty states and "take your records".

Web uses inline SVG from `templates/web/partials/brand_art.html`, coloured by
the `--art-*` tokens, so paper and midnight follow with no image request.
Android uses one generated vector per skin through `BrandArt`. Both stay
decorative: hidden from assistive technology, and never carrying state.

## 夹夹 (mascot)

`render_mascot.py` draws 夹夹, a little crab. A crab's claws 夹 (hold) things, so
the mascot is literally the 小票夹: it keeps a 票根 in its claw (the same `Stub`,
with a leaf tail because the claw is coral). 蟹蟹 also reads as 谢谢, which suits
the moment a debt is settled. The mark stays the stub pair; the crab is a
character, not a second logo.

- **dozing**: hugs its 票根 like a pillow, eyes closed, blowing bubbles.
- **celebrating**: holds the 票根 up, curved eyes, open smile, confetti.

The crab appears only where `MascotArt` already runs: the Android debt-settle
and plan-goal celebrations. Per PRODUCT.md, it is not a reason to put a
character on every screen. Android loads one generated vector per state and
skin (`mascot_{dozing,celebrating}_{paper,midnight}.xml`). The images stay
decorative, and the overlays own the announcement.

## Regenerate

```bash
python docs/design_reference/brand-icon/render_icons.py --chromium "$CHROME"
python docs/design_reference/brand-icon/render_art.py
python docs/design_reference/brand-icon/render_mascot.py   # --preview board.png to look at it
```

Needs Pillow and Playwright, the same toolchain as the Web journey tests. The
script writes every file in the table above plus `masters/`. Edit the geometry
in the script, not the generated XML.
