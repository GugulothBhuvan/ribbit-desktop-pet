# Architecture Decisions & Documentation Reconciliation

**Purpose:** `PRD.md`, `TRD.md`, and `architecture_specification.md` contradicted
each other in several places (AUDIT_REPORT.md, Appendix A). This file records
which value is authoritative and why, so the three documents stop being three
sources of "truth". Where a doc disagrees with this table, this table wins.

Last updated: 2026-07-12 (post Phase 0–9 stabilization).

| Topic | PRD | TRD | Arch spec | **Decision (implemented)** | Why |
|---|---|---|---|---|---|
| LLM provider/model | Gemini 2.5 Flash | Krutrim Qwen 3.6 35B | krutrim-2-instruct | **Krutrim `gemma-4-E4B-it` default; Gemini supported via `LLM_PROVIDER=gemini`** | Qwen 3.6 is a reasoning model on Krutrim: it spends the whole speech-bubble token budget on hidden thinking and returns empty replies. gemma-4-E4B-it streams a full reply in <1s and accepts images (vision). `krutrim-2-instruct` doesn't exist on the account. |
| Frame rate | 60 FPS stable | 60 FPS target | capped 30 FPS | **60 Hz physics loop; repaints only on visible change** | Measured idle CPU 0.23% avg at 60 Hz with repaint discipline — no need for the 30 FPS cap. |
| RAM budget | <300 MB (target 180) | <300 MB | <120 MB | **<300 MB budget; measured ~85 MB** | The 120 MB figure was aspirational; actual usage is comfortably under it anyway. |
| Conversation table | `conversation` | `conversation` | `conversation_logs` | **`conversation`** | TRD schema was implemented first; renaming buys nothing. |
| Memory store | `memory` k/v | `memory` k/v | `long_term_memories` (facts + importance) | **`memory` k/v** | Importance-scored episodic memory is future work; the k/v store covers MVP recall. |
| `users` table | required | absent | absent | **Not implemented** | The `memory` k/v store holds `user_name`/preferences; a dedicated table is redundant at MVP scope. |
| `max_tokens` | n/a (150 chars) | n/a | 60 | **150 tokens API-side + hard 150-char clamp at the stream layer** | The character budget (PRD §12.2) is what actually protects the bubble; it's enforced in `orchestrator.clamp_stream_text`. |
| Ambient AI cooldown | "strict cooldowns" | n/a | 10 s | **20 s default, configurable via `AMBIENT_AI_COOLDOWN_SEC`** | Ambient vision queries cost money; 10 s allowed unreasonably frequent invocations. |
| Voice / PTT | Phase 5 roadmap, PTT hotkey | Deepgram PTT | Spacebar PTT | **Global `Ctrl+Space` toggle (RegisterHotKey, configurable via `PTT_HOTKEY`)** | A focused-window Space handler contradicts PRD 8.6 (never take focus) and swallows the user's spacebar. Bare Space cannot be a global hotkey. Ctrl+Space shadows IDE autocomplete globally — documented, and rebindable. |
| Wake word | **Non-goal** (§18: no wake-word / continuous mic) | n/a | n/a | **Opt-in local wake word (openWakeWord), OFF by default** | The non-goal exists to protect "mic off until you act". A *local* engine keeps that promise for the cloud (audio only leaves after the phrase); the always-on-mic tradeoff is the user's explicit opt-in via `WAKE_WORD_ENABLED=1`. Reverses the §18 non-goal only under that opt-in. |
| Weather / geolocation | not in MVP scope | n/a | n/a | **Implemented (ipapi.co HTTPS + Open-Meteo); announced ≤1× per session, never at startup** | Was built ahead of roadmap; kept, but constrained by the "Never Spam" principle and moved off plain HTTP. |
| IDE sync (git/pytest) | Phase 3 roadmap (port listeners) | n/a | git telemetry | **Opt-in via `WATCH_PROJECT_DIR`; disabled when unset** | The original implementation scanned the pet's own CWD — meaningless data. Port-listener integration remains future work. |
| Battery warnings | Phase 2 roadmap | n/a | BATTERY_LOW event | **Observer-owned, discharging only, ≤1 per 30 min** | Two subsystems previously raced to warn, one of them every second. |
| Sprite sheet geometry | 128×128, 6×10 | 128×128 examples | 10×6 sheet | **138×191, 10 cols × 6 rows (60 frames), defined by `metadata.json`** | The real art is 138×191; metadata is authoritative, loaders are geometry-agnostic. |
| Missing animation frames | n/a | fall back to idle | n/a | **Loader falls back to idle frames for any undefined animation** | A sprite pack can never render the pet invisible (TRD §12). |
| DB size control | n/a | n/a | purge >100 conversations | **`Database.prune()` hourly: conversation ≤100 rows, usage ≤30 days** | Matches arch spec §9. |

## Event catalog deltas vs the docs

Implemented additions: `LLM_RESPONSE_CHUNK` (streaming), `SPEECH_REQUESTED`
(thread-safe bubble requests), `PTT_TOGGLED` (global hotkey), `SCREEN_CAPTURED`
carries a raw `QImage` (processing happens on the worker loop).
Arch-spec names not implemented: `BATTERY_LOW` (→ `BATTERY_WARNING`),
`SPEECH_EMITTED` (→ `LLM_RESPONSE_RECEIVED`), `STATE_TRANSITION`
(→ `STATE_TRANSITION_TRIGGERED`/`SPRITE_CHANGED`).

## Threading model (as built)

- **GUI thread:** Qt objects, window/renderer/state machine/orchestrator
  (QObject), physics timers, event-bus construction.
- **Worker asyncio loop:** DB, scheduler, LLM streaming, screenshot
  encoding, transcription. Subscribes to the bus with `executor="async"`.
- **Native threads:** Win32 observer (1 Hz polling), global hotkey message
  loop, PyAudio recording.
- The event bus routes deliveries per subscriber (`gui` via queued Qt signal,
  `async` via `call_soon_threadsafe`) — components never touch each other's
  threads directly.
