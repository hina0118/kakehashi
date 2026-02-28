"""3Dボックス画像生成の共通ロジック。

射影変換によるカバー正面・背表紙の変形とシャドウ合成を担当する。
背表紙の装飾（テキスト、ケース枠など）はプラットフォーム固有モジュールに委譲する。
"""

try:
    from PIL import Image, ImageFilter, ImageDraw
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def find_perspective_coeffs(
    src_points: list[tuple[float, float]],
    dst_points: list[tuple[float, float]],
) -> list[float]:
    """入力画像の4点(src)を出力画像の4点(dst)にマッピングする
    Pillow Image.transform(PERSPECTIVE) 用の8係数を返す。
    """
    import numpy as np
    A = []
    B = []
    for (sx, sy), (dx, dy) in zip(src_points, dst_points):
        A.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        A.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
        B.append(sx)
        B.append(sy)
    res = np.linalg.lstsq(np.array(A, dtype=float), np.array(B, dtype=float), rcond=None)[0]
    return list(res)


def generate_3dbox(
    cover_img: "Image.Image",
    *,
    canvas_w: int = 0,
    canvas_h: int = 0,
    spine_ratio: float = 0.08,
    angle_pct: float = 0.30,
    shadow: bool = True,
    spine_text: str = "",
    system: str = "",
    font_path: str = "",
    decorate_cover: "callable | None" = None,
    decorate_spine: "callable | None" = None,
) -> "Image.Image":
    """covers画像から斜め向きの3Dボックス画像を生成する。

    Args:
        cover_img:       カバー画像 (PIL Image, RGBA推奨)
        canvas_w:        出力キャンバス幅 (0=自動)
        canvas_h:        出力キャンバス高さ (0=自動)
        spine_ratio:     カバー幅に対する背表紙幅の比率
        angle_pct:       奥行き感の強さ (0.0=正面, 0.5=強い遠近)
        shadow:          ドロップシャドウを付けるか
        spine_text:      背表紙に描画するゲームタイトル
        system:          システム名 (例: "ps2")
        font_path:       フォントファイルのパス (空=自動検出)
        decorate_cover:  カバー画像を装飾するコールバック (cover_img, ch) -> None
        decorate_spine:  背表紙画像を装飾するコールバック (spine_img, spine_text, system, font_path) -> None
    Returns:
        透明背景の3DボックスPNG用RGBA画像
    """
    cover = cover_img.convert("RGBA")
    cw, ch = cover.size
    spine_w = max(4, int(cw * spine_ratio))

    if decorate_cover:
        decorate_cover(cover, ch)

    front_w = int(cw * (1.0 - angle_pct * 0.55))
    shrink = int(ch * angle_pct * 0.22)
    spine_drop = int(spine_w * angle_pct * 1.8)

    margin = int(cw * 0.04)
    out_w = canvas_w or (front_w + spine_w + margin)
    out_h = canvas_h or (ch + spine_drop + margin)

    fl_x = spine_w
    fl_y = margin

    front_src = [(0, 0), (cw, 0), (cw, ch), (0, ch)]
    front_dst = [
        (fl_x, fl_y),
        (fl_x + front_w, fl_y + shrink),
        (fl_x + front_w, fl_y + ch - shrink),
        (fl_x, fl_y + ch),
    ]
    coeffs_front = find_perspective_coeffs(front_src, front_dst)
    front_warped = cover.transform(
        (out_w, out_h), Image.PERSPECTIVE, coeffs_front, Image.BICUBIC,
    )

    # 背表紙ベース画像（カバー左端の平均色からグラデーション生成）
    spine_avg = cover.crop((0, 0, max(1, cw // 10), ch))
    spine_pixels = list(spine_avg.getdata())
    r = sum(p[0] for p in spine_pixels) // len(spine_pixels)
    g = sum(p[1] for p in spine_pixels) // len(spine_pixels)
    b = sum(p[2] for p in spine_pixels) // len(spine_pixels)
    dark = (max(0, int(r * 0.45)), max(0, int(g * 0.45)), max(0, int(b * 0.45)))
    light = (max(0, int(r * 0.70)), max(0, int(g * 0.70)), max(0, int(b * 0.70)))

    spine_img = Image.new("RGBA", (spine_w, ch), (*light, 255))
    for x in range(spine_w):
        t = x / max(1, spine_w - 1)
        cr = int(dark[0] + (light[0] - dark[0]) * t)
        cg = int(dark[1] + (light[1] - dark[1]) * t)
        cb = int(dark[2] + (light[2] - dark[2]) * t)
        for y in range(ch):
            spine_img.putpixel((x, y), (cr, cg, cb, 255))

    if decorate_spine:
        decorate_spine(spine_img, spine_text, system, font_path)

    spine_src = [(0, 0), (spine_w, 0), (spine_w, ch), (0, ch)]
    spine_dst = [
        (0, fl_y + spine_drop),
        (fl_x, fl_y),
        (fl_x, fl_y + ch),
        (0, fl_y + ch - spine_drop),
    ]
    coeffs_spine = find_perspective_coeffs(spine_src, spine_dst)
    spine_warped = spine_img.transform(
        (out_w, out_h), Image.PERSPECTIVE, coeffs_spine, Image.BICUBIC,
    )

    result = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))

    if shadow:
        shadow_layer = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        shadow_offset = 6
        for layer in [spine_warped, front_warped]:
            alpha = layer.split()[3]
            sh = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 80))
            sh.putalpha(alpha)
            shifted = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
            shifted.paste(sh, (shadow_offset, shadow_offset))
            shadow_layer = Image.alpha_composite(shadow_layer, shifted)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=4))
        result = Image.alpha_composite(result, shadow_layer)

    result = Image.alpha_composite(result, spine_warped)
    result = Image.alpha_composite(result, front_warped)

    bbox = result.getbbox()
    if bbox:
        result = result.crop(bbox)

    return result
