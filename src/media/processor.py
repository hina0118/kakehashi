import mimetypes
import os
import platform
import subprocess
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
import xml.etree.ElementTree as ET
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, filedialog

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from src.core.config_manager import (
    MEDIA_FOLDERS, IMAGE_SUFFIXES, VIDEO_SUFFIXES, THUMB_W, THUMB_H,
    resolve_paths,
)


def get_rom_stem(path_val: str) -> str:
    """gamelist.xml の <path> 値から拡張子なしファイル名を返す。
    例: "./Super Mario World.zip" → "Super Mario World"
    """
    return Path(path_val).stem


def check_media_for_game(media_path: str, rom_stem: str) -> dict[str, bool]:
    """11種のメディアフォルダそれぞれに rom_stem.* が存在するか確認する。"""
    base = Path(media_path)
    return {
        folder: bool(list((base / folder).glob(f"{rom_stem}.*")))
        for folder in MEDIA_FOLDERS
    }


def find_media_files(media_path: str, rom_stem: str) -> dict[str, "Path | None"]:
    """各メディアフォルダの最初にマッチしたファイルパスを返す。なければ None。"""
    base = Path(media_path)
    result: dict[str, "Path | None"] = {}
    for folder in MEDIA_FOLDERS:
        folder_path = base / folder
        if folder_path.is_dir():
            matches = list(folder_path.glob(f"{rom_stem}.*"))
            result[folder] = matches[0] if matches else None
        else:
            result[folder] = None
    return result


def open_with_default_app(file_path: Path) -> None:
    """ファイルをOSのデフォルトアプリで開く（Windows: os.startfile / Linux: xdg-open）。"""
    if platform.system() == "Windows":
        os.startfile(file_path)
    else:
        subprocess.Popen(["xdg-open", str(file_path)])


def open_fullsize_image(parent: tk.Widget, file_path: Path, folder_name: str) -> None:
    """画像をフルサイズで表示する。スクリーンサイズを超える場合は縮小して表示。"""
    try:
        img = Image.open(file_path)
    except Exception as e:
        messagebox.showerror("画像読み込みエラー", str(e), parent=parent)
        return

    orig_w, orig_h = img.size

    win = tk.Toplevel(parent)
    win.title(f"{folder_name}  —  {file_path.name}  ({orig_w}×{orig_h})")

    # スクリーンの85%以内に収まるようスケーリング（拡大はしない）
    max_w = int(win.winfo_screenwidth()  * 0.85)
    max_h = int(win.winfo_screenheight() * 0.85)
    scale  = min(max_w / orig_w, max_h / orig_h, 1.0)
    disp_w = max(1, int(orig_w * scale))
    disp_h = max(1, int(orig_h * scale))

    disp_img = img.resize((disp_w, disp_h), Image.LANCZOS) if scale < 1.0 else img
    photo    = ImageTk.PhotoImage(disp_img)

    win.geometry(f"{disp_w}x{disp_h}")
    win.resizable(False, False)

    lbl = tk.Label(win, image=photo, cursor="hand2")
    lbl.image = photo  # ガベージコレクション防止
    lbl.pack()

    # クリック または Escape で閉じる
    lbl.bind("<Button-1>", lambda e: win.destroy())
    win.bind("<Escape>",   lambda e: win.destroy())
    win.focus_set()


def open_url_download_dialog(
    parent: tk.Widget,
    folder: str,
    stem: str,
    media_path: str,
    game_title: str,
    on_success: "callable[[], None]",
) -> None:
    """URLからメディアファイルをダウンロードして登録するダイアログを開く。"""
    dest_dir = Path(media_path) / folder

    dlg = tk.Toplevel(parent)
    dlg.title(f"{folder} — URLからDL登録")
    dlg.geometry("520x200")
    dlg.resizable(True, False)
    dlg.grab_set()

    tk.Label(dlg, text=f"  {folder}  にダウンロード登録", font=("Arial", 10, "bold"), anchor="w").pack(
        fill="x", padx=12, pady=(10, 0)
    )
    tk.Label(dlg, text=f"  {game_title}", font=("Arial", 9), fg="#555", anchor="w").pack(
        fill="x", padx=12, pady=(2, 6)
    )
    tk.Frame(dlg, height=1, bg="#cccccc").pack(fill="x")

    body = tk.Frame(dlg)
    body.pack(fill="both", expand=True, padx=12, pady=8)
    body.columnconfigure(1, weight=1)

    tk.Label(body, text="URL:", font=("Arial", 9), anchor="w").grid(
        row=0, column=0, sticky="w", pady=(2, 2)
    )
    url_var = tk.StringVar()
    url_entry = tk.Entry(body, textvariable=url_var, font=("Arial", 9))
    url_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(2, 2))

    tk.Label(body, text="保存先:", font=("Arial", 9), anchor="w").grid(
        row=1, column=0, sticky="nw", pady=(4, 2)
    )
    dest_label = tk.Label(
        body, text="", font=("Arial", 8), fg="#555",
        anchor="w", wraplength=360, justify="left",
    )
    dest_label.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(4, 2))

    def _update_dest(*_) -> None:
        url = url_var.get().strip()
        if not url:
            dest_label.config(text="", fg="#555")
            return
        path_ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
        if path_ext:
            dest_label.config(text=str(dest_dir / f"{stem}{path_ext}"), fg="#555")
        else:
            dest_label.config(
                text="(拡張子をURLから判定できません。DL時にContent-Typeで判定します)",
                fg="#888",
            )

    url_var.trace_add("write", _update_dest)

    tk.Frame(dlg, height=1, bg="#cccccc").pack(fill="x")
    footer = tk.Frame(dlg, bg="#f5f5f5")
    footer.pack(fill="x", pady=6)

    def do_download() -> None:
        url = url_var.get().strip()
        if not url:
            messagebox.showwarning("URL未入力", "URLを入力してください。", parent=dlg)
            return
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
                path_ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
                if path_ext in IMAGE_SUFFIXES | VIDEO_SUFFIXES | {".pdf"}:
                    ext = path_ext
                else:
                    ext = mimetypes.guess_extension(content_type) or ""
                    if ext in (".jpe", ".jpeg"):
                        ext = ".jpg"
                if not ext:
                    messagebox.showwarning(
                        "拡張子不明",
                        "ファイル形式を判定できませんでした。\nURLを確認してください。",
                        parent=dlg,
                    )
                    return
                dest = dest_dir / f"{stem}{ext}"
                data = resp.read()
        except urllib.error.URLError as e:
            messagebox.showerror("ダウンロードエラー", str(e.reason), parent=dlg)
            return
        except Exception as e:
            messagebox.showerror("エラー", str(e), parent=dlg)
            return

        if not messagebox.askokcancel(
            "登録確認",
            f"保存先:\n{dest}\n\n登録しますか？",
            parent=dlg,
        ):
            return
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        except Exception as e:
            messagebox.showerror("保存エラー", str(e), parent=dlg)
            return

        dlg.destroy()
        on_success()

    tk.Button(
        footer, text="ダウンロード & 登録", font=("Arial", 9), width=16, command=do_download,
    ).pack(side="left", padx=(12, 6))
    tk.Button(
        footer, text="閉じる", font=("Arial", 9), width=8, command=dlg.destroy,
    ).pack(side="right", padx=12)

    url_entry.focus_set()


def open_cover_crop_dialog(
    parent: tk.Widget,
    cover_path: Path,
    stem: str,
    media_path: str,
    game_title: str,
    on_success: "callable[[], None]",
) -> None:
    """covers画像からロゴ領域をドラッグ選択で切り出し、marqueesに保存するダイアログ。PILが必要。"""
    if not _PIL_OK:
        messagebox.showwarning(
            "Pillow未インストール",
            "この機能にはPillowが必要です。\npip install pillow を実行してください。",
            parent=parent,
        )
        return

    try:
        orig_img = Image.open(cover_path).convert("RGBA")
    except Exception as e:
        messagebox.showerror("画像読み込みエラー", str(e), parent=parent)
        return

    orig_w, orig_h = orig_img.size

    # 表示用スケーリング（最大 600×600 に収める）
    MAX_DISP = 600
    scale = min(MAX_DISP / orig_w, MAX_DISP / orig_h, 1.0)
    disp_w = max(1, int(orig_w * scale))
    disp_h = max(1, int(orig_h * scale))
    disp_img = orig_img.resize((disp_w, disp_h), Image.LANCZOS) if scale < 1.0 else orig_img.copy()

    dlg = tk.Toplevel(parent)
    dlg.title("covers → marquees 切り出し")
    dlg.resizable(False, False)
    dlg.grab_set()

    tk.Label(dlg, text="  covers → marquees  切り出し", font=("Arial", 10, "bold"), anchor="w").pack(
        fill="x", padx=12, pady=(10, 0)
    )
    tk.Label(dlg, text=f"  {game_title}", font=("Arial", 9), fg="#555", anchor="w").pack(
        fill="x", padx=12, pady=(2, 2)
    )
    tk.Label(
        dlg, text="  ドラッグして切り出し範囲を指定してください", font=("Arial", 8), fg="#888", anchor="w",
    ).pack(fill="x", padx=12, pady=(0, 6))
    tk.Frame(dlg, height=1, bg="#cccccc").pack(fill="x")

    photo = ImageTk.PhotoImage(disp_img)
    canvas = tk.Canvas(dlg, width=disp_w, height=disp_h, cursor="crosshair", highlightthickness=0)
    canvas.pack(padx=8, pady=8)
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas._photo_ref = photo  # GC防止

    rect_id = [None]
    sel = {"x1": 0, "y1": 0, "x2": 0, "y2": 0}

    def _clamp(v: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, v))

    def on_press(e: tk.Event) -> None:
        sel["x1"] = sel["x2"] = _clamp(e.x, 0, disp_w)
        sel["y1"] = sel["y2"] = _clamp(e.y, 0, disp_h)
        if rect_id[0]:
            canvas.delete(rect_id[0])
        rect_id[0] = canvas.create_rectangle(
            sel["x1"], sel["y1"], sel["x2"], sel["y2"],
            outline="#ff3333", width=2, dash=(4, 2),
        )

    def on_drag(e: tk.Event) -> None:
        sel["x2"] = _clamp(e.x, 0, disp_w)
        sel["y2"] = _clamp(e.y, 0, disp_h)
        canvas.coords(rect_id[0], sel["x1"], sel["y1"], sel["x2"], sel["y2"])

    def on_release(e: tk.Event) -> None:
        sel["x2"] = _clamp(e.x, 0, disp_w)
        sel["y2"] = _clamp(e.y, 0, disp_h)
        canvas.coords(rect_id[0], sel["x1"], sel["y1"], sel["x2"], sel["y2"])

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)

    tk.Frame(dlg, height=1, bg="#cccccc").pack(fill="x")
    footer = tk.Frame(dlg, bg="#f5f5f5")
    footer.pack(fill="x", pady=6)

    def do_crop() -> None:
        x1 = min(sel["x1"], sel["x2"])
        y1 = min(sel["y1"], sel["y2"])
        x2 = max(sel["x1"], sel["x2"])
        y2 = max(sel["y1"], sel["y2"])

        if x2 - x1 < 5 or y2 - y1 < 5:
            messagebox.showwarning(
                "選択範囲が小さすぎます",
                "もう少し広い範囲をドラッグして選択してください。",
                parent=dlg,
            )
            return

        # 表示座標 → 元画像座標に変換
        ox1 = int(x1 / scale)
        oy1 = int(y1 / scale)
        ox2 = int(x2 / scale)
        oy2 = int(y2 / scale)

        dest = Path(media_path) / "marquees" / f"{stem}.png"
        if not messagebox.askokcancel(
            "登録確認",
            f"保存先:\n{dest}\n\n登録しますか？",
            parent=dlg,
        ):
            return
        try:
            cropped = orig_img.crop((ox1, oy1, ox2, oy2))
            dest.parent.mkdir(parents=True, exist_ok=True)
            cropped.save(dest, "PNG")
        except Exception as e:
            messagebox.showerror("保存エラー", str(e), parent=dlg)
            return

        dlg.destroy()
        on_success()

    tk.Button(
        footer, text="切り出して登録", font=("Arial", 9), width=14, command=do_crop,
    ).pack(side="left", padx=(12, 6))
    tk.Button(
        footer, text="閉じる", font=("Arial", 9), width=8, command=dlg.destroy,
    ).pack(side="right", padx=12)


def open_media_check_window(parent: tk.Tk, config: dict, system: str, games: list[ET.Element]) -> None:
    """メディアファイル過不足チェックダイアログを開く。"""
    media_path = resolve_paths(config, system)["media_path"]

    win = tk.Toplevel(parent)
    win.title(f"メディアチェック - {system}")
    win.geometry("900x500")
    win.minsize(600, 300)

    # ── ヘッダー情報 ────────────────────────────────────────────
    header_frame = tk.Frame(win, bg="#f5f5f5")
    header_frame.pack(fill="x", padx=8, pady=(8, 0))

    summary_label = tk.Label(header_frame, text="", font=("Arial", 9), bg="#f5f5f5", anchor="w")
    summary_label.pack(side="left")

    only_missing_var = tk.BooleanVar(value=False)
    chk = tk.Checkbutton(
        header_frame, text="欠損のみ表示", variable=only_missing_var,
        font=("Arial", 9), bg="#f5f5f5",
    )
    chk.pack(side="right", padx=8)

    tk.Frame(win, height=1, bg="#cccccc").pack(fill="x", padx=0, pady=(6, 0))

    # ── テーブルエリア ──────────────────────────────────────────
    from tkinter import ttk
    table_frame = tk.Frame(win)
    table_frame.pack(fill="both", expand=True, padx=8, pady=4)

    columns = ["title"] + MEDIA_FOLDERS
    col_headers = ["タイトル"] + MEDIA_FOLDERS

    tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="none")

    # 列幅設定
    tree.column("title", width=200, minwidth=120, anchor="w")
    for folder in MEDIA_FOLDERS:
        tree.column(folder, width=72, minwidth=56, anchor="center")

    for col, header in zip(columns, col_headers):
        tree.heading(col, text=header)

    # スクロールバー
    vsb = ttk.Scrollbar(table_frame, orient="vertical",   command=tree.yview)
    hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0,  column=1, sticky="ns")
    hsb.grid(row=1,  column=0, sticky="ew")
    table_frame.rowconfigure(0, weight=1)
    table_frame.columnconfigure(0, weight=1)

    # 行カラータグ
    tree.tag_configure("ok",      background="white")
    tree.tag_configure("missing", background="#fff0f0")

    # ── データ収集・描画 ────────────────────────────────────────
    def get_field_local(game: ET.Element, key: str) -> str:
        el = game.find(key)
        return (el.text or "") if el is not None else ""

    rows: list[tuple[str, dict[str, bool], bool]] = []  # (title, result_dict, has_missing)
    for game in games:
        path_val = get_field_local(game, "path")
        title    = get_field_local(game, "name") or path_val or "(不明)"
        if not path_val:
            rows.append((title, {f: False for f in MEDIA_FOLDERS}, True))
            continue
        stem   = get_rom_stem(path_val)
        result = check_media_for_game(media_path, stem)
        has_missing = not all(result.values())
        rows.append((title, result, has_missing))

    missing_count = sum(1 for _, _, hm in rows if hm)

    def refresh_table() -> None:
        tree.delete(*tree.get_children())
        show_missing_only = only_missing_var.get()
        for title, result, has_missing in rows:
            if show_missing_only and not has_missing:
                continue
            values = [title] + ["○" if result[f] else "-" for f in MEDIA_FOLDERS]
            tag = "missing" if has_missing else "ok"
            tree.insert("", "end", values=values, tags=(tag,))

    def update_summary() -> None:
        summary_label.config(text=f"{len(games)} ゲーム中 {missing_count} ゲームに欠損あり")

    only_missing_var.trace_add("write", lambda *_: refresh_table())

    update_summary()
    refresh_table()

    # ── フッター ────────────────────────────────────────────────
    tk.Frame(win, height=1, bg="#cccccc").pack(fill="x")
    footer = tk.Frame(win, bg="#f5f5f5")
    footer.pack(fill="x", pady=6)
    tk.Button(footer, text="閉じる", width=8, font=("Arial", 9), command=win.destroy).pack(side="right", padx=12)
