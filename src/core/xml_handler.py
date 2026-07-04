import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def parse_gamelist_content(content: str) -> tuple[ET.Element, list[ET.Element], str]:
    """gamelist.xml の文字列内容をパースし (_root_要素, game要素リスト, XML宣言) を返す。

    ES-DE の gamelist.xml は <alternativeEmulator> と <gameList> の
    2トップレベル要素を持つため、_root_ でラップして標準パーサで処理する。
    """
    decl_match = re.match(r'<\?xml[^?]*\?>', content)
    decl = decl_match.group(0) if decl_match else '<?xml version="1.0"?>'
    body = re.sub(r'<\?xml[^?]*\?>\s*', '', content).strip()
    root_elem = ET.fromstring(f'<_root_>{body}</_root_>')
    gamelist = root_elem.find('gameList')
    games = gamelist.findall('game') if gamelist is not None else []
    return root_elem, games, decl


def parse_gamelist(path: str) -> tuple[ET.Element, list[ET.Element], str]:
    """gamelist.xml ファイルを読み込んでパースする。"""
    content = Path(path).read_text(encoding="utf-8")
    return parse_gamelist_content(content)


def get_field(game: ET.Element, key: str) -> str:
    el = game.find(key)
    return (el.text or "") if el is not None else ""


def set_field(game: ET.Element, key: str, value: str) -> None:
    el = game.find(key)
    if value:
        if el is None:
            el = ET.SubElement(game, key)
        el.text = value
    else:
        if el is not None:
            game.remove(el)


def serialize_gamelist(root_elem: ET.Element, decl: str) -> str:
    parts = [decl]
    for child in root_elem:
        child.tail = None
        ET.indent(child, space='\t')
        parts.append(ET.tostring(child, encoding='unicode'))
    return '\n'.join(parts) + '\n'


def merge_gamelist_diff(
    content: str,
    diffs: dict[str, dict[str, str]],
    deleted_paths: set[str],
) -> tuple[str, int, int]:
    """リモートの最新gamelist.xml内容に、フィールド単位の差分だけをマージする。

    diffs: {path値: {タグ名: 新しい値}} 形式の差分。path値で対象<game>を特定し、
           該当タグだけを上書きする。kakehashiが管理しない未知タグ(favorite等)には触れない。
    deleted_paths: 削除対象のpath値の集合。該当<game>要素をgameListごと除去する。

    戻り値: (マージ後のXML文字列, 反映件数, 削除件数)
    """
    root_elem, games, decl = parse_gamelist_content(content)
    gamelist = root_elem.find("gameList")

    by_path = {get_field(g, "path"): g for g in games}

    deleted_count = 0
    if gamelist is not None:
        for path_val in deleted_paths:
            game = by_path.get(path_val)
            if game is not None:
                gamelist.remove(game)
                deleted_count += 1

    applied_count = 0
    for path_val, fields in diffs.items():
        if path_val in deleted_paths:
            continue
        game = by_path.get(path_val)
        if game is None:
            continue
        for key, value in fields.items():
            set_field(game, key, value)
        applied_count += 1

    return serialize_gamelist(root_elem, decl), applied_count, deleted_count


def save_gamelist_file(path: str, content: str, backup_max: int) -> None:
    p = Path(path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p.parent / f"{p.name}.{timestamp}.bak"
    shutil.copy2(p, bak)
    backups = sorted(p.parent.glob(f"{p.name}.*.bak"))
    for old in backups[:-backup_max]:
        old.unlink()
    p.write_text(content, encoding="utf-8")
