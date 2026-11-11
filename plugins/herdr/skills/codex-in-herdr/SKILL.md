---
name: codex-in-herdr
description: Herdr の中（HERDR_ENV=1）で Codex を起動、待機、追加指示、終了させるときの手順。Codex に探索、テスト作成、実装、レビューを出す前に必ず使う。ペインの分割先の決め方、herdr pane run、herdr agent wait、herdr agent prompt、herdr pane close を扱う。
---

# Herdr のペインで Codex を動かす

Herdr の中では Codex を Herdr のペインで動かす。サイドバーで実行中か完了かが見えるようにするため。裏で codex exec を流してログに書く方式は使わない。手順は次のとおり。

- ペインを作る前に `herdr pane layout --current` で今の配置を見て、分割先と方向を決める。左右は2列まで
  - 自分（Claude）しかいないとき: `herdr pane split --current --direction right --no-focus --cwd <worktree>`
  - 右列があるとき: 自分と x が同じペインを左列、x が大きいペインを右列として数える。右列の数が左列以下なら右列、多ければ左列を選び、その列で一番高いペイン（同じ高さなら下のもの）を `herdr pane split <pane_id> --direction down --no-focus --cwd <worktree>` で上下に割る
  - 分割は1回ずつ行い、前の split の結果が返ってから次を割る
  - 返る pane_id を控える
- `herdr pane run <pane_id> "codex --sandbox workspace-write '<短い英語のプロンプト>'"` で起動する。pane run は引数をつなげて1行のシェルコマンドにするので、全体を1つの文字列にし、プロンプトは内側の単引用符で囲む。長い指示はファイルに書き、そのパスをプロンプトで渡す
- 完了待ちは `herdr agent wait <pane_id>` をバックグラウンドで動かす。起動直後は Herdr が Codex を認識する前で agent_not_found になるので、先に `herdr agent wait <pane_id> --until working --timeout 60000` で起動を確かめ、失敗したら数秒おいてもう一度呼ぶ。結果は `herdr pane read <pane_id>` で読む
- 同じ作業への追加指示（レビュー指摘の修正など）は、起動中の Codex に `herdr agent prompt <pane_id> "<短い英語のプロンプト>" --wait --until working --timeout 30000` で送る
- テスト作成と実装は別セッションにする。同じペインを使い回すときは `herdr pane send-text <pane_id> "/quit"` と `herdr pane send-keys <pane_id> enter` で前の Codex を閉じてから起動し直す
- 作業が終わったら、結果を `herdr pane read` で読み、コミットまで済んだことを確かめてから `herdr pane close <pane_id>` でペインを閉じる。閉じると画面の履歴も消えるので、読む前には閉じない
