# Technical Requirements Document (TRD): AI-Powered Desktop Pet Companion

**Version:** 3.0  
**Status:** Architecture Freeze  
**Target Platform:** Windows (Primary), macOS & Linux (Future Compatibility)  
**Language:** Python 3.11+  
**GUI Framework:** PyQt6  

---

## 1. Project Purpose & System Objectives

The goal is to develop a lightweight, AI-powered Desktop Pet that lives as a transparent, borderless window on the user's desktop. The pet acts as an ambient interactive companion rather than a transactional chatbot. It combines interactive sprite animations, physics simulations, persistent memory, screen understanding, and local speech-to-text (STT).

### Performance Budgets

* **Idle CPU Usage:** < 1.0%
* **Active CPU Usage:** < 2.0% (during physics calculations or rendering)
* **Memory Footprint:** Target < 180 MB, absolute maximum < 300 MB
* **Cold Startup Time:** < 3.0 seconds
* **Rendering Performance:** Target a stable, non-blocking 60 FPS

### Engineering Guardrails

* **Strict Decoupling:** Every core subsystem communicates purely via an asynchronous event bus. Zero circular imports.
* **Non-Blocking GUI Loop:** The GUI thread must handle only UI rendering, mouse/keyboard inputs, and lightweight physics updates. All file operations, network requests, audio processing, database transactions, and LLM requests must run on separate background worker threads.
* **Resource Optimization:** No full sprite sheets are to be continuously held in memory. Animation frames are lazy-loaded, scaled, cached dynamically, and managed via clean asset pools.

---

## 2. Directory Structure

The project conforms to the following standardized file and folder structure:

```text
desktop-pet/
├── assets/
│   ├── sprites/
│   │   └── default/
│   │       ├── idle/
│   │       ├── walk/
│   │       ├── think/
│   │       ├── talk/
│   │       ├── listen/
│   │       ├── sleep/
│   │       ├── jump/
│   │       ├── wave/
│   │       ├── sit/
│   │       ├── fall/
│   │       ├── landing/
│   │       └── metadata.json
│   ├── themes/
│   └── icons/
├── docs/
│   └── TRD.md
├── src/
│   ├── main.py
│   ├── config.py
│   ├── constants.py
│   ├── event_bus.py
│   ├── core/
│   │   ├── application.py
│   │   ├── signals.py
│   │   └── scheduler.py
│   ├── ui/
│   │   ├── window.py
│   │   ├── renderer.py
│   │   ├── speech_bubble.py
│   │   ├── context_menu.py
│   │   └── overlay.py
│   ├── animation/
│   │   ├── animator.py
│   │   ├── sprite_loader.py
│   │   ├── state_machine.py
│   │   └── transitions.py
│   ├── physics/
│   │   ├── gravity.py
│   │   ├── collision.py
│   │   ├── movement.py
│   │   └── screen.py
│   ├── ai/
│   │   ├── orchestrator.py
│   │   ├── context_engine.py
│   │   ├── memory_manager.py
│   │   ├── prompts.py
│   │   ├── llm.py
│   │   ├── vision.py
│   │   ├── voice.py
│   │   └── providers/
│   │       ├── base.py
│   │       ├── krutrim.py
│   │       └── deepgram.py
│   ├── storage/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repository.py
│   └── utils/
│       ├── logger.py
│       └── helpers.py
├── tests/
├── .env
├── requirements.txt
└── README.md
```

---

## 3. Technology Stack & Core Packages

* **Runtime:** Python 3.11+
* **GUI Engine:** PyQt6 (utilizes `QWidget`, `QPainter`, and native window handle flags)
* **Image Processing:** Pillow (PIL) for image loading and optimization before conversion to `QPixmap`
* **Networking Client:** `httpx` (asynchronous, non-blocking HTTP requests for API integration)
* **Speech-to-Text:** Deepgram API (Push-to-Talk execution only)
* **Large Language Model:** Krutrim API (Default Model: Qwen 3.6 35B A3B)
* **Local Database:** SQLite (built-in standard library, accessed asynchronously)
* **Configuration:** `python-dotenv` for local environment parameters (`.env`)

---

## 4. Architectural Layers

```
 ┌────────────────────────────────────────────────────────────┐
 │                        Presentation Layer                  │
 │                                                            │
 │  Transparent Window │ Sprite Renderer │ Speech Bubble UI   │
 └────────────────────────────────────────────────────────────┘
                              ▲
                              │ (Qt Signals / Painter)
                              ▼
 ┌────────────────────────────────────────────────────────────┐
 │                    Behavior & Physics Layer                │
 │                                                            │
 │ State Machine │ Animation │ Physics │ Event Bus Controller │
 └────────────────────────────────────────────────────────────┘
                              ▲
                              │ (Decoupled Events)
                              ▼
 ┌────────────────────────────────────────────────────────────┐
 │                      Intelligence Layer                    │
 │                                                            │
 │ Orchestrator │ Context │ Memory │ Voice │ Vision │ LLM     │
 └────────────────────────────────────────────────────────────┘
                              ▲
                              │ (Asynchronous Workers)
                              ▼
 ┌────────────────────────────────────────────────────────────┐
 │                   External Services / DB                   │
 │                                                            │
 │ Deepgram │ Krutrim │ Local SQLite DB │ OS Window System   │
 └────────────────────────────────────────────────────────────┘
```

---

## 5. Event Bus Subsystem

All components must operate under a decoupled publish-subscribe model. No component is allowed to make direct import calls or reference objects outside its direct responsibility. Communication is routed through a centralized `EventBus` using customized PySignaling or standard signal relays.

### 5.1 Event Manifest (`src/event_bus.py`)

```python
class EventType:
    # Interaction Events
    PET_CLICKED = "PET_CLICKED"
    PET_DOUBLE_CLICKED = "PET_DOUBLE_CLICKED"
    PET_DRAGGED = "PET_DRAGGED"
    PET_DROPPED = "PET_DROPPED"
    
    # State and Animation Events
    SPRITE_CHANGED = "SPRITE_CHANGED"
    ANIMATION_FINISHED = "ANIMATION_FINISHED"
    STATE_TRANSITION_TRIGGERED = "STATE_TRANSITION_TRIGGERED"
    
    # Input Processing Events
    VOICE_START_RECORDING = "VOICE_START_RECORDING"
    VOICE_STOP_RECORDING = "VOICE_STOP_RECORDING"
    VOICE_RECEIVED = "VOICE_RECEIVED"
    SCREEN_CAPTURED = "SCREEN_CAPTURED"
    
    # AI Lifecycle Events
    LLM_REQUEST_SENT = "LLM_REQUEST_SENT"
    LLM_RESPONSE_RECEIVED = "LLM_RESPONSE_RECEIVED"
    LLM_ERROR_OCCURRED = "LLM_ERROR_OCCURRED"
    
    # System Actions
    REMINDER_TRIGGERED = "REMINDER_TRIGGERED"
    APPLICATION_STARTED = "APPLICATION_STARTED"
    APPLICATION_SHUTTING_DOWN = "APPLICATION_SHUTTING_DOWN"
```

---

## 6. GUI, Window Management & Rendering

The presentation window must float seamlessly on top of active desktop workspaces without visible system decoration.

### 6.1 Window Flag Configuration (`src/ui/window.py`)

The pet's target container utilizes specific PyQt6 window parameters to achieve translucency and standard behavior on the desktop workspace:

```python
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt

class PetWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        # Strip frame borders, keep window always on top, set tool window behavior 
        # to omit taskbar representations depending on user configurations.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        
        # Configure backing translucency
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        
        # Disable manual layout resizing 
        self.setFixedSize(128, 128) # Default bounding box limits
```

### 6.2 Rendering Pipeline (`src/ui/renderer.py`)

* Drawing must occur strictly on the main GUI thread during the widget's `paintEvent`.
* Use `QPainter` to render the active animation frame.
* Frame scale operations must use high-quality rendering hints (`QPainter.RenderHint.SmoothPixmapTransform`) to avoid pixelation during layout scaling.

---

## 7. Physics Subsystem

The custom physics engine operates on a fixed 60 Hz timer loop, calculating vectors and resolving collisions.

### 7.1 Kinematics

* **Gravity:** Active when the pet is falling. Modified gravity vector is calculated as:
  $$v_y(t + \Delta t) = v_y(t) + g \cdot \Delta t$$
* **Friction & Drag:** Standard linear deceleration is applied when walking or sliding on surfaces:
  $$v_x(t + \Delta t) = v_x(t) \cdot (1 - C_{drag})$$

### 7.2 Dragging Mechanics

* When the user clicks and drags the pet, the physical simulation loop is suspended.
* Velocity is calculated dynamically during the drag operation to allow throwing the pet:
  $$\vec{v}_{throw} = \frac{\vec{p}_{release} - \vec{p}_{prev}}{\Delta t}$$
* On release, the state transitions to `Fall` if the pet is suspended above the lower collision floor boundaries.

### 7.3 Multi-Monitor & Collision Resolution (`src/physics/collision.py`)

* Collisions must be validated against physical desktop geometry derived from PyQt6's `QGuiApplication.screens()`.
* **Taskbar Detection:** Read screen work areas (excluding taskbar layouts) via `screen.availableGeometry()`.
* **Clamping boundaries:**
  * Left and Right edges: Absorb velocity and reverse direction (bounce) or halt.
  * Bottom surface: Triggers transition from `Fall` -> `Landing` -> `Idle`.

---

## 8. Sprite Sheet & Animation Management

To keep memory limits below the 300 MB maximum, the sprite loader handles assets efficiently instead of keeping multiple uncompressed layouts in volatile memory.

### 8.1 Sheet Loading and Metadata Parser (`src/animation/sprite_loader.py`)

Animations must read structured metadata to slice composite sheets or directory assets.

#### Configuration Schema (`metadata.json`)

```json
{
  "animations": {
    "idle": {
      "fps": 10,
      "loop": true,
      "frames": [
        {"x": 0, "y": 0, "w": 128, "h": 128, "duration_ms": 100},
        {"x": 128, "y": 0, "w": 128, "h": 128, "duration_ms": 100}
      ]
    },
    "walk": {
      "fps": 12,
      "loop": true,
      "frames": [
        {"x": 0, "y": 128, "w": 128, "h": 128, "duration_ms": 83}
      ]
    }
  }
}
```

### 8.2 Animation Cache Strategy

* Load standard frames lazily as needed.
* Re-scaled frames are stored in an LRU (Least Recently Used) cache to avoid redundant scaling transformations.
* Safely discard frame pools for states that have been inactive for more than 60 seconds (e.g., transitioning from `Sleep` to standard `Idle`).

### 8.3 State Machine Definition (`src/animation/state_machine.py`)

The state engine routes transitions deterministically:

```
          ┌──────────────────────────────────────────────────────────┐
          ▼                                                          │
   ┌─────────────┐             ┌──────────────┐             ┌────────┴─────┐
   │    Idle     ├────────────►│     Walk     ├────────────►│     Sit      │
   └──────┬──────┘             └──────┬───────┘             └────────┬─────┘
          │                           │                              │
          │ (Click / Drag)            │ (Gravity Active)             │
          ▼                           ▼                              ▼
   ┌─────────────┐             ┌──────────────┐             ┌──────────────┐
   │   Dragged   ├────────────►│     Fall     ├────────────►│   Landing    │
   └─────────────┘             └──────────────┘             └──────────────┘
          ▲                                                          ▲
          │ (Interaction Ends)                                       │
          └──────────────────────────────────────────────────────────┘
```

#### AI Sequence Pipeline

* **Listening:** Triggered via Push-to-Talk activation -> State: `Listen`
* **Thinking:** Initiated on query dispatch to local server -> State: `Think`
* **Talking:** Displaying response within speech bubble -> State: `Talk`
* **Resolution:** Return to standard state evaluation -> State: `Idle`

---

## 9. AI Orchestrator & Integrations

The AI layer is structured to route intelligence tasks away from the client layout thread using decoupled interface blocks.

```
 User Prompt ──► AIOrchestrator ──► ContextEngine ──► MemoryManager ──► Provider Dispatch
                                                                              │
                                                                              ▼
                                                                        Krutrim LLM
```

### 9.1 Base Interface Classes (`src/ai/providers/base.py`)

```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, context: Dict[str, Any]) -> str:
        """Sends blocking generation request to designated endpoint."""
        pass

    @abstractmethod
    async def stream(self, prompt: str, context: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Streams tokens sequentially to the calling handler."""
        pass

    @abstractmethod
    def supports_vision(self) -> bool:
        """Returns True if the provider is capable of processing multi-modal image buffers."""
        pass

    @abstractmethod
    async def health(self) -> bool:
        """Determines online status of target server endpoint."""
        pass

class VoiceProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_filepath: str) -> str:
        """Accepts target audio path and returns raw transcription text."""
        pass

    @abstractmethod
    async def health(self) -> bool:
        """Returns online status of translation services."""
        pass
```

### 9.2 Context Engine (`src/ai/context_engine.py`)

Constructs the context block injected into base LLM prompt systems:

* **System Metrics:** Local time, active layout foreground application name, battery charge level.
* **Pet Properties:** Current state parameters, physical mood meters, active scheduler reminders.
* **History Segment:** Context window history fetched via storage.

### 9.3 Vision Subsystem (`src/ai/vision.py`)

Screen capture runs purely on-demand, triggered only when explicitly requested by user prompt analysis (e.g. "What am I working on right now?").

1. **Screen Capture:** Capture active display using PyQt6 `QScreen.grabWindow()`.
2. **Post-Processing:** Convert to PIL Image, downscale to target boundaries (e.g., maximum 1024x1024 width), compress to low-weight JPEG, and encode to Base64.
3. **Execution:** Send Base64 payload payload asynchronously to the Krutrim Multimodal API.

### 9.4 Voice System (Push-to-Talk)

* Continuous, wake-word background listening is disabled.
* Sound recording runs exclusively while a specific hotkey or button is held down.
* Captured wave sequences are compressed locally and sent to Deepgram's STT endpoint via a dedicated background worker thread.

---

## 10. Threading & Concurrency Architecture

To guarantee a stutter-free 60 FPS presentation, code execution must follow this strict threading architecture:

```
┌────────────────────────────────────────────────────────────────────────┐
│                              GUI Thread                                │
│  • PyQt6 App Loop                                                      │
│  • Physics Updates (60Hz QTimer)                                       │
│  • Active Sprite Rendering (paintEvent)                                │
│  • Keyboard / Mouse event capture                                      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                    Signals / Slots│ (Non-blocking PySignals)
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          Background QThreads                           │
│  • Network Thread: (Krutrim HTTP streaming, Deepgram audio uploads)     │
│  • Disk Thread: (SQLite Reads/Writes, image compression, file I/O)     │
│  • Audio Thread: (Microphone recording buffers)                        │
└────────────────────────────────────────────────────────────────────────┘
```

* **Zero Direct Access:** Background threads must never modify GUI widget properties or call UI methods directly.
* **Signal Passing:** Data returned from background tasks must be passed to the GUI thread via PyQt6 safe signals (`pyqtSignal`).

---

## 11. Storage & Persistence Schema

The database relies on a local SQLite instance, managed through repository layout managers.

```
 ┌───────────────┐        ┌──────────────────┐        ┌───────────────┐
 │   settings    │        │   conversation   │        │    memory     │
 ├───────────────┤        ├──────────────────┤        ├───────────────┤
 │ key (PK)      │        │ id (PK)          │        │ key (PK)      │
 │ value         │        │ timestamp        │        │ val           │
 └───────────────┘        │ role             │        │ last_updated  │
                          │ message          │        └───────────────┘
                          └──────────────────┘
```

### SQLite Schema Definition (`src/storage/models.py`)

```sql
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS conversation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    role TEXT NOT NULL, -- 'user' or 'assistant'
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    key TEXT PRIMARY KEY,
    val TEXT NOT NULL,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    val TEXT
);

CREATE TABLE IF NOT EXISTS analytics (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    payload TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_time DATETIME NOT NULL,
    task_description TEXT NOT NULL,
    is_completed INTEGER DEFAULT 0
);
```

---

## 12. Error Recovery & Resiliency

The application must remain stable and operational even if external APIs or local subsystems fail.

* **API Failure Grace Period:** If Krutrim or Deepgram requests time out or fail, the pet must not lock or freeze. The system interceptor logs the issue, and triggers an event to display a pre-cached fallback error response inside the speech bubble (e.g., "I'm having trouble thinking right now."). The physical state machine then transitions back to `Idle`.
* **Missing Assets Grace Period:** If a target animation frame or metadata file is corrupted or missing, the loading system must log the error, skip the missing assets, and gracefully fall back to the default `idle` sprite set.
* **Local DB Recovery:** If the SQLite file becomes corrupt, the storage initializer must backup the damaged file, generate a fresh database, run migrations, and write clean fallback records to preserve operation.

---

## 13. Implementation Phases

```
 Phase 1: Core Framework  ──►  Phase 2: Physics & Input  ──►  Phase 3: Decoupled UI
 (PyQt6 Window, Spites)        (State transitions, Drag)      (Speech, Context Menu)
                                                                       │
                                                                       ▼
 Phase 6: Screen & Audio  ◄──  Phase 5: Voice / STT      ◄──  Phase 4: AI & DB
 (Krutrim Vision)              (Deepgram integration)         (Krutrim API, SQLite)
```

### Phase 1: Core Desktop Engine (Estimated: Weeks 1-2)

* Base transparent PyQt6 borderless container architecture.
* Sprite loader, dynamic scaling pipeline, and asset caching engine.
* Event Bus base structures and core application signal loop.

### Phase 2: Physics, Interaction & State Machine (Estimated: Weeks 3-4)

* 60 Hz kinematics updates (gravity, sliding mechanics).
* Boundary collision mapping and multi-monitor available geometry integrations.
* Click, hover, drag, and throw handling.
* State Machine transitions (`Idle` -> `Walk` -> `Dragged` -> `Fall` -> `Landing` -> `Idle`).

### Phase 3: Interface Accessories & Speech Bubble (Estimated: Week 5)

* Custom speech bubble painting (layered rendering path).
* Context menu logic and clean user settings windows.
* Integration of the local Scheduler utility module.

### Phase 4: Storage & AI Integration (Estimated: Weeks 6-7)

* Database tables implementation and asynchronous helper structures.
* Base LLM provider initialization with async Krutrim support.
* Memory management layer implementation.
* Context assembler.

### Phase 5: Voice Capability (Estimated: Week 8)

* Push-to-Talk recording state handlers.
* Asynchronous audio collection, file compression, and Deepgram upload pipelines.
* Safe callback state routes mapping to the animation state machine.

### Phase 6: Screen Understanding & Vision (Estimated: Week 9)

* Selective screenshot capture pipelines.
* Downscaling, optimization, and conversion to base64.
* Integration of the Krutrim multimodal API.

### Phase 7: Personality & Ambient Life (Estimated: Week 10)

* Passive behavior triggers, periodic ambient actions (e.g., occasional stretching, yawning, or waving).
* Integration of scheduled reminder popups.
* Refinement of visual animations.

### Phase 8: Extensibility, Themes & Refinements (Estimated: Week 11+)

* Custom visual skin selectors.
* Core codebase cleanup and verification against performance targets.
