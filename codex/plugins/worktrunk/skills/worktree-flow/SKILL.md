---
name: worktree-flow
description: Worktrunkで必要な作業分離、設定・非公開資料の引継ぎ、明示依頼されたマージ後のworktreeとブランチの削除を行うときに使う。単なるマージ通知では削除しない。
---

# Worktrunkでの作業分離と引継ぎ

統括が必要な作業分離を管理する。独立した複数の実装や既存作業の保持に役立つ場合に使い、読み取り調査や軽微な文書修正では不要にworktreeを増やさない。同じ項目の既存worktreeは再利用する。作業者の作業先が指定済みなら二重に作成せず、その絶対パス・ブランチ・基点を照合してから指定範囲を編集する。

## 開始と資料の準備

- 開始前に `git status --short`、`git worktree list`、`git branch --show-current`、`git rev-parse HEAD` を確認し、既存作業を保全する。インストール済み `wt --help` と使うサブコマンドのhelpで構文を確認してから実行する。
- 新規作成は `wt switch --create feature/<topic> --base <base> --no-hooks` を基本とし、既存ブランチの再利用でも `--no-hooks` を付ける。リポジトリ指定の命名を優先し、既存変更を無断で移動・上書きしない。
- `.worktreeinclude` があれば内容を読み、`wt step copy-ignored --from <source> --to <target> --require-include --dry-run` で対象を確認する。必要な対象だけで、既存先を上書きしないと確認してから同じ指定で `--dry-run` を外す。
- `.worktreeinclude` がなければ必要なファイルを個別に確認する。無差別なcopy-ignored、`--force`、既存先の上書きはしない。秘密値を表示しない。
- 依存関係はworktreeごとに準備する。別worktreeの `node_modules` 等を丸ごと共有するsymlinkは作らない。パッケージ管理ツール内部の正規のsymlinkは対象外とする。
- 開始元と担当先の最新指示、存在する `ROADMAP.md` / `doc/ROADMAP.md` / `progress.txt` の正本を読む。Git管理外の資料は必要な対象だけ引き継ぎ、コピー側から正本へ並行上書きしない。正本の更新は統括が集約する。
- 同じworktreeの編集者は1体に限る。旧担当の編集停止を確認して引き継ぎ、環境を変えるテストと実装は並行させない。

Worktrunk未導入、非Gitディレクトリ、権限不足では環境を勝手に変更せず、既存作業を保全して制約を報告する。

## 明示依頼された削除

マージ通知だけでは削除しない。対象のworktree・ブランチが明示された削除依頼がある場合だけ進める。自動merge、自動pullは行わず、`git push`は絶対に実行しない。

1. 対象の絶対パス・ブランチ・対応PRを照合し、接続済みGitHubツールまたは `gh pr view <number> --json state` で `MERGED` を確認する。マージ前なら削除しない。
2. `git -C <target> status --short --untracked-files=all` とworktree一覧を確認する。未コミット変更・未追跡ファイルがあれば停止する。Git管理外の設定・非公開資料も失われないか確認し、必要な資料が対象にしかない場合は削除を止めて報告する。
3. `wt remove --help` で現在の構文と削除の挙動を確認する。対象外の安全なworktreeから、確認した構文で `wt remove <branch> --foreground --no-hooks --format json` を実行する。`-f`・`-D`などforce相当の指定は使わない。
4. 結果と `git worktree list`、ローカルブランチの有無を確認する。`branch_outcome` が `deleted` でなければ残った理由を報告する。基点が古い場合やsquashマージで未マージ判定になっても、自動pullや強制削除で解消しない。

完了時は残したworktree・ブランチ、検証結果、未削除の理由を報告する。
