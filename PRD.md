# Product Requirements Document (PRD)

# Desktop Pet AI (Unabridged Developer Edition)

**Version:** 1.0 (MVP Context Base)  
**Status:** Approved for Development  
**Author:** Product & Architecture Team  
**Last Updated:** July 2026  

---

## 1. Executive Summary

Desktop Pet AI is a lightweight, AI-powered virtual desktop companion that lives directly on the user's desktop as an animated 2D character. Unlike traditional desktop assistants, the pet behaves like a living creature rather than a chatbot. It walks, idles, reacts to the user, obeys simple physics, remembers conversations, and interacts through natural dialogue powered by Google's Gemini 2.5 Flash model (using an AI-agnostic architecture).

The application is intentionally designed to be lightweight, visually unobtrusive, and responsive while maintaining a delightful personality.

The long-term vision is to evolve Desktop Pet AI into a contextual desktop companion capable of understanding user activity, assisting with productivity, and providing emotional engagement without becoming intrusive.

---

## 2. Vision Statement

Create the most delightful AI desktop companion that feels alive through animation, personality, memory, and contextual awareness while remaining lightweight enough to run continuously in the background.

The pet should feel like:

* A tiny companion,
* Not another application,
* Never blocking the user's work,
* Always available when needed,
* And entertaining without becoming distracting.

---

## 3. Problem Statement

Modern desktop assistants generally fall into one of two categories:

* **Static desktop mascots** with repetitive, hard-coded scripted behaviors and no real intelligence.
* **Powerful AI chatbots** that require users to actively open a browser, sidebar, or heavy application.

There is little in between. Users increasingly spend most of their day working on their computers, yet no desktop companion successfully combines natural 2D animation, responsive physics, and contextual conversational AI in a lightweight package. Desktop Pet AI fills this gap.

---

## 4. Product Goals

### Primary Goals

* **Believable Virtual Companion:** Create a companion that feels organic and alive.
* **Low Resource Footprint:** Maintain extremely low CPU and RAM usage to prevent performance impact on high-intensity tasks (compiling, rendering, gaming).
* **60 FPS Performance:** Deliver smooth animations at 60 FPS under a custom rendering pipeline.
* **Natural Conversational AI:** Integrate an AI context and dialogue pipeline that streams responses smoothly.
* **Unobtrusive Interactive Experience:** Keep user interactions quick and delightful without interrupting active workflows.
* **Zero Disruption:** Never steal keyboard focus or block important operating system UI.

### Secondary Goals

* **Modular Codebase:** Build a highly decoupled, event-driven architecture for future expansion.
* **Cross-Platform Readiness:** Design with future macOS and Linux compatibility in mind (using PyQt6 as the abstract GUI layer).
* **Extensible Plugins & Vision:** Lay the architectural foundation for future third-party plugins and on-demand screen understanding.

---

## 5. Success Metrics

### 5.1 Performance Budgets

* **Memory Usage (RAM):**
  * Target idle: `< 180 MB`
  * Maximum allowed limit: `< 300 MB`
* **CPU Usage:**
  * Idle: `< 1%`
  * Active (walking, processing physics, rendering): `< 2%`
  * *AI network requests must never affect UI thread rendering or cause frames to drop.*
* **Frame Rate:** Stable 60 FPS rendering target.
* **Application Startup:** Under `3.0 seconds` from execution to window transparency initialization.
* **AI Latency:** Typographic output streaming must begin in under `2.0 seconds` from user prompt submittal (network permitting).

### 5.2 User Experience Metrics

* **Perceived Aliveness:** The pet moves spontaneously and behaves dynamically rather than looping animations predictably.
* **Workflow Harmony:** The pet never intercepts active mouse focus or forces its way over fullscreen apps.
* **Physical Consistency:** Dropping and throwing the pet follows natural, intuitive momentum and landing behaviors.

---

## 6. Target Audience

* **Developers:** Spends long hours in IDEs; values technical humor, micro-breaks, and non-intrusive companions.
* **Designers & Digital Creators:** Highly sensitive to aesthetic fluidity, workspace layout, and animation quality.
* **Students & Remote Workers:** Needs motivation, hydration reminders, emotional engagement, and desktop customization.
* **AI Enthusiasts:** Desires ambient ways to interact with LLMs outside traditional chat interfaces.

---

## 7. User Personas

### Persona A – Developer (The Code-Focused User)

* **Profile:** Works in VS Code/terminal environments all day.
* **Needs:**
  * Subtle entertainment during long compile times.
  * Programming jokes and quick motivation.
  * Task reminders.
  * An extremely lightweight background process that does not compete with heavy Docker containers or local builds.

### Persona B – Student (The Study Companion User)

* **Profile:** Uses a laptop to write papers, study, and attend online classes.
* **Needs:**
  * Encouragement during long reading sessions.
  * Structured study reminders (e.g., hydration, posture checks).
  * Fun, lightweight interactive loops to relieve stress.
  * A warm, emotionally encouraging companion personality.

### Persona C – Designer (The Layout-Sensitive User)

* **Profile:** Works inside creative suites (Figma, Adobe Creative Cloud).
* **Needs:**
  * A visually polished, transparent desktop companion.
  * Animations that flow smoothly without visual tearing or ugly bounding borders.
  * Simple controls to easily move the pet out of the way when working on critical UI.

---

## 8. Core User Stories

### 8.1 Movement & Presence

* **User Story:** *As a user, I want the pet to walk naturally across my desktop and rest on my taskbar so that it feels like a real creature inhabiting my workspace.*
* **Acceptance Criteria:** The pet's horizontal movement loop recognizes active monitor boundaries and screen taskbar heights, treating the top of the taskbar as its walking surface.

### 8.2 Gravity & Momentum

* **User Story:** *As a user, I want the pet to obey natural falling physics when dropped so that its physical reactions feel grounded and realistic.*
* **Acceptance Criteria:** Dropping the pet triggers a falling animation that accelerates under gravity and transitions into a squatted landing sequence upon collision with the taskbar, before returning to idle.

### 8.3 Interaction & AI Dialogue

* **User Story:** *As a user, I want to click on the pet to trigger quick, witty, and contextual dialogue so that interacting with it feels rewarding and responsive.*
* **Acceptance Criteria:** Left-clicking the pet triggers a non-blocking dialogue sequence. The text displays inside an automatically resizing, typewriter-animated speech bubble without freezing the pet's idle animation or locking the desktop thread.

### 8.4 Dragging & Re-positioning

* **User Story:** *As a user, I want to be able to drag the pet anywhere on my screen and throw it with momentum without breaking its animation state.*
* **Acceptance Criteria:** Dragging disables gravity, tracking the mouse coordinates. Releasing the mouse calculates velocity; if thrown, the pet flies in an arc before falling back to the floor.

### 8.5 Personality & Memory

* **User Story:** *As a user, I want the pet to remember our past conversations, my name, and my programming preferences so that it feels like our relationship grows over time.*
* **Acceptance Criteria:** The pet persistently saves user details to a local database and references this database to inject personalized context into subsequent AI prompts.

### 8.6 Non-Intrusiveness

* **User Story:** *As a user, I want the pet to sit quietly and avoid stealing my keyboard focus so that it never disrupts my active work.*
* **Acceptance Criteria:** The pet window utilizes specific operating system flags (`Qt.WindowType.Tool`) to prevent grabbing keyboard focus when clicked, allowing users to type continuously in their primary applications.

---

## 9. Product Principles

### The "Always" Guidelines

* **Always Lightweight:** Maintain a minimal runtime footprint so the application is never blamed for system lag.
* **Always Responsive:** All physical movements, dragging, and rendering must feel instantaneous.
* **Always Decoupled:** Keep the UI, animation, physics, and AI execution loops strictly separate via an asynchronous event bus.

### The "Never" Guidelines

* **Never Steal Focus:** The pet window must reject active focus so users can type in their editor uninterrupted.
* **Never Overlap Important UI:** The pet must be easily draggable and respect screen workspace boundaries.
* **Never Spam:** Conversational speech bubbles must have strict cooldowns and never generate infinite loops of text.
* **Never Auto-Monitor:** Avoid continuous background audio recording or passive screen capturing. All vision/voice tasks must be explicitly initiated by the user.

---

## 10. Functional Requirements

### 10.1 Transparent Desktop Rendering

The application shall:

* Render as a completely transparent window with no visible borders, headers, or frame decorations.
* Utilize PyQt6 flags `Qt.WindowType.FramelessWindowHint`, `Qt.WindowType.WindowStaysOnTopHint`, and `Qt.WindowType.Tool` to ensure it hovers over other applications without stealing keyboard focus or appearing in the OS Alt-Tab switcher.
* Support High-DPI displays dynamically.
* Correctly detect multi-monitor layouts, treating the boundaries of individual active monitor workspaces as solid vertical walls.

### 10.2 Animation System & Sprite Sheet Mapping

Animations must be driven by a standard **6-row by 10-column sprite sheet (60 frames total)**. Frame slicing, scaling, and caching are managed dynamically to optimize memory.

```
Row 1 (Frames 00-09):  Idle State ──► Blinking and subtle breathing loops.
Row 2 (Frames 10-19):  Walk State ──► Fast-walk sequence (faced right; programmatically mirrored for left).
Row 3 (Frames 20-29):  Wave State ──► Ambient greeting or AI completion celebration.
Row 4 (Frames 30-39):  Physical   ──► Crouch (30-31), launch (32), fly/fall (33-35), landing (36-39).
Row 5 (Frames 40-49):  AI State   ──► Hand-to-chin thinking/listening loop.
Row 6 (Frames 50-59):  Talk State ──► Active speaking mouth and facial changes.
```

### 10.3 Physics Engine

The custom physics engine runs on a fixed **60 Hz update loop** inside the main thread:

* **Gravity:** Active when the pet's bottom edge is above the floor coordinate ($y_{floor} = ScreenHeight - TaskbarHeight - PetHeight$).
* **Friction & Drag:** Linear horizontal drag dampens movement velocity to a stop when walking transitions to idle.
* **Terminal Velocity:** Implements a terminal downward velocity limit to keep falling visually natural.
* **Dragging and Throwing:** While dragging, gravity is suspended. Releasing the mouse calculates momentum:
  $$\vec{v} = \frac{\vec{p}_{release} - \vec{p}_{previous}}{\Delta t}$$
  Applying this velocity vector initiates an arc movement before gravity pulls the pet down.

### 10.4 User Interaction Loops

* **Left Click:** Triggers conversational dialogue, interrupts long sleeps, or plays random interactive reactions.
* **Double Click:** Triggers a randomized special wave or physical jump animation (Row 3 or Row 4).
* **Hover:** Walking animations pause temporarily, and the pet turns its head toward the user's mouse coordinates.
* **Drag:** Lifts the pet, suspends gravity, tracks mouse position, and switches to the flailing frame (Row 4, Frame 34).
* **Right Click (Context Menu):** Displays a styled context menu containing:
  * *Settings* (Adjust scale, change volume, toggle Voice/PTT)
  * *Change Character* (Select sprite themes)
  * *Mute / Unmute*
  * *Clear Chat Memory*
  * *Quit Application*

### 10.5 Speech Bubble Subsystem

The speech bubble is painted dynamically next to the pet's active coordinates:

* **Natural Typing:** Text renders frame-by-frame (typewriter effect) to feel active.
* **Auto-Sizing:** The bubble boundary adjusts dynamically up to a maximum width, avoiding screen clutter.
* **Auto-Fade:** If the user does not click to dismiss, the bubble automatically fades out after a reading duration proportional to the word count.
* **Length Restriction:** AI outputs are strictly capped at **100–150 characters** to prevent covering important desktop files or workspaces.

### 10.6 Conversational AI (Gemini 2.5 Flash Engine)

The AI engine runs asynchronously, processing queries via a decoupled pipeline:

* **Non-Blocking Execution:** Under no circumstances shall an AI request block the 60 Hz physics or rendering loop.
* **Context Gathering:** Before dispatch, the pet compiles active runtime variables:
  * Current time and session duration.
  * Active application name (if permissions allow).
  * Device battery life.
  * Pet's active physical state.
* **Streaming Output:** The LLM's response streams tokens asynchronously and emits a PyQt signal to update the UI typewriter effect in real-time.

### 10.7 Ambient Random Behaviors

To prevent repetitive, robotic loops, the behavior engine runs a cooldown checker. Every few minutes, a randomized chance wheel triggers:

* **Stretch / Yawn:** Transitions to a lazy animation.
* **Take a Nap:** Transitions from `Idle` -> `Sit` -> `Sleep` (Row 4).
* **Look Around / Wave:** Triggers an ambient check or waving frame (Row 3).
* **Scratch Head:** Plays a short thinking/curious animation loop (Row 5).

---

## 11. State Machine & Behavioral Transitions

The state machine coordinates state shifts to ensure the pet behaves predictably and consistently.

```
                              Idle
                             /  |  \
                            /   |   \
                        Walk   Sit   Sleep
                         │
                      Dragged
                         │
                      Falling
                         │
                      Landing
                         │
                        Idle
```

### AI Pipeline States

```
                      Listening
                          │
                      Thinking
                          │
                       Talking
                          │
                        Idle
```

* **Transition Protection:** The pet cannot transition directly from `Sleep` to `Walk` without first running the `Wake` (standing up) animation.
* **Physical Interruption:** Clicking or dragging the pet at any point during an AI talking or sleeping state instantly cancels the current behavior, closes the active speech bubble, and enters the `Dragged` state.

---

## 12. Personality & Dialogue Design

### 12.1 Personality Parameters

* **Playful & Curious:** Comments on the user's active screen elements, files, or working hours.
* **Intelligent but Slightly Sarcastic:** Delivers witty, developer-centric humor (e.g., commenting on uncommitted git files or missing semi-colons).
* **Encouraging & Emotionally Positive:** Helps reduce user fatigue during long coding or design sessions.

### 12.2 Explicit Conversational Boundaries

* **Avoid Toxicity:** Absolutely no offensive humor, political topics, or aggressive commentary.
* **No Long Messages:** If the LLM generates output exceeding 150 characters, the local validator must truncate or reject the response to preserve the speech bubble scale.

---

## 13. Memory Subsystem

The application utilizes a local, lightweight SQLite database to maintain persistent context.

### Database Tables Schema

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                              users                                     │
 │  • id (INTEGER PRIMARY KEY)                                            │
 │  • name (TEXT)                                                         │
 │  • preferred_language (TEXT)                                           │
 └────────────────────────────────────────────────────────────────────────┘
 ┌────────────────────────────────────────────────────────────────────────┐
 │                              memory                                    │
 │  • key (TEXT PRIMARY KEY)                                              │
 │  • val (TEXT)                                                          │
 │  • last_updated (DATETIME DEFAULT CURRENT_TIMESTAMP)                   │
 └────────────────────────────────────────────────────────────────────────┘
 ┌────────────────────────────────────────────────────────────────────────┐
 │                            conversation                                │
 │  • id (INTEGER PRIMARY KEY AUTOINCREMENT)                              │
 │  • timestamp (DATETIME DEFAULT CURRENT_TIMESTAMP)                      │
 │  • role (TEXT)                                                         │
 │  • message (TEXT)                                                      │
 └────────────────────────────────────────────────────────────────────────┘
 ┌────────────────────────────────────────────────────────────────────────┐
 │                              reminders                                 │
 │  • id (INTEGER PRIMARY KEY AUTOINCREMENT)                              │
 │  • trigger_time (DATETIME NOT NULL)                                    │
 │  • task_description (TEXT NOT NULL)                                    │
 │  • is_completed (INTEGER DEFAULT 0)                                    │
 └────────────────────────────────────────────────────────────────────────┘
```

* **Short-Term Context:** The `conversation` table retains only the last 20 messages for prompt construction to prevent context window bloat.
* **Long-Term Memory:** The `memory` table acts as a key-value store containing user preferences, favorite coding frameworks, ongoing project names, and custom-defined pet behaviors.

---

## 14. Performance & Non-Functional Requirements

* **Zero Dropped Frames:** The 60Hz GUI timer must never experience frame drops. Calculations for file system changes, SQLite updates, and API networking must run on separate `QThread` instances.
* **Memory Constraints:** Sliced `QPixmap` frames are cached in an LRU (Least Recently Used) cache. If the pet enters a state like `Walk`, walk frames are loaded; if the pet returns to `Idle` for > 60 seconds, walk assets are flushed from memory to keep RAM usage strictly below the `300 MB` maximum limit.
* **Thread Safety:** Background threads are strictly prohibited from manipulating UI widgets directly. All background events must communicate with the GUI thread via PyQt6 safe signals (`pyqtSignal`).

---

## 15. Accessibility

* **Dynamic Scaling:** The right-click context menu lets users scale the pet size (e.g., 0.5x, 1.0x, 1.5x, 2.0x) using smooth anti-aliased scaling (`QPainter.RenderHint.SmoothPixmapTransform`).
* **Speech Control:** Users can customize speech bubbles, adjust the text typing speed, or disable the typewriter effect entirely.
* **Reduced Motion:** Includes a setting to disable automatic wandering and falling animations, confining the pet to a stationary idle state on the taskbar.

---

## 16. Privacy & Security

* **Microphone Policy:** The microphone is never passively active. Recording is strictly user-initiated via an explicit Push-to-Talk hotkey or interface button.
* **Screen Capture Policy:** Screenshots are captured on-demand only when a user explicitly submits a visual analysis prompt.
* **Data Sovereignty:** All database storage, conversations, and settings reside locally on the host machine. No user metrics or files are automatically uploaded to external cloud servers, except for user-initiated prompt payloads sent to the designated Gemini API endpoint.

---

## 17. MVP Scope vs. Multi-Phase Roadmap

### MVP Scope (Phase 1)

* Transparent, borderless window on top of active workspaces.
* Full 6-row sprite loading, slicing, scaling, and caching.
* Fixed-rate 60Hz gravity, momentum, dragging, and taskbar collision detection.
* Automated typewriter speech bubbles.
* Asynchronous Gemini 2.5 Flash dialogue integration.
* Persistent local SQLite memory system.
* Custom, styled right-click context menu.

### Future Roadmap

* **Phase 2 (Ambient Context):** Battery warnings, weather dialogue integration, desktop calendar reminders, and local Pomodoro task tracking.
* **Phase 3 (Active IDE Integration):** Local port listeners to sync with VS Code, reacting directly to compile success, unit test failures, or git commits.
* **Phase 4 (On-Demand Gemini Vision):** Screen capture OCR and visual analysis on user command to explain visual bugs.
* **Phase 5 (Speech & Voice Loops):** Built-in local Push-to-Talk with Deepgram transcription and Text-to-Speech vocal output.
* **Phase 6 (Multiple Pets):** Support for running multiple pets on-screen with pet-to-pet physical collision and shared database memory.
* **Phase 7 (Plugin Ecosystem):** Structured directory structure to load custom behavior plugins and custom community-crafted sprite themes.

---

## 18. Non-Goals

The MVP will not include:

* Continuous, passive background screen recording.
* Autonomous system file editing or operating system shell control.
* Wake-word voice activation (no continuous microphone monitoring).
* Autonomous desktop web browsing.
* GPU processing dependencies (must run smoothly on standard integrated graphics).

---

## 19. Risks & Mitigations

### 19.1 Technical Risks

* **Risk:** Operating system differences in handling window transparency and click-through properties (especially on Linux/macOS composition managers).
  * *Mitigation:* Focus development primarily on Windows desktop composition APIs using native PyQt6 handles, and abstract window properties cleanly to allow platform-specific adjustments later.
* **Risk:** High network latency when calling the Gemini API, freezing speech bubble displays.
  * *Mitigation:* Ensure the speech bubble displays a "Thinking..." typing loop immediately upon sending the request, with a strict 10-second request timeout fallback.

### 19.2 Product Risks

* **Risk:** The pet becomes distracting, causing user fatigue.
  * *Mitigation:* Implement customizable behavior frequency sliders (e.g., "Quiet", "Normal", "Chatty") in the settings window to give users full control over interaction levels.

---

## 20. Acceptance Criteria

The MVP is complete when:

1. [ ] The application launches as a borderless, transparent window with no system decorations.
2. [ ] The sprite animation renders cleanly at 60 FPS without visual tearing or black bounding frames.
3. [ ] The pet walks, idles, falls, and lands predictably on top of the system taskbar.
4. [ ] Dragging the pet suspends gravity, and releasing it calculates throwing velocity.
5. [ ] Left-clicking the pet triggers an asynchronous Gemini 2.5 Flash prompt stream, displaying output in an auto-resizing speech bubble.
6. [ ] The application runs continuously for 8 hours without leaking memory (RAM remains below 300 MB) or spiking CPU usage above 2%.
7. [ ] All conversation context and user profiles are stored locally in an SQLite database.
