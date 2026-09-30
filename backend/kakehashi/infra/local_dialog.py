"""サーバが動いているPCでファイル/フォルダ選択ダイアログを開く。

ブラウザからはPC上の実パスを得られない（数GBのROMをアップロードさせたくもない）ため、
サーバと同じPCで動かす前提を利用してOSのダイアログを開く。Tkはスレッドから使うと
不安定なので、別プロセスで起動して結果をJSONで受け取る。
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Literal

DialogMode = Literal["files", "file", "folder"]

_SCRIPT = r"""
import json, sys, tkinter as tk
from tkinter import filedialog
args = json.loads(sys.argv[1])
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
kw = {"title": args["title"], "parent": root}
if args.get("filetypes"):
    kw["filetypes"] = [tuple(t) for t in args["filetypes"]] + [("すべてのファイル", "*.*")]
if args["mode"] == "folder":
    r = filedialog.askdirectory(mustexist=True, **kw)
    paths = [r] if r else []
elif args["mode"] == "file":
    r = filedialog.askopenfilename(**kw)
    paths = [r] if r else []
else:
    paths = list(filedialog.askopenfilenames(**kw))
root.destroy()
sys.stdout.write(json.dumps(paths))
"""


def pick(mode: DialogMode, title: str, filetypes: list[tuple[str, str]] | None = None) -> list[str]:
    """選択されたパスの一覧。キャンセル時は空リスト。"""
    args = json.dumps({"mode": mode, "title": title, "filetypes": filetypes or []}, ensure_ascii=False)
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT, args],
        capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ファイル選択ダイアログを開けませんでした: {proc.stderr.strip()[-300:]}")
    return json.loads(proc.stdout or "[]")
