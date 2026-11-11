# Third-party components

- OpenJarvis: https://github.com/open-jarvis/OpenJarvis — Apache-2.0. Recovered Python source is vendored. The original commit was not available in the installed distribution; local modifications are not presented as upstream code.
- Piper: https://github.com/OHF-Voice/piper1-gpl — separately installed dependency, not vendored. Review its license before redistribution.
- US Ryan medium voice: https://huggingface.co/rhasspy/piper-voices/tree/b4e358ffcb232591bf73a540e70f7de528e4174a/en/en_US/ryan/medium — the model card identifies the dataset as CC BY-NC-SA 4.0. Weights are not included. They are optional for personal evaluation; check use restrictions yourself.
- faster-whisper / MLX Whisper / Kokoro: separately installed speech dependencies. Weights are not included.
- Ollama and Qwen3-VL: separately installed local vision components. No model binary is included.
- 3d-force-graph and Three.js: the knowledge viewer uses CDN imports. Their upstream licenses apply.
- MediaPipe and upstream frontend dependencies: the recovered built UI includes distribution assets from the original customized UI. Retain shipped notices. Original frontend package metadata could not be recovered; review bundled assets before commercial redistribution.
- The included `third-party/ultron-MIT-LICENSE.txt` documents the original gesture/orb reference attribution, where present.
- REA is optional external tooling. This project does not vendor REA or claim its authorship.

The root Apache-2.0 license applies to this export's original code and OpenJarvis-derived code to the extent permitted by upstream licensing; it does not replace third-party component or model licenses. No endorsement or affiliation is implied.
