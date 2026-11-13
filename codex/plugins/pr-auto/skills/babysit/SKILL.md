---
name: babysit
description: PR作成直後の状態確認や、依頼されたPRのCI・レビュー・未解決スレッドの確認と修正の調整に使う。継続監視は依頼された期間と停止条件内で行う。
---

# PRの状態確認と修正の調整

Codex統括が状態確認と担当の調整を行う。作業者は引継ぎ範囲を守り、担当外の修正や再委譲を始めない。実装とレビューは別の新規セッションにし、モデル選択は共通指示に従う。

## 確認と停止条件

PR作成後は現在の状態を確認する。継続監視はユーザーが依頼した場合だけ行い、依頼された期間・停止条件を守る。期間・停止条件が不明なら継続分を確認し、まず現在の状態を報告する。待機は1回45秒程度までにし、変化のない状態を短間隔でAPIへ問い合わせない。新たなスケジュールや常駐処理は作らない。

1. PR番号、URL、ブランチ、基点ブランチ、リモートhead SHAを確認する。手元のブランチ・`git rev-parse HEAD`・`git status --short`と区別する。
2. state、draft、マージ可否、CIの名前と結果、レビュー判定、コメント、未解決スレッドを読む。CIやレビューが取得できなければ未確認とする。
3. レビューの対象SHAが最新のリモートheadと一致するか確認する。botのサマリーだけで完了扱いせず、指摘を対象コード・差分・再現条件と照合する。`outdated`だけでは解決扱いしない。
4. 妥当な指摘は、許可範囲で実装担当が修正し、必要なテスト・型チェック・lint・ビルドと独立レビューを行う。同種の不具合も範囲内で確認する。修正ラウンドはPRごとに通算3回までとし、4回目には進まず、残る指摘と設計見直しの要否を報告する。
5. 報告直前にリモートhead、CI、レビュー対象SHA、未解決スレッド、最近のコメント、手元の状態を再確認する。途中でheadが変われば、新しいheadで判定し直す。

`git push`は絶対に実行しない。pushはユーザーが手動で行う。ローカル修正が未pushなら、そのSHAと検証結果を報告し、リモートCI・レビューがその修正まで済んだとは扱わない。ユーザーのpush後はリモートheadを再取得する。

コメント投稿、`@codex review`による再レビュー依頼、スレッドのresolveなどの外部書き込みは、対象操作の明示依頼がある場合だけ行う。妥当でない指摘は理由を報告し、必要なら返信・再レビュー依頼の文案を添える。未投稿の文案は「返信済み」と数えない。

## マージ準備の判定と報告

draftではなくマージ可能で、CIがある場合は最新のリモートheadの必要なCIがすべて成功し、最新headに対する必要なレビューが済んでいることを確認する。未解決スレッドは、最新headで修正を確認できたものか、修正しない理由が実際に返信済みで以後新しい指摘がないものに限る。後者は人の判断が残るものとして明記する。保留・失敗・競合・対象SHA不明があれば、マージ準備が整ったとは報告しない。

報告には次を含める。

- PRで変わることを2〜3行、PRのURL、リモートhead SHAとローカルHEAD、未push変更の有無。
- CIの名前・結果、レビュー対象SHA、未解決スレッド数、修正した指摘と修正しない理由、残る指摘、修正ラウンド数。
- 実行した検証コマンドと結果、手を付けずに残した未コミットファイル。
- 人が理解してからマージすべき点を最大3つ、`file:line`付きで示す。該当しなければ「なし」とする。
- 実機、通信失敗、データ移行など、テスト・レビューの未検証範囲。

マージ準備が整った報告は1回行って監視を止め、マージまで待ち続けない。依頼期限・停止条件への到達、3ラウンド後の未解決事項も報告して修正を止める。その後の監視は既存の依頼範囲内でのみ続ける。

マージ完了の通知だけではworktreeやブランチを削除しない。対象を明示した削除依頼がある場合だけ、利用可能な `worktree-flow` の手順を読む。デプロイコマンドを案内する場合は変更範囲に合うビルド等の前準備を含め、デプロイ自体は実行しない。

## 読み取り手段

接続済みGitHubツールで必要なSHA、CI、レビュー、全スレッドを取得できるなら優先する。不足する場合は以下の `gh` を代替に使う。どちらもページネーションを最後まで確認し、途中の一覧を全件と扱わない。

PRの状態、ブランチ、レビュー・コメント:

```bash
gh pr view <number> --json number,url,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,reviews,comments
gh repo view --json owner,name
```

レビュー対象のcommit SHA。`<owner>`・`<repo>`は取得した値を使う。

```bash
gh api graphql -f query='query($owner:String!,$repo:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$repo){pullRequest(number:$number){reviews(first:100,after:$cursor){pageInfo{hasNextPage endCursor}nodes{author{login}state submittedAt body url commit{oid}}}}}}' -f owner=<owner> -f repo=<repo> -F number=<number>
```

未解決スレッドと最新コメント:

```bash
gh api graphql -f query='query($owner:String!,$repo:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$repo){pullRequest(number:$number){reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}nodes{id isResolved isOutdated path line comments(last:1){nodes{author{login}body createdAt url}}}}}}}' -f owner=<owner> -f repo=<repo> -F number=<number>
```

各接続の `hasNextPage` がtrueなら、同じコマンドに `-f cursor=<endCursor>` を付けて次ページを1回ずつ取得し、falseまで確認する。異なる接続のcursorを混用しない。スレッドの最新コメントだけで判断できないときは、次の読み取りで全履歴を確認する。

```bash
gh api graphql -f query='query($id:ID!,$cursor:String){node(id:$id){... on PullRequestReviewThread{comments(first:100,after:$cursor){pageInfo{hasNextPage endCursor}nodes{author{login}body createdAt url}}}}}' -f id=<thread-id>
```

このcomments接続も同じ方法で全ページを取得する。件数の多いPRコメントなど、ほかの一覧もツールの続きを取得する。botのサマリーに対象SHAがなければ推測せず、最新headのレビューは未確認として報告する。
