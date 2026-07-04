"""PS2 (DVDトールケース) 用の3Dボックス装飾。

公式PS2パッケージテンプレート画像を合成して本物に近い外観を再現する。
  カバー正面: assets/ps2_topbar.png をカバー幅に合わせてリサイズ・合成
  背表紙    : assets/ps2_spine.png (PSロゴ+PlayStation.®2) をスパイン幅に合わせて合成
              + ゲームタイトルを縦書き白文字でセンタリング
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# アセットディレクトリ
_ASSETS_DIR = Path(__file__).parent / "assets"

PLATFORM_DISPLAY: dict[str, str] = {
    "ps2":    "PlayStation.®2",
    "ps3":    "PlayStation.®3",
    "ps4":    "PlayStation.®4",
    "psp":    "PSP",
    "psvita": "PS Vita",
    "psx":    "PlayStation",
}

# フォールバック用カラー定数（アセット非使用時）
_COVER_DARK  = (  8,   8,   8, 255)
_SPINE_BG    = ( 10,  10,  10, 255)
_SPINE_TEXT  = (230, 230, 230, 255)


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


def _load_asset(name: str) -> "Image.Image | None":
    """assetsディレクトリからテンプレート画像を読み込む。失敗時はNone。"""
    path = _ASSETS_DIR / name
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


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
    """1文字ずつ縦に積み重ねて描画し、描画終了Y座標を返す。"""
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


def _calc_total_text_h(
    draw: "ImageDraw.ImageDraw",
    chars: list[str],
    font: "ImageFont.FreeTypeFont | ImageFont.ImageFont",
    spacing: int,
) -> int:
    """縦書き時のテキスト総高さを計算する。"""
    return (
        sum(
            draw.textbbox((0, 0), c, font=font)[3] - draw.textbbox((0, 0), c, font=font)[1]
            for c in chars
        )
        + spacing * max(0, len(chars) - 1)
    )


def _add_spine_highlight(spine_img: "Image.Image") -> None:
    """背表紙にプラスチックケースの光沢を2層で追加する。

    Layer 1 — アンビエント: 左→右の線形グラデーション（立体的な面の向き）
    Layer 2 — スペキュラー: 右端寄りの鋭い光沢帯（直接光の反射）
    """
    sw, sh = spine_img.size
    if sw < 6:
        return

    # ── Layer 1: アンビエントグラデーション（控えめ） ────────────
    ambient = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    a_draw = ImageDraw.Draw(ambient)
    for x in range(sw):
        t = x / max(1, sw - 1)          # 0.0(左端) → 1.0(右端)
        alpha = int(15 * t)              # 最大α=15（主役はスペキュラー）
        a_draw.line([(x, 0), (x, sh - 1)], fill=(255, 255, 255, alpha))
    spine_img.paste(Image.alpha_composite(spine_img, ambient), (0, 0))

    # ── Layer 2: スペキュラーハイライト（右端の鋭い光沢線） ──────
    specular = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(specular)
    center_x = int(sw * 0.88)           # より右端寄り
    width = max(1, int(sw * 0.13))      # 幅を狭く
    for x in range(sw):
        dist = abs(x - center_x)
        if dist > width:
            continue
        t = 1.0 - (dist / width)
        alpha = int(110 * t * t * t)    # α最大110・3乗で鋭い収束
        s_draw.line([(x, 0), (x, sh - 1)], fill=(255, 255, 255, alpha))
    spine_img.paste(Image.alpha_composite(spine_img, specular), (0, 0))


def decorate_cover(cover: "Image.Image", ch: int) -> None:
    """カバー正面にPS2パッケージ風の装飾を描画する。

    assets/ps2_topbar.png をカバー幅にリサイズして上部に合成。
    アセットが存在しない場合はテキスト描画でフォールバック。
    下部に薄い黒帯を描画。
    """
    cw = cover.size[0]
    draw = ImageDraw.Draw(cover)

    topbar = _load_asset("ps2_topbar.png")

    if topbar is not None:
        # テンプレート帯をカバー幅に合わせてリサイズ
        # 元のアスペクト比を維持（高さ比率を転用）
        orig_w, orig_h = topbar.size
        top_h = max(10, int(cw * orig_h / orig_w))
        top_h = min(top_h, int(ch * 0.12))   # カバー高の12%を上限
        resized = topbar.resize((cw, top_h), Image.LANCZOS)
        cover.paste(resized, (0, 0), resized)
    else:
        # フォールバック: テキスト描画
        top_h = max(10, int(ch * 0.082))
        draw.rectangle([(0, 0), (cw, top_h)], fill=_COVER_DARK)
        font_size = max(7, int(top_h * 0.58))
        font = _load_font(font_size)
        text = "PlayStation\u00ae2"
        bbox = draw.textbbox((0, 0), text, font=font)
        th = bbox[3] - bbox[1]
        tx = max(4, int(cw * 0.04))
        ty = max(0, (top_h - th) // 2)
        draw.text((tx, ty), text, fill=(230, 230, 230, 255), font=font)

    # 下部帯（薄い黒）
    bot_h = max(2, int(ch * 0.018))
    draw.rectangle([(0, ch - bot_h), (cw, ch)], fill=_COVER_DARK)


def decorate_spine(
    spine_img: "Image.Image",
    title: str,
    system: str = "",
    font_path: str = "",
) -> None:
    """背表紙に公式PS2テンプレートを合成して装飾する。

    assets/ps2_spine.png (PSロゴ+PlayStation.®2) をスパイン幅にリサイズして上部に合成し、
    残りの黒背景エリアにゲームタイトルを縦書き白文字でセンタリング描画する。
    アセットが存在しない場合はテキスト描画でフォールバック。
    """
    sw, sh = spine_img.size
    if sw < 6:
        return

    draw = ImageDraw.Draw(spine_img)

    edge_h = max(3, int(sh * 0.022))   # 上下エッジ高さを先に確定

    brand_asset = _load_asset("ps2_spine.png")
    brand_bottom_y = edge_h   # ブランディング画像の描画終了Y座標

    if brand_asset is not None:
        # スパイン幅に合わせてリサイズ（高さはアスペクト比で決定）
        orig_w, orig_h = brand_asset.size
        brand_h = int(sw * orig_h / orig_w)
        brand_h = min(brand_h, int(sh * 0.45))   # スパイン高の45%を上限

        # 上部: 黒（エッジ＋ブランディング領域）
        draw.rectangle([(0, 0), (sw, edge_h + brand_h)], fill=_SPINE_BG)
        resized_brand = brand_asset.resize((sw, brand_h), Image.LANCZOS)
        # エッジ分ずらして貼り付け → エッジがロゴに被らない
        spine_img.paste(resized_brand, (0, edge_h), resized_brand)

        # 下部: 白（タイトル領域）
        draw.rectangle([(0, edge_h + brand_h), (sw, sh)], fill=(255, 255, 255, 255))

        brand_bottom_y = edge_h + brand_h + max(2, int(sh * 0.012))
    else:
        # フォールバック: テキスト縦積み描画
        platform_name = PLATFORM_DISPLAY.get(system.lower(), system) if system else ""
        if platform_name:
            plat_font_size = max(5, int(sw * 0.50))
            plat_font = _load_font(plat_font_size, font_path)
            plat_chars = list(platform_name)
            plat_spacing = max(0, int(plat_font_size * 0.05))
            total_plat_h = _calc_total_text_h(draw, plat_chars, plat_font, plat_spacing)
            while total_plat_h > sh * 0.35 and plat_font_size > 5:
                plat_font_size -= 1
                plat_font = _load_font(plat_font_size, font_path)
                plat_spacing = max(0, int(plat_font_size * 0.05))
                total_plat_h = _calc_total_text_h(draw, plat_chars, plat_font, plat_spacing)
            brand_bottom_y = _draw_vertical_text(
                draw, plat_chars, plat_font,
                sw // 2, max(2, int(sh * 0.018)),
                sh - max(2, int(sh * 0.018)),
                _SPINE_TEXT, plat_spacing,
            ) + max(2, int(sh * 0.015))

    # ── 上下エッジ: 最前面で確定（白塗りやブランディングへの被りを防ぐ） ──
    draw.rectangle([(0, 0),           (sw, edge_h)],  fill=_SPINE_BG)
    draw.rectangle([(0, sh - edge_h), (sw, sh)],      fill=_SPINE_BG)

    # ── タイトル: 縦書き白文字・センタリング ──────────────────
    if title:
        bot_pad = edge_h
        t_margin = max(2, int(sh * 0.012))
        t_start  = brand_bottom_y + t_margin
        t_end    = sh - bot_pad - t_margin

        if t_end > t_start + 10:
            t_font_size = max(7, int(sw * 0.60))
            t_font      = _load_font(t_font_size, font_path)
            t_chars     = list(title)
            t_spacing   = max(1, int(t_font_size * 0.10))

            draw2 = ImageDraw.Draw(spine_img)
            total_h = _calc_total_text_h(draw2, t_chars, t_font, t_spacing)
            while total_h > (t_end - t_start) and t_font_size > 6:
                t_font_size -= 1
                t_font      = _load_font(t_font_size, font_path)
                t_spacing   = max(1, int(t_font_size * 0.10))
                total_h     = _calc_total_text_h(draw2, t_chars, t_font, t_spacing)

            y_offset = max(0, (t_end - t_start - total_h) // 2)
            # 下部は白背景なので黒文字（アセットなし時は白文字のまま）
            title_color = (20, 20, 20, 230) if brand_asset is not None else _SPINE_TEXT
            _draw_vertical_text(
                draw2, t_chars, t_font,
                sw // 2,
                t_start + y_offset,
                t_end,
                title_color,
                t_spacing,
            )

    # ── 光沢ハイライト ────────────────────────────────────────
    _add_spine_highlight(spine_img)
