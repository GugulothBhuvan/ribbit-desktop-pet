# Training a custom wake word ("Hey Pet") — openWakeWord

The pet ships with built-in phrases (`hey_jarvis`, `alexa`, …). To use **your
own** phrase you train a small model once, drop the file in `assets/wake/`, and
point `WAKE_WORD_MODEL` at it. Training is free, runs on-device is not
required (it runs in a free Google Colab notebook), and takes ~30–60 min of
mostly hands-off compute. No account or API key.

## 1. Open the training notebook

openWakeWord's official Colab notebook (Google account only, free GPU):

<https://github.com/dscripka/openWakeWord> → **"Training your own models"** →
the *automatic training* Colab (`automatic_model_training.ipynb`).

Direct: <https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb>

> If that link has moved, the repo's README always links the current notebook
> under "Training New Models".

## 2. Fill in your phrase

In the notebook's config cell set:

- `target_word` / `model_name`: your phrase, e.g. **`hey_pet`**
  (use the same token you'll put in `WAKE_WORD_MODEL`).
- Leave the synthetic-data, augmentation, and training settings at their
  defaults for a first pass.

Then **Runtime → Run all**. The notebook:

1. synthesizes thousands of spoken samples of "hey pet" with a TTS engine,
2. mixes in background noise / negative speech so it doesn't false-trigger,
3. trains the model, and
4. produces **`hey_pet.onnx`** (and usually a `.tflite`).

Download the **`.onnx`** file at the end.

## 3. Install it in the pet

```text
desk-pet/
└── assets/
    └── wake/
        └── hey_pet.onnx      <-- put it here
```

Then in `.env`:

```ini
WAKE_WORD_ENABLED=1
WAKE_WORD_MODEL=assets/wake/hey_pet.onnx
# optional tuning:
WAKE_WORD_THRESHOLD=0.5      # raise toward 0.7 if it false-triggers, lower to 0.3 if it misses you
WAKE_WORD_RECORD_SEC=5       # how long it records after the phrase
```

Make sure the voice deps are installed:

```bash
pip install -e .[voice]
```

Restart the pet. You should see:

```text
[WakeWord]: Wake word active: say the 'hey_pet' phrase to talk.
```

Say **"Hey Pet"** → it records ~5s → transcribes (Deepgram) → the pet answers.
`Ctrl+Space` still works as a manual trigger.

## Notes

- The internal detection key is the file's **basename without extension**
  (`hey_pet.onnx` → `hey_pet`). Name the file after your phrase and everything
  lines up automatically.
- Multi-word, distinctive phrases ("hey pixel pet") train and detect far better
  than short/common ones ("pet", "hey"). If detection is flaky, retrain with a
  longer phrase or more synthetic samples (a notebook setting).
- Everything after training is 100% local: the model runs on your machine and
  audio only leaves for transcription **after** the phrase fires.
