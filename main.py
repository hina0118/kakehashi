import json
import re
import shutil
import platform
import urllib.parse
import webbrowser
import tkinter as tk
import xml.etree.ElementTree as ET
from datetime import date, datetime
from tkinter import ttk, messagebox
from pathlib import Path

from tkcalendar import DateEntry


CONFIG_PATH       = Path(__file__).parent / "config.json"
WINDOW_STATE_PATH = Path(__file__).parent / "window_state.json"

DEFAULT_GEOMETRY = "1100x700"


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
        "rom_path":      f"{base.get('rom_base', '')}/{system}",
        "gamelist_path": f"{base.get('gamelist_base', '')}/{system}/gamelist.xml",
        "media_path":    f"{base.get('media_base', '')}/{system}",
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

    # ── 中央ペイン：編集フォーム ──────────────────────────────
    mid_frame = tk.Frame(paned)
    paned.add(mid_frame, minsize=400)
    tk.Label(mid_frame, text="ゲーム情報の編集", font=("Arial", 9, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 4))
    tk.Frame(mid_frame, height=1, bg="#dddddd").pack(fill="x", padx=8)

    # 検索バー（下部固定）
    search_bar_frame = tk.Frame(mid_frame, bg="#f5f5f5")
    search_bar_frame.pack(side="bottom", fill="x")
    tk.Frame(mid_frame, height=1, bg="#e0e0e0").pack(side="bottom", fill="x")

    form = tk.Frame(mid_frame)
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
        grid_row = r + 2
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
        for game in games:
            display = get_field(game, "name") or get_field(game, "path") or "(不明)"
            listbox.insert("end", display)
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
