import json
import tkinter as tk
from tkinter import ttk
from pathlib import Path


CONFIG_PATH      = Path(__file__).parent / "config.json"
WINDOW_STATE_PATH = Path(__file__).parent / "window_state.json"

DEFAULT_GEOMETRY = "640x360"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_window_state() -> str:
    """保存済みのジオメトリ文字列を返す。なければデフォルト値。"""
    try:
        with open(WINDOW_STATE_PATH, encoding="utf-8") as f:
            return json.load(f).get("geometry", DEFAULT_GEOMETRY)
    except FileNotFoundError:
        return DEFAULT_GEOMETRY


def save_window_state(root: tk.Tk) -> None:
    """現在のジオメトリを保存する。"""
    with open(WINDOW_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"geometry": root.geometry()}, f, indent=2)


def resolve_paths(config: dict, system: str) -> dict:
    """指定した機種に対応した実パスを返す。"""
    env = config.get("environment", "windows")
    base = config.get(env, {})
    return {
        "ROM パス":      f"{base.get('rom_base', '')}/{system}",
        "gamelist パス": f"{base.get('gamelist_base', '')}/{system}/gamelist.xml",
        "メディアパス":  f"{base.get('media_base', '')}/{system}",
    }


def build_ui(root: tk.Tk, config: dict) -> None:
    root.title("kakehashi")

    # タイトル
    tk.Label(root, text="kakehashi", font=("Arial", 20, "bold")).pack(pady=(20, 4))
    tk.Label(
        root,
        text="ES-DE 日本語メタデータ管理ツール",
        font=("Arial", 11),
        fg="gray",
    ).pack(pady=(0, 12))

    tk.Frame(root, height=1, bg="#cccccc").pack(fill="x", padx=20, pady=(0, 12))

    env = config.get("environment", "unknown")
    systems = config.get("systems", [])
    current_system = config.get("system", systems[0] if systems else "")

    # 環境・機種選択行
    info_frame = tk.Frame(root)
    info_frame.pack(anchor="w", padx=30, pady=(0, 12))

    tk.Label(info_frame, text="動作環境:", font=("Arial", 11, "bold"), width=12, anchor="w").grid(
        row=0, column=0, sticky="w"
    )
    tk.Label(info_frame, text=env, font=("Arial", 11), anchor="w").grid(row=0, column=1, sticky="w")

    tk.Label(info_frame, text="対象機種:", font=("Arial", 11, "bold"), width=12, anchor="w").grid(
        row=1, column=0, sticky="w", pady=(6, 0)
    )
    system_var = tk.StringVar(value=current_system)
    combo = ttk.Combobox(
        info_frame,
        textvariable=system_var,
        values=systems,
        state="readonly",
        width=16,
        font=("Arial", 11),
    )
    combo.grid(row=1, column=1, sticky="w", pady=(6, 0))

    tk.Frame(root, height=1, bg="#eeeeee").pack(fill="x", padx=20, pady=(0, 12))

    # パスラベル（動的更新用に保持）
    path_frame = tk.Frame(root)
    path_frame.pack(fill="x", padx=30)

    path_labels: dict[str, tk.Label] = {}
    for row, key in enumerate(["ROM パス", "gamelist パス", "メディアパス"]):
        tk.Label(path_frame, text=key + ":", font=("Arial", 10, "bold"), anchor="w", width=16).grid(
            row=row, column=0, sticky="w", pady=4
        )
        lbl = tk.Label(path_frame, text="", font=("Arial", 10), anchor="w", fg="#333333")
        lbl.grid(row=row, column=1, sticky="w", pady=4)
        path_labels[key] = lbl

    def update_paths(*_):
        paths = resolve_paths(config, system_var.get())
        for key, lbl in path_labels.items():
            lbl.config(text=paths.get(key, "（未設定）"))

    combo.bind("<<ComboboxSelected>>", update_paths)
    update_paths()  # 初期表示


def main() -> None:
    try:
        config = load_config()
    except FileNotFoundError:
        config = {}
        print(f"[警告] {CONFIG_PATH} が見つかりません。デフォルト設定で起動します。")

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
