# kakehashi
ES-DE（EmulationStation Desktop Edition）において、ゲームの日本語メタデータを効率的に管理するためのGUIツール

---

## 1. 開発目的
EmulationStation Desktop Edition (ES-DE) において、標準のスクレイパーでは取得が難しい「日本語のゲームタイトル」「日本語の解説文」「国内版のボックスアート」を、.m3u ファイルや各種ROMファイルに対して個別に編集・管理するためのツール。

---

## 2. 主な機能

### gamelist.xml エディタ
* ゲーム一覧からタイトルを選択して各フィールドを編集
* 編集対象フィールド: タイトル / 説明 / 発売日 / 開発 / 発売元 / ジャンル
* 発売日はカレンダーUIで入力（チェックで有効/無効を切替）
* ジャンルはタグ形式で複数入力に対応
* 保存時にタイムスタンプ付きバックアップを自動生成（世代数は `config.json` の `backup_max` で設定）

### Web検索 / 翻訳
画面下部のバーからワンクリックでブラウザを起動します。

| ボタン | 用途 |
|---|---|
| DuckDuckGo | タイトル＋機種名で検索 |
| Google | タイトル＋機種名で検索 |
| Wikipedia | 日本語Wikipediaで検索 |
| Famitsu | ファミ通サイトで検索 |
| DeepL | 説明文を英日翻訳 |
| Google翻訳 | 説明文を英日翻訳 |

### 環境の自動判別
`platform.system()` でOSを自動判別し、Windows / Steam Deck のパス設定を切り替えます。
`config.json` に `environment` を明示した場合はそちらが優先されます。

### 対象機種の自動検出
`gamelist_base` 配下のフォルダ名を自動スキャンして機種一覧を生成します。
フォルダが見つからない場合は `config.json` の `systems` リストにフォールバックします。

---

## 3. ターゲットファイルとディレクトリ構造

### 3.1 メタデータ定義ファイル (gamelist.xml)
* 場所: `~/.emulationstation/gamelists/[機種名]/gamelist.xml`
* 役割: ゲームのタイトル、説明、画像パス、発売日、メーカー情報をXML形式で保持する。

### 3.2 メディアフォルダ
* 場所: `~/.emulationstation/downloaded_media/[機種名]/`
* サブフォルダ: `covers/`（パッケージ画像）, `screenshots/`（スクリーンショット）, `videos/`（動画）

---

## 4. XMLデータ構造の定義 (ES-DE準拠)
各ゲームエントリは以下のタグを持ちます。

| タグ名 | 内容 | 備考 |
|---|---|---|
| path | ./filename.m3u | ROMの相対パス |
| name | 日本語タイトル | 表示名 |
| desc | ゲームのあらすじ | 日本語テキスト |
| image | ./downloaded_media/ps2/covers/filename.png | 画像へのパス |
| releasedate | YYYYMMDDT000000 | 発売日フォーマット |
| developer | 開発会社名 | |
| publisher | 発売元 | |
| genre | ジャンル（カンマ区切り） | |

---

## 5. 技術スタック

* **言語**: Python 3.10以上
* **GUIフレームワーク**: tkinter（標準ライブラリ）
* **外部ライブラリ**:
  * `tkcalendar` — カレンダー形式の日付入力
* **パッケージ管理**: uv（推奨）または pip
* **プラットフォーム**: Windows 11 / SteamOS (Linux)

---

## 6. 設定ファイル (config.json)

```json
{
  "system": "ps2",
  "systems": ["ps2", "ps1", "psp", "ds", "gba"],
  "backup_max": 5,
  "windows": {
    "rom_base": "C:/Users/YourName/Desktop/test_emu/roms",
    "gamelist_base": "C:/path/to/gamelists",
    "media_base": "C:/Users/YourName/.emulationstation/downloaded_media"
  },
  "steam_deck": {
    "rom_base": "/run/media/mmcblk0p1/Emulation/roms",
    "gamelist_base": "/home/deck/.emulationstation/gamelists",
    "media_base": "/home/deck/.emulationstation/downloaded_media"
  }
}
```

* `environment` キーは**省略可**。省略するとOSを自動判別します（Windows / Steam Deck）
* `systems` は `gamelist_base` 配下のフォルダが存在する場合は自動検出されるため省略可

---

## 7. 運用上の注意点
* ES-DEが起動している間に `gamelist.xml` を上書きすると、ES-DE終了時にデータが消える可能性があります。**必ずES-DEを終了させた状態で実行**してください。

---

## 8. WindowsとSteam Deckの「パス」の違い

| 項目 | Windowsでの標準的な場所 | Steam Deck (Linux) での場所 |
|---|---|---|
| gamelist.xml | `%HOMEPATH%\.emulationstation\gamelists\` | `~/.emulationstation/gamelists/` |
| メディアフォルダ | `%HOMEPATH%\.emulationstation\downloaded_media\` | `~/.emulationstation/downloaded_media/` |
| ROMフォルダ | （任意の設定場所） | `/run/media/mmcblk0p1/Emulation/roms/`（SDカード） |

---

## 🖥️ Windows での実行方法

```bash
# 依存ライブラリをインストール（初回のみ）
pip install -r requirements.txt

# 起動
python main.py
```

uv を使う場合：
```bash
uv sync
uv run python main.py
```

---

## 🚀 Steam Deck (SteamOS) での実行方法
Steam Deckのデスクトップモードで以下の手順を実行してください。

### 1. リポジトリのクローン
ターミナル（Konsole）を開き、プロジェクトをダウンロードします。

```bash
cd ~/Desktop
git clone https://github.com/hina0118/kakehashi.git
cd kakehashi
```

### 2. 起動スクリプトで実行（推奨）
`start.sh` が環境を自動セットアップして起動します。
`uv` がインストールされていれば uv を、なければ pip を使います。

```bash
chmod +x start.sh
./start.sh
```

**uv を使う場合（高速・推奨）:**
```bash
# uv のインストール（初回のみ）
curl -LsSf https://astral.sh/uv/install.sh | sh

./start.sh
```

**pip を使う場合:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### 3. 設定ファイルの確認
`config.json` の `steam_deck` セクションのパスが環境に合っているか確認してください。
`environment` キーは省略可能で、SteamOS（Linux）上では自動的に `steam_deck` 設定が使われます。

---

## 🛠️ トラブルシューティング

**パスが見つからない場合**
Steam Deckでは、SDカードのパスが個体によって異なる場合があります。
ターミナルで `ls /run/media/` を実行し、自分の環境のSDカード名（`mmcblk0p1` など）を確認してください。

**ES-DEへの反映**
`gamelist.xml` を更新した後は、ES-DEを再起動するか、ES-DEのメニューから
`「MAIN MENU」>「UI SETTINGS」>「RELOAD ALL MIXED IMAGES」` を実行してください。
※ES-DEが起動中にスクリプトを実行すると、ES-DE終了時にデータが上書きされる可能性があるため、ES-DEを閉じてからの実行を推奨します。
