import locale
import tkinter as tk

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    locale.setlocale(locale.LC_ALL, "C")

from src.app import build_ui
from src.core.config_manager import CONFIG_PATH, load_config, load_window_state, save_window_state


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
