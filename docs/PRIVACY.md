# Privacy and sharing

## What was excluded

The export is assembled from allowlisted source/distribution files, rather than copying the whole installation. It excludes API key files, OAuth sessions, account catalogs, local TOML settings, databases, user notes, captures, routine/handoff data, logs, browser profiles, cookies, model weights, compiled application bundles, original Git history and runtime backups.

The owner's morning/health schedule was replaced with an empty schedule list. Recipient-specific reminders must be created by the recipient. Fictional sample notes are clearly separated from personal notes.

## Data flows

- Whisper and Piper operate locally after models have been downloaded.
- Screen summaries send the explicitly selected snapshot to local Ollama at 127.0.0.1:11434.
- The configured OpenRouter route sends questions and relevant tool context to an external provider. Free-only price constraints do not make it local or private.
- Browser actions visit the websites chosen by the user. Website sessions remain private runtime state.
- Slack is an optional external service. Generic ntfy notifications are also optional and require pairing.
- The notes viewer loads its 3D library from a CDN. The note graph itself is served locally.

Do not share captures of authenticated pages, account selectors, medical notes, private chats, access URLs, saved passwords, or QR pairing codes.

## Checks

Run `scripts/privacy_scan.py` against all export files, then `--tracked` before publishing. The Git hook scans staged blob contents, not only the working tree, to catch a secret that was staged before it was edited out. An optional manual workflow template is included in docs/privacy-workflow.example.yml. No GitHub Actions workflow is enabled by this export.

The scanner is deliberately content-redacting. It reports file names, line numbers where practical, and categories only. Neither scanner passes nor `.gitignore` prove the absence of every private value. Manually review the final diff and media.

## If a secret is published

Revoke or rotate it immediately at its provider. Deleting the file or commit is not enough because copies may exist. Avoid committing replacement credentials. Contact maintainers privately rather than pasting a key into a public issue.
