# FRONTIR-UI — the Frontir Sentry reskin

This fork rebrands Hermes WebUI as **Frontir Sentry**: a near-black,
voice-first console look built from the Frontir shield/wordmark brand.
This document records exactly what changed, what was added versus edited
in place, how to re-apply the layer after an upstream merge, and what was
deliberately left alone.

**Design intent (agreed constraint): Hermes WebUI wearing Frontir's skin.**
The existing structure and DOM are preserved — sidebar, session list,
composer, panels, settings, navigation all stay where a Hermes user expects
them. The reference "Codex OS" console contributes a *visual language*
(near-black canvas, restrained type, hairline glass cards, luminous orb,
circular bottom icon bar), delivered as a skin plus additive surfaces —
never as a replacement shell.

---

## 1. Architecture: why a skin + two additive files

Per `THEMES.md`, a *skin* only drives the `--accent` family and a *theme*
drives base surfaces — neither can deliver a new product shell on its own.
But `style.css` already contains full-palette-rewrite skins (`graphite`,
`codex`, `terracotta`) that restyle chrome per `[data-skin]`, which proves
the pattern: **a skin key can carry an arbitrary amount of scoped CSS as
long as that CSS lives behind `[data-skin="..."]` selectors.**

So Frontir ships as:

| Piece | Mechanism |
|---|---|
| Palette (light + dark) | `:root[data-skin="frontir"]` and `:root.dark[data-skin="frontir"]` token blocks in **frontir.css** — the documented THEMES.md recipe, but housed in our own file so `style.css` is untouched |
| Native picker / `/theme frontir` | `window.registerHermesSkin()` (documented in `docs/EXTENSIONS.md`), called from **frontir.js** — zero edits to `boot.js`, `commands.js`, `panels.js` |
| Shell restyle | Additive overrides in **frontir.css**, all scoped under `[data-skin="frontir"]` — selecting any other skin restores stock Hermes pixel-for-pixel |
| Voice console (orb, glass cards, dock) | Built by **frontir.js** as a `<section>` overlay appended to `<body>`; opened from the "Voice" nav item or automatically when the built-in voice mode activates under this skin |
| Sidebar additions (New task / Voice / Scheduled nav + user chip) | Injected by **frontir.js**, CSS-hidden unless the frontir skin is active |
| First-run default | A 1-line inline `<head>` script seeds `hermes-skin=frontir` **only when the key is absent**; a user's explicit later choice is never overridden |

The `registerHermesSkin` call passes the *light* token subset (identical
values to the CSS file). Reason: core injects registered tokens as a
`:root[data-skin]` style element appended to `<head>`, which wins cascade
ties against our `<link>` — passing identical values makes injection order
irrelevant, and the dark variant only exists in frontir.css via the
higher-specificity `:root.dark[data-skin="frontir"]` block.

## 2. Design tokens

Defined once at the top of `static/frontir.css` under the `--fs-*`
namespace (namespaced to never collide with upstream vars). Dark
("Nightwatch") is primary; light ("Daywatch") is a true variant, not a
grey flip — the orb becomes an ink lens on bone paper.

| Group | Dark | Light |
|---|---|---|
| Canvas / raised | `#09090B` / `#101013` | `#F4F3EF` / `#FBFAF7` |
| Glass card fill | `rgba(22,22,27,.58)` + blur(14px) | `rgba(255,255,255,.72)` + blur(14px) |
| Hairlines | `rgba(255,255,255,.07)` / `.16` | `rgba(20,20,24,.12)` / `.22` |
| Text / muted / meta | `#F4F3EF` / `#A3A3AB` (8.1:1) / `#8E8E98` (5.6:1) | `#1B1B1F` / `#565660` (7:1) / `#6E6E78` (4.9:1) |
| Chrome accent | bone `#E9E7E0` on ink `#131316` | ink `#22222A` on bone |
| Live hues (orb + status) | listen `#7FD4C1` · think `#A99EF8` · speak `#E8C48A` · idle moonstone `#A9BFCD` | `#14766A` · `#5D4FC0` · `#8A5F14` · dusk `#46555E` |
| Type | system UI stack; signature = 11px engraved caps (`.14em` tracking) for labels + `ui-monospace` 10.5px for ages/status meta; state word 21px/300 |
| Spacing / radii | 4-based scale; cards 14px, buttons 10px, pills 999 |
| Shadow | `0 18px 50px rgba(0,0,0,.55), 0 2px 8px rgba(0,0,0,.4)` (dark) |
| Motion | `cubic-bezier(.22,1,.36,1)`; 160/260ms UI; ambient orb 4.5s breathe / 22s wave drift / 64s speckle orbit — all ≤ 0.25 Hz |

Chrome stays monochrome bone/ink; only the orb and status dot carry the
three live hues. That is the deliberate aesthetic risk: a tri-hue "living"
orb inside an otherwise monochrome console instead of the generic
one-neon-accent dark theme.

## 3. Files ADDED (safe under any upstream merge)

- `static/frontir.css` — tokens, skin palettes, scoped shell restyle,
  console components. ~700 lines, fully self-contained.
- `static/frontir.js` — skin registration, sidebar nav/user-chip
  injection, voice console (orb/cards/dock), passive voice-state observer,
  card drag, focus trap. Idempotent IIFE; no upstream function is patched
  except one *wrapper* (see §6).
- `static/frontir-shield.png`, `frontir-shield-ink.png` — shield emblem
  (white / ink), cropped from the master lockup.
- `static/frontir-wordmark.png`, `frontir-wordmark-ink.png` — trimmed
  full lockup (white / ink).
- `static/frontir-icon-32.png`, `frontir-icon-192.png`,
  `frontir-icon-512.png` — app icons: white shield at 60% on opaque
  `#09090B` (maskable-safe).
- `static/frontir-icon.svg` — SVG favicon wrapper embedding the 192px PNG.
- `FRONTIR-UI.md` — this file.

Asset provenance: generated from
`C:\Users\Bryce\Desktop\frontir_logo_2_horizontal.png` (shield = left
126×118px content box) via System.Drawing; no Desktop path is referenced
at runtime.

## 4. Files EDITED IN PLACE (each block delimited with `<!-- FRONTIR -->` / `// FRONTIR`)

**`static/index.html`** — 7 small, structural-free edits:
1. `<title>` → `Frontir Sentry`.
2. Favicon `<link>` hrefs → `frontir-icon.svg` / `frontir-icon-32.png`
   (upstream `favicon.*` files untouched; legacy `.ico` line untouched).
3. `apple-mobile-web-app-title` → `Sentry`; `apple-touch-icon` href →
   `frontir-icon-512.png`.
4. First-run skin seed script (before the stock skin-normalization script,
   which would otherwise write `default` on first visit — boot.js's
   `pendingExt` path then preserves `frontir` until frontir.js registers it).
5. Pre-boot `theme-color` metas + inline constants → `#09090B` / `#F4F3EF`
   (boot.js re-syncs from computed `--sidebar` after boot, so other skins
   correct themselves at runtime).
6. `<link>` for `frontir.css` directly after `style.css`.
7. `<script defer>` for `frontir.js` after `boot.js`/`outline.js` (it needs
   `registerHermesSkin` defined).

**`static/sw.js`** — one delimited block appending the frontir assets to
`SHELL_ASSETS` (versioned entries use the same `__WEBUI_VERSION__` query;
the request-time substitution in `api/routes.py` covers them automatically).

**`static/manifest.json`** — rebranded `name`/`short_name`/`description`/
`background_color`/`theme_color` and pointed `icons`/`shortcuts` at the
frontir icon set. JSON cannot carry comments; treat the whole file as
Frontir-owned on merges (see §7).

**Zero edits to:** `style.css` (7,240 lines untouched), `boot.js`,
`panels.js`, `sessions.js`, `messages.js`, `ui.js` (see §6), `commands.js`,
`workspace.js`, `terminal.js`, any Python.

## 5. The voice console

- Opened from the injected **Voice** nav item, and auto-surfaces when the
  built-in voice mode (composer audio-lines button) activates while the
  frontir skin is selected. `Escape`, the ✕ button, or **Transcript**
  return to the normal chat view; a running voice session continues.
- **Orb**: pure CSS — layered radial gradients + fine box-shadow rim, two
  blurred gradient "aurora" lobes clipped inside the sphere, and 18
  hand-placed speckle motes on a single 2.5px element's box-shadow list.
  No canvas, no SVG filters, no external assets, no libraries.
- **Cheap by construction**: exactly three animated layers (two waves +
  speckle ring), all animating `transform` only, at 22s/30s/64s periods;
  `will-change` on the two waves only. When the console is closed
  (`hidden` → `display:none`) all animation stops entirely. Idle state
  animates nothing but the waves' drift.
- **Reduced motion**: every `animation` lives inside
  `@media (prefers-reduced-motion: no-preference)` — reduced-motion users
  get a fully static (still legible, still state-colored) orb. Nothing
  flashes above 0.25 Hz for anyone, far below photosensitivity thresholds.
- **State machine**: frontir.js *observes* `#voiceModeIndicator` /
  `#btnVoiceMode` class changes via MutationObserver and mirrors
  idle/listening/thinking/speaking into `data-frontir-state`. It never
  re-implements or monkey-patches the boot.js voice loop; the orb and
  "Start session" button just `.click()` the existing `#btnVoiceMode`.
- **Realtime availability**: boot.js only exposes `_voiceModeActive` when
  both SpeechRecognition and speechSynthesis exist, so the status line
  shows "Realtime ready" / "Realtime unavailable" from that single signal
  (Firefox and some WKWebView contexts land on unavailable, with orb and
  Start button disabled).
- **Glass cards**: "Live context" (Project / Focus / Files / Recent /
  Workspace, read defensively from `S` and existing DOM — no new API
  calls) and "Current goals" (from `S.todos`). Draggable by the grab
  handle on desktop (pointer events, viewport-clamped, persisted to
  localStorage); static stacked flow below the orb under 980px. The
  footers ("View context ›" / "View goals ›") deep-link to the workspace
  panel and Todos panel.
- **Dialog semantics**: `role="dialog" aria-modal="true"`, focus moves to
  the orb on open, Tab is trapped within the console, focus restored on
  close. The state word is `role="status" aria-live="polite"`.
- **Scroll safety**: the console is its own fixed, full-viewport scroll
  container (`overscroll-behavior:contain`). No upstream scroll container
  (`.messages`, `.messages-inner`, sidebar lists) is touched, so the iOS
  `overflow-anchor` / `content-visibility` / scroll-anchoring fixes from
  CHANGELOG (#4856, #5338 et al.) are untouched.
- **Safe areas**: console padding, dock offset, and the sidebar user chip
  all use `env(safe-area-inset-*)`.

## 6. The one runtime wrapper (and why)

`frontir.js` wraps `window.assistantDisplayName` so its `'Hermes'`
*fallback* reads `'Sentry'`. A user-chosen bot name always wins (the
wrapper only rewrites the exact string `'Hermes'`), and the original
function is still called — so upstream changes to it keep working. This
was chosen over editing `ui.js` (merge pain) or overriding `_botName`
(that's user data). If upstream ever renames the default, the wrapper
silently becomes a no-op — worst case the UI says "Hermes" again.

## 7. Re-applying after an upstream merge

Daily-merge playbook, in order of likelihood:

1. **`static/frontir.*` + `FRONTIR-UI.md`**: ours-only files; upstream can
   never conflict with them. If git ever flags them, take ours.
2. **`index.html`**: conflicts appear only inside/adjacent to the seven
   `<!-- FRONTIR -->` blocks. Resolution: take upstream's version of the
   surrounding markup, then re-apply each block verbatim (they are
   position-tolerant: the CSS link just needs to be *after* style.css, the
   JS script *after* boot.js, the skin seed *before* the stock skin
   script, everything else is order-free head metadata).
3. **`sw.js`**: take upstream's `SHELL_ASSETS`, re-append the delimited
   FRONTIR block before the closing `];`.
4. **`manifest.json`**: take upstream's version, then re-apply the six
   brandable fields (`name`, `short_name`, `description`,
   `background_color`, `theme_color`, icon/shortcut `src`s). The diff is
   the whole file, so `git checkout --theirs` + re-brand is fastest.
5. **Selector drift**: if upstream renames a class that frontir.css
   overrides (e.g. `.session-time`), the override silently stops applying
   — the app still works, one detail reverts to stock styling. Grep
   frontir.css for the old name and update. The token contract
   (`--bg`/`--surface`/`--accent`/…) is upstream-documented in THEMES.md
   and is the least likely thing to move.
6. **Behavioral hooks used by frontir.js** (all with graceful degradation
   if absent): `registerHermesSkin`, `switchPanel`, `stopTTS`,
   `toggleWorkspacePanel`, `_voiceModeActive`, `#btnVoiceMode`,
   `#voiceModeIndicator`, `#btnNewChat`, `#profileChipLabel`,
   `#composerWorkspaceLabel`, `#sessionList`, `#fileTree`, `window.S`.
   Every access is `typeof`/null-guarded; a renamed hook degrades a
   feature (e.g. a card row shows "—") rather than breaking the app.

Quick post-merge smoke: load the app → Frontir look present; Settings →
Appearance shows the Frontir swatch; `/theme default` restores stock;
`/theme frontir` returns; Voice nav opens the console; reduced-motion OS
setting freezes the orb.

## 8. Deliberately left alone

- **`style.css`** — zero in-place edits, by design.
- **The rail/sidebar/panel DOM** — untouched; the target's single-sidebar
  look is approximated by *recoloring* rail + sidebar into one visual
  column instead of restructuring (course-corrected requirement; also the
  cheapest possible merge posture).
- ~~**`favicon.ico`**~~ — RESOLVED 2026-07-20, see §10.
- ~~**`static/login.js` / the login page template**~~ — RESOLVED: the login
  page in `api/routes.py` now carries inlined Nightwatch/Daywatch tokens
  (it cannot use `frontir.css` — it renders before the skin system boots).
- ~~**`share.html`**~~ — RESOLVED: its inline boot script already forwarded
  an unrecognised skin to `dataset.skin` via `pendingExt`, so `frontir` was
  being set all along with no stylesheet defining it. Adding the `<link>`
  was the whole fix.
- **i18n** — console copy is English-only; the upstream `t()` catalog was
  not extended, to avoid touching `i18n.js` (merge pain for ~30 strings).
- **`assistantDisplayName` default** — wrapped, not edited (§6).
- **Hidden-tab reorder inline script, CSRF shim, RTL bootstrap** — all
  adjacent head scripts untouched.
- **The extension-manifest route** (`HERMES_WEBUI_EXTENSION_DIR`) was
  *not* used to load frontir.js/css: this is a fork shipping its own
  brand, so the layer belongs in the repo where the SW can precache it and
  no operator env-vars are required. The code is still written to the
  extension authoring guidelines (additive, reversible, guarded), so it
  could be repackaged as an extension later with only the index.html/sw.js
  edits dropped.

## 9. Known limitations / open decisions for Bryce

- **Light-mode theme_color**: the PWA manifest allows only one
  `theme_color` (`#09090B`); iOS light-theme users see a dark status bar
  until boot.js re-syncs. Cosmetic, first-paint only.
- ~~**"Projects" section**~~ — DECIDED 2026-07-20: ship it, as a *promotion
  of the real thing*. Hermes already has a full project system (create /
  rename / delete / colour, profile-scoped, `projects.json`, `/api/projects`)
  rendered as `.project-bar` at the top of the session list. frontir.js adds
  no state, no API calls and no handlers — it labels that bar (`role=group`,
  `aria-label`, an `<h3>`) and frontir.css lays it out as the mock's vertical
  section. Every upstream interaction survives; another skin restores the
  stock chip row. The section appears with the first conversation (the bar
  is absent only on a profile with no projects *and* no sessions), which is
  also the first moment it could say anything true.
- ~~**Speaker button**~~ — DECIDED 2026-07-20: a persistent mute, as asked.
  **The note above was wrong about the mechanism and it matters.**
  `hermes-tts-enabled` is not a mute: its entire effect is the
  `body.tts-enabled` class, which CSS uses to *show* the per-message
  read-aloud buttons. Wiring a mute to it would hide affordances and
  silence nothing, and there is no other upstream mute preference — so the
  layer owns `frontir-muted`.
  Enforcement is a wrapper on `window.autoReadLastAssistant`, the single
  entry to every speech path (messages.js calls it on stream completion;
  boot.js overrides it so a live session routes into `_speakResponse()`).
  Two consequences worth knowing:
  - boot.js **restores the original** on voice deactivate, dropping the
    wrapper — so it is re-asserted from the voice observer (idempotent).
  - a live voice session is deliberately let through. boot.js only returns
    the turn loop to listening from *inside* `_speakResponse()`, so
    skipping it would park the session in `thinking` forever. Muting still
    stops the utterance that is playing; ending the session stops voice.
    Gating voice properly needs a boot.js patch — a separate call.
- ~~**`login` page and `share.html`**~~ — both branded, see §8.
- **Light-mode theme_color** remains the one open cosmetic item (above).
- Console screenshots were verified against a static harness (real
  `style.css` + real markup slices + mocked JS surfaces) — dark, light,
  mobile, and stock-skin-reversion all pass. Behaviour is now covered too:
  `node tests/frontir_layer_harness.mjs` executes frontir.js against a
  minimal DOM and asserts the Projects re-labelling (including across a
  session-list re-render) and the whole mute contract, boot.js
  clobber/re-wrap cycle included. A live end-to-end pass on the running
  gateway + an actual iOS PWA install is still worth doing.

## 10. Icon set (2026-07-20)

Regenerated from the brand master by a traced-geometry pipeline rather than
by resizing rasters. Four defects were found and fixed:

| Was | Now |
|---|---|
| `frontir-icon.svg` was a 192px PNG inside an `<image>` tag, while `manifest.json` advertised it `sizes:"any"` — it claimed vector and was not | genuine vector: the shield alpha traced to 5 closed loops / 540 vertices, verified at **99.4% IoU** by re-rasterising the polygons and diffing against the source. 7.4KB, down from 21.7KB |
| `favicon.ico` was the upstream Hermes caduceus, one 256px frame | Frontir mark, real multi-size **16/24/32/48/64/128/256** |
| one icon declared `purpose:"any maskable"`, but the shape reaches **r=54.3%** of the canvas where Android's circular mask allows 40% — it was being clipped | `any` and `maskable` are separate assets; `frontir-icon-maskable-512.png` composes the mark to **r=38%** |
| small sizes reused the large composition, so at 16px the mark resolved to grey mush | optical sizing on two axes: the mark grows (58.8% → 82% of canvas) *and* sheds its two finest shapes (triangle ≤20px, lens ≤24px) as size drops |

`favicon-32.png`, `favicon-192.png`, `favicon-512.png`, `favicon.svg`,
`favicon-512.svg` and `apple-touch-icon.png` are upstream *filenames* that
are now rebranded in place. This is a deliberate departure from "upstream
files left untouched": `messages.js` uses `favicon-192`/`favicon-32` as the
push-notification icon and badge, so leaving them stock shipped the Hermes
caduceus in every notification. Rebranding the files fixes that with no
edit to `messages.js`. Binary conflicts on an upstream merge resolve as
"always take ours".

Also added: `frontir-icon-16.png`, `frontir-icon-180.png` (the size iOS
actually rasterises the home-screen icon at — it had been downsampling the
512 on every install), both linked from `index.html` and precached in
`sw.js`.

Regenerate with `python scripts/frontir/gen_icons.py` (pure PIL — no
numpy/cv2 needed). `scripts/frontir/trace_shield.py` holds the tracer and
prints the fidelity number; both are deterministic, so re-running produces
byte-identical assets.
