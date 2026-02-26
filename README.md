# kakehashi
ES-DE（EmulationStation Desktop Edition）において、ゲームの日本語メタデータを効率的に管理するためのツール

1. 開発目的
EmulationStation Desktop Edition (ES-DE) において、標準のスクレイパーでは取得が難しい「日本語のゲームタイトル」「日本語の解説文」「国内版のボックスアート」を、.m3u ファイルや各種ROMファイルに対して一括、または個別で紐付けるためのツールを開発する。

2. ターゲットファイルとディレクトリ構造
ツールは以下のディレクトリおよびファイルに対して読み書きを行う。

2.1 メタデータ定義ファイル (gamelist.xml)
* 場所: ~/.emulationstation/gamelists/[機種名]/gamelist.xml
* 役割: ゲームのタイトル、説明、画像パス、発売日、メーカー情報をXML形式で保持する。

2.2 メディアフォルダ
* 場所: ~/.emulationstation/downloaded_media/[機種名]/
* サブフォルダ: covers/ (パッケージ画像), screenshots/ (スクリーンショット), videos/ (動画)

3. 主要機能 (コア・モジュール)

3.1 ROMスキャン・マッチング機能
* 指定した機種フォルダ（例: roms/ps2/）内のファイルを走査する。
* 特に .m3u ファイルを優先的に検出し、複数枚組ディスクを1つのエントリとして扱う。
* ファイル名から不要な記号（例: (Japan), [Disc1]）を除去し、検索用クエリを生成する。

3.2 外部データ連携 (日本語ソース)
* ローカルCSV/JSON: ユーザーが用意した「ファイル名, 日本語名, 解説文」のリストを読み込む。
* Webスクレイピング: (オプション) 日本のゲームデータベースサイトから情報を取得する。
3.3 XML編集エンジン
* 既存の gamelist.xml をパースし、重複があれば更新(Update)、なければ新規追加(Append)する。
* 重要: 書き込み前にバックアップ (gamelist.xml.bak) を自動生成する。

4. XMLデータ構造の定義 (ES-DE準拠)
各ゲームエントリは以下のタグを必須・推奨項目とする。

| タグ名 | 内容 | 備考 |
|---|---|---|
| path | ./filename.m3u | ROMの相対パス |
| name | 日本語タイトル | 表示名 |
| desc | ゲームのあらすじ | 日本語テキスト |
| image | ./downloaded_media/ps2/covers/filename.png | 画像へのパス |
| releasedate | YYYYMMDDT000000 | 発売日フォーマット |
| developer | 開発会社名 | |
| genre | ジャンル | |

5. 開発環境・技術スタック (推奨)
* 言語: Python 3.x
* ライブラリ:
* lxml または xml.etree.ElementTree (XML操作用)
* pandas (CSV/JSON管理用)
* BeautifulSoup4 (スクレイピング用)
* プラットフォーム: SteamOS (Linux) / Windows
6. 運用上の注意点
* ES-DEが起動している間に gamelist.xml を上書きすると、ES-DE終了時にデータが消える可能性があるため、必ず**「ES-DEを終了させた状態で実行」**する仕様とする。

7. 開発環境のセットアップ（Windows 11）
まずは、Windows上でES-DEの挙動を再現できる環境を作ります。
* Pythonのインストール: Microsoft Storeまたは公式サイトからPython 3.10以上をインストール。
* 仮想ES-DE環境の作成:
Windows版のES-DEをインストールするか、あるいは単にデスクトップに test_emu/roms/ps2/ や test_emu/gamelists/ps2/ といったダミーのフォルダ構成を作るだけでOKです。
* パスの互換性: Pythonの os.path や pathlib ライブラリを使えば、Windowsの \ と Linuxの / の違いを自動で吸収できます。

8. WindowsとSteam Deckの「パス」の違い
ツールを完成させたあと、Steam Deckへ持っていくことを想定して、設定ファイルなどでパスを切り替えられるようにしておくとスマートです。

| 項目 | Windowsでの標準的な場所 | Steam Deck (Linux) での場所 |
|---|---|---|
| gamelist.xml | %HOMEPATH%\.emulationstation\gamelists\ | ~/.emulationstation/gamelists/ |
| メディアフォルダ | %HOMEPATH%\.emulationstation\downloaded_media\ | ~/.emulationstation/downloaded_media/ |
| ROMフォルダ | （任意の設定場所） | /run/media/mmcblk0p1/Emulation/roms/ (SDカード) |

# 🚀 Steam Deck (SteamOS) での実行方法
Steam Deckのデスクトップモードで以下の手順を実行してください。

1. リポジトリのクローン
ターミナル（Konsole）を開き、プロジェクトをダウンロードします。

```Bash
cd ~/Desktop
git clone https://github.com/hina0118/kakehashi.git
cd kakehashi
```

2. セットアップ
SteamOSのシステム環境を汚さないよう、Pythonの仮想環境を使用してセットアップします。

```Bash
# 仮想環境を作成
python -m venv venv

# 仮想環境を有効化
source venv/bin/activate

# 必要なライブラリをインストール
# ※lxmlなどを使用している場合
pip install -r requirements.txt
```

3. 設定ファイルの編集
config.json を開き、environment を "steam_deck" に変更するか、パスが正しいか確認してください。

gamelist.xml の標準的な場所: /home/deck/.emulationstation/gamelists/ps2/gamelist.xml

ROMフォルダの場所（SDカードの場合）: /run/media/mmcblk0p1/Emulation/roms/ps2/

4. 実行
```Bash
python main.py
```

🛠️ トラブルシューティング
パスが見つからない場合
Steam Deckでは、SDカードのパスが個体によって異なる場合があります。
ターミナルで ls /run/media/ を実行し、自分の環境のSDカード名（mmcblk0p1 など）を確認してください。

ES-DEへの反映
gamelist.xml を更新した後は、ES-DEを再起動するか、ES-DEのメニューから 「MAIN MENU」>「UI SETTINGS」>「RELOAD ALL MIXED IMAGES」 を実行してください。
※ES-DEが起動中にスクリプトを実行すると、ES-DE終了時にデータが上書きされる可能性があるため、ES-DEを閉じてからの実行を推奨します。
