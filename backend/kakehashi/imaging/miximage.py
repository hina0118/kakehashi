"""miximage（合成画像）の生成ロジック。

1280×960 の透過PNGを生成する。
レイアウト:
  - 背景: screenshots（角丸 + ドロップシャドウ）
  - 右上: marquees（タイトルロゴ）
  - 左下: 3dboxes
  - 左下(3dboxesの右): physicalmedia（存在する場合のみ）
"""
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

CANVAS_W = 1280
CANVAS_H = 960

_CORNER_RADIUS = 24
_SHADOW_OFFSET = 8
_SHADOW_BLUR = 12
_SHADOW_COLOR = (0, 0, 0, 100)

_SCREENSHOT_MARGIN = 40
_SCREENSHOT_W = CANVAS_W - _SCREENSHOT_MARGIN * 2
_SCREENSHOT_H = CANVAS_H - _SCREENSHOT_MARGIN * 2

_MARQUEE_MAX_W = int(CANVAS_W * 0.45)
_MARQUEE_MAX_H = int(CANVAS_H * 0.25)
_MARQUEE_MARGIN_RIGHT = 30
_MARQUEE_MARGIN_TOP = 20

_BOX3D_MAX_H = int(CANVAS_H * 0.55)
_BOX3D_MARGIN_LEFT = 20
_BOX3D_MARGIN_BOTTOM = 20

_PMEDIA_MAX_H = int(CANVAS_H * 0.30)
_PMEDIA_MARGIN_BOTTOM = 30
_PMEDIA_GAP = -10


def _round_rect_mask(w: int, h: int, radius: int) -> "Image.Image":
    """角丸矩形のアルファマスクを返す。"""
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=255)
    return mask


def _fit_image(img: "Image.Image", max_w: int, max_h: int) -> "Image.Image":
    """アスペクト比を保ったまま max_w×max_h 以内に縮小する（拡大はしない）。"""
    w, h = img.size
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 1.0:
        return img.copy()
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def _add_shadow(canvas: "Image.Image", layer: "Image.Image", x: int, y: int) -> "Image.Image":
    """layer のシルエットからドロップシャドウを canvas に合成する。"""
    alpha = layer.split()[3]
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_fill = Image.new("RGBA", layer.size, _SHADOW_COLOR)
    shadow_fill.putalpha(alpha)
    shadow.paste(shadow_fill, (x + _SHADOW_OFFSET, y + _SHADOW_OFFSET))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=_SHADOW_BLUR))
    return Image.alpha_composite(canvas, shadow)


def _load_image(path: "Path | str") -> "Image.Image":
    return Image.open(path).convert("RGBA")


def generate_miximage(
    screenshot_path: "Path | str",
    marquee_path: "Path | str | None" = None,
    box3d_path: "Path | str | None" = None,
    physicalmedia_path: "Path | str | None" = None,
) -> "Image.Image":
    """各素材画像から 1280×960 の miximage を合成して返す。

    Args:
        screenshot_path: スクリーンショット画像のパス（必須）
        marquee_path: マーキー（タイトルロゴ）画像のパス
        box3d_path: 3Dボックス画像のパス
        physicalmedia_path: フィジカルメディア（ディスク等）画像のパス

    Returns:
        1280×960 の RGBA Image
    """
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))

    # ── 背景: screenshot（角丸 + シャドウ）──────────────────────
    ss_img = _load_image(screenshot_path)
    ss_w, ss_h = ss_img.size
    ss_scale = max(_SCREENSHOT_W / ss_w, _SCREENSHOT_H / ss_h)
    scaled_w = max(1, int(ss_w * ss_scale))
    scaled_h = max(1, int(ss_h * ss_scale))
    ss_scaled = ss_img.resize((scaled_w, scaled_h), Image.LANCZOS)

    crop_x = (scaled_w - _SCREENSHOT_W) // 2
    crop_y = (scaled_h - _SCREENSHOT_H) // 2
    ss_cropped = ss_scaled.crop((crop_x, crop_y, crop_x + _SCREENSHOT_W, crop_y + _SCREENSHOT_H))

    mask = _round_rect_mask(_SCREENSHOT_W, _SCREENSHOT_H, _CORNER_RADIUS)
    ss_layer = Image.new("RGBA", (_SCREENSHOT_W, _SCREENSHOT_H), (0, 0, 0, 0))
    ss_layer.paste(ss_cropped, mask=mask)

    ss_x = _SCREENSHOT_MARGIN
    ss_y = _SCREENSHOT_MARGIN
    canvas = _add_shadow(canvas, ss_layer, ss_x, ss_y)
    canvas = Image.alpha_composite(
        canvas,
        _paste_on_transparent(canvas.size, ss_layer, ss_x, ss_y),
    )

    # ── 右上: marquee ─────────────────────────────────────────
    if marquee_path:
        mq_img = _load_image(marquee_path)
        mq_img = _fit_image(mq_img, _MARQUEE_MAX_W, _MARQUEE_MAX_H)
        mq_w, mq_h = mq_img.size
        mq_x = CANVAS_W - mq_w - _MARQUEE_MARGIN_RIGHT
        mq_y = _MARQUEE_MARGIN_TOP
        canvas = _add_shadow(canvas, mq_img, mq_x, mq_y)
        canvas = Image.alpha_composite(
            canvas,
            _paste_on_transparent(canvas.size, mq_img, mq_x, mq_y),
        )

    # ── 左下: 3dbox ───────────────────────────────────────────
    box3d_right_edge = _BOX3D_MARGIN_LEFT
    if box3d_path:
        b3d_img = _load_image(box3d_path)
        b3d_img = _fit_image(b3d_img, int(CANVAS_W * 0.40), _BOX3D_MAX_H)
        b3d_w, b3d_h = b3d_img.size
        b3d_x = _BOX3D_MARGIN_LEFT
        b3d_y = CANVAS_H - b3d_h - _BOX3D_MARGIN_BOTTOM
        canvas = _add_shadow(canvas, b3d_img, b3d_x, b3d_y)
        canvas = Image.alpha_composite(
            canvas,
            _paste_on_transparent(canvas.size, b3d_img, b3d_x, b3d_y),
        )
        box3d_right_edge = b3d_x + b3d_w

    # ── physicalmedia（3dboxes の右）──────────────────────────
    if physicalmedia_path:
        pm_img = _load_image(physicalmedia_path)
        pm_img = _fit_image(pm_img, int(CANVAS_W * 0.25), _PMEDIA_MAX_H)
        pm_w, pm_h = pm_img.size
        pm_x = box3d_right_edge + _PMEDIA_GAP
        pm_y = CANVAS_H - pm_h - _PMEDIA_MARGIN_BOTTOM
        canvas = _add_shadow(canvas, pm_img, pm_x, pm_y)
        canvas = Image.alpha_composite(
            canvas,
            _paste_on_transparent(canvas.size, pm_img, pm_x, pm_y),
        )

    return canvas


def _paste_on_transparent(
    canvas_size: tuple[int, int],
    layer: "Image.Image",
    x: int,
    y: int,
) -> "Image.Image":
    """透明キャンバスに layer を (x, y) に配置した RGBA 画像を返す。"""
    tmp = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    tmp.paste(layer, (x, y))
    return tmp


def generate_miximage_for_game(
    media_path: "str | Path",
    rom_stem: str,
) -> "Image.Image | None":
    """media_path 配下の各フォルダから素材を探し、miximage を生成する。

    screenshots が見つからない場合は None を返す。

    Args:
        media_path: メディアベースパス（例: work/downloaded_media/ps2）
        rom_stem: ROMファイルの拡張子なしファイル名

    Returns:
        生成された miximage (RGBA) または None
    """
    base = Path(media_path)

    def _find(folder: str) -> "Path | None":
        d = base / folder
        if not d.is_dir():
            return None
        for f in d.iterdir():
            if f.stem == rom_stem and f.suffix.lower() in {
                ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tga",
            }:
                return f
        return None

    ss = _find("screenshots")
    if ss is None:
        return None

    return generate_miximage(
        screenshot_path=ss,
        marquee_path=_find("marquees"),
        box3d_path=_find("3dboxes"),
        physicalmedia_path=_find("physicalmedia"),
    )
