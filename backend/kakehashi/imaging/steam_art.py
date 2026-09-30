"""台帳の画像から、Steamのライブラリ画像（縦長カバー・横長ヘッダー・ヒーロー）を作る。

比率が合わない画像は、ぼかして暗くした同じ画像を背景に敷き、元画像を収まる大きさで重ねる。
"""
from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# Steamのライブラリ画像: 種類 → (出力サイズ, 台帳画像の優先順)
ART_SPECS: dict[str, tuple[tuple[int, int], tuple[str, ...]]] = {
    "portrait": ((600, 900), ("cover", "header", "hero")),
    "header": ((920, 430), ("header", "hero", "cover")),
    "hero": ((1920, 620), ("hero", "header", "cover")),
}
# 比率の差がこの割合以内なら、はみ出た部分を切り落とすだけにする
_ASPECT_TOLERANCE = 0.12


def fit(src: Image.Image, size: tuple[int, int]) -> Image.Image:
    src = src.convert("RGBA")
    w, h = size
    src_ratio, dst_ratio = src.width / src.height, w / h
    if abs(src_ratio - dst_ratio) / dst_ratio <= _ASPECT_TOLERANCE:
        return ImageOps.fit(src, size, Image.LANCZOS).convert("RGB")

    background = ImageOps.fit(src, size, Image.LANCZOS).convert("RGB")
    background = background.filter(ImageFilter.GaussianBlur(radius=max(w, h) / 40))
    background = ImageEnhance.Brightness(background).enhance(0.55)
    fg = ImageOps.contain(src, (int(w * 0.94), int(h * 0.94)), Image.LANCZOS)
    background.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2), fg)
    return background


def build(kind: str, sources: dict[str, Image.Image]) -> Image.Image | None:
    """kind（portrait/header/hero）の画像を作る。使える台帳画像が無ければ None。"""
    size, order = ART_SPECS[kind]
    src = next((sources[k] for k in order if k in sources), None)
    return fit(src, size) if src is not None else None
