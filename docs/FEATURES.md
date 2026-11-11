# Features and limits

## Voice and responsiveness

The custom free OpenRouter adapter emits provisional text snapshots while the original agent retains tool execution. Ordinary replies default to one or two sentences. Early sentence playback is restricted to self-contained tool-free explanations. Action results wait for receipts. Local command shortcuts avoid a model request for a small, explicit set of browser/reminder commands. Timing records contain durations, not transcript text.

Piper retains its loaded model. Acknowledgments are prepared when hands-free is enabled. Higher-quality transcription can still take time; no universal or measured latency promise is made.

## Screen summaries

The built web interface contains a small, separately versioned script that intercepts screen questions and opens an in-page chooser. Browser security requires a user gesture to start sharing. A single JPEG is captured and sharing stops; the result is summarized locally by `qwen3-vl:2b`. The web UI can ask Piper to read it. If autoplay is blocked, use Read aloud. Embedded WebKit may not offer display capture; upload a screenshot or use Chrome.

This is a snapshot tool, not continuous observation. Text inside a screenshot is treated as untrusted data. The small local vision model can misread dense pages, so confirm critical details in the source.

## Routines and handoffs

Saved routines contain up to eight HTTPS URLs and an optional reminder listing. A user-triggered run opens the saved sites through the local operating system. It reports that the OS accepted an open request; that is not proof that a page is loaded or an account is signed in.

Work handoffs contain explicit sites, allowed existing document paths and a next-step note. No active-tab history is captured automatically.

## Teaching

Teaching attaches Playwright navigation listeners to Jarvis's dedicated browser. It stores URL paths only in a temporary in-memory recording, removes query strings/fragments, and ignores several sensitive routes. This does not guarantee a URL path cannot contain private information: review all addresses before saving. Recordings are limited to eight unique pages and expire after ten minutes. They are not a click/typing macro recorder.

## Optional modules

Report generation, scheduling, memory, Slack, REA, phone alerts and ChatGPT subscription adapter sources are included for completeness. They require separate configuration and may depend on upstream interfaces or missing native pieces. ChatGPT is not the default route and no paid API key is requested by the export setup. Calendar and Home Assistant are optional connectors, not preconfigured accounts.
