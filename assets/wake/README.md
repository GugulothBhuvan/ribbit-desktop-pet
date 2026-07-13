# Custom wake-word models

Drop a custom-trained openWakeWord model here (e.g. `hey_pet.onnx`), then set
in `.env`:

```
WAKE_WORD_ENABLED=1
WAKE_WORD_MODEL=assets/wake/hey_pet.onnx
```

The pet listens for the phrase the model was trained on. See the training
walkthrough in `docs/WAKE_WORD_TRAINING.md`.

Score key = the file's basename without extension (`hey_pet.onnx` -> `hey_pet`),
which is what the listener matches against internally.
