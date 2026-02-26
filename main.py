import json
import os
import re
import shutil
import subprocess
import platform
import urllib.parse
import urllib.request
import urllib.error
import mimetypes
import webbrowser
import tkinter as tk
import xml.etree.ElementTree as ET
from datetime import date, datetime
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from tkcalendar import DateEntry

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

import locale
try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    locale.setlocale(locale.LC_ALL, "C")

CONFIG_PATH       = Path(__file__).parent / "config.json"
WINDOW_STATE_PATH = Path(__file__).parent / "window_state.json"

DEFAULT_GEOMETRY = "1100x700"

MEDIA_FOLDERS = [
    "3dboxes", "backcovers", "covers", "fanart", "manuals",
    "marquees", "miximages", "physicalmedia", "screenshots",
    "titlescreens", "videos",
]

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tga"}
VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v"}

THUMB_W, THUMB_H = 96, 72  # メディアタブのサムネイルサイズ


# ── カスタムウィジェット ──────────────────────────────────────────

class DateInput(tk.Frame):
    """発売日入力ウィジェット。チェックで日付あり/なしを切り替える。"""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._enabled = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(self, variable=self._enabled, text="設定する", font=("Arial", 9), command=self._on_toggle)
        chk.pack(side="left")
        self._entry = DateEntry(self, date_pattern="yyyy/mm/dd", font=("Arial", 9), width=12,
                               state="disabled", year=2000, month=1, day=1)
        self._entry.pack(side="left", padx=(6, 0))

    def _on_toggle(self) -> None:
        self._entry.config(state="normal" if self._enabled.get() else "disabled")

    def set_date_str(self, s: str) -> None:
        """XML形式 (YYYYMMDDTHHMMSS) の文字列をセットする。空なら未設定状態にする。"""
        if s:
            try:
                d = datetime.strptime(s, "%Y%m%dT%H%M%S").date()
                self._entry.config(state="normal")
                self._entry.set_date(d)
                self._enabled.set(True)
                return
            except ValueError:
                pass
        self._entry.config(state="normal")
        self._entry.set_date(date(2000, 1, 1))
        self._entry.config(state="disabled")
        self._enabled.set(False)

    def get_date_str(self) -> str:
        """XML形式の文字列を返す。未設定の場合は空文字列。"""
        if not self._enabled.get():
            return ""
        return self._entry.get_date().strftime("%Y%m%dT000000")


class TagInput(tk.Frame):
    """カンマ区切りのタグを視覚的に編集するウィジェット。"""

    TAG_BG     = "#dce8ff"
    TAG_BORDER = "#99aacc"

    def __init__(self, parent, **kwargs):
        super().__init__(parent, relief="sunken", bd=1, bg="white", **kwargs)
        self._tags: list[str] = []
        self._var = tk.StringVar()
        self._render()

    def _render(self) -> None:
        for w in self.winfo_children():
            w.destroy()
        for tag in self._tags:
            chip = tk.Frame(self, bg=self.TAG_BG, relief="flat", bd=1)
            chip.pack(side="left", padx=(3, 0), pady=3)
            tk.Label(chip, text=tag, bg=self.TAG_BG, font=("Arial", 9), padx=4, pady=1).pack(side="left")
            tk.Button(
                chip, text="×", bg=self.TAG_BG, relief="flat",
                font=("Arial", 8), padx=2, pady=0, bd=0, cursor="hand2",
                command=lambda t=tag: self._remove(t),
            ).pack(side="left")
        entry = tk.Entry(self, textvariable=self._var, font=("Arial", 9), relief="flat", bd=0, bg="white")
        entry.pack(side="left", fill="x", expand=True, padx=(4, 4), pady=3)
        entry.bind("<Return>",   self._add)
        entry.bind("<KP_Enter>", self._add)

    def _add(self, _=None) -> None:
        val = self._var.get().strip()
        if val and val not in self._tags:
            self._tags.append(val)
            self._var.set("")
            self._render()

    def _remove(self, tag: str) -> None:
        if tag in self._tags:
            self._tags.remove(tag)
            self._render()

    def set_tags(self, tags: list[str]) -> None:
        self._tags = [t for t in tags if t]
        self._var.set("")  # 入力途中のテキストもクリア
        self._render()

    def get_tags(self) -> list[str]:
        return list(self._tags)


# ── ファイル I/O ─────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_window_state() -> str:
    try:
        with open(WINDOW_STATE_PATH, encoding="utf-8") as f:
            return json.load(f).get("geometry", DEFAULT_GEOMETRY)
    except FileNotFoundError:
        return DEFAULT_GEOMETRY


def save_window_state(root: tk.Tk) -> None:
    with open(WINDOW_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"geometry": root.geometry()}, f, indent=2)


def detect_environment(config: dict) -> str:
    """config.json の environment を優先し、未設定の場合は OS を自動判別する。"""
    if env := config.get("environment"):
        return env
    return "windows" if platform.system() == "Windows" else "steam_deck"


def discover_systems(config: dict) -> list[str]:
    """gamelist_base 配下のフォルダ名からシステム一覧を取得する。
    フォルダが見つからない場合は config.json の systems にフォールバックする。
    """
    env = detect_environment(config)
    base = config.get(env, {}).get("gamelist_base", "")
    if base:
        p = Path(base)
        if p.is_dir():
            dirs = sorted(d.name for d in p.iterdir() if d.is_dir())
            if dirs:
                return dirs
    return config.get("systems", [])


def resolve_paths(config: dict, system: str) -> dict:
    env = detect_environment(config)
    base = config.get(env, {})
    return {
        "rom_path":      str(Path(base.get("rom_base",      "")) / system),
        "gamelist_path": str(Path(base.get("gamelist_base", "")) / system / "gamelist.xml"),
        "media_path":    str(Path(base.get("media_base",    "")) / system),
    }


def parse_gamelist(path: str) -> tuple[ET.Element, list[ET.Element], str]:
    """gamelist.xml をパースし (_root_要素, game要素リスト, XML宣言) を返す。

    ES-DE の gamelist.xml は <alternativeEmulator> と <gameList> の
    2トップレベル要素を持つため、_root_ でラップして標準パーサで処理する。
    """
    content = Path(path).read_text(encoding="utf-8")
    decl_match = re.match(r'<\?xml[^?]*\?>', content)
    decl = decl_match.group(0) if decl_match else '<?xml version="1.0"?>'
    body = re.sub(r'<\?xml[^?]*\?>\s*', '', content).strip()
    root_elem = ET.fromstring(f'<_root_>{body}</_root_>')
    gamelist = root_elem.find('gameList')
    games = gamelist.findall('game') if gamelist is not None else []
    return root_elem, games, decl


def serialize_gamelist(root_elem: ET.Element, decl: str) -> str:
    parts = [decl]
    for child in root_elem:
        child.tail = None
        ET.indent(child, space='\t')
        parts.append(ET.tostring(child, encoding='unicode'))
    return '\n'.join(parts) + '\n'


def save_gamelist_file(path: str, content: str, backup_max: int) -> None:
    p = Path(path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p.parent / f"{p.name}.{timestamp}.bak"
    shutil.copy2(p, bak)
    backups = sorted(p.parent.glob(f"{p.name}.*.bak"))
    for old in backups[:-backup_max]:
        old.unlink()
    p.write_text(content, encoding="utf-8")


# ── メディアチェック ─────────────────────────────────────────────

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


# ── UI ───────────────────────────────────────────────────────────

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


def main() -> None:
    try:
        config = load_config()
    except FileNotFoundError:
        config = {}
        print(f"[警告] {CONFIG_PATH} が見つかりません。")

    root = tk.Tk()
    root.geometry(load_window_state())

    def on_close():
        save_window_state(root)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    build_ui(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
