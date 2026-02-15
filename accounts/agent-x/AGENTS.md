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
- Auto publish (opt-in): set `AUTO_PUBLISH=1` (and keep `MAX_POSTS_PER_DAY` low).
  - Draft must include frontmatter: `auto_publish: true` and due `scheduled_at`.
  - Kill switch: create `workspace/state/STOP_PUBLISH` (or set `STOP_PUBLISH=1`).
- Auto schedule (recommended when auto publish is on): set `AUTO_SCHEDULE=1`.
  - Schedule config: `SCHEDULE_TZ` and `SCHEDULE_SLOTS` (default: Asia/Tokyo + 07:30,12:10,20:30).

## Guardrails
- Do not publish unless the human explicitly approves it in `workspace/human/messages.md`.
- Use the X API only (no browser automation); do not automate likes.
