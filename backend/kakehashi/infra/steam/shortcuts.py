"""shortcuts.vdf（非Steamゲームの一覧）の操作。"""
from __future__ import annotations

import posixpath
import zlib
from dataclasses import dataclass

from kakehashi.infra.steam import binary_vdf as bvdf
from kakehashi.infra.steam.binary_vdf import Node


def shortcut_appid(exe: str, name: str) -> int:
    """非Steamゲームの appID（符号なし32bit）。Steam ROM Manager などと同じ算出方法。

    exe は shortcuts.vdf に書く値そのもの（引用符付き）を渡す。
    """
    return (zlib.crc32((exe + name).encode("utf-8")) & 0xFFFFFFFF) | 0x80000000


def to_signed(appid: int) -> int:
    return appid - (1 << 32) if appid >= (1 << 31) else appid


def to_unsigned(appid: int) -> int:
    return appid & 0xFFFFFFFF


def rungame_id(appid: int) -> int:
    """steam://rungameid/ で使う64bitのID。"""
    return (to_unsigned(appid) << 32) | 0x02000000


def quote(path: str) -> str:
    return f'"{path}"'


def normalize_path(value: str) -> str:
    """Exe/StartDir の値を比較用に正規化する（引用符・重複した / ・末尾の / を除く）。"""
    p = value.strip().strip('"')
    return posixpath.normpath(p) if p else ""


def entry_appid(entry: Node) -> int | None:
    v = entry.get("appid")
    return to_unsigned(v) if isinstance(v, int) else None


@dataclass
class ShortcutSpec:
    appid: int
    name: str
    exe: str
    """引用符付きの起動ファイルのパス"""
    start_dir: str
    """引用符付きの作業フォルダ"""
    icon: str | None = ""
    """None なら既存の値を残す"""
    launch_options: str | None = ""
    """None なら既存の値を残す"""


class Shortcuts:
    def __init__(self, data: bytes | None) -> None:
        self.root = bvdf.loads(data) if data else Node([bvdf.Item(bvdf.T_MAP, "shortcuts", Node())])
        item = self.root.find("shortcuts")
        if item is None or item.type != bvdf.T_MAP:
            raise bvdf.VdfError("shortcuts.vdf に shortcuts がありません")
        self._list: Node = item.value  # type: ignore[assignment]

    def entries(self) -> list[Node]:
        return [i.value for i in self._list.items if i.type == bvdf.T_MAP]  # type: ignore[misc]

    def find(self, appid: int) -> Node | None:
        target = to_unsigned(appid)
        for e in self.entries():
            v = e.get("appid")
            if isinstance(v, int) and to_unsigned(v) == target:
                return e
        return None

    def find_by_exe(self, exe_path: str) -> Node | None:
        """起動ファイルのパスが一致するエントリ（引用符や / の重複の違いは無視する）。"""
        target = normalize_path(exe_path)
        return next((e for e in self.entries() if normalize_path(str(e.get("Exe") or "")) == target), None)

    def upsert(self, spec: ShortcutSpec) -> bool:
        """appID が一致するエントリを更新し、無ければ追加する。追加したら True。

        既存のエントリでは kakehashi が管理する項目だけを書き換え、
        プレイ時間・非表示設定・タグなど Steam 側で変わる項目はそのまま残す。
        """
        entry = self.find(spec.appid)
        created = entry is None
        if entry is None:
            entry = Node()
            entry.set_int32("appid", to_signed(spec.appid))
            for key, value, t in [
                ("AppName", "", bvdf.T_STRING), ("Exe", "", bvdf.T_STRING), ("StartDir", "", bvdf.T_STRING),
                ("icon", "", bvdf.T_STRING), ("ShortcutPath", "", bvdf.T_STRING),
                ("LaunchOptions", "", bvdf.T_STRING), ("IsHidden", 0, bvdf.T_INT32),
                ("AllowDesktopConfig", 1, bvdf.T_INT32), ("AllowOverlay", 1, bvdf.T_INT32),
                ("OpenVR", 0, bvdf.T_INT32), ("Devkit", 0, bvdf.T_INT32), ("DevkitGameID", "", bvdf.T_STRING),
                ("DevkitOverrideAppID", 0, bvdf.T_INT32), ("LastPlayTime", 0, bvdf.T_INT32),
                ("FlatpakAppID", "", bvdf.T_STRING), ("sortas", "", bvdf.T_STRING),
            ]:
                entry.set(key, value, t)
            entry.set("tags", Node(), bvdf.T_MAP)
            self._list.items.append(bvdf.Item(bvdf.T_MAP, str(len(self._list.items)), entry))
        entry.set_int32("appid", to_signed(spec.appid))
        entry.set_str("AppName", spec.name)
        entry.set_str("Exe", spec.exe)
        entry.set_str("StartDir", spec.start_dir)
        if spec.icon is not None:
            entry.set_str("icon", spec.icon)
        if spec.launch_options is not None:
            entry.set_str("LaunchOptions", spec.launch_options)
        self._reindex()
        return created

    def remove(self, appid: int) -> bool:
        entry = self.find(appid)
        if entry is None:
            return False
        self._list.items = [i for i in self._list.items if i.value is not entry]
        self._reindex()
        return True

    def _reindex(self) -> None:
        # エントリのキーは "0", "1", ... の連番でなければならない
        for n, item in enumerate(i for i in self._list.items if i.type == bvdf.T_MAP):
            item.key = str(n)

    def dumps(self) -> bytes:
        return bvdf.dumps(self.root)
