import json
import threading
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from src.core.config_manager import (
    CONFIG_PATH, MEDIA_FOLDERS, IMAGE_SUFFIXES, VIDEO_SUFFIXES, THUMB_W, THUMB_H,
    discover_systems, resolve_paths, resolve_remote_gamelist_path,
)
from src.core.xml_handler import (
    parse_gamelist_content, get_field, set_field,
)
from src.core.sync_manager import (
    _PARAMIKO_OK, test_connection, transfer_files, pull_files,
    fetch_remote_text, push_gamelist_diff,
)
from src.media.processor import (
    get_rom_stem, find_media_files,
    open_with_default_app, open_fullsize_image,
    open_url_download_dialog, open_cover_crop_dialog,
    open_miximage_dialog,
    open_media_check_window,
)
from src.media.box3d import open_3dbox_dialog
from src.widgets.custom_inputs import DateInput, TagInput


def build_ui(root: tk.Tk, config: dict) -> None:
    root.title("kakehashi")

    # ── トップバー ──────────────────────────────────────────────
    topbar = tk.Frame(root, bg="#f5f5f5")
    topbar.pack(fill="x")
    tk.Label(topbar, text="kakehashi", font=("Arial", 12, "bold"), bg="#f5f5f5").pack(side="left", padx=(12, 4), pady=7)
    tk.Label(topbar, text="ES-DE 日本語メタデータ管理ツール", font=("Arial", 9), fg="gray", bg="#f5f5f5").pack(side="left", pady=7)

    btn_media_check = tk.Button(topbar, text="メディアチェック", font=("Arial", 9), state="disabled")
    btn_media_check.pack(side="right", padx=(4, 8), pady=5)
    btn_sync = tk.Button(topbar, text="同期", font=("Arial", 9))
    btn_sync.pack(side="right", padx=(4, 0), pady=5)
    btn_push = tk.Button(
        topbar, text="プッシュ", font=("Arial", 9, "bold"),
        bg="#0066cc", fg="white", activebackground="#0055aa", relief="flat",
    )
    btn_push.pack(side="right", padx=(4, 0), pady=5)

    systems = discover_systems(config)
    current_system = config.get("system", systems[0] if systems else "")
    system_var = tk.StringVar(value=current_system)
    combo = ttk.Combobox(topbar, textvariable=system_var, values=systems, state="readonly", width=10, font=("Arial", 9))
    combo.pack(side="right", padx=(4, 8), pady=5)
    combo.bind("<<ComboboxSelected>>", lambda e: load_file())
    tk.Label(topbar, text="対象機種:", font=("Arial", 9), bg="#f5f5f5").pack(side="right", pady=5)

    # SSH接続設定・プッシュ設定（「同期」ウィンドウ・load_file()・プッシュ処理のいずれからも参照するため共有する）
    _sync_cfg = config.get("sync", {})
    sync_host_var = tk.StringVar(value=_sync_cfg.get("host", ""))
    sync_port_var = tk.StringVar(value=str(_sync_cfg.get("port", 22)))
    sync_user_var = tk.StringVar(value=_sync_cfg.get("username", "deck"))
    sync_pass_var = tk.StringVar(value=_sync_cfg.get("password", ""))

    _default_media_on = {"covers", "screenshots", "videos"}
    sync_media_type_vars: dict[str, tk.BooleanVar] = {
        folder: tk.BooleanVar(value=folder in _default_media_on) for folder in MEDIA_FOLDERS
    }
    sync_overwrite_var = tk.BooleanVar(value=False)

    # ── ステータス行（メディア自動プル状況・gamelist未同期件数） ──────
    statusbar = tk.Frame(root, bg="#f5f5f5")
    statusbar.pack(fill="x")
    media_status_label = tk.Label(statusbar, text="", font=("Arial", 8), fg="#888888", bg="#f5f5f5", anchor="w")
    media_status_label.pack(side="left", padx=(12, 4), pady=(0, 4))
    gl_status_label = tk.Label(statusbar, text="", font=("Arial", 8), fg="#888888", bg="#f5f5f5", anchor="e")
    gl_status_label.pack(side="right", padx=(4, 12), pady=(0, 4))

    def _refresh_gl_status() -> None:
        n = len(state["dirty"]) + len(state["deleted_paths"])
        if n > 0:
            gl_status_label.config(text=f"gamelist.xml: 未同期の変更 {n}件", fg="#cc6600")
        else:
            gl_status_label.config(text="gamelist.xml: 変更なし", fg="#888888")

    tk.Frame(root, height=1, bg="#cccccc").pack(fill="x")

    # ── メインエリア（左右分割）────────────────────────────────
    paned = tk.PanedWindow(root, orient="horizontal", sashwidth=5, sashrelief="groove", bg="#e0e0e0")
    paned.pack(fill="both", expand=True)

    # ── 左ペイン：ゲーム一覧 ────────────────────────────────
    left_frame = tk.Frame(paned, bg="white")
    paned.add(left_frame, minsize=160, width=240)
    tk.Label(left_frame, text="ゲーム一覧", font=("Arial", 9, "bold"), bg="white", anchor="w").pack(fill="x", padx=8, pady=(8, 4))

    # フィルター（タイトル検索・動画の有無）
    filter_frame = tk.Frame(left_frame, bg="white")
    filter_frame.pack(fill="x", padx=8, pady=(0, 4))

    filter_title_var = tk.StringVar()
    filter_entry = tk.Entry(filter_frame, textvariable=filter_title_var, font=("Arial", 9))
    filter_entry.pack(fill="x")
    filter_title_var.trace_add("write", lambda *_a: apply_filter())

    filter_video_row = tk.Frame(filter_frame, bg="white")
    filter_video_row.pack(fill="x", pady=(4, 0))
    tk.Label(filter_video_row, text="動画:", font=("Arial", 8), bg="white").pack(side="left")
    filter_video_var = tk.StringVar(value="all")
    for _label, _val in (("すべて", "all"), ("あり", "yes"), ("なし", "no")):
        tk.Radiobutton(
            filter_video_row, text=_label, variable=filter_video_var, value=_val,
            font=("Arial", 8), bg="white", command=lambda: apply_filter(),
        ).pack(side="left", padx=(4, 0))

    lb_frame = tk.Frame(left_frame)
    lb_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
    lb_scroll = tk.Scrollbar(lb_frame)
    lb_scroll.pack(side="right", fill="y")
    listbox = tk.Listbox(
        lb_frame, yscrollcommand=lb_scroll.set,
        font=("Arial", 9), selectmode="single",
        activestyle="none", bd=0, highlightthickness=0,
    )
    listbox.pack(side="left", fill="both", expand=True)
    lb_scroll.config(command=listbox.yview)

    # ── 中央ペイン：タブ ──────────────────────────────────────
    mid_frame = tk.Frame(paned)
    paned.add(mid_frame, minsize=400)

    notebook = ttk.Notebook(mid_frame)
    notebook.pack(fill="both", expand=True)

    # ── タブ1: 編集 ────────────────────────────────────────
    tab_edit = tk.Frame(notebook)
    notebook.add(tab_edit, text="編集")

    # 検索バー（下部固定）
    search_bar_frame = tk.Frame(tab_edit, bg="#f5f5f5")
    search_bar_frame.pack(side="bottom", fill="x")
    tk.Frame(tab_edit, height=1, bg="#e0e0e0").pack(side="bottom", fill="x")

    form = tk.Frame(tab_edit)
    form.pack(fill="both", expand=True, padx=8, pady=6)
    form.columnconfigure(1, weight=1)

    # ファイルパス（読み取り専用）
    tk.Label(form, text="ファイル:", font=("Arial", 9, "bold"), anchor="w").grid(row=0, column=0, sticky="w", pady=(4, 2))
    path_label = tk.Label(form, text="", font=("Arial", 9), fg="#666", anchor="w")
    path_label.grid(row=0, column=1, sticky="ew", pady=(4, 2), padx=(4, 0))
    tk.Frame(form, height=1, bg="#eeeeee").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 6))

    # フィールド定義: (key, 表示名, widget種別)
    fields: list[tuple[str, str, str]] = [
        ("name",        "タイトル", "entry"),
        ("desc",        "説明",     "text"),
        ("releasedate", "発売日",   "date"),
        ("developer",   "開発",     "entry"),
        ("publisher",   "発売元",   "entry"),
        ("genre",       "ジャンル", "tags"),
    ]
    field_widgets: dict[str, tk.Widget] = {}

    for r, (key, label_ja, wtype) in enumerate(fields):
        grid_row = r + 3
        tk.Label(form, text=f"{label_ja}:", font=("Arial", 9, "bold"), anchor="nw").grid(
            row=grid_row, column=0, sticky="nw", pady=(2, 2)
        )
        if wtype == "text":
            frame = tk.Frame(form)
            frame.grid(row=grid_row, column=1, sticky="nsew", pady=(2, 2), padx=(4, 0))
            sb = tk.Scrollbar(frame)
            sb.pack(side="right", fill="y")
            widget = tk.Text(frame, height=6, font=("Arial", 9), wrap="word", yscrollcommand=sb.set, undo=True)
            widget.pack(side="left", fill="both", expand=True)
            sb.config(command=widget.yview)
            form.rowconfigure(grid_row, weight=1)
        elif wtype == "date":
            widget = DateInput(form)
            widget.grid(row=grid_row, column=1, sticky="w", pady=(2, 2), padx=(4, 0))
        elif wtype == "tags":
            widget = TagInput(form)
            widget.grid(row=grid_row, column=1, sticky="ew", pady=(2, 2), padx=(4, 0))
        else:  # entry
            widget = tk.Entry(form, font=("Arial", 9))
            widget.grid(row=grid_row, column=1, sticky="ew", pady=(2, 2), padx=(4, 0))
        field_widgets[key] = widget

    # ── タブ2: メディア ────────────────────────────────────
    tab_media = tk.Frame(notebook)
    notebook.add(tab_media, text="メディア")

    media_header_label = tk.Label(
        tab_media, text="ゲームを選択してください",
        font=("Arial", 9), fg="#888", anchor="w",
    )
    media_header_label.pack(fill="x", padx=12, pady=(8, 4))
    tk.Frame(tab_media, height=1, bg="#dddddd").pack(fill="x", padx=8)

    # スクロール可能なメディアテーブル
    _media_table_outer = tk.Frame(tab_media)
    _media_table_outer.pack(fill="both", expand=True, padx=0, pady=(4, 0))

    media_canvas = tk.Canvas(_media_table_outer, highlightthickness=0, bg="white")
    _media_vsb = ttk.Scrollbar(_media_table_outer, orient="vertical", command=media_canvas.yview)
    media_canvas.configure(yscrollcommand=_media_vsb.set)
    _media_vsb.pack(side="right", fill="y")
    media_canvas.pack(side="left", fill="both", expand=True)

    media_scroll_frame = tk.Frame(media_canvas, bg="white")
    _media_canvas_win = media_canvas.create_window((0, 0), window=media_scroll_frame, anchor="nw")

    def _on_media_scroll_frame_configure(e=None) -> None:
        media_canvas.configure(scrollregion=media_canvas.bbox("all"))

    def _on_media_canvas_configure(e) -> None:
        media_canvas.itemconfig(_media_canvas_win, width=e.width)

    media_scroll_frame.bind("<Configure>", _on_media_scroll_frame_configure)
    media_canvas.bind("<Configure>", _on_media_canvas_configure)

    # マウスホイールスクロール（キャンバスにフォーカスがある間のみ）
    def _on_media_mousewheel(e) -> None:
        media_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    media_canvas.bind("<Enter>", lambda e: media_canvas.bind_all("<MouseWheel>", _on_media_mousewheel))
    media_canvas.bind("<Leave>", lambda e: media_canvas.unbind_all("<MouseWheel>"))

    # ── 「同期」ウィンドウ（システム全体が対象のため、選択中ゲームのタブ群とは別の独立ウィンドウにする）
    def open_sync_window() -> None:
        win = tk.Toplevel(root)
        win.title("同期")
        win.geometry("900x650")
        win.minsize(700, 480)

        if not _PARAMIKO_OK:
            # paramiko 未インストール時の案内
            _no_param_frame = tk.Frame(win)
            _no_param_frame.pack(expand=True)
            tk.Label(
                _no_param_frame,
                text="⚠  paramiko がインストールされていません",
                font=("Arial", 11, "bold"), fg="#cc6600",
            ).pack(pady=(0, 8))
            tk.Label(
                _no_param_frame,
                text="以下のコマンドを実行してから再起動してください:",
                font=("Arial", 9), fg="#444",
            ).pack()
            tk.Label(
                _no_param_frame,
                text="    pip install paramiko    (または  uv sync)",
                font=("Courier", 10), fg="#003399", bg="#f0f4ff",
                relief="sunken", padx=12, pady=6,
            ).pack(pady=(6, 0))
            return

        content = tk.Frame(win)
        content.pack(fill="both", expand=True, padx=14, pady=12)

        # ── 接続設定 ─────────────────────────────────────────
        # sync_host_var等はbuild_ui()冒頭で定義済み（load_file()と共有するため）
        tk.Label(content, text="接続設定 (Steam Deck)", font=("Arial", 9, "bold"), anchor="w").pack(fill="x")
        tk.Frame(content, height=1, bg="#eeeeee").pack(fill="x", pady=(4, 8))

        conn_grid = tk.Frame(content)
        conn_grid.pack(fill="x")
        conn_grid.columnconfigure(1, weight=1)
        conn_grid.columnconfigure(3, weight=1)

        tk.Label(conn_grid, text="ホスト (IP):", font=("Arial", 9), anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        tk.Entry(conn_grid, textvariable=sync_host_var, font=("Arial", 9)).grid(row=0, column=1, sticky="ew", padx=(6, 20))
        tk.Label(conn_grid, text="ポート:", font=("Arial", 9), anchor="w").grid(row=0, column=2, sticky="w")
        tk.Entry(conn_grid, textvariable=sync_port_var, font=("Arial", 9), width=8).grid(row=0, column=3, sticky="w", padx=(6, 0))

        tk.Label(conn_grid, text="ユーザー名:", font=("Arial", 9), anchor="w").grid(row=1, column=0, sticky="w", pady=2)
        tk.Entry(conn_grid, textvariable=sync_user_var, font=("Arial", 9)).grid(row=1, column=1, sticky="ew", padx=(6, 20))
        tk.Label(conn_grid, text="パスワード:", font=("Arial", 9), anchor="w").grid(row=1, column=2, sticky="w")
        tk.Entry(conn_grid, textvariable=sync_pass_var, show="*", font=("Arial", 9)).grid(row=1, column=3, sticky="ew", padx=(6, 0))

        def _save_sync_cfg() -> None:
            config.setdefault("sync", {})
            config["sync"].update({
                "host":     sync_host_var.get(),
                "port":     int(sync_port_var.get() or 22),
                "username": sync_user_var.get(),
                "password": sync_pass_var.get(),
            })
            try:
                CONFIG_PATH.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as e:
                messagebox.showerror("保存エラー", str(e))

        def _test_connection() -> None:
            host = sync_host_var.get().strip()
            if not host:
                sync_conn_label.config(text="✗  ホストを入力してください", fg="#cc0000")
                return
            sync_conn_label.config(text="接続テスト中...", fg="#666666")
            win.update_idletasks()
            try:
                test_connection(
                    host=host,
                    port=int(sync_port_var.get() or 22),
                    username=sync_user_var.get(),
                    password=sync_pass_var.get(),
                )
                sync_conn_label.config(text="✓  接続成功 — 設定を保存しました", fg="#009900")
                _save_sync_cfg()
            except Exception as _ex:
                sync_conn_label.config(text=f"✗  {_ex}", fg="#cc0000")

        conn_status_row = tk.Frame(content)
        conn_status_row.pack(fill="x", pady=(8, 0))
        tk.Button(
            conn_status_row, text="接続テスト & 保存", font=("Arial", 9),
            command=_test_connection,
        ).pack(side="left")
        sync_conn_label = tk.Label(conn_status_row, text="", font=("Arial", 9))
        sync_conn_label.pack(side="left", padx=(12, 0))

        tk.Frame(content, height=1, bg="#eeeeee").pack(fill="x", pady=(12, 8))

        # ── 対象メディアフォルダ（プッシュ時） ──────────────────
        tk.Label(content, text="対象メディアフォルダ（プッシュ時）", font=("Arial", 9, "bold"), anchor="w").pack(fill="x")

        media_row = tk.Frame(content)
        media_row.pack(fill="x", pady=(6, 0))
        media_select_all_btn = tk.Button(media_row, text="すべて選択", font=("Arial", 8))
        media_select_none_btn = tk.Button(media_row, text="すべて解除", font=("Arial", 8))
        media_select_none_btn.pack(side="right")
        media_select_all_btn.pack(side="right", padx=(0, 6))

        # メディアタイプ チェックボックス群（sync_media_type_varsはbuild_ui()冒頭で定義済み）
        _mt_frame = tk.Frame(content)
        _mt_frame.pack(fill="x", pady=(4, 0))
        for _mi, _mf in enumerate(MEDIA_FOLDERS):
            tk.Checkbutton(
                _mt_frame, text=_mf, variable=sync_media_type_vars[_mf], font=("Arial", 9),
            ).grid(row=_mi // 4, column=_mi % 4, sticky="w", padx=(0, 20), pady=2)

        def _set_all_media(value: bool) -> None:
            for _v in sync_media_type_vars.values():
                _v.set(value)

        media_select_all_btn.config(command=lambda: _set_all_media(True))
        media_select_none_btn.config(command=lambda: _set_all_media(False))

        overwrite_row = tk.Frame(content)
        overwrite_row.pack(fill="x", pady=(8, 0))
        tk.Label(overwrite_row, text="既存ファイル:", font=("Arial", 9), anchor="w").pack(side="left")
        tk.Radiobutton(
            overwrite_row, text="スキップ（差分のみ転送）",
            variable=sync_overwrite_var, value=False, font=("Arial", 9),
        ).pack(side="left", padx=(8, 0))
        tk.Radiobutton(
            overwrite_row, text="上書き",
            variable=sync_overwrite_var, value=True, font=("Arial", 9),
        ).pack(side="left", padx=(16, 0))

    btn_sync.config(command=open_sync_window)

    _media_img_refs: list = []  # PhotoImage のガベージコレクション防止

    # ── ロジック ─────────────────────────────────────────────
    state: dict = {
        "root_elem": None, "games": [], "decl": "", "selected": -1,
        "dirty": {}, "deleted_paths": set(), "visible": [],
    }

    def _display_name(game: ET.Element) -> str:
        return get_field(game, "name") or get_field(game, "path") or "(不明)"

    def render_listbox() -> None:
        """state["visible"]（表示対象のgamesインデックス列）に基づき一覧を再描画する。"""
        listbox.delete(0, "end")
        for gi in state["visible"]:
            listbox.insert("end", _display_name(state["games"][gi]))

    def apply_filter() -> None:
        query = filter_title_var.get().strip().lower()
        video_mode = filter_video_var.get()

        video_stems: set[str] = set()
        if video_mode != "all":
            videos_dir = Path(resolve_paths(config, system_var.get())["media_path"]) / "videos"
            if videos_dir.is_dir():
                video_stems = {p.stem for p in videos_dir.iterdir() if p.is_file()}

        visible = []
        for i, game in enumerate(state["games"]):
            if query and query not in _display_name(game).lower():
                continue
            if video_mode != "all":
                has_video = get_rom_stem(get_field(game, "path")) in video_stems
                if video_mode == "yes" and not has_video:
                    continue
                if video_mode == "no" and has_video:
                    continue
            visible.append(i)
        state["visible"] = visible
        render_listbox()

    def update_media_tab(game: ET.Element | None) -> None:
        """メディアタブをサムネイル付きテーブルで更新する。"""
        _media_img_refs.clear()
        for w in media_scroll_frame.winfo_children():
            w.destroy()

        if game is None:
            media_header_label.config(text="ゲームを選択してください", fg="#888", font=("Arial", 9))
            return

        title = get_field(game, "name") or get_field(game, "path") or "(不明)"
        media_header_label.config(text=title, fg="black", font=("Arial", 9, "bold"))

        path_val = get_field(game, "path")
        if not path_val:
            return

        stem       = get_rom_stem(path_val)
        media_path = resolve_paths(config, system_var.get())["media_path"]
        file_map   = find_media_files(media_path, stem)

        def _do_file_select(f: str) -> None:
            filetypes = [
                ("画像ファイル", " ".join(f"*{s}" for s in sorted(IMAGE_SUFFIXES))),
                ("動画ファイル", " ".join(f"*{s}" for s in sorted(VIDEO_SUFFIXES))),
                ("PDFファイル", "*.pdf"),
                ("すべてのファイル", "*.*"),
            ]
            src = filedialog.askopenfilename(title=f"{f} — ファイル選択", filetypes=filetypes)
            if not src:
                return
            src_path = Path(src)
            dest = Path(media_path) / f / f"{stem}{src_path.suffix.lower()}"
            if not messagebox.askokcancel("登録確認", f"保存先:\n{dest}\n\n登録しますか？"):
                return
            try:
                (Path(media_path) / f).mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(src_path, dest)
            except Exception as e:
                messagebox.showerror("コピーエラー", str(e))
                return
            update_media_tab(game)

        def _do_delete(fp: Path) -> None:
            if not messagebox.askokcancel("削除確認", f"削除しますか？\n{fp}"):
                return
            try:
                fp.unlink()
            except Exception as e:
                messagebox.showerror("削除エラー", str(e))
                return
            update_media_tab(game)

        for row_i, folder in enumerate(MEDIA_FOLDERS):
            file_path = file_map[folder]
            bg = "white" if row_i % 2 == 0 else "#f5f5f5"

            row = tk.Frame(media_scroll_frame, bg=bg)
            row.pack(fill="x")

            # フォルダ名列
            tk.Label(
                row, text=folder, font=("Arial", 9), anchor="w",
                width=14, bg=bg, fg="#444",
            ).pack(side="left", padx=(10, 4), pady=6)

            if file_path is None:
                tk.Label(row, text="-", font=("Arial", 10, "bold"), fg="#cc0000", bg=bg).pack(
                    side="left", padx=4, pady=6,
                )
                btn_f = tk.Frame(row, bg=bg)
                btn_f.pack(side="left", padx=(4, 0))
                tk.Button(
                    btn_f, text="URLからDL", font=("Arial", 8),
                    command=lambda f=folder: open_url_download_dialog(
                        media_scroll_frame, f, stem, media_path, title,
                        lambda: update_media_tab(game)
                    ),
                ).pack(side="left", padx=2)
                tk.Button(
                    btn_f, text="ファイル選択...", font=("Arial", 8),
                    command=lambda f=folder: _do_file_select(f),
                ).pack(side="left", padx=2)
                tk.Button(
                    btn_f, text="検索", font=("Arial", 8),
                    command=lambda f=folder: webbrowser.open(
                        "https://www.google.com/search?tbm=isch&q="
                        + urllib.parse.quote(f"{title} {f}")
                    ),
                ).pack(side="left", padx=2)
                if folder == "marquees" and file_map.get("covers") is not None:
                    tk.Button(
                        btn_f, text="coverから切り出し", font=("Arial", 8),
                        command=lambda: open_cover_crop_dialog(
                            media_scroll_frame, file_map["covers"],
                            stem, media_path, title,
                            lambda: update_media_tab(game),
                        ),
                    ).pack(side="left", padx=2)
                if folder == "3dboxes" and file_map.get("covers") is not None:
                    tk.Button(
                        btn_f, text="coverから3Dbox生成", font=("Arial", 8),
                        command=lambda: open_3dbox_dialog(
                            media_scroll_frame, file_map["covers"],
                            stem, media_path, title, system_var.get(),
                            lambda: update_media_tab(game),
                        ),
                    ).pack(side="left", padx=2)
                if folder == "miximages" and file_map.get("screenshots") is not None:
                    tk.Button(
                        btn_f, text="miximage生成", font=("Arial", 8),
                        command=lambda: open_miximage_dialog(
                            media_scroll_frame, stem, media_path, title,
                            lambda: update_media_tab(game),
                        ),
                    ).pack(side="left", padx=2)
                continue

            tk.Button(
                row, text="削除", font=("Arial", 8), fg="#cc0000",
                command=lambda fp=file_path: _do_delete(fp),
            ).pack(side="right", padx=(4, 8))

            suffix = file_path.suffix.lower()

            if suffix in IMAGE_SUFFIXES and _PIL_OK:
                # 画像サムネイル（クリックでフルサイズ表示）
                try:
                    img = Image.open(file_path)
                    img.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    _media_img_refs.append(photo)
                    lbl_img = tk.Label(row, image=photo, bg=bg, cursor="hand2")
                    lbl_img.pack(side="left", padx=(4, 8), pady=4)
                    lbl_img.bind(
                        "<Button-1>",
                        lambda e, fp=file_path, fn=folder: open_fullsize_image(row, fp, fn),
                    )
                except Exception:
                    tk.Label(row, text="(読込失敗)", font=("Arial", 8), fg="#888", bg=bg).pack(
                        side="left", padx=4, pady=6,
                    )
            elif suffix in IMAGE_SUFFIXES:
                # PIL未使用時は○のみ
                tk.Label(row, text="○ (画像)", font=("Arial", 9), fg="#007700", bg=bg).pack(
                    side="left", padx=4, pady=6,
                )
            elif suffix in VIDEO_SUFFIXES:
                lbl_v = tk.Label(row, text="[動画] ▶", font=("Arial", 9), fg="#007700", bg=bg, cursor="hand2")
                lbl_v.pack(side="left", padx=4, pady=6)
                lbl_v.bind("<Button-1>", lambda e, fp=file_path: open_with_default_app(fp))
            elif suffix == ".pdf":
                lbl_p = tk.Label(row, text="[PDF] ▶", font=("Arial", 9), fg="#0055cc", bg=bg, cursor="hand2")
                lbl_p.pack(side="left", padx=4, pady=6)
                lbl_p.bind("<Button-1>", lambda e, fp=file_path: open_with_default_app(fp))
            else:
                tk.Label(row, text="○", font=("Arial", 10, "bold"), fg="#007700", bg=bg).pack(
                    side="left", padx=4, pady=6,
                )

        _on_media_scroll_frame_configure()

    def fill_form(game: ET.Element) -> None:
        path_label.config(text=get_field(game, "path"))
        for key, widget in field_widgets.items():
            val = get_field(game, key)
            if isinstance(widget, TagInput):
                widget.set_tags([t.strip() for t in val.split(",") if t.strip()])
            elif isinstance(widget, DateInput):
                widget.set_date_str(val)
            elif isinstance(widget, tk.Text):
                widget.delete("1.0", "end")
                widget.insert("1.0", val)
            else:
                widget.delete(0, "end")
                widget.insert(0, val)
        update_media_tab(game)

    def flush_form(idx: int) -> None:
        if idx < 0 or idx >= len(state["games"]):
            return
        game = state["games"][idx]
        path_val = get_field(game, "path")
        for key, widget in field_widgets.items():
            if isinstance(widget, TagInput):
                val = ", ".join(widget.get_tags())
            elif isinstance(widget, DateInput):
                val = widget.get_date_str()
            elif isinstance(widget, tk.Text):
                val = widget.get("1.0", "end-1c").strip()
            else:
                val = widget.get().strip()
            if val != get_field(game, key) and path_val:
                state["dirty"].setdefault(path_val, {})[key] = val
            set_field(game, key, val)
        try:
            row = state["visible"].index(idx)
        except ValueError:
            row = None
        if row is not None:
            listbox.delete(row)
            listbox.insert(row, _display_name(game))
        _refresh_gl_status()

    def on_select(event=None) -> None:
        sel = listbox.curselection()
        if not sel:
            return
        idx = state["visible"][sel[0]]
        if idx == state["selected"]:
            return
        flush_form(state["selected"])
        state["selected"] = idx
        fill_form(state["games"][idx])

    listbox.bind("<<ListboxSelect>>", on_select)

    # ── 検索バー ────────────────────────────────────────────
    tk.Label(search_bar_frame, text="Web検索:", font=("Arial", 9, "bold"), bg="#f5f5f5").pack(
        side="left", padx=(10, 6), pady=6
    )

    _search_sites = [
        ("DuckDuckGo", "https://duckduckgo.com/?q={query}"),
        ("Google",     "https://www.google.com/search?q={query}"),
        ("Wikipedia",  "https://ja.wikipedia.org/w/index.php?search={query}"),
        ("Famitsu",    "https://www.famitsu.com/search/?q={query}"),
    ]

    def open_search(url_template: str) -> None:
        name_widget = field_widgets.get("name")
        name = name_widget.get().strip() if isinstance(name_widget, tk.Entry) else ""
        if name:
            query = urllib.parse.quote(f"{name} {system_var.get()}")
            webbrowser.open(url_template.format(query=query))

    for _site_name, _tmpl in _search_sites:
        tk.Button(
            search_bar_frame, text=_site_name, font=("Arial", 9),
            relief="groove", padx=6, pady=2, cursor="hand2", bg="#f5f5f5",
            command=lambda t=_tmpl: open_search(t),
        ).pack(side="left", padx=(0, 4), pady=5)

    tk.Frame(search_bar_frame, width=1, bg="#cccccc").pack(side="left", fill="y", padx=(4, 8), pady=6)
    tk.Label(search_bar_frame, text="翻訳:", font=("Arial", 9, "bold"), bg="#f5f5f5").pack(side="left", padx=(0, 6))

    _translate_sites = [
        ("DeepL",      "https://www.deepl.com/translator#en/ja/{text}"),
        ("Google翻訳", "https://translate.google.com/?sl=auto&tl=ja&text={text}&op=translate"),
    ]

    def open_translate(url_template: str) -> None:
        desc_widget = field_widgets.get("desc")
        text = desc_widget.get("1.0", "end-1c").strip() if isinstance(desc_widget, tk.Text) else ""
        if text:
            webbrowser.open(url_template.format(text=urllib.parse.quote(text)))

    for _site_name, _tmpl in _translate_sites:
        tk.Button(
            search_bar_frame, text=_site_name, font=("Arial", 9),
            relief="groove", padx=6, pady=2, cursor="hand2", bg="#f5f5f5",
            command=lambda t=_tmpl: open_translate(t),
        ).pack(side="left", padx=(0, 4), pady=5)

    def _auto_pull_media() -> None:
        """起動時・機種切替時に、メディア全フォルダをバックグラウンドで自動プルする。"""
        system = system_var.get()
        local_paths = resolve_paths(config, system)
        sd_cfg = config.get("steam_deck", {})
        remote_media_base = sd_cfg.get("media_base", "/home/deck/.emulationstation/downloaded_media")
        local_media_sys = Path(local_paths["media_path"])
        dir_mappings = [
            (f"{remote_media_base}/{system}/{folder}", local_media_sys / folder)
            for folder in MEDIA_FOLDERS
        ]
        host = sync_host_var.get().strip()
        port = int(sync_port_var.get() or 22)
        username = sync_user_var.get()
        password = sync_pass_var.get()

        media_status_label.config(text="🔄 メディア取得中...", fg="#666666")

        def _do() -> None:
            try:
                ok, skipped, errors = pull_files(
                    host=host, port=port, username=username, password=password,
                    file_tasks=[], dir_mappings=dir_mappings, overwrite=False,
                    on_log=print, on_progress=lambda v: None,
                )
                if errors == 0:
                    text, fg = f"✓ メディア取得済み（{ok}件 / スキップ{skipped}件）", "#009900"
                else:
                    text, fg = f"⚠ メディア取得エラー {errors}件", "#cc0000"
            except Exception as ex:
                text, fg = f"⚠ メディア取得失敗: {ex}", "#cc0000"
            root.after(0, lambda: media_status_label.config(text=text, fg=fg))

        threading.Thread(target=_do, daemon=True).start()

    def load_file() -> None:
        if not _PARAMIKO_OK:
            messagebox.showwarning(
                "paramiko未インストール",
                "gamelist.xmlの編集にはSteam DeckへのSSH接続が必要です。\n"
                "pip install paramiko を実行してください。",
            )
            return
        host = sync_host_var.get().strip()
        if not host:
            messagebox.showwarning(
                "読み込みエラー",
                "「同期」タブでSteam DeckのホストIPを設定してください。",
            )
            return
        remote_path = resolve_remote_gamelist_path(config, system_var.get())
        try:
            content = fetch_remote_text(
                host=host,
                port=int(sync_port_var.get() or 22),
                username=sync_user_var.get(),
                password=sync_pass_var.get(),
                remote_path=remote_path,
            )
        except Exception as e:
            messagebox.showerror("読み込みエラー", f"Steam Deckから取得できませんでした:\n{e}")
            return
        try:
            root_elem, games, decl = parse_gamelist_content(content)
        except ET.ParseError as e:
            messagebox.showerror("XMLエラー", f"XMLのパースに失敗しました:\n{e}")
            return
        state.update({
            "root_elem": root_elem, "games": games, "decl": decl, "selected": -1,
            "dirty": {}, "deleted_paths": set(), "visible": list(range(len(games))),
        })
        filter_title_var.set("")
        filter_video_var.set("all")
        apply_filter()
        path_label.config(text="")
        for widget in field_widgets.values():
            if isinstance(widget, tk.Text):
                widget.delete("1.0", "end")
            elif isinstance(widget, TagInput):
                widget.set_tags([])
            elif isinstance(widget, DateInput):
                widget.set_date_str("")
            else:
                widget.delete(0, "end")
        update_media_tab(None)
        btn_media_check.config(state="normal")
        _refresh_gl_status()
        _auto_pull_media()

    def _do_push() -> None:
        if not _PARAMIKO_OK:
            messagebox.showwarning(
                "paramiko未インストール",
                "プッシュにはSteam DeckへのSSH接続が必要です。\npip install paramiko を実行してください。",
            )
            return
        host = sync_host_var.get().strip()
        if not host:
            messagebox.showwarning("設定エラー", "「同期」画面でホスト（Steam DeckのIPアドレス）を設定してください。")
            return

        flush_form(state["selected"])  # 現在編集中の内容を確定してからプッシュする

        btn_push.config(state="disabled", text="プッシュ中...")

        system = system_var.get()
        local_paths = resolve_paths(config, system)
        sd_cfg = config.get("steam_deck", {})
        remote_media_base = sd_cfg.get("media_base", "/home/deck/.emulationstation/downloaded_media")
        remote_gl = resolve_remote_gamelist_path(config, system)

        tasks: list[tuple[Path, str]] = []
        local_media_sys = Path(local_paths["media_path"])
        for folder, fvar in sync_media_type_vars.items():
            if not fvar.get():
                continue
            local_folder = local_media_sys / folder
            if not local_folder.is_dir():
                continue
            for _f in sorted(local_folder.iterdir()):
                if _f.is_file():
                    tasks.append((_f, f"{remote_media_base}/{system}/{folder}/{_f.name}"))

        overwrite = sync_overwrite_var.get()
        port = int(sync_port_var.get() or 22)
        username = sync_user_var.get()
        password = sync_pass_var.get()

        def _do() -> None:
            gl_summary = ""
            try:
                if state["dirty"] or state["deleted_paths"]:
                    applied, deleted = push_gamelist_diff(
                        host=host, port=port, username=username, password=password,
                        remote_path=remote_gl,
                        diffs=state["dirty"], deleted_paths=state["deleted_paths"],
                        backup_max=config.get("backup_max", 5), on_log=print,
                    )
                    state["dirty"].clear()
                    state["deleted_paths"].clear()
                    root.after(0, _refresh_gl_status)
                    gl_summary = f"gamelist: 反映{applied}件 / 削除{deleted}件\n"

                ok, skipped, errors = transfer_files(
                    host=host, port=port, username=username, password=password,
                    tasks=tasks, overwrite=overwrite, on_log=print, on_progress=lambda v: None,
                )
                summary = f"{gl_summary}メディア: 転送{ok} / スキップ{skipped} / エラー{errors}"
                if errors == 0:
                    root.after(0, lambda: messagebox.showinfo("プッシュ完了", summary))
                else:
                    root.after(0, lambda: messagebox.showwarning("プッシュ完了（一部エラーあり）", summary))
            except Exception as ex:
                root.after(0, lambda: messagebox.showerror("プッシュエラー", str(ex)))
            finally:
                root.after(0, lambda: btn_push.config(state="normal", text="プッシュ"))

        threading.Thread(target=_do, daemon=True).start()

    btn_media_check.config(
        command=lambda: open_media_check_window(root, config, system_var.get(), state["games"])
    )
    btn_push.config(command=_do_push)
    load_file()
