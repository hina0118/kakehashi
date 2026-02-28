"""AI-based logo extraction from cover images using Florence-2 + BiRefNet.

1. Florence-2-large でロゴ領域を検出 (bounding box)
2. BiRefNet で背景を除去し透過PNGとして出力

モデルは初回呼び出し時にロード（合計 ~2.5GB VRAM）され、以降はキャッシュされる。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_FLORENCE_MODEL_ID = "florence-community/Florence-2-large"
_BIREFNET_MODEL_ID = "ZhengPeng7/BiRefNet"

_florence_model = None
_florence_processor = None
_birefnet_model = None
_birefnet_transform = None


@dataclass
class LogoDetection:
    """検出されたロゴ領域。"""
    x1: int
    y1: int
    x2: int
    y2: int
    label: str
    confidence_hint: str  # "primary" / "secondary"

    @property
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)

    def with_margin(self, pct: float, img_w: int, img_h: int) -> "LogoDetection":
        """各辺にpct%のマージンを追加した新しいDetectionを返す。"""
        margin_x = int(self.width * pct)
        margin_y = int(self.height * pct)
        return LogoDetection(
            x1=max(0, self.x1 - margin_x),
            y1=max(0, self.y1 - margin_y),
            x2=min(img_w, self.x2 + margin_x),
            y2=min(img_h, self.y2 + margin_y),
            label=self.label,
            confidence_hint=self.confidence_hint,
        )


def is_available() -> bool:
    """Florence-2が利用可能か（torch + CUDAが使えるか）を返す。"""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _ensure_florence():
    """Florence-2 モデルとプロセッサをロード（初回のみ）。"""
    global _florence_model, _florence_processor
    if _florence_model is not None:
        return

    import torch
    from transformers import AutoProcessor, Florence2ForConditionalGeneration

    logger.info("Loading Florence-2-large model...")
    _florence_processor = AutoProcessor.from_pretrained(_FLORENCE_MODEL_ID)
    _florence_model = Florence2ForConditionalGeneration.from_pretrained(
        _FLORENCE_MODEL_ID, torch_dtype=torch.float32,
    ).to("cuda")
    _florence_model.eval()
    logger.info("Florence-2-large model loaded on GPU.")


def _ensure_birefnet():
    """BiRefNet モデルをロード（初回のみ）。"""
    global _birefnet_model, _birefnet_transform
    if _birefnet_model is not None:
        return

    import torch
    from torchvision import transforms
    from transformers import AutoModelForImageSegmentation

    logger.info("Loading BiRefNet model...")
    _birefnet_model = AutoModelForImageSegmentation.from_pretrained(
        _BIREFNET_MODEL_ID, trust_remote_code=True,
    ).to("cuda").half()
    _birefnet_model.eval()

    _birefnet_transform = transforms.Compose([
        transforms.Resize((1024, 1024)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    logger.info("BiRefNet model loaded on GPU.")


def _run_detection(image: Image.Image, task: str, prompt: str) -> list[dict]:
    """単一プロンプトで検出を実行し、bbox + label のリストを返す。"""
    import torch

    _ensure_florence()
    full_prompt = task + prompt
    inputs = _florence_processor(text=full_prompt, images=image, return_tensors="pt").to("cuda")
    with torch.no_grad():
        generated_ids = _florence_model.generate(**inputs, max_new_tokens=1024, num_beams=3)
    generated_text = _florence_processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
    parsed = _florence_processor.post_process_generation(
        generated_text, task=task, image_size=image.size,
    )

    results = []
    data = parsed.get(task, {})
    bboxes = data.get("bboxes", [])
    labels = data.get("bboxes_labels", data.get("labels", []))
    for bbox, label in zip(bboxes, labels):
        results.append({"bbox": bbox, "label": label})
    return results


def remove_background(image: Image.Image) -> Image.Image:
    """BiRefNetを使って画像の背景を除去し、透過PNGとして返す。"""
    import torch
    from torchvision import transforms

    _ensure_birefnet()

    input_tensor = _birefnet_transform(image.convert("RGB")).unsqueeze(0).to("cuda").half()
    with torch.no_grad():
        preds = _birefnet_model(input_tensor)[-1].sigmoid().cpu()

    mask = transforms.ToPILImage()(preds[0].squeeze()).resize(image.size)
    result = image.convert("RGBA")
    result.putalpha(mask)
    return result


def _is_ps2_logo_region(bbox: list, img_w: int, img_h: int) -> bool:
    """PS2ロゴ（左上の「PlayStation 2」帯）かどうかを推定する。"""
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1

    in_top_10pct = y1 < img_h * 0.12
    is_narrow_height = h < img_h * 0.10
    is_left_aligned = x1 < img_w * 0.15
    is_not_full_width = w < img_w * 0.65

    return in_top_10pct and is_narrow_height and is_left_aligned and is_not_full_width


def detect_logo(image_or_path: "Image.Image | Path | str", margin_pct: float = 0.05) -> list[LogoDetection]:
    """カバー画像からタイトルロゴ領域を検出する。

    複数のプロンプト戦略で検出し、PS2ロゴなどのノイズをフィルタリングした上で
    信頼度の高い順にソートして返す。

    Args:
        image_or_path: PIL Image または画像ファイルパス
        margin_pct: bboxの各辺に追加するマージン比率 (0.05 = 5%)

    Returns:
        検出されたロゴ領域のリスト（信頼度順）。空リストなら検出失敗。
    """
    if isinstance(image_or_path, (str, Path)):
        image = Image.open(image_or_path).convert("RGB")
    else:
        image = image_or_path.convert("RGB")

    img_w, img_h = image.size

    strategies = [
        ("<CAPTION_TO_PHRASE_GROUNDING>", "the game title logo"),
        ("<OPEN_VOCABULARY_DETECTION>", "game title logo"),
        ("<OPEN_VOCABULARY_DETECTION>", "title text"),
    ]

    all_detections: list[LogoDetection] = []
    seen_areas: set[int] = set()

    for task, prompt in strategies:
        try:
            results = _run_detection(image, task, prompt)
        except Exception as e:
            logger.warning("Detection failed for %s+'%s': %s", task, prompt, e)
            continue

        for r in results:
            bbox = r["bbox"]

            if _is_ps2_logo_region(bbox, img_w, img_h):
                logger.debug("Filtered out PS2 logo region: %s", bbox)
                continue

            x1, y1, x2, y2 = [int(v) for v in bbox]
            w, h = x2 - x1, y2 - y1

            if w < img_w * 0.08 or h < img_h * 0.04:
                continue

            area = w * h
            area_key = area // 500
            if area_key in seen_areas:
                continue
            seen_areas.add(area_key)

            is_primary = len(all_detections) == 0
            det = LogoDetection(
                x1=x1, y1=y1, x2=x2, y2=y2,
                label=r["label"],
                confidence_hint="primary" if is_primary else "secondary",
            )
            if margin_pct > 0:
                det = det.with_margin(margin_pct, img_w, img_h)

            all_detections.append(det)

    all_detections.sort(key=lambda d: d.area, reverse=True)

    if all_detections:
        all_detections[0].confidence_hint = "primary"
        for d in all_detections[1:]:
            d.confidence_hint = "secondary"

    return all_detections


def extract_logo(
    image_or_path: "Image.Image | Path | str",
    margin_pct: float = 0.05,
    transparent: bool = True,
) -> "Image.Image | None":
    """カバー画像からタイトルロゴを切り出して返す。検出できなければ None。

    Args:
        image_or_path: PIL Image または画像ファイルパス
        margin_pct: bboxの各辺に追加するマージン比率 (0.05 = 5%)
        transparent: True なら BiRefNet で背景除去して透過PNG化する
    """
    if isinstance(image_or_path, (str, Path)):
        image = Image.open(image_or_path).convert("RGBA")
    else:
        image = image_or_path.convert("RGBA")

    rgb_image = image.convert("RGB")
    detections = detect_logo(rgb_image, margin_pct=margin_pct)
    if not detections:
        return None

    best = detections[0]
    cropped = image.crop(best.to_tuple())

    if transparent:
        cropped = remove_background(cropped)

    return cropped


def unload_model() -> None:
    """GPU VRAMを解放する。"""
    global _florence_model, _florence_processor, _birefnet_model, _birefnet_transform
    import torch

    freed = []
    if _florence_model is not None:
        del _florence_model, _florence_processor
        _florence_model = _florence_processor = None
        freed.append("Florence-2")
    if _birefnet_model is not None:
        del _birefnet_model, _birefnet_transform
        _birefnet_model = _birefnet_transform = None
        freed.append("BiRefNet")
    if freed:
        torch.cuda.empty_cache()
        logger.info("Models unloaded (%s), VRAM freed.", ", ".join(freed))
