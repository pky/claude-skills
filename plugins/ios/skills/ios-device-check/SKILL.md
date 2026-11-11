---
name: ios-device-check
description: iOS 実機（iPad mini / iPhone）で動作確認するときに使う。WebDriverAgent と mobile-mcp を起動し、mobile_* ツールでアプリ起動、画面要素の取得、タップ、スクリーンショットを行う。「実機で確認して」「iPad で動かして」「スクショ撮って」と言われたら必ず使う。
---

# iOS 実機確認（WebDriverAgent + mobile-mcp）

実機操作は mobile-mcp（MCP サーバー名 `mobile`）経由で行う。前提は USB 接続、ロック解除、WDA 起動の3つ。

## 手順

1. 端末が USB で見えているか確認する

```sh
ios list
```

空なら「USB で接続してロック解除してください」と依頼して止まる。Wi-Fi 接続では go-ios が端末を列挙しないため mobile-mcp から見えない。

2. WDA を起動する（tunnel、port forward、WDA を一括起動し ready まで待つ）

```sh
sh ~/works/mobile-mcp-tools/start-wda.sh            # 既定: iPad mini
sh ~/works/mobile-mcp-tools/start-wda.sh <UDID>     # 別端末
```

`WDA ready` が出れば準備完了。失敗したら ~/Library/Logs/mobile-mcp-tools/wda.log を見る。

3. mobile_* ツールで操作する
   - mobile_list_available_devices で端末 ID を取る
   - mobile_launch_app に Bundle ID を渡して起動する（PFile は jp.pky.pfile）
   - mobile_list_elements_on_screen で要素と座標を取り、mobile_click_on_screen_at_coordinates でタップする
   - mobile_take_screenshot で画面を確認する
   - mobile_get_foreground_app は legacy モード非対応。使わない

4. 終わったら停止する

```sh
sh ~/works/mobile-mcp-tools/stop-wda.sh
```

## mobile ツールがセッションに無いとき

MCP はセッション起動時に読み込まれる。ツールが見えない場合は再起動を案内する。再起動できない場合は、mobile-mcp を stdio で直接呼ぶ Node スクリプトを書いて代用する（initialize と notifications/initialized を送ってから tools/call を送る。環境変数 MOBILEMCP_LEGACY_ROBOT=1 を付ける）。

## 制約

- 同時に扱えるのは 1 端末のみ（localhost:8100 固定）。切り替えは stop-wda.sh のあと start-wda.sh <UDID>
- WDA は端末ごとに署名済みビルドが必要。新しい端末は `sh ~/works/mobile-mcp-tools/build-wda.sh <UDID>`
- 署名で「maximum number of registered iPhone devices」が出たら、ユーザーに developer.apple.com で端末枠を空けてもらう
- 詳細は ~/works/mobile-mcp-tools/README.md
