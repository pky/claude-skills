---
name: ios-sim-check
description: iOS シミュレータでの動作確認を、他の開発とぶつからないように空き台を借りて行う。「シミュレータで確認して」「シミュレータで見て」「sim で確認」と言われたら使う。scripts/sim-lease で空き台を取得・返却し、Mobile MCP の mobile_ ツールで操作・スクリーンショット取得する。実機の確認には使わない。
---

# シミュレータ確認 (sim-lease + Mobile MCP)

複数の開発が同じシミュレータを奪い合わないよう、登録簿に載せた台だけを貸し出し台帳で借りて使う。
ユーザーに手順を聞かず、以下を順に自動で実行する。

この skill の Base directory にある scripts/sim-lease を `<SIM_LEASE>` と書く。

## 0. 登録簿が無いとき

この Mac にある iPhone のシミュレータを ~/.config/sim-lease/pool.txt に登録する。台は作らない。登録する台を絞りたいときは pool.txt を直接編集する。UDID は Mac ごとに違うので、別の Mac から持ち込まない。

1. `xcrun simctl list devices available` を実行する（リダイレクトやパイプは付けない。付けるとサンドボックスの除外から外れて失敗する）
2. 出力をそのまま scratchpad の sim-devices.txt に Write で保存する
3. `<SIM_LEASE> init <scratchpad>/sim-devices.txt` を実行する

sim-lease は simctl を呼ばない。サンドボックス内からは CoreSimulatorService に届かないため、一覧の取得と起動は自分で `xcrun simctl` を打つ。

## 1. 空き台を借りる (最初に必ず実行)

```
<SIM_LEASE> acquire <ラベル>
```

- ラベルは作業を区別できる名前にする (例: ブランチ名)
- `<SIM_LEASE> acquire --udid <UDID> <ラベル>` で台を指定して借りられる。指定した台が使用中なら空くまで待つ
- 標準出力に出た UDID が自分の台。以降のコマンドと mobile_ ツールすべてにこの UDID を渡す
- 空きが無ければ既定で 120 秒待つ。それでも無ければ exit 1 で終わる。その場合は `<SIM_LEASE> status` を見て、ユーザーに状況を報告する
- 台は新しく作らない。登録簿に無い台は使わない

## 2. 台を起動して検出する

```
xcrun simctl boot <UDID>
xcrun simctl bootstatus <UDID>
```

- 既に起動していて "Unable to boot device in current state: Booted" と出たときは、そのまま進む
- bootstatus は起動が終わるまで待つ（初回は数十秒かかる）。boot の直後は simctl で Booted と出ても Mobile MCP の一覧に出ないので、bootstatus が Finished か "Device already booted" を出すまで次へ進まない
- mobile_list_available_devices を呼び、取得した UDID が出ることを確認する。出なければ登録簿の台が消えているので、返却して `<SIM_LEASE> status` の別の台を試す旨をユーザーに報告する

## 3. アプリを入れる (コード変更の確認時)

```
xcodebuild -workspace <X.xcworkspace or -project X.xcodeproj> -scheme <スキーム> -destination 'platform=iOS Simulator,id=<UDID>' -derivedDataPath <DerivedData> build
xcrun simctl install <UDID> <DerivedData>/Build/Products/<構成名>-iphonesimulator/<App>.app
```

- -configuration は指定せず、スキームの既定構成でビルドする
- スキーム、構成名、バンドル ID は対象リポジトリの指示ファイル（CLAUDE.md、AGENTS.md）か `xcodebuild -list` で調べる
- 起動は mobile_launch_app (packageName: バンドル ID)

## 4. 操作して確認する

- mobile_take_screenshot で画面を取得し、画像を見て判断する
- mobile_list_elements_on_screen で要素の座標とラベルを取る
- タップは mobile_click_on_screen_at_coordinates、スクロールは mobile_swipe_on_screen、文字入力は mobile_type_keys
- 画面遷移のたびにスクリーンショットを撮り直す
- アプリ起動直後は画面が白紙のことがある。白紙なら描画待ちとみなし、同じ台でもう一度撮り直してから判断する

## 5. 返却する (確認が終わったら必ず実行)

```
<SIM_LEASE> release <UDID>
```

- 失敗や中断のときも返却する
- 台は落とさない。他の開発が起動中のまま使っている可能性がある
- 返却し忘れても、借りてから 7200 秒で次の取得時に自動回収される

### sim-lease が sandbox で実行できないとき(`Operation not permitted`)

登録簿は ~/.config/sim-lease/pool.txt(HOME が別の場所なら、その下の .config)を Read で読む。ロックの仕組みは `mkdir` だけなので、同じ手順を手で行う。rm と rmdir が使えない環境では、返却を mv で行う。

- 借りる: `mkdir -p /tmp/sim-lease-<uid>/locks/<UDID>`(`ls /tmp/sim-lease-<uid>/locks` で他の貸出中の台を避ける。借りる前に、下の返却手順が使えることを確かめる)
- 返す: 返却先 R=/private/tmp/claude-*/sim-lease-released を毎回同じ名前で上書きし、ファイルを増やさない(R が無ければ先に `mkdir -p R`)。
  1. `mv -f <ロック>/owner R/owner-<UDID>`(owner が無ければ省く)
  2. `mv -f <ロック>/time R/time-<UDID>`(time が無ければ省く)
  3. `mv <ロック> R/`(末尾のスラッシュ付き。空のロックが R/<UDID> を置き換える。ディレクトリ単体を既存のディレクトリ名へ mv すると、その中へ入ってしまうので使わない)
- 返却後に `ls` で状態を確かめてから報告する。他の開発が借りた台には触らない。「返せない」とユーザーに報告しない

## 6. 報告する

- 確認した画面ごとにスクリーンショットの内容を言葉で説明する
- 期待どおりかどうかを明記し、崩れや不具合があれば座標と要素名を添える
- スクリーンショットを見ずに「問題ない」と言わない。取得できなかった場合はそう書く

## 補足

- 貸出状況は `<SIM_LEASE> status`
- 登録簿の場所は環境変数 SIM_LEASE_POOL、ロックの場所は SIM_LEASE_LOCKS で変えられる
