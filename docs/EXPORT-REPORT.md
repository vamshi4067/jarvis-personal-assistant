# Export report — 2026-11-10

## Origin

Recovered from an installed Jarvis runtime with the owner's authorization. The original development checkout could not be read through macOS permissions. This is a new source/distribution snapshot, with a fresh Git history, not a fork that preserves private development commits.

Included: recovered Python backend, custom sidecar modules, built chat UI and standalone screen scripts, routines/teaching/handoff editor, notes indexer/viewer, portable example settings, guarded new-install helper, privacy scan and media/documentation.

Not recoverable from this installation: the original editable React/TypeScript frontend, original native Swift app source, native Rust workspace, and exact original upstream Git revision. These gaps are explicit in PROVENANCE.json. No fake original files or unverified signed app installer were substituted.

## Privacy result

- Full export scan: zero findings after replacing personal home paths and removing private account-link strings.
- Exact comparison against the installed API key/OAuth/integration secret values: zero matching export files. Values were never printed.
- Fresh Git repository, with no original history or remote credentials inherited.
- Owner's schedules, personal notes, databases, browser profiles, saved routines/handoffs, logs, private configuration and model weights excluded.
- Generated media contains fabricated demonstration content and is labeled as illustration, not a live recording.

These checks reduce accidental exposure; they do not constitute a guarantee against every conceivable private detail or future modification. Re-run the redacting scanner and manually review future additions before sharing.

## Verification performed

- Python 3.12 AST parsing: 725 source files, zero syntax errors at export time.
- Custom routine/screen JavaScript syntax checks: passed.
- Example TOML configuration and source package metadata: parsed successfully.
- New demo graph: three fictional notes; no real personal graph copied.
- Publish helper shell syntax: passed.
- Poster visually inspected; no personal information present.

No assistant conversations, model inference, screenshot capture, routine replay, Slack messages, personal reminders, or trial audio playback were run for this export. A full clean-machine installation and end-to-end runtime verification have not been performed. No latency improvement or runtime success claim is made by this repository.

## Source adaptations for sharing

- Replaced VCS-derived package version with a static snapshot version because private Git metadata is intentionally absent.
- Disabled automatic startup of the legacy local FreeLLMAPI router in the exported launcher; OpenRouter free-only remains the example route.
- Removed the original owner's fixed recurring schedule and phone notification bodies.
- Added setup scripts that refuse to overwrite an existing runtime.
- Added a manual-only privacy workflow template (not enabled), local Git hook and source provenance.

The installed assistant was not modified by this export.
