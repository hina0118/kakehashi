# kakehashi 再構築計画

ES-DEのメタデータ編集ツールから、「ES-DEのゲーム」と「同人ゲーム」をまとめて管理するツールへ作り直す。

## 決定事項

| 項目 | 決定 |
|---|---|
| 実行場所 | Windows PC のみ。Steam Deck へは SSH/SFTP で反映する |
| バックエンド | Python + FastAPI |
| フロントエンド | React + Vite（TypeScript）。本番ビルドは FastAPI が静的配信する |
| 同人ゲーム | 台帳管理（PC上のSQLite）＋ Steam への非Steamゲーム登録 |
| 進め方 | `rebuild` ブランチで新規に書き直す。完成まで旧アプリ（`src/`）は main で使える状態を保つ |

## 設計方針

- **データの正本**
  - ES-DE のゲーム: Deck 上の `gamelist.xml` が正本。取得してから編集し、フィールド単位の差分だけを書き戻す（`favorite` など kakehashi が扱わないタグは保持する）。
  - 同人ゲーム: PC 上の台帳（SQLite）が正本。Deck への転送と Steam 登録は、台帳の内容を反映する操作として扱う。
- **GUI と MCP でロジックを共有する**: `services` 層に業務処理を集め、REST API と MCP サーバはどちらもそれを呼ぶだけの薄い層にする。
- **Deck との通信は `infra/deck.py` に集約する**: 接続・読み書き・バックアップ・一括転送・コマンド実行をここにまとめる。

## ディレクトリ構成

```
backend/kakehashi/
  config.py            config.json の読み書き（旧形式と互換）
  domain/              EsdeGame, DoujinGame などのモデル
  infra/
    deck.py            SSH/SFTP クライアント
    gamelist.py        gamelist.xml のパース・差分マージ
    doujin_db.py       同人台帳（SQLite）          ※Phase 3
    steam/             shortcuts.vdf・グリッド画像・Proton 設定  ※Phase 4
  services/            esde / media / transfer / doujin / steam
  api/                 FastAPI ルーター
  mcp/                 MCP サーバ
frontend/              React + Vite
tests/                 pytest
```

## フェーズ

| Phase | 内容 | 状態 |
|---|---|---|
| 0 | 骨格（FastAPI・Vite・設定・テスト基盤・起動コマンド） | 完了 |
| 1 | ES-DE メタデータ：機種一覧、ゲーム一覧/検索、編集、差分プッシュ、未登録ROM検出、Web検索/翻訳リンク。MCP を新サービスへ移行 | 完了 |
| 2 | メディア：存在チェック、サムネイル配信、3Dボックス・miximage・AIロゴ生成、動画（yt-dlp）、Deck へのメディア転送・ROM追加 | 完了 |
| 3 | 同人台帳：フォルダ登録、メタデータ編集（サークル・作品ID・タグ・プレイ状況・起動exe）、カバー画像、Deck への転送 | |
| 4 | Steam 登録：`shortcuts.vdf`（バイナリVDF）への追加、appid 算出、グリッド画像、Proton 設定（`config.vdf` の CompatToolMapping）、Steam 起動中チェック | |
| 5 | 旧 tkinter アプリ（`src/`）の削除、README 更新、main へマージ | |

## メディアの扱い（Phase 2）

- **正本はPC側の `windows.media_base`**。「Deckから取得」はPCに無いファイルだけを取り、PCで同じゲーム・同じ種類のファイルがあれば取得しない（PCでの編集を上書きしない）。
- 削除・拡張子違いへの差し替えは `work/pending_media_deletions.json` に記録し、次の「Deckへプッシュ」でDeckからも削除する。記録中のファイルは取得の対象外にする（旧アプリでは削除したファイルが次の取得で復活していた）。
- 「Deckへプッシュ」は、gamelist.xml の編集を反映したあと、フォルダごとの一覧でサイズを比べて変わったメディアだけを送る。
- ファイル名は stem の完全一致で照合する（旧アプリの glob は `Game [USA]` のような名前を誤判定していた）。
- 生成（3Dボックス・miximage・ロゴ切り出し・AIロゴ）は「プレビューを作る → 確認して保存」の2段階。プレビューはサーバのメモリに一時保持する。
- ROMや画像ファイルは、サーバと同じPCのファイル選択ダイアログ（`/api/local/pick`）で選ぶ。数GBのROMをブラウザ経由でアップロードせずに済む。
- 転送・動画取得・AIロゴ抽出はバックグラウンドジョブ（`/api/jobs`）で実行し、画面右下に進捗を出す。

## ローカルサーバの保護

- 更新系API（GET以外）は `X-Kakehashi: 1` ヘッダが必須。独自ヘッダはCORSのプリフライト対象になるため、他サイトのページからの操作（CSRF）を防げる。
- Host ヘッダが `127.0.0.1` / `localhost` 以外のリクエストは拒否する（DNSリバインディング対策）。

## Steam 登録の注意点（Phase 4）

- Steam は起動中に `shortcuts.vdf` をメモリに保持し、終了時に上書きする。書き込みは Steam が停止している間だけ行い、実行前に Deck 側のプロセスを確認する。
- 非Steamゲームの appid は `crc32(exe + name) | 0x80000000` で決まる。グリッド画像のファイル名（`{appid}p.png` など）もこの値から作る。

## 開発版の起動方法

```bash
# 依存関係（AIロゴ抽出も使うなら --extra ai を追加）
uv sync --extra mcp

# フロントエンドをビルドしてから起動（http://127.0.0.1:8765/ がブラウザで開く）
npm --prefix frontend install
npm --prefix frontend run build
uv run kakehashi serve
```

フロントエンドを開発するときは、`uv run kakehashi serve --no-browser --reload` と `npm --prefix frontend run dev` を並べて起動する（Vite が `/api` を 8765 番へ中継する）。

MCP サーバは `uv run kakehashi mcp` で起動する。旧版（`src/mcp_server.py`）と同じ6つのツールを同じ名前・引数で公開しているため、登録先のコマンドを差し替えるだけで移行できる。

テストは `uv run pytest`。Deck への接続はインメモリの偽実装に置き換えて実行する。
