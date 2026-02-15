Xアカウントを AI Agent で自律運用し、収益化（Creator Revenue Sharing）を目指すリポジトリ。

## 構成
- `accounts/<name>/` にアカウントごとのエージェントを置く
- `accounts/<name>/AGENT_PROMPT.md` がエージェントへの指示
- `accounts/<name>/workspace/` が運用データ（下書き、メモリ、状態、ログ）
- `scripts/` にアカウント共通のスクリプト

## 人間とのやりとり
- `workspace/human/requests.md`: Agent → 人間（提案・依頼・質問）
- `workspace/human/messages.md`: 人間 → Agent（承認・回答・指示）
- 対話型セッション（Claude Code等）はリポジトリ全体の改善に使う

## 安全制約
- シークレットをコミット・出力しない
- 対外アクション（投稿等）は人間の明示承認があるもののみ。`AUTO_PUBLISH=1` 設定時はガードレール付きで自動投稿を許可
- X規約を遵守する（いいね自動化禁止、スパム行為禁止）
