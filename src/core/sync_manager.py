from __future__ import annotations

import stat as _stat
from datetime import datetime
from pathlib import Path
from typing import Callable

try:
    import paramiko
    _PARAMIKO_OK = True
except ImportError:
    _PARAMIKO_OK = False


def _sftp_makedirs(sftp: "paramiko.SFTPClient", remote_dir: str) -> None:
    """SFTPでリモートディレクトリパスを再帰的に作成する（存在済みはスキップ）。"""
    parts = remote_dir.split("/")
    path = ""
    for part in parts:
        if not part:
            continue
        path = f"{path}/{part}"
        try:
            sftp.stat(path)
        except FileNotFoundError:
            try:
                sftp.mkdir(path)
            except Exception:
                pass  # 競合・権限エラーは無視


def test_connection(host: str, port: int, username: str, password: str) -> None:
    """SSH接続テスト。失敗時は例外を送出する。"""
    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cl.connect(
        hostname=host, port=port, username=username, password=password,
        timeout=10, look_for_keys=False, allow_agent=False,
    )
    cl.close()


def transfer_files(
    host: str,
    port: int,
    username: str,
    password: str,
    tasks: list[tuple[Path, str]],
    overwrite: bool,
    on_log: Callable[[str], None],
    on_progress: Callable[[int], None],
) -> tuple[int, int, int]:
    """ファイル転送を実行する。戻り値は (転送数, スキップ数, エラー数)。"""
    ok = skipped = errors = 0

    on_log(f"[{datetime.now().strftime('%H:%M:%S')}] 接続中: {host} ...")
    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cl.connect(
        hostname=host, port=port, username=username, password=password,
        timeout=15, look_for_keys=False, allow_agent=False,
    )
    sftp = cl.open_sftp()
    on_log("  接続OK\n")

    total = len(tasks)
    on_log(f"転送対象: {total} ファイル\n")
    if total == 0:
        on_log("転送するファイルがありません。")
        sftp.close()
        cl.close()
        return ok, skipped, errors

    for i, (lp, rp) in enumerate(tasks, 1):
        if not overwrite:
            try:
                remote_size = sftp.stat(rp).st_size
                if remote_size == lp.stat().st_size:
                    on_log(f"  → スキップ: {lp.name}")
                    skipped += 1
                    on_progress(i * 100 // total)
                    continue
            except FileNotFoundError:
                pass

        _sftp_makedirs(sftp, rp.rsplit("/", 1)[0])
        try:
            sftp.put(str(lp), rp)
            on_log(f"  ✓ {lp.name}")
            ok += 1
        except Exception as ue:
            on_log(f"  ✗ {lp.name}: {ue}")
            errors += 1

        on_progress(i * 100 // total)

    sftp.close()
    cl.close()
    return ok, skipped, errors


def _collect_remote_files(
    sftp: "paramiko.SFTPClient",
    remote_dir: str,
    local_dir: Path,
    tasks: list[tuple[str, Path]],
) -> None:
    """リモートディレクトリを再帰的に走査して (remote_path, local_path) をtasksに追記する。"""
    try:
        for entry in sftp.listdir_attr(remote_dir):
            rp = f"{remote_dir}/{entry.filename}"
            lp = local_dir / entry.filename
            if entry.st_mode and _stat.S_ISDIR(entry.st_mode):
                _collect_remote_files(sftp, rp, lp, tasks)
            else:
                tasks.append((rp, lp))
    except FileNotFoundError:
        pass


def pull_files(
    host: str,
    port: int,
    username: str,
    password: str,
    file_tasks: list[tuple[str, Path]],
    dir_mappings: list[tuple[str, Path]],
    overwrite: bool,
    on_log: Callable[[str], None],
    on_progress: Callable[[int], None],
) -> tuple[int, int, int]:
    """SteamDeck→ローカルへファイルをプルする。戻り値は (取得数, スキップ数, エラー数)。

    file_tasks:   [(remote_path, local_path), ...] 単一ファイルの転送指示
    dir_mappings: [(remote_dir, local_dir), ...]   ディレクトリ単位（再帰列挙）
    """
    ok = skipped = errors = 0

    on_log(f"[{datetime.now().strftime('%H:%M:%S')}] 接続中: {host} ...")
    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cl.connect(
        hostname=host, port=port, username=username, password=password,
        timeout=15, look_for_keys=False, allow_agent=False,
    )
    sftp = cl.open_sftp()
    on_log("  接続OK\n")

    # 単一ファイル指定分：リモートに存在するものだけ追加
    tasks: list[tuple[str, Path]] = []
    for rp, lp in file_tasks:
        try:
            sftp.stat(rp)
            tasks.append((rp, lp))
        except FileNotFoundError:
            on_log(f"  [スキップ] リモートに存在しません: {rp.rsplit('/', 1)[-1]}")

    # ディレクトリ指定分を再帰列挙して追加
    for remote_dir, local_dir in dir_mappings:
        _collect_remote_files(sftp, remote_dir, local_dir, tasks)

    total = len(tasks)
    on_log(f"取得対象: {total} ファイル\n")
    if total == 0:
        on_log("取得するファイルがありません。")
        sftp.close()
        cl.close()
        return ok, skipped, errors

    for i, (rp, lp) in enumerate(tasks, 1):
        if not overwrite and lp.exists():
            if sftp.stat(rp).st_size == lp.stat().st_size:
                on_log(f"  → スキップ: {lp.name}")
                skipped += 1
                on_progress(i * 100 // total)
                continue

        lp.parent.mkdir(parents=True, exist_ok=True)
        try:
            sftp.get(rp, str(lp))
            on_log(f"  ✓ {lp.name}")
            ok += 1
        except Exception as ue:
            on_log(f"  ✗ {lp.name}: {ue}")
            errors += 1

        on_progress(i * 100 // total)

    sftp.close()
    cl.close()
    return ok, skipped, errors
