"""Steamのテキスト VDF（KeyValues 形式: config.vdf / loginusers.vdf など）の読み書き。

重複キーやキーの順序も保ったまま書き戻せるよう、ノードは (キー, 値) のリストで表す。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

Value = Union["KV", str]


@dataclass
class KV:
    items: list[tuple[str, Value]] = field(default_factory=list)

    def get(self, key: str) -> Value | None:
        k = key.lower()
        return next((v for kk, v in self.items if kk.lower() == k), None)

    def child(self, key: str, create: bool = False) -> KV | None:
        """子ノードを返す。create=True なら無ければ作る。"""
        v = self.get(key)
        if isinstance(v, KV):
            return v
        if not create:
            return None
        node = KV()
        self.items.append((key, node))
        return node

    def path(self, *keys: str, create: bool = False) -> KV | None:
        node: KV | None = self
        for k in keys:
            node = node.child(k, create=create) if node else None
        return node

    def set(self, key: str, value: Value) -> None:
        k = key.lower()
        for i, (kk, _) in enumerate(self.items):
            if kk.lower() == k:
                self.items[i] = (kk, value)
                return
        self.items.append((key, value))

    def remove(self, key: str) -> bool:
        k = key.lower()
        before = len(self.items)
        self.items = [(kk, v) for kk, v in self.items if kk.lower() != k]
        return len(self.items) != before


class VdfSyntaxError(ValueError):
    pass


_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl + 1
        elif c in "{}":
            yield c, i
            i += 1
        elif c == '"':
            buf = []
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(_ESCAPES.get(text[i + 1], "\\" + text[i + 1]))
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            if i >= n:
                raise VdfSyntaxError("文字列が閉じていません")
            yield "".join(buf), -1
            i += 1
        else:
            # 引用符なしのトークン（まれに使われる）
            start = i
            while i < n and text[i] not in ' \t\r\n{}"':
                i += 1
            yield text[start:i], -1


def loads(text: str) -> KV:
    tokens = list(_tokens(text.lstrip("﻿")))
    pos = 0

    def parse_block(top: bool) -> KV:
        nonlocal pos
        node = KV()
        while pos < len(tokens):
            tok, where = tokens[pos]
            if tok == "}" and where >= 0:
                if top:
                    raise VdfSyntaxError("対応しない '}' があります")
                pos += 1
                return node
            if where >= 0:  # '{'
                raise VdfSyntaxError("キーの前に '{' があります")
            key = tok
            pos += 1
            if pos >= len(tokens):
                raise VdfSyntaxError(f"キー {key!r} に値がありません")
            val, vwhere = tokens[pos]
            if val == "{" and vwhere >= 0:
                pos += 1
                node.items.append((key, parse_block(False)))
            else:
                node.items.append((key, val))
                pos += 1
        if not top:
            raise VdfSyntaxError("'}' が足りません")
        return node

    return parse_block(True)


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(node: KV) -> str:
    lines: list[str] = []

    def walk(n: KV, depth: int) -> None:
        pad = "\t" * depth
        for k, v in n.items:
            if isinstance(v, KV):
                lines.append(f"{pad}{_quote(k)}")
                lines.append(f"{pad}{{")
                walk(v, depth + 1)
                lines.append(f"{pad}}}")
            else:
                lines.append(f"{pad}{_quote(k)}\t\t{_quote(v)}")

    walk(node, 0)
    return "\n".join(lines) + "\n"
