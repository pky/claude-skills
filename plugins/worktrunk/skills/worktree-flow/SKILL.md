---
name: worktree-flow
description: Worktrunk（wt コマンド）で worktree を作る、設定や資料を準備する、マージ後に消すときの手順。wt switch で新しい worktree を作る前、.worktreeinclude や copy-ignored を使う前、PR がマージされたと聞いて worktree とブランチを片付ける前に必ず使う。
---

# Worktrunk の手順

- 開始前に `git status --short`、`git worktree list`、ブランチと基点コミットを確認する。新規作成は `wt switch --create feature/<topic> --base <base> --no-hooks` を基本とし、既存ブランチの再利用時も `--no-hooks` を付ける。命名はリポジトリ指定を優先し、既存変更の無断移動・上書きをしない。
- 環境設定・非公開資料は必要な対象だけ準備する。`.worktreeinclude` がある場合も内容を確認し、`wt step copy-ignored --from <source> --to <target> --require-include --dry-run` で対象を確認してから、同じ指定で `--dry-run` を外してコピーする。依存関係は各 worktree 内で独立して準備し、別 worktree の node_modules 等の依存ディレクトリを丸ごと共有する symlink は作らない（パッケージ管理ツール内部の正規の symlink は対象外）。`.worktreeinclude` がない場合は必要なファイルを個別確認し、無差別な copy-ignored や `--force`、既存先の上書きをしない。秘密値を表示しない。
- 開始元の最新の指示ファイルと、存在する `ROADMAP.md` / `doc/ROADMAP.md` / `progress.txt` の正本を確認する。Git管理外の資料は引継ぎ先でも読めるよう必要な対象だけ用意し、コピー側から正本へ並行上書きしない。正本の更新は統括側で集約する。
- PR がマージされたら worktree とローカルブランチを消す: `gh pr view <番号> --json state` で `MERGED` を確かめ、先に元の worktree の main を `git pull --ff-only` で最新にしてから、元の worktree で `wt remove <branch> --foreground --no-hooks --format json` を実行する。main が古いままだと squash マージしたブランチを未マージと判定して残すので、順番を守る。`-f` と `-D` は付けない。未コミットの変更があると何も消さずに止まる。出力の `branch_outcome` が `deleted` でなければ、聞かずに `~/mac_home/hooks/wt-remove-merged -C <元の worktree> <branch>` を実行する。この入口がない環境では実行せず、ブランチ名と「ユーザーが手動で消す」とだけ報告する。取り込み済み（ブランチを今の HEAD にマージしても中身が変わらない）なら消えるので報告する。取り込まれていなければ何も消さずに止まるので、ブランチ名と「ユーザーが手動で消す」とだけ報告する。`wt remove -D` は直接打たない。マージ前の worktree は消さない
