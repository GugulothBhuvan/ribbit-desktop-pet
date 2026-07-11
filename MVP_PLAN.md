# MVP Stabilization Plan — Desktop Pet AI

**Companion to:** `AUDIT_REPORT.md` (2026-07-12). Finding IDs (C-x, M-x, m-x, AV-x) refer to that report.
**Goal:** every PRD §20 acceptance criterion passing, on a foundation that won't need re-wiring later.
**Estimated effort:** ~13–18 working days for one engineer, sequenced so the app is runnable and testable after every phase.

**Ground rule for the whole plan:** after Phase 1, *nothing* merges without being observed working in the running app. The audit showed every subsystem was written but the core loop never once functioned in any recorded session.

---

## Phase 0 — Security & hygiene (½ day) — DO FIRST, independent of everything

- [ ] **0.1 Rotate all three API keys** (Gemini, Krutrim, Deepgram). They live in plaintext `.env` and have been exposed to tooling; the Gemini key also leaks via error strings (C-5).
- [ ] **0.2** `git init` + `.gitignore` covering `.env`, `storage/`, `*.wav`, `__pycache__/`, `.venv/`, `.pytest_cache/`, `*.db`. Commit the clean tree as the baseline for all following work.
- [ ] **0.3** Move Gemini key from URL query param to `x-goog-api-key` header (`src/ai/providers/gemini.py:21`). Never yield `str(e)` into speech bubbles (`gemini.py:77,133`, `krutrim.py:68,104`, `deepgram.py:59`) — replace with the TRD §12 canned line ("I'm having trouble thinking right now.") and log the real error.
- [ ] **0.4** Drop window-title logging to DEBUG (`src/observer/win32_hook.py:110`); add log rotation (`RotatingFileHandler`, ~2 MB × 3) in `src/utils/logger.py`.
- [ ] **0.5** Delete stray artifacts: `speech_record.wav` (root), `storage/test_memory.db`; write future PTT audio to `%TEMP%` and delete after transcription (m-17).

**Exit check:** fresh clone + new `.env` runs identically; no secret appears in `storage/logs/app.log` after a forced network error.

---

## Phase 1 — Runtime skeleton: composition root + event bus (2–3 days) — fixes C-1, C-2, C-3, AV-1..5

This is the phase that turns the product on. Do it as one unit; the pieces don't work separately.

- [ ] **1.1 Reorder `main.py`:** create `QApplication` *first*, then build everything, then start the worker thread *last* (fixes AV-4).
- [ ] **1.2 New `src/core/composition.py`:** a `CompositionRoot` constructed on the GUI thread that explicitly builds, in order: `EventBus → Database → SpriteLoader → StateMachine → ContextEngine → AIOrchestrator → PetWindow → TelemetryTracker → PluginManager → Win32Observer → AmbientScheduler`, passing dependencies as constructor args.
- [ ] **1.3 Delete every `get_instance()`** (8 singletons: `event_bus.py:66`, `application.py:18`, `db.py:16`, `sprite_loader.py:20`, `scheduler.py:79`, `telemetry.py:17`, `audio_recorder.py:16`, `plugins/manager.py:18`). Constructors take dependencies; no module-level state.
- [ ] **1.4 Rebuild `EventBus`** (thread-correct, per-type):
  - `subscribe(event_type: str, callback, *, executor: Literal["gui","async"])`.
  - GUI-executor callbacks delivered via a queued `pyqtSignal` on a QObject owned by the GUI thread.
  - Async-executor callbacks delivered via `loop.call_soon_threadsafe` onto the worker loop.
  - `publish()` callable from any thread.
  - This kills the silent-queued-forever defect (C-2) and the every-subscriber-gets-every-event dispatch towers (m-23).
- [ ] **1.5 Wire `AIOrchestrator`:** instantiate it in the root (C-1); replace `self.ai_orchestrator` in `window.py:372` with an event (`SCREEN_CAPTURED` carrying bytes) or an injected reference. Decide the **single owner** of `VISION_CAPTURE_REQUESTED` now (recommended: window performs hide+grab, orchestrator consumes the result) — removes AV-6 double-capture.
- [ ] **1.6 `StateMachine` lives on the GUI thread** (it drives sprites; arch spec agrees). `AmbientScheduler.on_event` and telemetry subscribe with `executor="async"`.
- [ ] **1.7 Keep the asyncio worker** (`Application`) but it now only hosts: DB, scheduler loop, LLM prep, transcription. It owns zero Qt objects.

**Exit check (the audit's smoking gun, inverted):** run the app, drag the pet up, release → it *falls and lands*; log shows `State transition: idle -> fall -> landing -> idle`. Left-click → `LLM_REQUEST_SENT` appears in the log and a bubble streams (with a real key). This exact scenario becomes integration test IT-1 in Phase 8.

---

## Phase 2 — One-line & mechanical bug fixes (1 day)

All small, all from the audit, all testable:

- [ ] **2.1** `telemetry.py:71` `execute_update` → `execute_non_query` (C-4). Add a unit test that inserts a row.
- [ ] **2.2** `BatteryLifePercent`: `c_byte` → `c_ubyte`; deduplicate `SYSTEM_POWER_STATUS` + battery read into one `src/utils/win32.py` used by both `context_engine.py` and `win32_hook.py` (M-3). Return `None` for unknown (255) and omit from prompts/warnings.
- [ ] **2.3** `deepgram.py:59`: return `None` on failure; `orchestrator._transcribe_and_query` branches on `None` (M-5).
- [ ] **2.4** `krutrim.py:117`: health URL → `https://cloud.olakrutrim.com/v1/models` (m-12).
- [ ] **2.5** `config.py:41-43`: `validate()` accepts `{"krutrim","gemini"}`; replace all `print()` with logger (M-13, m-11).
- [ ] **2.6** `collision.py:45-47`: use `bottom()+1` / `right()+1` semantics or `top()+height()` (m-1).
- [ ] **2.7** `_observe_network` (`win32_hook.py:156-168`): delete it (its result is unused) — or if kept for future offline mode: close the socket, no `setdefaulttimeout`, poll every 60 s, publish an event (M-8).
- [ ] **2.8** Fix memory-extraction splits with word-boundary regex; fix the `" teases me..."` prompt string (m-6, m-14).
- [ ] **2.9** Single-instance guard (named mutex via `CreateMutexW` or a lock file) (m-18).

---

## Phase 3 — Input & conversation correctness (1–2 days)

- [ ] **3.1 Click vs drag vs double-click** (`window.py:123-165`, M-2): record press position/time; treat as *click* only if release is <6 px and <250 ms from press; use `mouseDoubleClickEvent` for double-click; a drag-release triggers physics only, never chat.
- [ ] **3.2 Speech cooldown:** gate all non-user-initiated bubbles behind `Config.SPEECH_BUBBLE_COOLDOWN_SEC` (currently dead config); user clicks bypass it but are limited to one in-flight query.
- [ ] **3.3 Streaming bubble fixes** (`speech_bubble.py`): clear "Thinking..." on first chunk (M-1); cancel `dismiss_timer` in `append_chunk` (m-8); don't pre-size to final text (m-9); reuse one `QFontMetrics`.
- [ ] **3.4 Response validator:** enforce `MAX_CHARACTERS=150` *at the stream layer* — stop consuming, close the stream, append "…" (PRD §12.2, currently unimplemented). Strip markdown/newlines.
- [ ] **3.5 One in-flight LLM query:** persistent `LLMStreamWorker` (or asyncio task) with cancellation; new query while busy either cancels the old one or is ignored with a shake animation (M-6).
- [ ] **3.6 Hover:** resume prior state in `leaveEvent`; use `event.position()` (m-24).
- [ ] **3.7** LLM error bubble shows a generic canned line, and `LLM_ERROR_OCCURRED` returns state machine to idle (already does) — remove the misleading "API unconfigured?" (m-10).

---

## Phase 4 — Physics & animation to spec (2 days)

- [ ] **4.1 Delta-time physics:** `QElapsedTimer`-measured `dt`, clamped to ≤50 ms; `Qt.TimerType.PreciseTimer` for the 60 Hz loop (m-3).
- [ ] **4.2 Retune gravity** so falls visibly accelerate (~2000 px/s², terminal ~1200 px/s; express constants in px/s², not per-frame) (m-2).
- [ ] **4.3** Single `resolve_boundaries` per tick (m-4); floor coyote-margin to stop IDLE/FALL flapping.
- [ ] **4.4 Missing states:** add `sleep`, `listen`, `dragged` entries to `metadata.json` (reuse existing rows if art is pending) **and** implement the fallback chain `requested → idle` in `SpriteLoader`/renderer (TRD §12, M-4) so a bad sprite pack can never make the pet invisible.
- [ ] **4.5 Cache correctness:** touch `_last_accessed` from the render path; never purge the active animation; renderer re-pulls frames after `set_scale`/`set_mascot`; cache mirrored frames keyed `(anim, scale, direction)` (M-7, perf #2).
- [ ] **4.6 Repaint discipline:** call `self.update()` only when the frame index or window position actually changed — this is the single biggest idle-CPU win (perf #1). `move()` only on position change.
- [ ] **4.7** Honor per-frame `duration_ms` from metadata (drive `anim_timer` per frame instead of fixed fps).
- [ ] **4.8** Double-click plays `wave` or a real jump (`crouch → launch → fall → landing`), never bare `FALL` on the ground (m-5) — this also finally uses the crouch/launch frames.

**Exit check:** drop from top of screen shows visible acceleration and a landing squash; task manager shows the idle process at <1% CPU (measure, don't assume).

---

## Phase 5 — AI pipeline hardening (2–3 days)

- [ ] **5.1 Vision path:** capture via window hide → grab; downscale to ≤1024 px and encode JPEG q≈70 with Pillow **on the worker thread**, not the GUI thread (M-10, TRD 9.3); gate on `provider.supports_vision()` — if the active provider can't see, say so in the bubble instead of silently dropping the image.
- [ ] **5.2 Retry policy:** 2 retries with exponential backoff + jitter on timeouts/5xx, none on 4xx; single pooled `httpx.AsyncClient` per provider (perf #8).
- [ ] **5.3 Prompt cleanup:** extract `SYSTEM_PROMPT_TEMPLATE` to `src/ai/prompts.py`; omit unavailable fields (no "Battery: -1%", no "git: unknown"); inject memories as structured bullets, not `dict` repr; history limit consistent with PRD (20).
- [ ] **5.4 Ambient scheduler:** confirm the arch-spec loop (cooldown → buffer → stability → dispatch) now actually receives events post-Phase 1; align cooldown with docs (10 s vs current 20 s — pick one and update the doc).
- [ ] **5.5 Git/pytest context:** run `subprocess` in `run_in_executor` with `CREATE_NO_WINDOW`; target the *foreground app's* working directory or disable until Phase-3-of-PRD; never block the worker loop (M-9).
- [ ] **5.6 PTT via global hotkey** (`RegisterHotKey` on the observer thread, or click-and-hold mic affordance) so voice works without focusing the pet and without stealing Space from the IDE (M-11).

---

## Phase 6 — Persistence, scheduler, ambient behavior (1–2 days)

- [ ] **6.1 DB:** one persistent aiosqlite connection on the worker loop; `PRAGMA journal_mode=WAL`, `busy_timeout=3000` (M-14).
- [ ] **6.2 Prune jobs:** conversation >100 rows, `application_usage` >30 days (arch spec §9); corruption recovery: on open failure, back up file, recreate schema (TRD §12).
- [ ] **6.3 Reminders become usable:** "Add reminder…" dialog in the context menu (and/or LLM extraction of "remind me to X at Y") — the polling engine exists, the create path doesn't (M-12).
- [ ] **6.4 Weather:** HTTPS endpoints, fetch silently at startup (no unprompted bubble), announce at most once per session behind the cooldown; document the ip-api dependency or replace it (M-15).
- [ ] **6.5 Settings that PRD promises:** persist scale + mute (currently reset every launch); add typing-speed and reduced-motion toggles (stationary idle mode) to the menu (PRD §15).
- [ ] **6.6 Battery warning:** only when on battery, ≤20%, at most once per hour.

---

## Phase 7 — Lifecycle & shutdown (1 day)

- [ ] **7.1** `closeEvent`/quit path: stop `physics_timer`, `anim_timer`, bubble timers; cancel the in-flight LLM worker; `AudioRecorder.cleanup()`; publish `APPLICATION_SHUTTING_DOWN` and flush telemetry *before* stopping the loop (m-16, m-19).
- [ ] **7.2** `Application.shutdown`: cancel pending tasks (`asyncio.all_tasks`), await briefly, then `loop.stop()`; `loop.close()` after join.
- [ ] **7.3** Scheduler loop exits on a cancellation event instead of `while True`.

---

## Phase 8 — Tests & verification (2–3 days)

- [ ] **8.1 `tests/conftest.py`:** tmp-path DB fixture (stop mutating the shared singleton path — it's gone anyway post-Phase 1), event-bus fixture, `qapp` re-export.
- [ ] **8.2 Regression tests for every audit critical:** state-machine transition delivery across threads (C-2), orchestrator wiring (C-1), telemetry insert (C-4), battery unsigned read (M-3), Deepgram failure → no LLM call (M-5), stream truncation at 150 chars (3.4), click-vs-drag classification (M-2), cache purge exempts active anim (M-7), missing-animation fallback (M-4).
- [ ] **8.3 IT-1 headless integration test:** boot composition root with a mocked provider → simulate click → assert `think → talk → idle` transitions and bubble text — the test that would have caught the entire audit headline.
- [ ] **8.4 Soak & budget measurement:** scripted 2-hour run logging CPU%/RSS every 30 s (psutil or `Get-Counter`); assert idle CPU <1%, RSS <300 MB, no monotonic RSS growth. Do one manual 8-hour run before calling MVP done (PRD §20.6).

---

## Phase 9 — Docs & packaging (1 day)

- [ ] **9.1** `pyproject.toml` (packaging, pytest config, `asyncio_mode`), `__init__.py` files, remove the `sys.path` hack in `main.py:5`.
- [ ] **9.2** `README.md`: setup, `.env.example` flow, run, test.
- [ ] **9.3 Reconcile the three documents** (audit Appendix A): pick one LLM default (recommend documenting the dual-provider reality: Krutrim default, Gemini for vision), one FPS target (60), one RAM budget (300 MB), one schema. Move Pomodoro/weather/IDE-sync from "roadmap" to "implemented" sections. Docs are the source of truth again only once they agree with each other.
- [ ] **9.4** Move `generate_debug_sprites.py` to `tools/`; fix its 128×128 vs 138×191 mismatch or regenerate metadata alongside (m-21).

---

## MVP acceptance gate (PRD §20 mapped to phases)

| # | PRD acceptance criterion | Satisfied by |
|---|---|---|
| 1 | Borderless transparent window | Already ✅ |
| 2 | Clean 60 FPS sprite rendering | Phases 1, 4 (4.5–4.7) |
| 3 | Walks, idles, falls, lands on taskbar | Phases 1, 4 |
| 4 | Drag suspends gravity; release computes throw velocity | Phases 1, 3.1, 4 |
| 5 | Left-click → async LLM stream in auto-resizing bubble | Phases 1, 3 |
| 6 | 8-hour run, <300 MB, <2% CPU | Phases 4.6, 2.7, 8.4 |
| 7 | Conversation + profile persisted in SQLite | Phase 6.1–6.2 (+ existing repos) |

**Definition of done:** IT-1 green in CI, all Phase-8 regression tests green, soak run within budgets, and a manual checklist pass of the seven criteria above on a real desktop with a real API key.
