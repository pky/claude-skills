---
name: retro
description: Claude Code の会話記録（jsonl）を読み、止められた操作、繰り返す失敗、守られなかった指示を集めて、直す先（CLAUDE.md、AGENTS.md、hook、メモリ）を提案する。「振り返って」「retro して」と言われたときに使う。設定や skill は変えない。
---

# retro

引数は任意の `[日数]`。既定は 7。対象は全プロジェクト。

## 1. 抽出

- この skill の Base directory にある scripts/retro_extract.py を `python3 -I <Base directory>/scripts/retro_extract.py --days <日数>` で実行し、出力をセッションの scratchpad に retro.json として保存する
- 終了コードが 0 でなければ、標準エラーをそのまま報告して終える

## 2. 照合

retro.json の3つを読む。

- blocked: 止められた操作。同じ source と reason_head が何度も出るものは、指示か hook のどちらかが行動に届いていない
- failures: 同じコマンドで同じエラーが2回以上出たもの
- corrections: ユーザーの発言のうち、セッションで2つ目以降で、訂正によく出る言葉を含むもの。指示への訂正でないもの（次の依頼、質問への答え）は捨てる。corrections_total は言葉で絞る前の件数

訂正だと判断したものは、既存ルールと照らし合わせる。照合先は次のとおり。

- ~/.claude/CLAUDE.md
- 発言の cwd にある AGENTS.md と CLAUDE.md（cwd は corrections の各項目にある）
- そのプロジェクトのメモリ（`<記録のディレクトリ>/<project>/memory/`）

照合の結果を、次の3つに分ける。

- 守られなかった指示: 既にルールがあるのに、同じことを指摘された
- 足りない指示: ルールが無い
- 一度きり: その場の判断の違いで、ルールにするほどではない

## 3. 報告

会話には次だけを出す。

```
止められた操作  <件数>  <一番多いもの1行>
繰り返す失敗    <件数>  <一番多いもの1行>
守られなかった指示 <件数>  <代表例1行>
足りない指示    <件数>  <代表例1行>

→ 直す先の案（最大3つ。1行に1つ、変える場所と中身）
```

- 2回以上起きたものは、指示を足すより hook や検査スクリプトで止める案にする
- 許可の追加で済むものは、自分で案を書かず `/fewer-permission-prompts` を勧める
- 全文（各グループの例、照合したルールの場所、判断の理由）は ~/Documents/retro/YYYY-MM-DD-HHMM.md に保存し、報告の最後にパスを書く

## やらないこと

- CLAUDE.md、AGENTS.md、hook、skill、メモリを変えない。変えるのは利用者が頼んだときだけ
- 会話記録の本文を外部に送らない。サブエージェントや Codex にも渡さない
