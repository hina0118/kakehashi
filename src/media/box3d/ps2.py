"""PS2 (DVDトールケース) 用の3Dボックス装飾。

カバー正面の上下に黒帯、背表紙にプラットフォーム名(横書き回転)+タイトル(縦書き)を描画する。
"""

try:
    from PIL import Image, ImageDraw
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

PLATFORM_DISPLAY: dict[str, str] = {
    "ps2": "PlayStation 2",
    "ps3": "PlayStation 3",
    "ps4": "PlayStation 4",
    "psp": "PSP",
    "psvita": "PS Vita",
    "psx": "PlayStation",
}


def _load_font(
    size: int, font_path: str = "",
) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    from PIL import ImageFont
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    for candidate in [
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_vertical_text(
    draw: "ImageDraw.ImageDraw",
    chars: list[str],
    font: "ImageFont.FreeTypeFont | ImageFont.ImageFont",
    x_center: int,
    y_start: int,
    y_end: int,
    color: tuple,
    spacing: int = 2,
) -> int:
    """1文字ずつ縦に描画し、描画終了Y座標を返す。"""
    y = y_start
    for ch in chars:
        bbox = draw.textbbox((0, 0), ch, font=font)
        char_w = bbox[2] - bbox[0]
        char_h = bbox[3] - bbox[1]
        if y + char_h > y_end:
            break
        x = x_center - char_w // 2
        draw.text((x, y), ch, fill=color, font=font)
        y += char_h + spacing
    return y


def _add_spine_highlight(spine_img: "Image.Image") -> None:
    """背表紙の右端寄りにプラスチックケースの光沢反射を追加する。"""
    sw, sh = spine_img.size
    if sw < 6:
        return

    highlight = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))

    # 反射帯の位置: 右端から20-35%あたりに縦のハイライト
    center_x = int(sw * 0.75)
    width = max(2, int(sw * 0.25))

    for x in range(sw):
        dist = abs(x - center_x)
        if dist > width:
            continue
        # 中心が最も明るく、端に向かってフェード
        t = 1.0 - (dist / width)
        alpha = int(50 * t * t)
        for y in range(sh):
            highlight.putpixel((x, y), (255, 255, 255, alpha))

    spine_img.paste(Image.alpha_composite(spine_img, highlight), (0, 0))


def decorate_cover(cover: "Image.Image", ch: int) -> None:
    """カバー正面の上下にDVDトールケースの黒帯を描画する。"""
    cw = cover.size[0]
    case_band = max(2, int(ch * 0.02))
    draw = ImageDraw.Draw(cover)
    draw.rectangle([(0, 0), (cw, case_band)], fill=(20, 20, 20, 255))
    draw.rectangle([(0, ch - case_band), (cw, ch)], fill=(20, 20, 20, 255))


def decorate_spine(
    spine_img: "Image.Image",
    title: str,
    system: str = "",
    font_path: str = "",
) -> None:
    """背表紙にDVDトールケース風の装飾を描画する。
    上から: [黒帯(パッケージ上)] [黒帯(プラットフォーム名/横書き回転)]
            [白帯(タイトル/縦書き)] [黒帯(パッケージ下)]
    """
    sw, sh = spine_img.size
    if sw < 6:
        return

    platform_name = PLATFORM_DISPLAY.get(system.lower(), system) if system else ""

    draw = ImageDraw.Draw(spine_img)
    x_center = sw // 2

    case_top_h = int(sh * 0.02)
    case_bot_h = int(sh * 0.02)

    # --- プラットフォーム名領域（黒背景 + 横書き回転） ---
    plat_region_h = 0
    plat_rotated: "Image.Image | None" = None

    if platform_name:
        plat_font_size = max(6, int(sw * 0.50))
        plat_font = _load_font(plat_font_size, font_path)
        plat_bbox = draw.textbbox((0, 0), platform_name, font=plat_font)
        text_w = plat_bbox[2] - plat_bbox[0]
        text_h = plat_bbox[3] - plat_bbox[1]

        while text_w > sh * 0.35 and plat_font_size > 5:
            plat_font_size -= 1
            plat_font = _load_font(plat_font_size, font_path)
            plat_bbox = draw.textbbox((0, 0), platform_name, font=plat_font)
            text_w = plat_bbox[2] - plat_bbox[0]
            text_h = plat_bbox[3] - plat_bbox[1]

        pad = max(2, int(text_h * 0.3))
        tmp_w = text_w + pad * 2
        tmp_h = text_h + pad * 2
        tmp = Image.new("RGBA", (tmp_w, tmp_h), (0, 0, 0, 0))
        tmp_draw = ImageDraw.Draw(tmp)
        tmp_draw.text((pad, pad), platform_name, fill=(255, 255, 255, 230), font=plat_font)
        plat_rotated = tmp.rotate(-90, expand=True, resample=Image.BICUBIC)
        plat_region_h = plat_rotated.size[1]

    total_black_top = case_top_h + plat_region_h
    title_region_top = total_black_top
    title_region_bot = sh - case_bot_h

    # 背景塗り分け: 全面黒 → タイトル領域だけ白
    draw.rectangle([(0, 0), (sw, sh)], fill=(20, 20, 20, 255))
    if title:
        draw.rectangle(
            [(0, title_region_top), (sw, title_region_bot)],
            fill=(255, 255, 255, 255),
        )

    # プラットフォーム名（回転画像を貼り付け）
    if plat_rotated is not None:
        pr_w, pr_h = plat_rotated.size
        px = (sw - pr_w) // 2
        py = case_top_h
        spine_img.paste(plat_rotated, (px, py), plat_rotated)

    # タイトル（白背景上に黒文字で縦書き）
    if title:
        title_pad = int(sw * 0.15)
        title_y_start = title_region_top + title_pad
        title_y_end = title_region_bot - title_pad

        title_font_size = max(7, int(sw * 0.55))
        title_font = _load_font(title_font_size, font_path)
        title_chars = list(title)
        title_spacing = max(1, int(title_font_size * 0.12))

        draw = ImageDraw.Draw(spine_img)

        total_title_h = sum(
            draw.textbbox((0, 0), c, font=title_font)[3] - draw.textbbox((0, 0), c, font=title_font)[1]
            for c in title_chars
        ) + title_spacing * max(0, len(title_chars) - 1)

        while total_title_h > (title_y_end - title_y_start) and title_font_size > 6:
            title_font_size -= 1
            title_font = _load_font(title_font_size, font_path)
            title_spacing = max(1, int(title_font_size * 0.12))
            total_title_h = sum(
                draw.textbbox((0, 0), c, font=title_font)[3] - draw.textbbox((0, 0), c, font=title_font)[1]
                for c in title_chars
            ) + title_spacing * max(0, len(title_chars) - 1)

        _draw_vertical_text(
            draw, title_chars, title_font, x_center,
            title_y_start, title_y_end, (0, 0, 0, 200), title_spacing,
        )

    # --- 光沢反射（右端寄りの縦ハイライト）---
    _add_spine_highlight(spine_img)
