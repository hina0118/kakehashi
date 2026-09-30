"""Steamのバイナリ VDF（shortcuts.vdf など）の読み書き。

Steam が書いた内容を kakehashi が知らない項目も含めて失わずに書き戻せるよう、
キーの順序と値の型をそのまま保持する。ノードは (型, キー, 値) のリストで表す。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Union

T_MAP = 0x00
T_STRING = 0x01
T_INT32 = 0x02
T_FLOAT32 = 0x03
T_UINT64 = 0x07
T_END = 0x08

Value = Union["Node", str, int, float]


@dataclass
class Item:
    type: int
    key: str
    value: Value


@dataclass
class Node:
    items: list[Item] = field(default_factory=list)

    def find(self, key: str) -> Item | None:
        """キーを大文字小文字を区別せずに探す（Steamのバージョンで "appname"/"AppName" が揺れる）。"""
        k = key.lower()
        return next((i for i in self.items if i.key.lower() == k), None)

    def get(self, key: str, default: Value | None = None) -> Value | None:
        item = self.find(key)
        return item.value if item else default

    def set(self, key: str, value: Value, type_: int) -> None:
        item = self.find(key)
        if item:
            item.type, item.value = type_, value
        else:
            self.items.append(Item(type_, key, value))

    def set_str(self, key: str, value: str) -> None:
        self.set(key, value, T_STRING)

    def set_int32(self, key: str, value: int) -> None:
        self.set(key, value, T_INT32)

    def remove(self, key: str) -> None:
        k = key.lower()
        self.items = [i for i in self.items if i.key.lower() != k]


class VdfError(ValueError):
    pass


def loads(data: bytes) -> Node:
    root, pos = _read_map(data, 0)
    if pos != len(data):
        # 末尾に余分な終端（0x08）が付いたファイルもあるので、終端以外が残っていたときだけエラーにする
        if any(b != T_END for b in data[pos:]):
            raise VdfError(f"VDFの末尾に解釈できないデータがあります（位置 {pos}）")
    return root


def _read_cstr(data: bytes, pos: int) -> tuple[str, int]:
    end = data.find(b"\x00", pos)
    if end < 0:
        raise VdfError(f"文字列が終端していません（位置 {pos}）")
    return data[pos:end].decode("utf-8", errors="surrogateescape"), end + 1


def _read_map(data: bytes, pos: int) -> tuple[Node, int]:
    node = Node()
    while pos < len(data):
        t = data[pos]
        pos += 1
        if t == T_END:
            return node, pos
        key, pos = _read_cstr(data, pos)
        if t == T_MAP:
            value, pos = _read_map(data, pos)
        elif t == T_STRING:
            value, pos = _read_cstr(data, pos)
        elif t == T_INT32:
            (value,) = struct.unpack_from("<i", data, pos)
            pos += 4
        elif t == T_FLOAT32:
            (value,) = struct.unpack_from("<f", data, pos)
            pos += 4
        elif t == T_UINT64:
            (value,) = struct.unpack_from("<Q", data, pos)
            pos += 8
        else:
            raise VdfError(f"未対応の型です: 0x{t:02x}（キー {key!r}）")
        node.items.append(Item(t, key, value))
    # ルートは終端を持たないこともある
    return node, pos


def dumps(node: Node) -> bytes:
    out = bytearray()
    _write_map(out, node)
    return bytes(out)


def _write_map(out: bytearray, node: Node) -> None:
    for item in node.items:
        out.append(item.type)
        out += item.key.encode("utf-8", errors="surrogateescape") + b"\x00"
        if item.type == T_MAP:
            _write_map(out, item.value)  # type: ignore[arg-type]
        elif item.type == T_STRING:
            out += str(item.value).encode("utf-8", errors="surrogateescape") + b"\x00"
        elif item.type == T_INT32:
            out += struct.pack("<i", int(item.value))  # type: ignore[arg-type]
        elif item.type == T_FLOAT32:
            out += struct.pack("<f", float(item.value))  # type: ignore[arg-type]
        elif item.type == T_UINT64:
            out += struct.pack("<Q", int(item.value))  # type: ignore[arg-type]
        else:
            raise VdfError(f"未対応の型です: 0x{item.type:02x}")
    out.append(T_END)
