"""生成した画像を保存前に確認するための一時置き場（メモリ上、古いものから破棄）。"""
from __future__ import annotations

import io
import threading
import uuid
from collections import OrderedDict

from PIL import Image
from pydantic import BaseModel

from kakehashi.errors import NotFoundError


class PreviewInfo(BaseModel):
    id: str
    width: int
    height: int


class PreviewStore:
    def __init__(self, capacity: int = 30) -> None:
        self._items: OrderedDict[str, tuple[bytes, PreviewInfo]] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def put(self, image: Image.Image) -> PreviewInfo:
        buf = io.BytesIO()
        image.save(buf, "PNG")
        info = PreviewInfo(id=uuid.uuid4().hex, width=image.width, height=image.height)
        with self._lock:
            self._items[info.id] = (buf.getvalue(), info)
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)
        return info

    def get(self, preview_id: str) -> bytes:
        with self._lock:
            item = self._items.get(preview_id)
        if item is None:
            raise NotFoundError("プレビューの有効期限が切れました。もう一度生成してください。")
        return item[0]
