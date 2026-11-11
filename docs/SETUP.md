# Setup on a new Mac

This is a development export, not a verified installer. Do not overwrite an existing Jarvis installation. The setup script stops if `~/.openjarvis/runtime` already exists. Python 3.12 is the recommended baseline; also install uv and Ollama yourself from their official sites.

1. Clone the repository and run `python3 scripts/setup.py`. It copies source into a new private runtime, not your secrets into the repository.
2. Create a Python 3.12 venv and install the recovered backend plus local optional packages:

```sh
uv venv --python 3.12 "$HOME/.openjarvis/runtime/OpenJarvis/.venv"
uv pip install --python "$HOME/.openjarvis/runtime/OpenJarvis/.venv/bin/python" \
  -e "$HOME/.openjarvis/runtime/OpenJarvis[server,voice,tools-search]" \
  piper-tts==1.8.0 PyJWT==2.15.1 cryptography slack-sdk \
  python-multipart python-docx reportlab Pillow playwright kokoro==0.9.4
"$HOME/.openjarvis/runtime/OpenJarvis/.venv/bin/python" -m playwright install chromium
```

`requirements-snapshot.txt` records the original installed package versions. It is reference material, not a portable lockfile. In particular, no private wheel is bundled. The native Rust memory extension requires the original matching upstream Rust workspace and a separate build; it is not recreated by these commands.

3. Run `python3 scripts/enter_openrouter_key.py`. Paste YOUR key into that hidden terminal prompt, never into chat or a tracked file. The custom engine accepts free model IDs and zero-price provider constraints only. Review your OpenRouter account limits and billing settings independently.
4. For Piper, download `en_US-ryan-medium.onnx` and its `.onnx.json` configuration from the pinned Piper voices revision recorded in `docs/THIRD-PARTY.md`. Put them under `~/.openjarvis/models/piper/`. Review the voice license before use. This export does not include weights.
5. For screen summaries, start Ollama and explicitly run `ollama pull qwen3-vl:2b`. It is a local model; model downloads need disk space and internet. No paid vision fallback is configured.
6. Run `python3 scripts/start.py`, then open `http://127.0.0.1:18766` in Chrome. Enable microphone permission when you want voice. Screen capture requires a click and a selected window or screen. A screenshot upload is available when capture is unsupported.

The default Whisper model may download on first use; all later recognition runs locally if the model is cached. MLX Whisper is optional and should be installed/configured separately on Apple Silicon. The original GPU integration had fallback issues, so the example uses CPU Whisper.

## What is not automatically configured

Slack, notification pairing, recurring schedules, Google Calendar, Home Assistant, ChatGPT subscription sign-in, REA, native app installation, and memory native extensions are not preconfigured. The source is included where recoverable. Do not infer that an included adapter or an HTTP 200 means its whole workflow has been verified.

## Feature URLs

- Main chat: `/`
- Routines, handoff and teaching: `/personal/routines`
- Speech readiness: `/v1/speech/health`
- Voice readiness: `/v1/speech/tts/health`
- Content-free timing diagnostics: `/v1/personal/responsiveness`
- Optional REA prerequisites: `/teardown/diag`

Start only one server on port 18766. Never kill an unknown process simply because it occupies that port.
