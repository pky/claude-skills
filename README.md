# claude-skills

pky の自作スキルを Claude Code のプラグインとして配るマーケットプレイス。

## 入れ方

```text
/plugin marketplace add pky/claude-skills
/plugin install core@pky-skills
```

- core: どの環境でも使う作業の型（completion-criteria）
- pr-auto: PR を作った後の見張りと片付け（babysit）。PR を自動で進めたくない環境では入れない
- worktrunk: Worktrunk（wt）で worktree を作る・消す手順（worktree-flow）
- herdr: Herdr のペインで Codex を動かす手順（codex-in-herdr）
- ios: iOS 実機での動作確認（ios-device-check）

PR を自動で進めたくない環境では pr-auto を入れない。

更新は `/plugin marketplace update pky-skills` で取り込む。

## 外部スキル

自作ではないスキル。中身はこのリポジトリに入れず、配布元から入れる。

- security-audit: `npx skills add cloudflare/security-audit-skill --skill security-audit` https://github.com/cloudflare/security-audit-skill
- stack-diagram: `npx skills add caru-ini/stack-diagram` https://github.com/caru-ini/stack-diagram
- yomiyasu: `npx skills add nanaism/yomiyasu` https://github.com/nanaism/yomiyasu
- herdr-automations、herdr-gpui-browser、herdr-mods: 出所未確認（Herdr アプリに付いてくるものと思われる）
