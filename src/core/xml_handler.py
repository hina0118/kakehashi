import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def parse_gamelist(path: str) -> tuple[ET.Element, list[ET.Element], str]:
    """gamelist.xml をパースし (_root_要素, game要素リスト, XML宣言) を返す。

    ES-DE の gamelist.xml は <alternativeEmulator> と <gameList> の
    2トップレベル要素を持つため、_root_ でラップして標準パーサで処理する。
    """
    content = Path(path).read_text(encoding="utf-8")
    decl_match = re.match(r'<\?xml[^?]*\?>', content)
    decl = decl_match.group(0) if decl_match else '<?xml version="1.0"?>'
    body = re.sub(r'<\?xml[^?]*\?>\s*', '', content).strip()
    root_elem = ET.fromstring(f'<_root_>{body}</_root_>')
    gamelist = root_elem.find('gameList')
    games = gamelist.findall('game') if gamelist is not None else []
    return root_elem, games, decl


def serialize_gamelist(root_elem: ET.Element, decl: str) -> str:
    parts = [decl]
    for child in root_elem:
        child.tail = None
        ET.indent(child, space='\t')
        parts.append(ET.tostring(child, encoding='unicode'))
    return '\n'.join(parts) + '\n'


def save_gamelist_file(path: str, content: str, backup_max: int) -> None:
    p = Path(path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p.parent / f"{p.name}.{timestamp}.bak"
    shutil.copy2(p, bak)
    backups = sorted(p.parent.glob(f"{p.name}.*.bak"))
    for old in backups[:-backup_max]:
        old.unlink()
    p.write_text(content, encoding="utf-8")
