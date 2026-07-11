# Desktop Pet AI — Complete Software Audit

**Audit date:** 2026-07-12
**Auditor role:** Principal Engineer / Architect / QA Lead / Python Performance review
**Scope:** Full source tree (`src/`, `tests/`, `assets/`), all documentation (`PRD.md`, `TRD.md`, `architecture_specification.md`), runtime evidence (`storage/logs/app.log`, `storage/pet_memory.db`, `speech_record.wav`).

> **Method note.** This audit is not purely static. The repository contains a runtime log (`storage/logs/app.log`) from three real application sessions on 2026-07-12. Several findings below are *empirically confirmed* by that log, not just inferred from code.

---

## 1. Executive Summary

The project has a clean-looking module layout that superficially matches the TRD/architecture spec, decent low-level building blocks (repositories, providers, sprite slicing), and reasonable intent everywhere. **However, the application as delivered is fundamentally non-functional as an "AI desktop pet."** Three defects, each independently fatal, combine so that the shipped behavior is: *a static, idle-looping sprite that can be dragged around and occasionally shows a weather bubble.*

The three fatal defects:

1. **The `AIOrchestrator` is never instantiated** (`src/ai/orchestrator.py:66`). No object ever constructs it, so no component handles `CHAT_QUERY_REQUESTED`, `VOICE_RECORD_STOPPED`, or vision events. Left-click chat, voice PTT transcription, and screen analysis are all dead code. `PetWindow._execute_capture` even references `self.ai_orchestrator` (`src/ui/window.py:372`), an attribute that never exists → guaranteed `AttributeError`. **Log evidence:** the user pressed PTT at 03:41:31, audio was saved, `VOICE_RECORD_STOPPED` was published — and no transcription/LLM log line ever appears.

2. **The event bus does not deliver events to any subscriber registered on the background thread.** `StateMachine`, `AmbientScheduler`, `TelemetryTracker`, and all plugins subscribe from the asyncio worker thread (`src/core/application.py:48-67`). PyQt queues cross-thread signal deliveries to the receiver's thread event loop — but that thread runs `asyncio.run_forever()`, not a Qt event loop, so queued deliveries are never processed. **Log evidence:** `StateMachine.set_state` logs every transition at INFO; across three sessions with dragging, PTT (which publishes `STATE_TRANSITION_TRIGGERED`), and constant physics recommendations, there is **not one** "State transition" line, not one "Cache miss" for any animation other than `idle`, and not one "Scheduler: Application change queued" line despite dozens of `APPLICATION_CHANGED` events. The pet therefore never walks, never falls after being dropped (physics `FALL` state is never entered — the pet hangs in mid-air), never plays think/talk/listen animations, and the ambient AI scheduler and telemetry are inert.

3. **Startup is a thread race.** `Application.start()` begins constructing Qt objects (`SpriteLoader` → `QPixmap`, `QTimer`) on the background thread *before* `QApplication` is created on the main thread (`src/main.py:18-26`), and every singleton uses an unsynchronized `if cls._instance is None` check hit concurrently from both threads. Which thread wins the `SpriteLoader`/`EventBus` singleton race is nondeterministic per run — this can produce duplicate event buses (events silently split) or a hard crash ("Must construct a QGuiApplication before a QPixmap").

Beyond these, the audit found ~40 defects including a security leak (the Gemini API key is embedded in URLs that are echoed into exception strings, then shown in the speech bubble and written to the log), a signed-byte bug that makes battery status report `-1%`, a per-second unclosed socket to `8.8.8.8`, an LLM-usage-tracking method call to a function that does not exist, and multiple PRD requirements (150-char validator, speech cooldowns, never-steal-focus, reduced-motion, settings UI) that are absent.

**Verdict: not shippable.** The skeleton is salvageable; the wiring is not. See §27.

---

## 2. Architecture Score: **3.5 / 10**

What's good: module boundaries mostly match the docs; provider abstraction (`LLMProvider`/`VoiceProvider`) is clean; repository layer is clean; event catalog exists.

What sinks it: the central architectural promise — "every core subsystem communicates purely via an asynchronous event bus" (TRD §1) — is implemented on a mechanism that provably does not deliver events across the app's actual thread topology. Thread-ownership rules (TRD §10, arch spec §10) are violated in at least four places. Singletons everywhere defeat the "decoupled, testable" goal and create races. Key orchestration (AI) is unwired entirely.

## 3. Code Quality Score: **5 / 10**

Readable, consistently formatted, docstrings present, some type hints. But: dead code (`MAX_CHARACTERS`, `PET_VOLUME`, `SPEECH_TYPING_SPEED_MS`, `SPEECH_BUBBLE_COOLDOWN_SEC`, `WANDER_INTERVAL_*`, `PET_CLICKED`, `CROUCH`), a call to a nonexistent method (`execute_update`), a reference to a nonexistent attribute (`ai_orchestrator`), `print()` mixed with logging, magic numbers throughout physics/UI, an event type misused as a scale-change message, and copy-pasted ctypes structs in two files.

## 4. Performance Score: **4 / 10**

Nothing here meets the "<1% idle CPU" budget: unconditional 60 Hz repaint + 60 Hz physics even when fully idle, a new socket connection to 8.8.8.8 every second, per-paint pixmap mirroring allocation, full-resolution PNG screen encode on the GUI thread, and a new SQLite connection per query. RAM is fine (single 6 MB decoded sheet + small frame caches). Startup is fine (<1s observed).

## 5. AI Architecture Score: **2 / 10**

The pipeline design on paper (orchestrator → context engine → memory → provider) is sound and matches the TRD. In the running binary it does not exist: the orchestrator is never constructed, the scheduler's decision engine never receives events, the default provider (Krutrim) silently discards images while the ambient pipeline is vision-based, STT errors are fed back into the LLM as user prompts, and there is no retry, rate limiting, response-length validation, or output sanitization.

## 6. Physics Score: **5 / 10**

Gravity/terminal velocity/drag/bounce/multi-monitor clamping are implemented and reasonable (`src/physics/`). But gravity reaches terminal velocity within ~2 frames (no visible acceleration), timing assumes a perfect 60 Hz timer with no measured delta-time, `resolve_boundaries` runs twice per tick, and — because of the event bus defect — the `FALL` state is never actually entered at runtime, so in practice **gravity never runs**: a pet dropped mid-air floats.

## 7. Animation Score: **4 / 10**

Metadata-driven slicing/scaling/caching is genuinely good and supports future sprite packs. But three states the code uses (`sleep`, `listen`, `dragged`) have **no animation in metadata.json** → empty frame list → invisible pet, with no idle fallback (TRD §12 requires one). Per-frame `duration_ms` is parsed but ignored. The "LRU" cache purges the *actively rendered* animation (log: `Purging stale animation 'idle'` while idle was on-screen) because access time is only touched on load, and the renderer keeps stale frame lists after purge/scale changes.

## 8. UX Score: **2 / 10**

As shipped it is neither a living companion nor a chatbot: it cannot chat at all. Every drag-release fires a chat query (if the AI worked), single-click fires before double-click can be detected, the pet speaks unprompted at startup (weather), the LLM error message is always "API unconfigured?", and hovering permanently interrupts walks with no resume. No settings window exists.

## 9. Maintainability Score: **4.5 / 10**

Small files, clear names — but 8 singletons with hidden construction-order dependencies, event handling via stringly-typed `if/elif` towers in 5 places, config duplicated between `Config` and `constants.py`, and no README/docs folder/git repo. A new engineer cannot know that instantiation order is load-bearing.

## 10. Security Score: **3 / 10**

Real API keys sit in `.env` (fine locally, but the folder isn't even a git repo with an ignore file — one `git init && git add .` away from leaking; **rotate all three keys**, they've also now been read by tooling). Gemini key is embedded in URL query strings (`src/ai/providers/gemini.py:21`) — httpx exceptions include the URL, and those exception strings are yielded into the speech bubble and written to `storage/logs/app.log`. Raw exception text is routinely shown to the user. Foreground window titles are continuously logged to plaintext (`win32_hook.py:110`) — titles can contain document names, emails, private-browsing titles. The host IP is sent to `ip-api.com` **over plain HTTP** hourly. The PTT recording `speech_record.wav` is written to the CWD and never deleted.

## 11. Documentation Compliance Score: **4 / 10**

The three documents also contradict *each other* (see §14/§26): PRD says Gemini 2.5 Flash; TRD says Krutrim Qwen 3.6; arch spec says `krutrim-2-instruct`, 30 FPS cap, <120 MB RAM vs PRD's 60 FPS, <300 MB. The implementation is a hybrid that fully satisfies none of them.

## 12. Feature Completion Percentage: **~40%**

(Weighted: rendering/window/physics/persistence largely present; AI/voice/vision/state-driven animation — the product core — effectively 0% functional at runtime.)

---

## 13. Feature Parity Checklist

Legend: ✅ fully implemented & working · 🟡 partial / implemented-but-broken · ❌ missing

| Feature (doc source) | Status | Evidence |
|---|---|---|
| Transparent frameless always-on-top Tool window (PRD 10.1, TRD 6.1) | ✅ | `src/ui/window.py:74-81` |
| High-DPI support (PRD 10.1) | 🟡 | Nothing explicit; Qt6 default scaling only |
| Multi-monitor boundary walls (PRD 10.1, TRD 7.3) | ✅ | `src/physics/collision.py:15-30` |
| Sprite sheet loading + metadata slicing (TRD 8.1) | ✅ | `src/animation/sprite_loader.py:93-136` |
| Animation metadata (fps/loop/frames) | 🟡 | `duration_ms` parsed but ignored; `sleep`/`listen`/`dragged` missing from `metadata.json` |
| LRU frame cache + 60s purge (PRD 14, TRD 8.2) | 🟡 | Exists but purges the active animation (`sprite_loader.py:152-166`); not actually LRU (no size bound) |
| Missing-asset fallback to idle (TRD §12) | ❌ | `renderer.set_animation` leaves empty list → invisible pet (`renderer.py:30-38`) |
| Idle animation | ✅ | Only state ever rendered (log-confirmed) |
| Walking / wandering (PRD 8.1) | 🟡 | Logic exists (`movement.py:100-119`) but state change never delivered → never walks at runtime |
| Gravity + terminal velocity (PRD 10.3) | 🟡 | `gravity.py` correct-ish; `FALL` never entered at runtime → pet floats when dropped |
| Dragging + throw momentum (PRD 8.4) | 🟡 | Drag works; throw velocity computed (`movement.py:49-70`) but release enters dead state path |
| Taskbar collision / land on taskbar (PRD 8.1/8.2) | 🟡 | `availableGeometry()` used ✅; landing state transition dead |
| Landing/crouch sequence (PRD 10.2 Row 4) | 🟡 | `landing` anim exists; `crouch`/`launch` states never reachable from code |
| Speech bubble w/ typewriter, auto-size, auto-fade (PRD 10.5) | ✅ | `src/ui/speech_bubble.py` — works standalone |
| 100–150 char response validator (PRD 12.2) | ❌ | `MAX_CHARACTERS` (`constants.py:42`) never referenced |
| Speech cooldown / "Never Spam" (PRD 9) | ❌ | `SPEECH_BUBBLE_COOLDOWN_SEC` never referenced |
| Thinking animation on request (PRD 19.1) | 🟡 | Event published (`window.py:263-264`) but state machine never receives it |
| Listening animation | ❌ | No `listen` frames in metadata + dead state machine |
| Sleeping / nap behavior (PRD 10.7) | ❌ | No `sleep` frames; state unreachable |
| Ambient random behaviors (stretch/yawn/scratch) (PRD 10.7) | 🟡 | Only idle→walk/wave/sleep roll (`movement.py:137-153`); none observable at runtime |
| Hover: pause + face cursor (PRD 10.4) | 🟡 | Direction flip works (`window.py:188-199`); "pause" is a permanent idle force, never resumes on leave (`leaveEvent` is `pass`) |
| Left-click dialogue (PRD 8.3) | ❌ | Publishes `CHAT_QUERY_REQUESTED`; no live subscriber (orchestrator never built) |
| Double-click special animation (PRD 10.4) | 🟡 | Fires *after* a single-click query already dispatched (`window.py:148-165`) |
| Right-click styled context menu (PRD 10.4) | 🟡 | Exists; missing Settings (volume/PTT toggle/typing speed), scale not persisted |
| Reduced-motion accessibility (PRD 15) | ❌ | Absent |
| Dynamic scaling 0.5–2.0x (PRD 15) | ✅ | `context_menu.py:92-99`, `window.py:93-103` (not persisted) |
| Gemini integration (PRD 10.6) | 🟡 | Provider complete (`providers/gemini.py`) but unreachable; provider default is Krutrim and `Config.validate()` rejects `"gemini"` (`config.py:41-43`) |
| Krutrim integration (TRD §3) | 🟡 | Provider complete; never invoked at runtime; `health()` targets wrong host (`krutrim.py:117`) |
| Streaming token output → typewriter (PRD 10.6) | 🟡 | Full path coded (`orchestrator.py:36-64` → `window.py:266-269`) but dead; streaming appends onto the literal text "Thinking..." (see bug M-1) |
| Conversation history (last 20) (PRD 13) | 🟡 | Repo correct (`repository.py:39-51`) but orchestrator fetches `limit=10` and is dead anyway |
| Long-term memory key-value store (PRD 13) | 🟡 | Repo ✅; extraction is a brittle substring heuristic (`orchestrator.py:229-239`) |
| `users` table (PRD 13) | ❌ | Not in schema (`db.py:36-104`) |
| SQLite persistence (PRD 13) | ✅ | aiosqlite, tables created |
| DB corruption recovery (TRD §12) | ❌ | No backup/regenerate path |
| DB size cap / log purge (arch spec §9) | ❌ | Nothing prunes `conversation` or `application_usage` |
| Reminder engine (PRD 13, TRD) | 🟡 | Polling + trigger works (`scheduler.py:201-213`) but there is **no way to create a reminder** from UI or AI |
| Deepgram STT (TRD §3) | 🟡 | Provider complete (`providers/deepgram.py`); pipeline dead; error text returned as transcript |
| Push-to-talk recording (PRD 16) | 🟡 | Records (log-confirmed) but requires window keyboard focus, which the design forbids the window from taking |
| On-demand vision / screen understanding (TRD 9.3) | 🟡 | Two competing capture paths; Krutrim path silently drops the image; `self.ai_orchestrator` AttributeError (`window.py:372`) |
| Screenshot downscale/JPEG/1024px (TRD 9.3) | ❌ | Full-res PNG, no downscale (`vision.py:13-30`, `window.py:355-361`) |
| Event bus (TRD §5) | 🟡 | Exists; cross-thread delivery broken for bg-thread subscribers (fatal) |
| AI invocation scheduler w/ cooldown+stability (arch spec §5) | 🟡 | Coded (`scheduler.py:108-150`) but never receives events |
| Active application detection (arch spec) | ✅ | `win32_hook.py:74-114` (log-confirmed) |
| User idle/active detection | ✅ | `win32_hook.py:116-138` |
| Screen-time telemetry → DB (arch spec §7) | ❌ | `execute_update` doesn't exist (`telemetry.py:71`) + subscriber never receives events — 0 rows ever written |
| Battery awareness (PRD 10.6) | 🟡 | Implemented twice, both with a signed-byte bug (see H-2) |
| Weather dialogue (PRD Phase 2) | ✅ | Works (log-confirmed) — though PRD scoped it to *Phase 2*, and it leaks IP over HTTP |
| Pomodoro (PRD Phase 2) | ✅ | Works via menu (log-confirmed); completion bubbles depend on cross-thread publish → GUI (works) |
| IDE sync: pytest outcome (PRD Phase 3) | 🟡 | Watches *the pet's own CWD* `.pytest_cache`, not the user's project (`context_engine.py:91-121`) |
| Git context (PRD 12.1) | 🟡 | Same CWD problem — and the project isn't a git repo, so it always reports "unavailable" |
| Plugin system (PRD Phase 7) | ✅ | Dynamic loader works (log-confirmed); plugin callbacks still subject to the event-bus thread defect |
| Settings persistence (TRD §11) | 🟡 | Mascot/model persisted; scale/mute not |
| Notifications engine (arch spec) | 🟡 | Speech bubble doubles as it; no `ui/notifications.py` |
| Graceful shutdown (TRD) | 🟡 | Background loop stopped; timers, audio device, in-flight LLM worker not cleaned |
| TTS voice output (PRD Phase 5) | ❌ | Absent (`PET_VOLUME` dead config) |
| Multiple pets (Phase 6) | ❌ | Out of MVP scope — acceptable |

---

## 14. Architecture Violations

Each: **Severity · Description · File/lines · Root cause · Fix · Impact**

**AV-1 (Critical) — Event bus cannot deliver to background-thread subscribers.**
`src/event_bus.py:57-88` + `src/core/application.py:48-67`. Root cause: `pyqtSignal.connect()` on plain Python callables binds delivery to the thread where `connect()` ran; cross-thread emissions are queued to that thread's Qt event dispatcher, but the worker thread runs an asyncio loop, never a Qt loop, so queued calls are never drained. Fix: make every subscriber a `QObject` living on the GUI thread (or run the worker as a `QThread` with `exec()`), or replace the bus with an explicit thread-safe dispatcher that routes callbacks onto the right executor (GUI via signal, async via `call_soon_threadsafe`). Impact: state machine, AI scheduler, telemetry, and plugins are deaf — the product core is inert (log-confirmed).

**AV-2 (Critical) — Ownerless AI orchestration.** `src/ai/orchestrator.py:66` defined, never constructed; `src/ui/window.py:372` references a nonexistent `self.ai_orchestrator`. Root cause: missing composition root — nothing in `main.py`/`application.py` wires the Intelligence layer. Fix: instantiate `AIOrchestrator` once at startup on the GUI thread and hand `PetWindow` a reference (or route strictly via bus once AV-1 is fixed). Impact: all AI features dead.

**AV-3 (High) — Unsynchronized singletons constructed concurrently from two threads.** All eight `get_instance()` implementations (`event_bus.py:66-70`, `application.py:18-22`, `db.py:16-20`, `sprite_loader.py:20-24`, `scheduler.py:79-83`, `telemetry.py:17-21`, `audio_recorder.py:16-20`, `plugins/manager.py:18-22`). Root cause: `if cls._instance is None` race while `Application.start()` (bg) and `PetWindow.__init__` (GUI) both bootstrap. Fix: construct everything in one composition root on the main thread before starting workers; drop the singleton pattern. Impact: possible duplicate `EventBus` (silently split subscriptions), `SpriteLoader` `QTimer`/`QPixmap` created on a non-GUI thread, nondeterministic startup crashes.

**AV-4 (High) — Qt objects created before `QApplication` and on the wrong thread.** `main.py:18-19` starts the worker (which builds `StateMachine → SpriteLoader → QPixmap/QTimer`) before `QApplication(sys.argv)` at `main.py:22`. Fix: create `QApplication` first; keep all Qt-object construction on the GUI thread. Impact: "Must construct a QGuiApplication before a QPixmap" crash window; `QTimer` started from a non-QThread never fires.

**AV-5 (High) — UI mutation from background thread.** `context_menu.py:172-179` (`_db_clear_records` calls `parent_window.display_speech_bubble` from the asyncio thread); also `orchestrator.py` `_transcribe_and_query → handle_user_query` would run GUI-adjacent logic on the worker. Violates TRD §10 "zero direct access". Fix: publish an event / use a signal. Impact: intermittent crashes or paint corruption.

**AV-6 (Medium) — Duplicate responsibility for vision capture.** Both `PetWindow.on_event` (`window.py:310-313`) and `AIOrchestrator.on_event` (`orchestrator.py:92-101`) handle `VISION_CAPTURE_REQUESTED`, each capturing and dispatching independently → double screenshots + double LLM calls once AV-2 is fixed naively. Fix: one owner (orchestrator requests, window performs hide+grab, replies with `SCREEN_CAPTURED`). Impact: duplicate cost/latency and a hidden future bug.

**AV-7 (Medium) — Module coupling / dependency direction breaks.** UI imports storage and core directly (`context_menu.py:6-8` builds repositories; `window.py:13-14` imports `AudioRecorder`, `Application`); scheduler (core) imports `ai.context_engine`; `ContextMenu` reaches into `AmbientScheduler.get_instance().pomodoro` (`context_menu.py:190-203`). TRD §5 forbids direct cross-module references. Impact: untestable UI, hidden init-order deps.

**AV-8 (Medium) — Event manifest drift and misuse.** `PET_CLICKED`, `SCREEN_CAPTURED`, `LLM_..._SENT` partially unused; `APPLICATION_STARTED` is published as a *scale-change* message (`context_menu.py:138`); arch-spec events `BATTERY_LOW`/`SPEECH_EMITTED`/`STATE_TRANSITION` renamed or absent. Impact: docs and code disagree; consumers can't rely on the catalog.

**AV-9 (Low) — Directory structure drift vs TRD §2 / arch spec §1.** Missing: `core/signals.py`, `ui/overlay.py`, `animation/animator.py`, `animation/transitions.py`, `physics/screen.py`, `ai/memory_manager.py`, `ai/prompts.py`, `ai/llm.py`, `ai/voice.py`, `storage/models.py`, `utils/helpers.py`, `observer/base.py`, `tests/conftest.py`, `docs/`, `README.md`, `assets/themes/`, `assets/icons/`; `event_bus.py` sits at `src/` not `src/core/`. Names differ (`db.py` vs `database.py`). Also no `__init__.py` anywhere (works via namespace packages + the `sys.path` hack at `main.py:5`, but fragile).

**AV-10 (Low) — No `Pillow` usage despite being a required stack element** (TRD §3, `requirements.txt:2`) except the debug-sprite generator; vision post-processing that Pillow was specified for (downscale/JPEG) is unimplemented.

---

## 15. Critical Bugs

**C-1 — AI pipeline completely unwired.** (= AV-2.) `orchestrator.py:66`, `window.py:372`. Severity: Critical. Impact: chat/voice/vision all non-functional; `_execute_capture` raises `AttributeError` (caught at `window.py:373-377`, shown as "Oops! I couldn't look at your screen"). Fix: construct + register orchestrator at startup.

**C-2 — Cross-thread event delivery failure.** (= AV-1.) Severity: Critical. Impact: no state transitions ever occur; pet never walks/falls/sleeps/thinks; dropped pet **floats in mid-air permanently** (physics only applies gravity in `FALL` state, `movement.py:83-98`, and `FALL` is never entered); telemetry and AI scheduler inert. Empirically confirmed by log.

**C-3 — Singleton construction race + Qt-thread affinity violations.** (= AV-3/AV-4.) Severity: Critical (nondeterministic crash / silent event loss). Log evidence of both orderings across sessions (sprite loader init interleaves differently at 03:41:05 vs 03:42:22).

**C-4 — Telemetry persists nothing: call to nonexistent method.** `telemetry.py:71` calls `self.db.execute_update(...)`; `Database` only defines `execute_query`/`execute_non_query` (`db.py:107-119`). The `AttributeError` is swallowed by the broad `except` at `telemetry.py:73`. Severity: Critical for the feature (100% data loss), Low for stability. Root cause: no test executes `_save_usage`. Fix: rename + add a test.

**C-5 — Gemini API key leaked into UI and logs via exception text.** Key is a URL query param (`gemini.py:21`); `httpx` exception messages contain the full URL; `stream()` yields `f"(Thinking connection interrupted: {str(e)})"` (`gemini.py:133`) into the speech bubble, and `generate()` returns it (`gemini.py:77`); errors are also logged to `storage/logs/app.log`. Severity: Critical (secret exposure). Fix: send the key via `x-goog-api-key` header; never surface raw exception text to users; scrub URLs in logs. **Rotate the keys currently in `.env`.**

---

## 16. Medium Bugs

**M-1 — Streaming text concatenates onto "Thinking...".** `LLM_REQUEST_SENT` → `show_text("Thinking...")` sets `full_text="Thinking..."` (`window.py:263-264`, `speech_bubble.py:54-77`); each `LLM_RESPONSE_CHUNK` then does `full_text += chunk` (`speech_bubble.py:79-87`) → bubble displays "Thinking...Here's your joke…" until the final message resets it. Fix: clear the bubble on the first chunk.

**M-2 — Every drag-release fires an AI chat query; click/drag/double-click logic conflated.** `mouseReleaseEvent` (`window.py:148-165`) treats *any* release (including a 30-second drag across monitors) as a "single click" → `CHAT_QUERY_REQUESTED`; a genuine double-click dispatches the single-click query on the first release *and* `PET_DOUBLE_CLICKED` on the second. No movement threshold, no cooldown (PRD "Never Spam" + unused `SPEECH_BUBBLE_COOLDOWN_SEC`). Fix: track press position/time; use Qt's `mouseDoubleClickEvent`; add a cooldown gate.

**M-3 — Battery percent read as signed byte.** `SYSTEM_POWER_STATUS.BatteryLifePercent` declared `ctypes.c_byte` (signed) in **both** `context_engine.py:16` and `win32_hook.py:24`. Windows returns 255 for "unknown" → reads as **-1**, so the `percent != 255` guards (`context_engine.py:58`, `win32_hook.py:148`) never match; desktops report battery `-1%`; `AmbientScheduler` (`scheduler.py:219-222`, `battery_percent <= 20`) would spam `BATTERY_WARNING` every 5 minutes on desktop PCs (currently masked only by C-2 for the scheduler path — but the observer path at `win32_hook.py:148` publishes straight to the GUI). Fix: `c_ubyte`. Also: the prompt template happily tells the LLM "Battery level: -1%".

**M-4 — Missing animations render the pet invisible.** `metadata.json` has no `sleep`, `listen`, or `dragged` entries; `sprite_loader.get_animation_frames` returns `[]` (`sprite_loader.py:109-113`), renderer draws nothing (`renderer.py:57-76`). TRD §12 requires idle fallback. Fix: fallback in `set_animation` + add frames.

**M-5 — Deepgram error string becomes the user's prompt.** `transcribe` returns `f"(STT error: {...})"` (`deepgram.py:59`); `_transcribe_and_query` checks only truthiness (`orchestrator.py:120-124`) → the error is sent to the LLM as user speech. Fix: return `None` on failure and branch.

**M-6 — LLM worker thread lifecycle.** `self.worker = LLMStreamWorker(...)` (`orchestrator.py:198`) overwrites any running worker → previous `QThread` may be garbage-collected while running ("QThread: Destroyed while thread is still running" crash); concurrent queries interleave chunks into one bubble; no cancellation or timeout at the worker level. Also creates a fresh asyncio loop + HTTP client per query. Fix: single persistent worker with a queue; reject/cancel overlapping queries.

**M-7 — Active-animation purge / stale renderer frames.** `_last_accessed` is only updated inside `get_animation_frames` (`sprite_loader.py:96`), which the renderer calls once per state change — so the 60s purge (`sprite_loader.py:152-166`) evicts the animation currently on screen (log-confirmed at 03:43:32). Renderer keeps its private `self.frames` list, so after `set_scale`/`set_mascot` clears the cache the renderer still draws old-scale frames until the next state change. Fix: touch access time from the render path or exempt the active state; re-pull frames after cache clears.

**M-8 — Unclosed socket to 8.8.8.8 every second + global timeout mutation.** `win32_hook.py:156-168`: `socket.socket(...).connect(...)` never closed → 1 leaked socket/second (Windows will recycle, but it churns handles and generates constant network traffic incl. on metered connections); `socket.setdefaulttimeout(1.0)` mutates process-global state affecting every other library. The computed `is_connected` is *only logged*, never published or used. Fix: delete the check or use `with closing(...)`, run it far less often, and publish an event someone consumes.

**M-9 — Git/pytest "IDE integration" watches the wrong directory.** `context_engine.py:64-121` runs `git status` and reads `.pytest_cache` relative to the **pet's own CWD**, not the user's active project. In this repo (not a git repo) git is always "unavailable", and the pytest results it reports are the pet's own test suite. The 5s poll (`scheduler.py:237-256`) plus two `subprocess.run` per prompt also block the asyncio loop (0.5s timeout each, and on Windows each spawn can flash/spawn conhost work). Fix: derive the project path from the foreground window/process, run in an executor, and use `creationflags=CREATE_NO_WINDOW`.

**M-10 — Vision: full-res PNG on the GUI thread; Krutrim drops the image silently.** `window.py:346-372` grabs and PNG-encodes the entire screen synchronously on the GUI thread (tens of ms → guaranteed frame drops; on 4K, worse); `vision.py:26` passes `compression_quality=80` to PNG (quality param is JPEG semantics; for PNG it maps oddly). TRD 9.3 requires downscale to ≤1024px + JPEG + Base64. With `LLM_PROVIDER=krutrim` (the default), `KrutrimProvider._build_payload` ignores `screenshot_bytes` entirely (`krutrim.py:26-51`) — the ambient vision feature can never work on the default provider and fails *silently*. Fix: encode off-thread, downscale, and route vision queries to a vision-capable provider or refuse loudly.

**M-11 — PTT contradicts the no-focus design.** `keyPressEvent` (`window.py:167-186`) only fires when the pet window has keyboard focus. PRD 8.6/9 demand the window never take focus — if it doesn't, PTT can't work; when it does (after a click), the pet swallows Space/keystrokes meant for the editor. Fix: global hotkey via Win32 `RegisterHotKey` or a click-and-hold mic button.

**M-12 — Reminders cannot be created.** `ReminderRepository.add_reminder` (`repository.py:93-95`) has zero callers outside tests. There is no UI, no AI tool-call, nothing. The 30s poll loop is servicing an always-empty table. Fix: add creation path (menu dialog or LLM function-calling).

**M-13 — `Config.validate()` forbids the documented provider.** `config.py:41-43` coerces any provider that isn't `"krutrim"` back to krutrim (with a `print`), while the PRD mandates Gemini and `get_active_provider` supports it (`orchestrator.py:129-133`). Setting `LLM_PROVIDER=gemini` in `.env` is silently ignored on every DB-override load.

**M-14 — SQLite connection-per-query + shared file with tests.** `db.py:25-34` opens a new `aiosqlite` connection (and spawns its internal thread) for **every** query; no WAL mode; no busy timeout. Tests mutate the same singleton's `db_path` and were executed while the app was live (log 03:45:04) — a recipe for `database is locked`. Fix: one persistent connection on the worker loop, `PRAGMA journal_mode=WAL`, proper test fixtures.

**M-15 — Weather startup behavior + plain-HTTP geolocation.** First scheduler tick fetches weather (`scheduler.py:228-231`) → pet announces the weather unprompted at every launch (violates PRD "entertaining without becoming distracting"; weather was Phase-2 scope anyway) and sends the host IP to `ip-api.com` over **http://** (`scheduler.py:158`). Fix: HTTPS, opt-in, cache city.

---

## 17. Minor Bugs

* **m-1** `QRect.bottom()/right()` are `top+height-1`/`left+width-1` in Qt → floor and right-wall computations are off by one pixel (`collision.py:45-47`).
* **m-2** Gravity constant confusion: comment says "scaled by 50", code multiplies by 60 (`gravity.py:12-13`); result: +9.8 px/frame² → terminal velocity (15) reached in 2 frames — falls are constant-speed, not natural acceleration (PRD 8.2).
* **m-3** Physics assumes exactly 60 Hz; `QTimer` default is CoarseTimer (±5%) and `int(1000/60)=16ms` (62.5 Хz nominal); no measured `dt` → speed varies with load (TRD "fixed 60 Hz" is met in spirit; frame-independence is not).
* **m-4** `resolve_boundaries` executed twice per tick (`movement.py:74`, then again in each state branch).
* **m-5** Double-click random action can pick `FALL` while standing on the floor (`window.py:281-284`) — with C-2 fixed this would put a grounded pet into fall state for one tick; PRD says Row-3/Row-4 wave *or jump* (launch), and `LAUNCH`/`CROUCH` are otherwise unreachable.
* **m-6** `_trigger_interaction_loop` prompt list contains `" teases me playfully about my uncommitted files."` — leading space, wrong person, will read oddly as a user turn (`window.py:236-242`).
* **m-7** `speech_bubble.position_bubble` contains dead line `app = QWidget.find(int(self.winId()))` (`speech_bubble.py:97`) — also forces native window realization.
* **m-8** `append_chunk` doesn't cancel `dismiss_timer` → a slow stream can start fading mid-response (`speech_bubble.py:79-87`).
* **m-9** `show_text` recalculates dimensions from the *full* final text immediately — bubble snaps to final size before the typewriter starts (cosmetic).
* **m-10** LLM error bubble always says "API unconfigured?" regardless of actual error (`window.py:276-279`).
* **m-11** `Config.load_db_overrides` / `validate` use `print()` not the logger (`config.py:42,74,76`).
* **m-12** `KrutrimProvider.health()` pings `https://api.krutrim.com/...` while chat uses `https://cloud.olakrutrim.com/...` (`krutrim.py:18` vs `117`); `health()` is also never called by anything.
* **m-13** `orchestrator` history `limit=10` vs PRD's "last 20 messages" (`orchestrator.py:171`); roles stored as `user`/`assistant` while arch spec says `user`/`pet` (TRD agrees with code — doc conflict).
* **m-14** Memory-extraction heuristic misfires: `"i prefer "` check splits on `"prefer "` so "I'd prefer…" or sentences containing "prefer" capture garbage; `"i code in "` triggers the *prefer* split path, storing the wrong substring (`orchestrator.py:236-239`).
* **m-15** `PomodoroTimer.tick()` is called from a loop that sleeps ≥1s *plus* work time → the 25-minute timer runs slow by the accumulated overhead of reminder/battery/IDE checks (`scheduler.py:194-258`).
* **m-16** `AudioRecorder.cleanup()` (`audio_recorder.py:116-128`) is never called; PyAudio never terminated; `closeEvent` (`window.py:384-386`) stops no timers, doesn't unhook.
* **m-17** `speech_record.wav` written to CWD and never deleted (`audio_recorder.py:28`) — see privacy; also a fixed filename → concurrent instances clobber it.
* **m-18** No single-instance guard — log shows two instances alive simultaneously at 03:41:05/03:41:19 sharing one DB + log.
* **m-19** `Application.shutdown` doesn't cancel the `AmbientScheduler.run()` infinite task or in-flight coroutines before `loop.stop()`; `loop.close()` never called; 3s join then abandons the thread (daemon).
* **m-20** `test_core.py:73` uses the `qapp` fixture with no `conftest.py` — works only because `pytest-qt` ships the fixture; arch spec's promised `tests/conftest.py` is missing; test DBs mutate the production singleton's path (test pollution — `storage/test_memory.db` left behind, visible in `storage/`).
* **m-21** Debug sheet generator writes `sprite_sheet.png` (`generate_debug_sprites.py:137`) but metadata points to `spritesheet.png` — both files sit in the assets dir; the debug sheet also uses 128×128 vs the real 138×191, so regenerating it breaks the metadata contract.
* **m-22** `logger.py` adds a `FileHandler` per logger name to the same file, relative to CWD (breaks if launched from another directory), with no rotation — unbounded growth over the PRD's 8-hour sessions.
* **m-23** `EventBus.subscribe(slot)` gives every subscriber *every* event (no per-type filtering) → every event wakes every handler chain (cost + fragility).
* **m-24** `enterEvent` forces IDLE (which also can't resume since `leaveEvent` is `pass`) and reads the cursor via `self.cursor().pos()` instead of the event position.

---

## 18. Performance Issues

1. **Unconditional 60 Hz repaint.** `_on_physics_tick` calls `self.update()` every tick (`window.py:225`) even when the pet is static and the idle animation advances at 10 fps. Repaint + composite of a 138×191 translucent window at 60 Hz alone likely blows the <1% idle CPU budget. Fix: repaint only on frame advance or position change.
2. **Per-paint mirrored pixmap allocation.** Facing left, `get_current_frame` runs `frame.transformed(...)` on every paint (`renderer.py:63-68`) — a fresh QPixmap ~60×/s. Cache mirrored frames.
3. **Per-second socket churn** (M-8) + 1 Hz observer polling with Win32 calls (fine) + 1 Hz scheduler loop — cumulative idle wakeups.
4. **Screen grab + PNG encode on GUI thread** (M-10): 100–300 ms stall per capture at 1080p+, guaranteed dropped frames (PRD "Zero Dropped Frames").
5. **SQLite connection-per-query** (M-14): each `execute_*` spins up an aiosqlite worker thread and re-opens the file.
6. **Blocking `subprocess.run` (git ×2) inside the async worker** per prompt/5s poll (M-9): stalls scheduler + any pending DB work.
7. **`sheet_pixmap` retained forever** (`sprite_loader.py:79`): the decoded 1380×1146 sheet (~6 MB RGBA) is never released — contradicts TRD §1 "no full sprite sheets continuously held in memory" (though at 6 MB this is pragmatically fine; the doc budget itself is the problem).
8. **LLM worker builds a new event loop + `httpx.AsyncClient` per request** (`orchestrator.py:48-64`): connection setup/TLS per query instead of a pooled client.
9. **`_calculate_dimensions` constructs `QFont`/`QFontMetrics` on every chunk** (`speech_bubble.py:112-132`) during streaming.
10. **Verdict vs budgets:** RAM <300 MB: ✅ likely (~120–180 MB with PyQt6). Idle CPU <1%: ❌ unlikely as written. Active <2%: ❌ during capture/stream. 60 FPS: ✅ nominally, ❌ during vision capture. Startup <3s: ✅ (log shows sub-second to first frame).

---

## 19. Technical Debt

* No composition root; 8 ad-hoc singletons with hidden ordering (the app's biggest structural debt).
* Stringly-typed event system, `if/elif` dispatch towers duplicated in 5 subscribers.
* Two config systems (`Config` env vars vs `constants.py`) with overlapping, partially dead keys.
* Duplicated ctypes structures (`SYSTEM_POWER_STATUS` in two files).
* Doc set internally inconsistent (three different LLM vendors, two FPS targets, three RAM budgets, two DB schemas) — the "source of truth" needs a truth of its own.
* No `README.md`, no `docs/`, no `.gitignore`, **not a git repository** (audit could not inspect history; PRD-personality features even depend on git).
* No `__init__.py` files; imports depend on a `sys.path` hack in `main.py:5`.
* `analytics` and `preferences` tables created, never used (`db.py:69-83`).
* Test artifacts (`storage/test_memory.db`) and runtime artifacts (`speech_record.wav`) polluting the tree.

---

## 20. Recommended Refactors (priority order)

1. **Fix the runtime skeleton first:** create `QApplication` before anything else; build a `CompositionRoot` on the GUI thread that constructs EventBus → DB → SpriteLoader → StateMachine → Orchestrator → Window → Observer → starts the asyncio worker last. Delete `get_instance()` everywhere; pass dependencies explicitly.
2. **Rebuild the EventBus** as a `QObject` created on the GUI thread with `subscribe(event_type, callback, *, executor)` — GUI callbacks via queued signal, async callbacks via `loop.call_soon_threadsafe`. Add per-type subscription.
3. **Wire the AI:** instantiate the orchestrator; single vision owner; single persistent LLM worker with cancellation; response validator (truncate at `MAX_CHARACTERS`, strip newlines/markdown).
4. **Thread hygiene:** all Qt objects GUI-thread only; all DB/network on the worker; UI updates only via events; run `git`/`pytest-cache` probes in `run_in_executor` with `CREATE_NO_WINDOW`.
5. **Input handling:** proper click/drag/double-click discrimination + speech cooldown.
6. **Persistence:** one pooled aiosqlite connection, WAL, prune jobs (conversation >100, usage >30 days), corruption recovery per TRD §12.
7. **Fix the four one-line killers:** `execute_update`→`execute_non_query`; `c_byte`→`c_ubyte` (×2); Gemini key→header; Deepgram error→`None`.

## 21. Suggested Project Structure Improvements

* Add `src/__init__.py` et al., `pyproject.toml` (packaging + pytest config + `asyncio_mode`), `README.md`, `.gitignore` (must cover `.env`, `storage/`, `*.wav`, `__pycache__`), and `git init`.
* Add `src/core/composition.py` (root), `src/ai/prompts.py` (extract the template from `orchestrator.py:18-34`), `src/ai/validators.py` (length/content caps), `tests/conftest.py` (tmp-path DB fixture, qapp).
* Move `event_bus.py` under `core/` to match both docs; fold `utils/generate_debug_sprites.py` into a `tools/` folder outside `src`.
* Resolve the doc conflicts into a single `docs/` source of truth and delete stale sections.

## 22. Suggested AI Improvements

* Retry with exponential backoff + jitter (currently zero retries anywhere); circuit-break after N failures; use the (currently never-called) `health()` probes.
* Client-side rate limiting & dedup (one in-flight query; drop or queue extras).
* Response validation: hard truncate to 150 chars *at the stream layer* so the bubble never overgrows; strip markdown/emoji per style; reject empty/refusal outputs to the fallback line.
* Prompt: don't inject `battery: -1%` / `git: unknown` noise — omit unavailable fields; move the few-shot personality rules to a maintained `prompts.py`; token budget the history (10 messages of unbounded length ≠ bounded context).
* Replace the substring memory heuristic with an explicit LLM extraction pass (or at least regex with word boundaries), and inject memories as structured bullets, not a raw `dict` repr (`orchestrator.py:192`).
* Vision: downscale to ≤1024 px, JPEG q≈70 via Pillow (it's already a dependency), and gate on `provider.supports_vision()` instead of silently dropping.

## 23. Suggested Sprite Improvements

* Honor per-frame `duration_ms` (the metadata already carries it) instead of a single fps per animation.
* Fallback chain: `requested → idle → colored placeholder`, per TRD §12.
* Cache mirrored + scaled variants keyed by `(anim, scale, direction)` with a real size-bounded LRU; touch access time on render; never purge the active state.
* Define `sleep`, `listen`, `dragged` (and a `wake` transition) in `metadata.json`; add a schema validation step at load with actionable errors.
* Release `sheet_pixmap` after slicing all animations once (or slice lazily from a memory-mapped image) if the doc's memory posture is to be honored.

## 24. Suggested Physics Improvements

* Measure real `dt` (`QElapsedTimer`) and integrate with it; clamp `dt` to avoid teleporting after stalls; use `Qt.PreciseTimer`.
* Retune gravity (e.g., ~2000 px/s² with terminal ~1200 px/s) so acceleration is visible over ~0.5 s falls.
* Single boundary resolution per tick; add coyote-margin so `y == floor±1` doesn't oscillate between IDLE/FALL recommendations.
* Land-impact squash should key off impact velocity (crouch frames exist and are unused).
* Multi-monitor: handle screens with different `availableGeometry` tops when walking across boundaries (currently the pet snaps to the new screen's floor via clamp — animate it).

## 25. Suggested UX Improvements

* Cooldowns + a "Quiet / Normal / Chatty" slider (PRD 19.2) before any ambient speech ships.
* First-run experience: greet once, don't announce weather at every startup.
* Click = talk, drag = move — never both; visible hover affordance; resume wandering after hover ends.
* A real settings dialog (typing speed, mute, scale persistence, reduced motion, PTT hotkey choice) — all PRD-promised, all missing.
* Global PTT hotkey so voice works without focusing (and without stealing Space from the IDE).
* Fallback personality lines when offline (pre-cached, per TRD §12) instead of raw error strings.

## 26. Future Features Missing From Documentation (implemented but undocumented)

The reverse-compliance check — code that exists with **no documentation mandate** (docs are the source of truth; these need PRD/TRD entries or removal):

* **Pomodoro timer** (menu + scheduler) — PRD lists Pomodoro as *Phase 2 roadmap*, yet it's implemented; no spec for durations/UX.
* **Weather via ip-api.com + Open-Meteo** — Phase 2 roadmap item, implemented with an *undocumented third-party IP-geolocation dependency* (privacy-relevant; must be documented and consented).
* **Network connectivity probe to 8.8.8.8** — appears in no document.
* **AI model picker (Llama 3, Mistral 7B via Krutrim) in the context menu** — undocumented.
* **pytest-cache watching & git-status polling** ("IDE sync") — PRD scopes IDE integration to Phase 3 via local port listeners; the shipped approach (CWD scraping) is undocumented and different.
* **Gemini provider** — PRD mandates it, TRD/arch spec mandate Krutrim; the dual-provider architecture itself is undocumented.
* **`application_usage` telemetry table** — only in arch spec, absent from TRD schema; the docs must reconcile (see §14 AV-8/AV-9 and §19).

## 27. Final Verdict

**Red — do not ship; do not build features on this foundation yet.**

The project reads like a well-planned system assembled without ever being *observed*: every subsystem was written, few were ever seen working together, and the one runtime artifact in the repo (the log) proves the core loop has never functioned — no state transition has ever occurred in any recorded session, and no AI call has ever been made from the running app.

The good news: the fatal problems are concentrated in ~5 places (composition root, event bus threading, orchestrator wiring, singleton races, and a handful of one-line bugs), not smeared across the codebase. The provider clients, repositories, sprite pipeline, speech bubble, and physics math are all reusable with modest fixes. A focused 1–2 week stabilization pass following §20's order — with an integration test that boots the app headless and asserts a full click→LLM→bubble→idle cycle — would bring this from "static sticker" to "MVP candidate." Security actions (rotate all three API keys, move the Gemini key out of URLs, stop logging window titles at INFO) should happen **today**, independent of the refactor.

---

### Appendix A — Documentation self-contradictions (resolve before re-audit)

| Topic | PRD | TRD | Arch spec | Code |
|---|---|---|---|---|
| LLM | Gemini 2.5 Flash | Krutrim Qwen 3.6 35B | krutrim-2-instruct | Both providers; default Krutrim `Qwen2.5-14B` |
| FPS | 60 stable | 60 target | **capped 30** | 60 |
| RAM | <300 MB (target 180) | <300 MB | **<120 MB** | unmeasured |
| Conversation table | `conversation` | `conversation` | `conversation_logs` | `conversation` |
| Memory store | `memory` k/v | `memory` k/v | `long_term_memories` (facts+importance) | `memory` k/v |
| `users` table | required | absent | absent | absent |
| max_tokens | n/a (150 chars) | n/a | **60** | 150 |
| AI cooldown | "strict cooldowns" | n/a | 10 s | 20 s (dead code) |
| Voice | Phase 5 roadmap | in scope (Deepgram) | in scope (Spacebar PTT) | half-implemented |

### Appendix B — Test coverage gaps (Phase 12 detail)

Existing tests (3 files, ~15 tests) cover: config, event bus same-thread pub/sub, one gravity step, repositories, Gemini payload shape, weather mapping, pomodoro state, plugin loading, recorder constants, context keys. **Zero coverage** of: state machine transitions (would have caught C-2 with a cross-thread test), orchestrator wiring (would have caught C-1), telemetry save (would have caught C-4), collision/boundaries, movement state kinematics, speech bubble streaming (M-1), sprite cache purge semantics (M-7), window mouse logic (M-2), battery struct (M-3), Deepgram failure path (M-5), Krutrim provider (no test at all), shutdown. No HTTP mocking; tests hit the real singleton DB path and leave artifacts; no headless integration boot test.
