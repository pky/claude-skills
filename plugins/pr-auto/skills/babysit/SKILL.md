---
name: babysit
description: gh pr create で PR を作った直後から、マージできる状態の報告と、マージ後の片付けまでの決まりと手順。PR を作ったら必ず使う。babysit、PR の見張り、CI やレビューコメントの確認を頼まれたときも使う。/loop 5m での見張り、@codex review での再レビュー、指摘を直すのは3ラウンドまで、マージできる状態の条件と報告の中身、マージ後の worktree 削除とデプロイコマンドの添え方、gh でスレッドを取るコマンドを扱う。
---

# PR を作った後の流れ

## 決まり

- PR を作ったら `/loop 5m` で5分ごとに、CI（GitHub Actions があるリポジトリだけ）と Codex の自動レビューの未解決スレッドを確認し、指摘は既存の流れ（修正は Codex、差分レビューは fresh-reviewer）で直して、コミットと push まで進める。指摘が妥当でないときは直さず、そのスレッドに直さない理由を返信する。スレッドの resolve はレビュアーに任せる
- Codex の自動レビューは PR を開いたときにしか走らない。PR を開いた後に push したら、PR に `@codex review` とコメントして最新のコミットを再レビューさせる。Codex のサマリーコメントに書かれたコミットが、PR の最新のコミットと一致するまでは、レビュー済みとみなさない
- レビュー指摘を直す push は、1つの PR で3ラウンドまで: 3回直しても新しい指摘が続くなら、それ以上は直さない。残った指摘を一覧にし、作り方そのものを見直すべきかの判断を添えてユーザーに報告する。報告のあともループは続けるが、新しい指摘は直さずに一覧へ足す。指摘を直すときは、指摘された行だけでなく同じ種類の間違いをほかの箇所でも探し、1回の push でまとめて直す
- マージできる状態の条件: CI があれば green、Codex のレビューが最新のコミットまで済んでいる、未解決スレッドがすべて「直した」か「理由を返信済みで、その後に新しい指摘がない」。満たしたら1回だけ報告し、理由を返信して直さなかった指摘の一覧を添える。報告には次の3つも書く。この PR で何が変わるかを2〜3行で。人が理解してからマージすべき箇所を file:line 付きで最大3つ（データを壊しうる変更、権限や秘密情報、CI や設定、あとで真似される設計の決め方。当たらなければ「なし」と書く）。テストとレビューが見ていない部分（実機での動作、ネットワークの失敗、既存データの移行など）。報告したらループを止める。マージまでは監視しない。PR がマージされたとユーザーから聞いたら、worktrunk:worktree-flow スキルの手順で worktree とローカルブランチを消す。片付けの報告には、その PR の変更範囲に合わせたデプロイコマンド（例: web だけなら Hosting、Functions やルールも変えたらその分）を、ビルドなどの前準備も含めて貼れる形で添える。デプロイ自体は実行しない

## 毎回の確認の手順

1. PR の番号、ブランチ、基点ブランチを確かめる
2. PR が draft でないことと、マージできるか、CI、レビューの判定、コメント、スレッドを見る
3. 新しいコメントと未解決スレッドを読む。bot のサマリーは参考にするが、指摘はコードと照らして確かめる
4. 本物の指摘は、決まりのとおり直してテストやビルドを通し、push してから2に戻る
5. bot の指摘が古いコードに対するものなら、スレッドが outdated か、最新のコミットで直っているかを確かめる
6. 最後の報告の前に、PR の状態、未解決スレッド、最近のコメント、手元の `git status` をもう一度まとめて見る
7. 報告には、最新のコミットの SHA、CI の名前と結果、未解決スレッドの数、走らせたテスト、手を付けずに残した未コミットのファイルを書く

## gh のコマンド

PR の大まかな状態:

```bash
gh pr view <number> --json number,state,isDraft,mergeable,mergeStateStatus,reviewDecision,headRefOid,statusCheckRollup,url
```

owner と repo の名前（GraphQL に渡す値。出力を見て、次のコマンドにそのまま書く）:

```bash
gh repo view --json owner,name
```

未解決スレッドの一覧。`<owner>` と `<repo>` には上の値を書く。整形は jq を使わず、返ってきた JSON の `isResolved` が false のものを読む:

```bash
gh api graphql -f query='query($owner:String!,$repo:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$repo){pullRequest(number:$number){reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}nodes{id,isResolved,isOutdated,path,line,comments(last:1){nodes{author{login},body,createdAt,url}}}}}}}' -f owner=<owner> -f repo=<repo> -F number=<number>
```

`hasNextPage` が true のときは、同じコマンドに `-f cursor=<endCursor の値>` を足して、次のページを1回ずつ取る。シェルの変数やループで回さない。
