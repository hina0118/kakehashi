# kakehashi 再構築計画

ES-DEのメタデータ編集ツールから、「ES-DEのゲーム」と「同人ゲーム」をまとめて管理するツールへ作り直す。

## 決定事項

| 項目 | 決定 |
|---|---|
| 実行場所 | Windows PC のみ。Steam Deck へは SSH/SFTP で反映する |
| バックエンド | Python + FastAPI |
| フロントエンド | React + Vite（TypeScript）。本番ビルドは FastAPI が静的配信する |
| 同人ゲーム | 台帳管理（PC上のSQLite）＋ Steam への非Steamゲーム登録 |
| 進め方 | `rebuild` ブランチで新規に書き直し、完成後に main へマージした（旧アプリの `src/` は削除済み） |

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
| 3 | 同人台帳：フォルダ登録、メタデータ編集（サークル・作品ID・タグ・プレイ状況・起動exe）、カバー画像、Deck への転送 | 完了 |
| 4 | Steam 登録：`shortcuts.vdf`（バイナリVDF）への追加、appid 算出、グリッド画像、Proton 設定（`config.vdf` の CompatToolMapping）、Steam 起動中チェック | 完了（実機での確認待ち） |
| 5 | 旧 tkinter アプリ（`src/`）の削除、README 更新、main へマージ | 完了 |

## メディアの扱い（Phase 2）

- **正本はPC側の `windows.media_base`**。「Deckから取得」はPCに無いファイルだけを取り、PCで同じゲーム・同じ種類のファイルがあれば取得しない（PCでの編集を上書きしない）。
- 削除・拡張子違いへの差し替えは `work/pending_media_deletions.json` に記録し、次の「Deckへプッシュ」でDeckからも削除する。記録中のファイルは取得の対象外にする（旧アプリでは削除したファイルが次の取得で復活していた）。
- 「Deckへプッシュ」は、gamelist.xml の編集を反映したあと、フォルダごとの一覧でサイズを比べて変わったメディアだけを送る。
- ファイル名は stem の完全一致で照合する（旧アプリの glob は `Game [USA]` のような名前を誤判定していた）。
- 生成（3Dボックス・miximage・ロゴ切り出し・AIロゴ）は「プレビューを作る → 確認して保存」の2段階。プレビューはサーバのメモリに一時保持する。
- ROMや画像ファイルは、サーバと同じPCのファイル選択ダイアログ（`/api/local/pick`）で選ぶ。数GBのROMをブラウザ経由でアップロードせずに済む。
- 転送・動画取得・AIロゴ抽出はバックグラウンドジョブ（`/api/jobs`）で実行し、画面右下に進捗を出す。

## 同人ゲーム台帳（Phase 3）

- 台帳は `work/doujin.db`（SQLite、`PRAGMA user_version` でスキーマを管理）、画像は `work/doujin_images/{id}/{種類}.{拡張子}`。
- 画像の種類は Steam のライブラリ画像に合わせて cover（縦長）/ header / hero / logo / icon の5つ。
- 登録方法は3つ: フォルダを1つ登録 / 親フォルダを選んで中の作品をまとめて登録 / Deck の格納先にある作品を取り込む。
  - フォルダ名から作品ID（`RJ…` / `d_…`）・サークル（`[サークル] タイトル` 形式）・タイトルを推定し、起動ファイルの候補（アンインストーラ等を除外）を選ぶ。
  - Deck からの取り込みは、作品IDか PC 側のフォルダ名が一致する未紐づけの作品があれば、新規登録せずにそこへ `deck_dir` を設定する。
- 販売サイトの作品情報を取得できる。反映する項目は選べ、入力済みの項目は初期状態では上書きしない。
  - DLsite: 作品情報API（作品名・画像・登録日）と作品ページ（サークル名・ジャンル）。検索はサジェストAPI（`site=adult-jp` で全年齢向けも含む）。
  - FANZA同人（`d_…`）: 作品ページの JSON-LD（作品名・サークル・画像）と本文（配信開始日・ジャンル）。検索は `/dc/doujin/-/list/narrow/=/word=…/`。
  - FANZA GAMES（`dlsoft.dmm.co.jp`）/ DMM GAMES（`dlsoft.dmm.com`）: 作品ページの JSON-LD（作品名・画像）、パンくず（ブランド）、詳細表（配信開始日・ジャンル。セール用のタグは除く）。検索結果は HTML の `productListItem`。
  - DMM の各サイトは公式APIに利用登録が要るため、ページのHTMLから読み取っている。構成が変わると取得できなくなる。
  - タイトル検索は4サイトへ並行して問い合わせ、失敗したサイトはエラーとして返し、他の結果は返す。検索語は台帳のタイトルから★・版数・「製品版」などを除いて作る。
  - DLsite のメイン画像は横長（4:3）なので、Steam の縦長カバーには Phase 4 で整形が必要。
- 詳細画面は入力が止まってから自動保存する。サーバ側で値が変わったとき（転送で `deck_dir` が入った等）は、ユーザーが触っていない項目だけを新しい値に合わせる。
- Deck への転送は、初回に選んだ格納先の `{格納先}/{PCのフォルダ名}` へ送り、以降は同じ場所へサイズの変わったファイルだけを送る。PC で削除したファイルは Deck に残る。

## ローカルサーバの保護

- 更新系API（GET以外）は `X-Kakehashi: 1` ヘッダが必須。独自ヘッダはCORSのプリフライト対象になるため、他サイトのページからの操作（CSRF）を防げる。
- Host ヘッダが `127.0.0.1` / `localhost` 以外のリクエストは拒否する（DNSリバインディング対策）。

## Steam 登録（Phase 4）

- 書き込むもの:
  - `{steam_root}/userdata/{アカウント}/config/shortcuts.vdf` … 非Steamゲームの一覧（バイナリVDF）
  - `{steam_root}/userdata/{アカウント}/config/grid/` … `{appid}p.png`（縦長 600×900）/ `{appid}.png`（横長 920×430）/ `{appid}_hero.png`（1920×620）/ `{appid}_logo.png` / `{appid}_icon.png`
  - `{steam_root}/config/config.vdf` … `CompatToolMapping` に Proton を割り当て（起動ファイルが .exe/.bat などのときだけ）
- Steam は起動中これらをメモリに保持し、終了時に上書きする。書き込み前に Deck で `pgrep -x steam` を確認し、起動中なら何も書かずに中止する。
- 書き込み前に `shortcuts.vdf` と `config.vdf` を世代バックアップする（`backup_max`）。Deck への書き込みは一時ファイル経由で置き換える。
- バイナリVDF・テキストVDFとも、kakehashi が知らないキー・型・重複キー・順序を保ったまま書き戻す。既存エントリはプレイ時間・非表示・タグなど Steam 側の項目を残し、名前・起動ファイル・作業フォルダ・アイコン・起動オプションだけを書き換える。
- appID は初回に `crc32(引用符付きexe + 名前) | 0x80000000` で決めて `shortcuts.vdf` に明示的に書き、台帳にも保存する。以降はタイトルや起動ファイルを変えても同じ appID のエントリを更新する（Steam 側の記録が別ゲームにならない）。Steam から外しても appID は台帳に残し、再登録で同じ ID を使う。
- 画像は台帳の cover/header/hero から各サイズを作る（比率の差が12%以内なら切り抜き、それ以上はぼかした背景に収める）。ロゴとアイコンは台帳にあるときだけ送り、台帳から消したものは Deck からも消す。
- 起動オプションの既定は `LANG=ja_JP.UTF-8 %command%`（Shift-JIS のゲームの文字化け対策）。互換ツールの既定は `proton_experimental`。どちらも作品ごとに上書きできる。
- 登録先アカウントは `steam_deck.steam_user`。空なら `userdata/` にアカウントが1つだけのときに自動で選ぶ。
- **既存の Steam 登録との共存**（手動や他のツールで登録済みの非Steamゲームが多数ある前提）:
  - 登録時、台帳に appID が無ければ、同じ起動ファイルを指す既存エントリを探してその appID を引き継ぐ（二重登録しない）。引き継ぐ appID が台帳の別の作品で使われていればエラーにする。
  - 既存エントリでは、Proton・起動オプションは台帳で明示的に指定したときだけ変え、空欄なら Steam 側の設定を残す。既定値を当てるのは新規登録のときだけ。
  - グリッド画像は、既定では Deck に既にある種類を残し、無い種類だけを書き込む（「既存の画像も置き換える」を選んだときは置き換え、拡張子違いの古いファイルも消す）。台帳から作れない種類には触れない。
  - 「Steamから取り込み」で、登録済みの Windows 用非Steamゲームを台帳に取り込む（appID・Proton・起動オプションを引き継ぐ。同じ起動ファイルの未紐づけの作品があれば紐づける）。作品フォルダは格納先の直下のフォルダとし、格納先の外に作品が固まっているフォルダは格納先の候補として提示する。

## 起動方法

```bash
# 依存関係（AIロゴ抽出も使うなら --extra ai を追加）
uv sync --extra mcp

# フロントエンドをビルドしてから起動（http://127.0.0.1:8765/ がブラウザで開く）
npm --prefix frontend install
npm --prefix frontend run build
uv run kakehashi serve
```

フロントエンドを開発するときは、`uv run kakehashi serve --no-browser --reload` と `npm --prefix frontend run dev` を並べて起動する（Vite が `/api` を 8765 番へ中継する）。

MCP サーバは `uv run kakehashi mcp`（または `.venv/Scripts/kakehashi.exe mcp`）で起動する。旧版（`python -m src.mcp_server`）と同じ6つのツールを同じ名前・引数で公開しているため、登録先のコマンドを差し替えるだけで移行できる。同人台帳用に `list_doujin` / `get_doujin` / `update_doujin` / `fetch_dlsite` も追加している。

テストは `uv run pytest`。Deck への接続はインメモリの偽実装に置き換えて実行する。
