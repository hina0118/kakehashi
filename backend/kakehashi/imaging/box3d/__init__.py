"""covers画像から3Dボックス画像を生成する。"""
from __future__ import annotations

from kakehashi.imaging.box3d import ps2 as _ps2
from kakehashi.imaging.box3d.base import generate_3dbox

# PS2風テンプレート（DVDトールケース）を使う機種
_PS2_STYLE_SYSTEMS = {"ps2", "ps3", "ps4", "psp", "psvita", "psx"}


def decorators_for(system: str) -> tuple:
    """機種に応じた (decorate_cover, decorate_spine) を返す。該当なしは (None, None)。"""
    if system.lower() in _PS2_STYLE_SYSTEMS:
        return _ps2.decorate_cover, _ps2.decorate_spine
    return None, None


__all__ = ["generate_3dbox", "decorators_for"]
