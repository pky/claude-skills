# claude-skills

pky の自作スキルを Claude Code と Codex のプラグインとして配るマーケットプレイス。

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

## Codex での入れ方

同じリポジトリを Codex に登録し、必要なプラグインを導入する。

仕事Macの既存設定を保全して導入する場合は、[Codex単独統括環境の導入手順](docs/codex-setup.md)をCodexへ渡す。

```bash
codex plugin marketplace add pky/claude-skills --ref main
codex plugin add core@pky-codex-skills
codex plugin add pr-auto@pky-codex-skills
codex plugin add worktrunk@pky-codex-skills
codex plugin add herdr@pky-codex-skills
```

Codex 版は `git push` を実行せず、worktree やブランチも自動削除しない。削除は対象を明示した依頼がある場合だけ行う。

iOS 実機確認スキルが既にある場合は重複導入しない。未導入の場合だけ追加する。

```bash
codex plugin add ios@pky-codex-skills
```

更新は次のコマンドで取り込む。

```bash
codex plugin marketplace upgrade pky-codex-skills
```

Claude Code 用カタログは `.claude-plugin/marketplace.json`（`pky-skills`）、Codex 用は `.agents/plugins/marketplace.json`（`pky-codex-skills`）。Codex 版の4プラグインは `codex/plugins/` に配置し、iOS だけは既存の `plugins/ios` を共有する。

## 外部スキル

自作ではないスキル。中身はこのリポジトリに入れず、配布元から入れる。

- security-audit: `npx skills add cloudflare/security-audit-skill --skill security-audit` https://github.com/cloudflare/security-audit-skill
- stack-diagram: `npx skills add caru-ini/stack-diagram` https://github.com/caru-ini/stack-diagram
- yomiyasu: `npx skills add nanaism/yomiyasu` https://github.com/nanaism/yomiyasu
- herdr-automations、herdr-gpui-browser、herdr-mods: 出所未確認（Herdr アプリに付いてくるものと思われる）
