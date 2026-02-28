"""3Dボックス生成ダイアログ（プレビュー付き）。"""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from src.media.box3d.base import generate_3dbox
from src.media.box3d import ps2 as ps2_style


def open_3dbox_dialog(
    parent: tk.Widget,
    cover_path: Path,
    stem: str,
    media_path: str,
    game_title: str,
    system: str,
    on_success: "callable[[], None]",
) -> None:
    """covers画像から3Dボックス画像を生成するダイアログ。プレビュー付き。"""
    if not _PIL_OK:
        messagebox.showwarning(
            "Pillow未インストール",
            "この機能にはPillowが必要です。\npip install pillow を実行してください。",
            parent=parent,
        )
        return

    try:
        import numpy as np  # noqa: F401
    except ImportError:
        messagebox.showwarning(
            "NumPy未インストール",
            "この機能にはNumPyが必要です。\npip install numpy を実行してください。",
            parent=parent,
        )
        return

    try:
        orig_img = Image.open(cover_path).convert("RGBA")
    except Exception as e:
        messagebox.showerror("画像読み込みエラー", str(e), parent=parent)
        return

    # システムに応じた装飾関数を選択
    decorate_cover, decorate_spine = _get_decorators(system)

    dlg = tk.Toplevel(parent)
    dlg.title("covers → 3dboxes 生成")
    dlg.resizable(False, False)
    dlg.grab_set()

    tk.Label(dlg, text="  covers → 3dboxes  生成", font=("Arial", 10, "bold"), anchor="w").pack(
        fill="x", padx=12, pady=(10, 0)
    )
    tk.Label(dlg, text=f"  {game_title}", font=("Arial", 9), fg="#555", anchor="w").pack(
        fill="x", padx=12, pady=(2, 6)
    )
    tk.Frame(dlg, height=1, bg="#cccccc").pack(fill="x")

    # コントロール部（横並び・上部）
    ctrl_frame = tk.Frame(dlg)
    ctrl_frame.pack(fill="x", padx=12, pady=(8, 4))

    spine_frame = tk.Frame(ctrl_frame)
    spine_frame.pack(side="left", padx=(0, 16))
    tk.Label(spine_frame, text="背表紙幅:", font=("Arial", 9), anchor="w").pack(anchor="w")
    spine_var = tk.DoubleVar(value=0.08)
    tk.Scale(
        spine_frame, from_=0.02, to=0.25, resolution=0.01,
        orient="horizontal", variable=spine_var, length=140,
        font=("Arial", 8),
    ).pack()

    angle_frame = tk.Frame(ctrl_frame)
    angle_frame.pack(side="left", padx=(0, 16))
    tk.Label(angle_frame, text="奥行き:", font=("Arial", 9), anchor="w").pack(anchor="w")
    angle_var = tk.DoubleVar(value=0.30)
    tk.Scale(
        angle_frame, from_=0.05, to=0.60, resolution=0.01,
        orient="horizontal", variable=angle_var, length=140,
        font=("Arial", 8),
    ).pack()

    opt_frame = tk.Frame(ctrl_frame)
    opt_frame.pack(side="left", anchor="s", pady=(0, 4))
    shadow_var = tk.BooleanVar(value=True)
    tk.Checkbutton(
        opt_frame, text="シャドウ", variable=shadow_var, font=("Arial", 9),
    ).pack(anchor="w")

    # 背表紙テキスト入力
    text_frame = tk.Frame(dlg)
    text_frame.pack(fill="x", padx=12, pady=(0, 4))
    text_frame.columnconfigure(1, weight=1)
    tk.Label(text_frame, text="背表紙テキスト:", font=("Arial", 9), anchor="w").pack(side="left")
    spine_text_var = tk.StringVar(value=game_title)
    tk.Entry(text_frame, textvariable=spine_text_var, font=("Arial", 9)).pack(
        side="left", fill="x", expand=True, padx=(6, 0),
    )

    tk.Frame(dlg, height=1, bg="#e0e0e0").pack(fill="x", padx=12)

    # プレビュー部（下部・チェッカーボード背景）
    PREVIEW_MAX = 420
    preview_canvas = tk.Canvas(
        dlg, width=PREVIEW_MAX, height=PREVIEW_MAX,
        bg="#d0d0d0", highlightthickness=1, highlightbackground="#cccccc",
    )
    preview_canvas.pack(padx=12, pady=8)
    preview_canvas._photo_ref = None

    def _draw_checker(canvas: tk.Canvas, w: int, h: int, size: int = 12) -> None:
        for y in range(0, h, size):
            for x in range(0, w, size):
                fill = "#ffffff" if (x // size + y // size) % 2 == 0 else "#cccccc"
                canvas.create_rectangle(x, y, x + size, y + size, fill=fill, outline="")

    generated_img_holder: list = [None]
    _preview_after_id: list = [None]

    def update_preview(*_) -> None:
        if _preview_after_id[0] is not None:
            dlg.after_cancel(_preview_after_id[0])
        _preview_after_id[0] = dlg.after(150, _do_update_preview)

    def _do_update_preview() -> None:
        _preview_after_id[0] = None
        try:
            img3d = generate_3dbox(
                orig_img,
                spine_ratio=spine_var.get(),
                angle_pct=angle_var.get(),
                shadow=shadow_var.get(),
                spine_text=spine_text_var.get(),
                system=system,
                decorate_cover=decorate_cover,
                decorate_spine=decorate_spine,
            )
            generated_img_holder[0] = img3d

            pw, ph = img3d.size
            scale = min(PREVIEW_MAX / pw, PREVIEW_MAX / ph, 1.0)
            dw = max(1, int(pw * scale))
            dh = max(1, int(ph * scale))
            disp = img3d.resize((dw, dh), Image.LANCZOS) if scale < 1.0 else img3d.copy()
            photo = ImageTk.PhotoImage(disp)

            preview_canvas.delete("all")
            _draw_checker(preview_canvas, PREVIEW_MAX, PREVIEW_MAX)
            preview_canvas.create_image(
                PREVIEW_MAX // 2, PREVIEW_MAX // 2, anchor="center", image=photo,
            )
            preview_canvas._photo_ref = photo
        except Exception:
            preview_canvas.delete("all")
            preview_canvas.create_text(
                PREVIEW_MAX // 2, PREVIEW_MAX // 2,
                text="(生成エラー)", fill="#cc0000", font=("Arial", 10),
            )

    spine_var.trace_add("write", update_preview)
    angle_var.trace_add("write", update_preview)
    shadow_var.trace_add("write", update_preview)
    spine_text_var.trace_add("write", update_preview)

    dlg.after(100, _do_update_preview)

    tk.Frame(dlg, height=1, bg="#cccccc").pack(fill="x")
    footer = tk.Frame(dlg, bg="#f5f5f5")
    footer.pack(fill="x", pady=6)

    def do_save() -> None:
        img3d = generated_img_holder[0]
        if img3d is None:
            messagebox.showwarning("未生成", "プレビューを確認してから保存してください。", parent=dlg)
            return
        dest = Path(media_path) / "3dboxes" / f"{stem}.png"
        if not messagebox.askokcancel("登録確認", f"保存先:\n{dest}\n\n登録しますか？", parent=dlg):
            return
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            img3d.save(dest, "PNG")
        except Exception as e:
            messagebox.showerror("保存エラー", str(e), parent=dlg)
            return
        dlg.destroy()
        on_success()

    tk.Button(
        footer, text="保存", font=("Arial", 9), width=14, command=do_save,
    ).pack(side="left", padx=(12, 6))
    tk.Button(
        footer, text="閉じる", font=("Arial", 9), width=8, command=dlg.destroy,
    ).pack(side="right", padx=12)


# PS2スタイルを適用するシステム一覧（DVDトールケース系）
_PS2_STYLE_SYSTEMS = {"ps2", "ps3", "ps4", "psp", "psvita", "psx"}


def _get_decorators(system: str) -> tuple:
    """システム名に応じた装飾関数ペアを返す。"""
    if system.lower() in _PS2_STYLE_SYSTEMS:
        return ps2_style.decorate_cover, ps2_style.decorate_spine
    return None, None
