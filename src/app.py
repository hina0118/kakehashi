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
    detect_environment, discover_systems, resolve_paths,
)
from src.core.xml_handler import parse_gamelist, serialize_gamelist, save_gamelist_file
from src.core.sync_manager import _PARAMIKO_OK, test_connection, transfer_files, pull_files
from src.media.processor import (
    get_rom_stem, find_media_files,
    open_with_default_app, open_fullsize_image,
    open_url_download_dialog, open_cover_crop_dialog, open_media_check_window,
)
from src.widgets.custom_inputs import DateInput, TagInput


def build_ui(root: tk.Tk, config: dict) -> None:
    root.title("kakehashi")

    # ── トップバー ──────────────────────────────────────────────
    topbar = tk.Frame(root, bg="#f5f5f5")
    topbar.pack(fill="x")
    tk.Label(topbar, text="kakehashi", font=("Arial", 12, "bold"), bg="#f5f5f5").pack(side="left", padx=(12, 4), pady=7)
    tk.Label(topbar, text="ES-DE 日本語メタデータ管理ツール", font=("Arial", 9), fg="gray", bg="#f5f5f5").pack(side="left", pady=7)

    btn_save_file = tk.Button(topbar, text="保存", width=8, font=("Arial", 9))
    btn_save_file.pack(side="right", padx=(4, 12), pady=5)
    btn_load_file = tk.Button(topbar, text="読み込み", width=8, font=("Arial", 9))
    btn_load_file.pack(side="right", pady=5)
    btn_media_check = tk.Button(topbar, text="メディアチェック", font=("Arial", 9), state="disabled")
    btn_media_check.pack(side="right", padx=(4, 8), pady=5)

    systems = discover_systems(config)
    current_system = config.get("system", systems[0] if systems else "")
    system_var = tk.StringVar(value=current_system)
    combo = ttk.Combobox(topbar, textvariable=system_var, values=systems, state="readonly", width=10, font=("Arial", 9))
    combo.pack(side="right", padx=(4, 8), pady=5)
    tk.Label(topbar, text="対象機種:", font=("Arial", 9), bg="#f5f5f5").pack(side="right", pady=5)

    env = detect_environment(config)
    tk.Label(topbar, text=f"環境: {env}", font=("Arial", 9), fg="#666", bg="#f5f5f5").pack(side="right", padx=(12, 4), pady=5)

    tk.Frame(root, height=1, bg="#cccccc").pack(fill="x")

    # ── メインエリア（左右分割）────────────────────────────────
    paned = tk.PanedWindow(root, orient="horizontal", sashwidth=5, sashrelief="groove", bg="#e0e0e0")
    paned.pack(fill="both", expand=True)

    # ── 左ペイン：ゲーム一覧 ────────────────────────────────
    left_frame = tk.Frame(paned, bg="white")
    paned.add(left_frame, minsize=160, width=240)
    tk.Label(left_frame, text="ゲーム一覧", font=("Arial", 9, "bold"), bg="white", anchor="w").pack(fill="x", padx=8, pady=(8, 4))
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

    # 削除バナー（ROMが存在しない場合のみ表示）
    del_banner = tk.Frame(form, bg="#fff0f0")
    del_banner.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 4))
    del_banner.grid_remove()
    tk.Label(del_banner, text="⚠ ROMファイルが見つかりません",
             font=("Arial", 9), fg="#cc0000", bg="#fff0f0").pack(side="left", padx=(6, 8), pady=4)
    btn_delete_entry = tk.Button(
        del_banner, text="エントリを削除", font=("Arial", 9),
        fg="white", bg="#cc0000", activebackground="#aa0000",
        relief="flat", padx=8, pady=2, cursor="hand2",
    )
    btn_delete_entry.pack(side="right", padx=6, pady=3)

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

    # ── タブ3: 同期 ─────────────────────────────────────────────
    tab_sync = tk.Frame(notebook)
    notebook.add(tab_sync, text="同期")

    if not _PARAMIKO_OK:
        # paramiko 未インストール時の案内
        _no_param_frame = tk.Frame(tab_sync)
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
    else:
        _sync_cfg = config.get("sync", {})

        # ── 接続設定フレーム ────────────────────────────────────
        conn_lf = tk.LabelFrame(
            tab_sync, text="SSH接続設定 (Steam Deck)",
            font=("Arial", 9, "bold"), padx=8, pady=6,
        )
        conn_lf.pack(fill="x", padx=8, pady=(8, 4))

        _r0 = tk.Frame(conn_lf)
        _r0.pack(fill="x", pady=2)
        tk.Label(_r0, text="ホスト (IP):", font=("Arial", 9), width=12, anchor="w").pack(side="left")
        sync_host_var = tk.StringVar(value=_sync_cfg.get("host", ""))
        tk.Entry(_r0, textvariable=sync_host_var, font=("Arial", 9), width=20).pack(side="left", padx=(0, 16))
        tk.Label(_r0, text="ポート:", font=("Arial", 9)).pack(side="left")
        sync_port_var = tk.StringVar(value=str(_sync_cfg.get("port", 22)))
        tk.Entry(_r0, textvariable=sync_port_var, font=("Arial", 9), width=6).pack(side="left", padx=(4, 0))

        _r1 = tk.Frame(conn_lf)
        _r1.pack(fill="x", pady=2)
        tk.Label(_r1, text="ユーザー名:", font=("Arial", 9), width=12, anchor="w").pack(side="left")
        sync_user_var = tk.StringVar(value=_sync_cfg.get("username", "deck"))
        tk.Entry(_r1, textvariable=sync_user_var, font=("Arial", 9), width=16).pack(side="left", padx=(0, 16))
        tk.Label(_r1, text="パスワード:", font=("Arial", 9)).pack(side="left")
        sync_pass_var = tk.StringVar(value=_sync_cfg.get("password", ""))
        tk.Entry(_r1, textvariable=sync_pass_var, show="*", font=("Arial", 9), width=16).pack(side="left", padx=(4, 0))

        sync_conn_label = tk.Label(conn_lf, text="", font=("Arial", 9))
        sync_conn_label.pack(anchor="w", pady=(4, 0))

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
            tab_sync.update_idletasks()
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

        _btn_row = tk.Frame(conn_lf)
        _btn_row.pack(fill="x", pady=(6, 0))
        tk.Button(
            _btn_row, text="接続テスト & 保存", font=("Arial", 9),
            command=_test_connection,
        ).pack(side="left")

        # ── 転送設定フレーム ────────────────────────────────────
        xfer_lf = tk.LabelFrame(
            tab_sync, text="転送設定",
            font=("Arial", 9, "bold"), padx=8, pady=6,
        )
        xfer_lf.pack(fill="x", padx=8, pady=4)

        _x0 = tk.Frame(xfer_lf)
        _x0.pack(fill="x", pady=2)
        tk.Label(_x0, text="転送内容:", font=("Arial", 9), width=12, anchor="w").pack(side="left")
        sync_gl_var = tk.BooleanVar(value=True)
        tk.Checkbutton(_x0, text="gamelist.xml", variable=sync_gl_var, font=("Arial", 9)).pack(side="left")
        sync_media_chk_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            _x0, text="メディア", variable=sync_media_chk_var, font=("Arial", 9),
        ).pack(side="left", padx=(16, 0))

        # メディアタイプ チェックボックス群
        _mt_frame = tk.Frame(xfer_lf)
        _mt_frame.pack(fill="x", pady=(2, 0), padx=(24, 0))
        _default_on = {"covers", "screenshots", "videos"}
        sync_media_type_vars: dict[str, tk.BooleanVar] = {}
        for _mi, _mf in enumerate(MEDIA_FOLDERS):
            _mv = tk.BooleanVar(value=_mf in _default_on)
            _mcb = tk.Checkbutton(_mt_frame, text=_mf, variable=_mv, font=("Arial", 8))
            _mcb.grid(row=_mi // 4, column=_mi % 4, sticky="w", padx=2)
            sync_media_type_vars[_mf] = _mv

        def _toggle_media_cbs(*_) -> None:
            _st = "normal" if sync_media_chk_var.get() else "disabled"
            for _w in _mt_frame.winfo_children():
                _w.config(state=_st)

        sync_media_chk_var.trace_add("write", _toggle_media_cbs)

        _x1 = tk.Frame(xfer_lf)
        _x1.pack(fill="x", pady=(8, 2))
        tk.Label(_x1, text="既存ファイル:", font=("Arial", 9), width=12, anchor="w").pack(side="left")
        sync_overwrite_var = tk.BooleanVar(value=False)
        tk.Radiobutton(
            _x1, text="スキップ（差分のみ転送）",
            variable=sync_overwrite_var, value=False, font=("Arial", 9),
        ).pack(side="left")
        tk.Radiobutton(
            _x1, text="上書き",
            variable=sync_overwrite_var, value=True, font=("Arial", 9),
        ).pack(side="left", padx=(16, 0))

        # ── 実行コントロール ────────────────────────────────────
        _ctrl = tk.Frame(tab_sync)
        _ctrl.pack(fill="x", padx=8, pady=6)

        sync_progress = ttk.Progressbar(_ctrl, mode="determinate", length=200)
        sync_progress.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_sync_run = tk.Button(
            _ctrl, text="→ プッシュ", font=("Arial", 9, "bold"),
            bg="#0066cc", fg="white", activebackground="#0055aa",
            relief="flat", padx=14, pady=3,
        )
        btn_sync_run.pack(side="right")

        btn_pull_run = tk.Button(
            _ctrl, text="← プル", font=("Arial", 9, "bold"),
            bg="#4a8f3f", fg="white", activebackground="#3a7030",
            relief="flat", padx=14, pady=3,
        )
        btn_pull_run.pack(side="right", padx=(0, 6))

        # ── ログエリア ──────────────────────────────────────────
        _log_lf = tk.LabelFrame(tab_sync, text="ログ", font=("Arial", 9, "bold"), padx=4, pady=4)
        _log_lf.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        _log_sb = tk.Scrollbar(_log_lf)
        _log_sb.pack(side="right", fill="y")
        sync_log = tk.Text(
            _log_lf, font=("Courier", 8),
            yscrollcommand=_log_sb.set, state="disabled", wrap="none",
        )
        sync_log.pack(fill="both", expand=True)
        _log_sb.config(command=sync_log.yview)

        def _log(msg: str) -> None:
            sync_log.config(state="normal")
            sync_log.insert("end", msg + "\n")
            sync_log.see("end")
            sync_log.config(state="disabled")

        def _clear_log() -> None:
            sync_log.config(state="normal")
            sync_log.delete("1.0", "end")
            sync_log.config(state="disabled")

        def _run_sync() -> None:
            if not sync_gl_var.get() and not sync_media_chk_var.get():
                messagebox.showwarning("設定エラー", "転送内容を1つ以上選択してください。")
                return
            host = sync_host_var.get().strip()
            if not host:
                messagebox.showwarning("設定エラー", "ホスト（Steam DeckのIPアドレス）を入力してください。")
                return

            btn_sync_run.config(state="disabled", text="転送中...")
            _clear_log()
            sync_progress["value"] = 0

            system       = system_var.get()
            local_paths  = resolve_paths(config, system)
            sd_cfg       = config.get("steam_deck", {})
            remote_gl_base    = sd_cfg.get("gamelist_base", "/home/deck/.emulationstation/gamelists")
            remote_media_base = sd_cfg.get("media_base",    "/home/deck/.emulationstation/downloaded_media")

            # 転送タスクリスト: (local_path, remote_path)
            tasks: list[tuple[Path, str]] = []

            if sync_gl_var.get():
                gl_local  = Path(local_paths["gamelist_path"])
                gl_remote = f"{remote_gl_base}/{system}/gamelist.xml"
                if gl_local.exists():
                    tasks.append((gl_local, gl_remote))
                else:
                    _log(f"  [スキップ] gamelist.xml が見つかりません: {gl_local}")

            if sync_media_chk_var.get():
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

            def _transfer() -> None:
                try:
                    ok, skipped, errors = transfer_files(
                        host=host,
                        port=int(sync_port_var.get() or 22),
                        username=sync_user_var.get(),
                        password=sync_pass_var.get(),
                        tasks=tasks,
                        overwrite=overwrite,
                        on_log=_log,
                        on_progress=lambda v: tab_sync.after(
                            0, lambda _v=v: sync_progress.__setitem__("value", _v)
                        ),
                    )
                    summary = f"\n[完了] 転送: {ok} / スキップ: {skipped} / エラー: {errors}"
                    _log(summary)

                    if errors == 0:
                        tab_sync.after(0, lambda: messagebox.showinfo(
                            "転送完了",
                            f"転送が完了しました。\n転送: {ok} ファイル / スキップ: {skipped} ファイル",
                        ))
                    else:
                        tab_sync.after(0, lambda: messagebox.showwarning(
                            "転送完了（一部エラーあり）",
                            f"転送は完了しましたが一部エラーがあります。\n転送: {ok} / スキップ: {skipped} / エラー: {errors}",
                        ))

                except Exception as _ex:
                    _log(f"\n[エラー] {_ex}")
                    tab_sync.after(0, lambda _m=str(_ex): messagebox.showerror("転送エラー", _m))
                finally:
                    tab_sync.after(0, lambda: btn_sync_run.config(state="normal", text="転送実行"))

            threading.Thread(target=_transfer, daemon=True).start()

        def _run_pull() -> None:
            if not sync_gl_var.get() and not sync_media_chk_var.get():
                messagebox.showwarning("設定エラー", "転送内容を1つ以上選択してください。")
                return
            host = sync_host_var.get().strip()
            if not host:
                messagebox.showwarning("設定エラー", "ホスト（Steam DeckのIPアドレス）を入力してください。")
                return

            btn_pull_run.config(state="disabled", text="プル中...")
            btn_sync_run.config(state="disabled")
            _clear_log()
            sync_progress["value"] = 0

            system      = system_var.get()
            local_paths = resolve_paths(config, system)
            sd_cfg      = config.get("steam_deck", {})
            remote_gl_base    = sd_cfg.get("gamelist_base", "/home/deck/.emulationstation/gamelists")
            remote_media_base = sd_cfg.get("media_base",    "/home/deck/.emulationstation/downloaded_media")

            # 単一ファイル転送指示 (gamelist.xml)
            file_tasks: list[tuple[str, Path]] = []
            if sync_gl_var.get():
                remote_gl = f"{remote_gl_base}/{system}/gamelist.xml"
                local_gl  = Path(local_paths["gamelist_path"])
                file_tasks.append((remote_gl, local_gl))

            # ディレクトリ単位転送指示 (メディア)
            dir_mappings: list[tuple[str, Path]] = []
            if sync_media_chk_var.get():
                local_media_sys = Path(local_paths["media_path"])
                for folder, fvar in sync_media_type_vars.items():
                    if not fvar.get():
                        continue
                    remote_folder = f"{remote_media_base}/{system}/{folder}"
                    local_folder  = local_media_sys / folder
                    dir_mappings.append((remote_folder, local_folder))

            overwrite = sync_overwrite_var.get()

            def _pull() -> None:
                try:
                    ok, skipped, errors = pull_files(
                        host=host,
                        port=int(sync_port_var.get() or 22),
                        username=sync_user_var.get(),
                        password=sync_pass_var.get(),
                        file_tasks=file_tasks,
                        dir_mappings=dir_mappings,
                        overwrite=overwrite,
                        on_log=_log,
                        on_progress=lambda v: tab_sync.after(
                            0, lambda _v=v: sync_progress.__setitem__("value", _v)
                        ),
                    )
                    summary = f"\n[完了] 取得: {ok} / スキップ: {skipped} / エラー: {errors}"
                    _log(summary)

                    if errors == 0:
                        tab_sync.after(0, lambda: messagebox.showinfo(
                            "プル完了",
                            f"プルが完了しました。\n取得: {ok} ファイル / スキップ: {skipped} ファイル",
                        ))
                    else:
                        tab_sync.after(0, lambda: messagebox.showwarning(
                            "プル完了（一部エラーあり）",
                            f"プルは完了しましたが一部エラーがあります。\n取得: {ok} / スキップ: {skipped} / エラー: {errors}",
                        ))

                except Exception as _ex:
                    _log(f"\n[エラー] {_ex}")
                    tab_sync.after(0, lambda _m=str(_ex): messagebox.showerror("プルエラー", _m))
                finally:
                    tab_sync.after(0, lambda: btn_pull_run.config(state="normal", text="← プル"))
                    tab_sync.after(0, lambda: btn_sync_run.config(state="normal"))

            threading.Thread(target=_pull, daemon=True).start()

        btn_sync_run.config(command=_run_sync)
        btn_pull_run.config(command=_run_pull)

    _media_img_refs: list = []  # PhotoImage のガベージコレクション防止

    # ── ロジック ─────────────────────────────────────────────
    state: dict = {"root_elem": None, "games": [], "decl": "", "selected": -1}

    def get_field(game: ET.Element, key: str) -> str:
        el = game.find(key)
        return (el.text or "") if el is not None else ""

    def set_field(game: ET.Element, key: str, value: str) -> None:
        el = game.find(key)
        if value:
            if el is None:
                el = ET.SubElement(game, key)
            el.text = value
        else:
            if el is not None:
                game.remove(el)

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
        rom_base = resolve_paths(config, system_var.get())["rom_path"]
        path_val = get_field(game, "path")
        if path_val and not (Path(rom_base) / path_val).exists():
            del_banner.grid()
        else:
            del_banner.grid_remove()
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
        for key, widget in field_widgets.items():
            if isinstance(widget, TagInput):
                val = ", ".join(widget.get_tags())
            elif isinstance(widget, DateInput):
                val = widget.get_date_str()
            elif isinstance(widget, tk.Text):
                val = widget.get("1.0", "end-1c").strip()
            else:
                val = widget.get().strip()
            set_field(game, key, val)
        display = get_field(game, "name") or get_field(game, "path") or "(不明)"
        listbox.delete(idx)
        listbox.insert(idx, display)
        rom_base = resolve_paths(config, system_var.get())["rom_path"]
        path_val = get_field(game, "path")
        if path_val and not (Path(rom_base) / path_val).exists():
            listbox.itemconfig(idx, fg="#cc0000")

    def on_select(event=None) -> None:
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx == state["selected"]:
            return
        flush_form(state["selected"])
        state["selected"] = idx
        fill_form(state["games"][idx])

    listbox.bind("<<ListboxSelect>>", on_select)

    def delete_entry() -> None:
        idx = state["selected"]
        if idx < 0 or idx >= len(state["games"]):
            return
        if not messagebox.askyesno("エントリ削除", "このゲームのエントリを削除しますか？\n\n保存するまでファイルには反映されません。"):
            return
        gamelist = state["root_elem"].find("gameList")
        if gamelist is not None:
            gamelist.remove(state["games"][idx])
        state["games"].pop(idx)
        listbox.delete(idx)
        state["selected"] = -1
        del_banner.grid_remove()
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

    btn_delete_entry.config(command=delete_entry)

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

    def load_file() -> None:
        path = resolve_paths(config, system_var.get())["gamelist_path"]
        if not Path(path).exists():
            messagebox.showwarning("読み込みエラー", f"ファイルが見つかりません:\n{path}")
            return
        try:
            root_elem, games, decl = parse_gamelist(path)
        except ET.ParseError as e:
            messagebox.showerror("XMLエラー", f"XMLのパースに失敗しました:\n{e}")
            return
        state.update({"root_elem": root_elem, "games": games, "decl": decl, "selected": -1})
        listbox.delete(0, "end")
        rom_base = resolve_paths(config, system_var.get())["rom_path"]
        for i, game in enumerate(games):
            display = get_field(game, "name") or get_field(game, "path") or "(不明)"
            listbox.insert("end", display)
            path_val = get_field(game, "path")
            if path_val and not (Path(rom_base) / path_val).exists():
                listbox.itemconfig(i, fg="#cc0000")
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

    def save_file() -> None:
        if state["root_elem"] is None:
            messagebox.showwarning("保存エラー", "ファイルが読み込まれていません。")
            return
        flush_form(state["selected"])
        path = resolve_paths(config, system_var.get())["gamelist_path"]
        content = serialize_gamelist(state["root_elem"], state["decl"])
        try:
            save_gamelist_file(path, content, config.get("backup_max", 5))
            messagebox.showinfo("保存完了", "保存しました。")
        except Exception as e:
            messagebox.showerror("保存エラー", str(e))

    btn_load_file.config(command=load_file)
    btn_save_file.config(command=save_file)
    btn_media_check.config(
        command=lambda: open_media_check_window(root, config, system_var.get(), state["games"])
    )
    load_file()
