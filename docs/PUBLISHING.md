# Publish to your GitHub

Double-click `Publish-to-GitHub.command` in Finder, or run `python3 scripts/publish.py` in Terminal. It scans committed files, requires a clean checkout, signs into GitHub through the official CLI when needed, confirms the account is `YOUR_GITHUB_USER`, and creates `jarvis-personal-assistant` as a **private** repository. It does not overwrite an existing repository.

A private repository lets you inspect the contents before exposing them publicly. Invite collaborators from GitHub, or intentionally change its visibility after reviewing the files and media. This export does not automatically make the repository public.

The helper can download a pinned, SHA-256-verified GitHub CLI for Apple Silicon if one is not installed. Its temporary binary is removed when the helper exits. GitHub CLI manages login; never paste an API key or GitHub token into a chat.

Publishing has not happened until the helper prints the final repository URL after a successful push. An existing local commit is not proof of an upload.
