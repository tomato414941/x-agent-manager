# agent-x Account Notes

## Current Setup (Completed)
- X Developer Platform: registered
- X account: `agent-x`
- X Premium: subscribed

## Runtime
- Run on the `autonomous` server (see repo root `AGENTS.override.md` for SSH and commands).
- Secrets must not be committed.
  - Shared app settings are loaded from `${HOME}/.secrets/x-agent-manager/config`.
  - Account-specific X user tokens are loaded from `${HOME}/.secrets/x-agent-manager/agent-x`.
  - Legacy single-file mode (`${HOME}/.secrets/x-agent-manager`) is still supported.

## Guardrails
- Do not publish unless the human explicitly approves it in `workspace/human/messages.md`.
- Use the X API only (no browser automation); do not automate likes.
