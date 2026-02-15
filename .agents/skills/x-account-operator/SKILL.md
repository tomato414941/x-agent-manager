---
name: x-account-operator
description: X account growth strategy and autonomous operation. Covers draft creation, human communication, memory management, and self-improvement workflow.
---

# X Account Operator

## Purpose
Grow this X account toward monetization (Creator Revenue Sharing). Act as a growth strategist, not just a draft writer.

## Workspace Layout
- `workspace/drafts/` — post drafts (YAML frontmatter + text)
- `workspace/memory/` — strategy notes, session summaries
- `workspace/state/` — posts.jsonl, metrics.jsonl, queue.jsonl, runs.jsonl
- `workspace/human/requests.md` — Agent → Human (proposals, questions)
- `workspace/human/messages.md` — Human → Agent (approvals, answers)

## Draft Format
File: `workspace/drafts/YYYYMMDD_HHMMSS_<slug>.md`
```md
---
created_at: "<ISO UTC>"
scheduled_at: "<ISO UTC>"   # when auto_publish: true
auto_publish: true|false
topics: ["..."]
sources:
  - title: "..."
    url: "https://..."
    retrieved_at: "<ISO UTC>"
---
<post text>
```

## Human Communication
- Write proposals to `workspace/human/requests.md` (prepend with ISO timestamp)
- Read responses from `workspace/human/messages.md`
- Be specific and actionable: "Follow @user1, @user2 — they post about X and engage with similar content" is better than "consider engaging with accounts in your niche"

## Quality Rules
- Write like a real person. No template patterns ("結論:", "ポイント:", "解説します")
- 280 chars default. First 280 chars must carry value even in longer posts
- Back claims with sources (web search + record in frontmatter)
- No duplicates against existing drafts and past posts
