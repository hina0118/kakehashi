# kakehashi

Steam Deck のゲームを Windows PC から管理するツールです。

- **ES-DE のゲーム**: 日本語のタイトル・説明文などのメタデータと、カバー・スクリーンショットなどのメディアを編集して Deck に反映する
- **同人ゲーム**: 台帳で管理し、Deck へ転送して、Steam に非Steamゲームとして登録する

PC で Web サーバを起動し、ブラウザで操作します。Deck へは SSH/SFTP で書き込みます。

---

## できること

### ES-DE

- 機種ごとの `gamelist.xml` を Deck から読み込み、タイトル・説明・発売日・開発・発売元・ジャンルを編集
  - 「Deckへプッシュ」で変更した項目だけを最新の `gamelist.xml` にマージして書き戻す（`favorite` など kakehashi が扱わないタグは残す。書き込み前に世代バックアップ）
  - Deck の ROM フォルダにあって未登録のファイルを一覧に出し、そのまま登録できる
  - タイトルで Web 検索（DuckDuckGo / Google / Wikipedia / ファミ通）、説明文を翻訳（DeepL / Google翻訳）
- **メディア**（PC の `downloaded_media` が正本）
  - 11種類（3Dボックス・カバー・ロゴ・スクリーンショット・動画など）の確認・登録（ファイル / URL / yt-dlp）・削除
  - 3Dボックス生成（PS2 などは公式パッケージ風の装飾）、miximage 合成、カバーからのロゴ切り出し（手動 / AI）
  - 全ゲームの有無を一覧する「メディアチェック」
  - Deck との同期: 取得は PC に無いものだけ（PC での編集を上書きしない）、PC で削除・差し替えたものは次のプッシュで Deck からも消す
- ROM の追加（PC のファイルを Deck の ROM フォルダへ送る）

### 同人ゲーム

- 台帳（PC 上の SQLite）で管理: タイトル・サークル・作品ID・販売サイト・タグ・説明・発売日・プレイ状況・評価・メモ・起動ファイル
- 登録方法: フォルダを1つ登録 / 作品フォルダが並んだ親フォルダからまとめて登録 / Deck に置いてある作品を取り込む
  - フォルダ名から作品ID（`RJ…` / `d_…`）・サークル（`[サークル] タイトル` 形式）・タイトルを推定し、起動ファイルの候補を選ぶ
- 販売サイト（DLsite / FANZA同人 / FANZA GAMES / DMM GAMES）をタイトルで検索して作品を選び、タイトル・サークル（ブランド）・発売日・ジャンル・カバー画像を取得
  - 作品IDの形式: DLsite `RJ01234567`、FANZA同人 `d_123456`、FANZA GAMES・DMM GAMES `aman_0937` など
  - DMM の各サイトは作品ページから読み取るため、ページの構成が変わると取得できなくなることがあります
- Deck への転送（2回目以降は変わったファイルだけ）
- Steam に登録済みの非Steamゲームの取り込み（appID・Proton・起動オプションを引き継ぐ）
- **Steam への登録**: Deck の Steam に非Steamゲームとして登録し、ライブラリ画像（カバー・ヘッダー・ヒーロー・ロゴ・アイコン）と Proton の設定も書き込む

### AI エージェントとの連携（MCP）

gamelist の参照・編集、プレイ動画の登録、同人台帳の参照・編集、販売サイトの検索と作品情報取得を MCP ツールとして公開しています（[MCP サーバ](#mcp-サーバ)）。

---

## 必要なもの

- Windows 11
- [uv](https://docs.astral.sh/uv/)（Python の実行環境を用意します）
- [Node.js](https://nodejs.org/)（画面のビルドに使います）
- SSH を有効にした Steam Deck（[Steam Deck の準備](#steam-deck-の準備初回のみ)）
- 任意: NVIDIA の CUDA 対応 GPU（AI によるロゴ抽出を使う場合。初回に約2.5GBのモデルを読み込みます）

## 起動

`kakehashi.cmd` をダブルクリックします。初回は依存関係のインストールと画面のビルドを行い、ブラウザで <http://127.0.0.1:8765/> が開きます。

コマンドで起動する場合:

```bash
uv sync --extra mcp
npm --prefix frontend install
npm --prefix frontend run build
uv run kakehashi serve
```

AI によるロゴ抽出も使う場合は `uv sync --extra mcp --extra ai` でインストールします。

初回は「設定」画面で Deck の接続先（IPアドレス・ユーザー名・パスワード）と各フォルダを設定し、「接続を確認」を押してください。設定は `config.json` に保存されます（旧版の `config.json` はそのまま使えます。例は `config.example.json`）。

## Steam Deck の準備（初回のみ）

デスクトップモードで Konsole を開き、SSH を有効にします。

```bash
sudo systemctl enable --now sshd
passwd deck   # パスワードが未設定の場合
ip addr show | grep "inet "   # 例: inet 192.168.1.42/24 → 192.168.1.42 がIPアドレス
```

---

## 使い方の注意

### ES-DE

- **ES-DE を終了した状態で**プッシュしてください。ES-DE は起動中に `gamelist.xml` を保持しており、終了時に書き戻すため、起動中に書き込むと消えてしまうことがあります。
- 反映後は ES-DE を再起動してください。

### Steam への登録

- **Deck の Steam を終了した状態で**実行してください。ゲームモードでは常に Steam が動いているので、デスクトップモードに切り替えて Steam を終了します。kakehashi は Steam が起動していると書き込まずに中止します。
- 書き込む前に `shortcuts.vdf` と `config.vdf` をバックアップします（`shortcuts.vdf.日時.bak`）。元に戻すときは、このファイルを元の名前に戻してください。
- 登録した作品のプレイ時間などは、タイトルを変えて更新しても引き継がれます（appID を台帳で保持しています）。
- 起動オプションの既定値 `LANG=ja_JP.UTF-8 %command%` は、Shift-JIS で作られたゲームの文字化けを防ぎます。設定画面・作品ごとに変えられます。
- Deck に複数の Steam アカウントがある場合は、設定画面で登録先を選んでください。

### データの置き場所（PC）

| 場所 | 内容 |
|---|---|
| `config.json` | 接続先・フォルダなどの設定 |
| `work/doujin.db` | 同人ゲーム台帳 |
| `work/doujin_images/` | 同人ゲームの画像 |
| `work/pending_media_deletions.json` | PC で削除し、まだ Deck から消していないメディア |
| `windows.media_base`（設定） | ES-DE のメディア（`downloaded_media`） |

`work/` と `config.json` は Git の管理外です。台帳をバックアップする場合は `work/` をコピーしてください。

---

## MCP サーバ

Claude などの MCP クライアントに、次のように登録します（パスは環境に合わせてください）。

```json
{
  "mcpServers": {
    "kakehashi": {
      "command": "C:/app/project/kakehashi/.venv/Scripts/kakehashi.exe",
      "args": ["mcp"]
    }
  }
}
```

| ツール | 内容 |
|---|---|
| `list_systems` / `list_games` / `get_games` / `update_games` | ES-DE の機種・ゲーム一覧とメタデータの参照・更新 |
| `check_videos` / `update_videos` | プレイ動画の有無の確認と、URL（yt-dlp）・ファイルからの登録・削除 |
| `list_doujin` / `get_doujin` / `update_doujin` | 同人台帳の参照・更新 |
| `search_works` / `fetch_work` | 販売サイト（DLsite / FANZA同人 / FANZA GAMES / DMM GAMES）の検索と作品情報の取得 |

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| Deck に接続できない | Deck がスリープしていないか、同じネットワークにいるかを確認。`sudo systemctl start sshd` で SSH を起動 |
| 「Steamが起動しています」と出る | デスクトップモードで Steam を終了してから実行 |
| ES-DE に反映されない | ES-DE を再起動する |
| SDカードのパスがわからない | Deck で `ls /run/media/` を実行 |
| 画面が表示されない | `npm --prefix frontend run build` で画面をビルド |

---

## 開発

```bash
uv run kakehashi serve --no-browser --reload   # API（ポート 8765）
npm --prefix frontend run dev                  # 画面（Vite が /api を 8765 に中継）
uv run pytest                                  # テスト（Deck はインメモリの偽実装に置き換える）
npm --prefix frontend run lint
```

構成と設計の経緯は [docs/rebuild-plan.md](docs/rebuild-plan.md) を参照してください。

```
backend/kakehashi/
  domain/      ES-DE・メディア・同人ゲームのモデル
  infra/       Deck への SSH/SFTP、gamelist.xml、VDF、SQLite、DLsite など外部とのやり取り
  imaging/     3Dボックス・miximage・ロゴ抽出・Steam 用画像の生成
  services/    業務処理（Web API と MCP の両方から呼ぶ）
  api/         FastAPI のルーター
  mcp/         MCP サーバ
frontend/      React + Vite
tests/         pytest
```
