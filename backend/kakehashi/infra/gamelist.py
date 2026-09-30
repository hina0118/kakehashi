"""ES-DEのgamelist.xmlのパースと差分マージ。

ES-DEのgamelist.xmlは <alternativeEmulator> と <gameList> の2つのトップレベル要素を
持つことがあるため、仮のルート要素で包んでから標準パーサで扱う。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from kakehashi.domain.esde import EDITABLE_FIELDS, EsdeGame

_DECL_RE = re.compile(r"<\?xml[^?]*\?>")


class Gamelist:
    def __init__(self, content: str) -> None:
        m = _DECL_RE.match(content.lstrip("﻿"))
        self._decl = m.group(0) if m else '<?xml version="1.0"?>'
        body = _DECL_RE.sub("", content.lstrip("﻿"), count=1).strip()
        self._root = ET.fromstring(f"<_root_>{body}</_root_>")
        self._list = self._root.find("gameList")
        if self._list is None:
            self._list = ET.SubElement(self._root, "gameList")

    def games(self) -> list[ET.Element]:
        return self._list.findall("game")

    def find(self, path: str) -> ET.Element | None:
        for g in self.games():
            if get_field(g, "path") == path:
                return g
        return None

    def add(self, path: str) -> ET.Element:
        game = ET.SubElement(self._list, "game")
        set_field(game, "path", path)
        return game

    def remove(self, path: str) -> bool:
        game = self.find(path)
        if game is None:
            return False
        self._list.remove(game)
        return True

    def apply(self, diffs: dict[str, dict[str, str]], deleted: set[str] = frozenset()) -> tuple[int, int]:
        """フィールド単位の差分を反映する。未登録のpathは新規エントリとして追加する。

        戻り値は (反映件数, 削除件数)。
        """
        deleted_count = sum(self.remove(p) for p in deleted)
        by_path = {get_field(g, "path"): g for g in self.games()}
        applied = 0
        for path, fields in diffs.items():
            if path in deleted:
                continue
            game = by_path.get(path)
            if game is None:
                game = by_path[path] = self.add(path)
            for key, value in fields.items():
                set_field(game, key, value)
            applied += 1
        return applied, deleted_count

    def serialize(self) -> str:
        parts = [self._decl]
        for child in self._root:
            child.tail = None
            ET.indent(child, space="\t")
            parts.append(ET.tostring(child, encoding="unicode"))
        return "\n".join(parts) + "\n"

    def to_models(self) -> list[EsdeGame]:
        return [to_model(g) for g in self.games()]


def get_field(game: ET.Element, key: str) -> str:
    el = game.find(key)
    return (el.text or "") if el is not None else ""


def set_field(game: ET.Element, key: str, value: str) -> None:
    el = game.find(key)
    if value:
        if el is None:
            el = ET.SubElement(game, key)
        el.text = value
    elif el is not None:
        game.remove(el)


def to_model(game: ET.Element) -> EsdeGame:
    known = {"path", *EDITABLE_FIELDS}
    return EsdeGame(
        path=get_field(game, "path"),
        **{f: get_field(game, f) for f in EDITABLE_FIELDS},
        extra={child.tag: (child.text or "") for child in game if child.tag not in known},
    )
