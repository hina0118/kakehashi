import tkinter as tk
from datetime import date, datetime

from tkcalendar import DateEntry


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
