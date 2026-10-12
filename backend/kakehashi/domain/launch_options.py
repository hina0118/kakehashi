"""Steamの起動オプションに、指定したオプションを足す（すでにあるものは足さない）。

起動オプションは「環境変数・ラッパー %command% 引数」の形。%command% が無いときは、
全体がゲームへの引数として扱われる（Steamの仕様）。
"""
from __future__ import annotations

import re

from pydantic import BaseModel

COMMAND = "%command%"
_TOKEN = re.compile(r"""(?:[^\s"']+|"[^"]*"|'[^']*')+""")
_ENV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


class MergeResult(BaseModel):
    options: str
    added: list[str] = []
    replaced: list[str] = []
    """同じ環境変数の値を置き換えたもの（"旧 → 新"）"""


def tokenize(options: str) -> list[str]:
    """空白で区切る（引用符の中の空白では区切らず、引用符もそのまま残す）。"""
    return _TOKEN.findall(options)


def _split(tokens: list[str], default_to_args: bool) -> tuple[list[str], list[str], bool]:
    """(%command% の前, 後, %command% があったか)。無ければ環境変数は前、それ以外は後（default_to_args）か前。"""
    if COMMAND in tokens:
        i = tokens.index(COMMAND)
        return tokens[:i], tokens[i + 1:], True
    if default_to_args:
        return [], tokens, False
    pre = [t for t in tokens if _ENV.match(t)]
    return pre, [t for t in tokens if not _ENV.match(t)], False


def merge_launch_options(current: str, add: str) -> MergeResult:
    """current に add を足す。同じものがあれば足さず、同じ環境変数で値が違えば置き換える。"""
    pre, post, had_command = _split(tokenize(current), default_to_args=True)
    add_pre, add_post, add_command = _split(tokenize(add), default_to_args=False)
    added: list[str] = []
    replaced: list[str] = []

    for t in add_pre:
        if t in pre:
            continue
        m = _ENV.match(t)
        same_key = next((i for i, p in enumerate(pre) if m and (pm := _ENV.match(p)) and pm.group(1) == m.group(1)), None)
        if same_key is not None:
            replaced.append(f"{pre[same_key]} → {t}")
            pre[same_key] = t
        elif m:
            # 環境変数は、ラッパー（gamemoderun など）より前に置く
            n_env = next((i for i, p in enumerate(pre) if not _ENV.match(p)), len(pre))
            pre.insert(n_env, t)
            added.append(t)
        else:
            pre.append(t)
            added.append(t)
    for t in add_post:
        if t not in post:
            post.append(t)
            added.append(t)

    if pre or had_command or add_command:
        options = " ".join([*pre, COMMAND, *post])
    else:
        options = " ".join(post)
    return MergeResult(options=options, added=added, replaced=replaced)
