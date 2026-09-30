"""Steam DeckへのSSH/SFTPアクセス。

サービス層は RemoteFS プロトコルだけに依存し、テストではインメモリ実装に差し替える。
"""
from __future__ import annotations

import posixpath
import stat as _stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, ContextManager, Iterator, Protocol

from kakehashi.config import SyncSettings


class DeckNotConfiguredError(RuntimeError):
    """Steam Deckの接続先が未設定。"""


class DeckConnectionError(RuntimeError):
    """Steam Deckへの接続・認証に失敗した。"""


class RemoteFS(Protocol):
    def read_text(self, path: str) -> str: ...
    def write_text(self, path: str, content: str) -> None: ...
    def read_bytes(self, path: str) -> bytes: ...
    def write_bytes(self, path: str, content: bytes) -> None: ...
    def listdir(self, path: str) -> list[str]: ...
    def exists(self, path: str) -> bool: ...
    def remove(self, path: str) -> None: ...


class TransferFS(RemoteFS, Protocol):
    """ファイル転送もできる RemoteFS。"""
    def list_files(self, path: str) -> dict[str, int]: ...
    def list_dirs(self, path: str) -> list[str]: ...
    def walk_files(self, path: str) -> Iterator[str]: ...
    def run(self, command: str, timeout: float = 30) -> tuple[int, str, str]: ...
    def upload(
        self, tasks: list[tuple[Path, str]], overwrite: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> "TransferResult": ...
    def download(
        self, tasks: list[tuple[str, Path]],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> "TransferResult": ...


DeckConnector = Callable[[], ContextManager[TransferFS]]


@dataclass
class TransferResult:
    transferred: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class DeckClient:
    """接続済みのSSH/SFTPセッション。open_deck() で生成する。"""

    def __init__(self, ssh, sftp) -> None:
        self._ssh = ssh
        self._sftp = sftp

    def read_text(self, path: str) -> str:
        with self._sftp.open(path, "r") as f:
            return f.read().decode("utf-8")

    def write_text(self, path: str, content: str) -> None:
        self.write_bytes(path, content.encode("utf-8"))

    def read_bytes(self, path: str) -> bytes:
        with self._sftp.open(path, "rb") as f:
            return f.read()

    def write_bytes(self, path: str, content: bytes) -> None:
        """一時ファイルに書いてから置き換える（書き込み途中で切断されても元のファイルが壊れない）。"""
        self.makedirs(posixpath.dirname(path))
        tmp = f"{path}.kakehashi-tmp"
        with self._sftp.open(tmp, "wb") as f:
            f.write(content)
        self._sftp.posix_rename(tmp, path)

    def listdir(self, path: str) -> list[str]:
        return self._sftp.listdir(path)

    def exists(self, path: str) -> bool:
        try:
            self._sftp.stat(path)
            return True
        except FileNotFoundError:
            return False

    def remove(self, path: str) -> None:
        self._sftp.remove(path)

    def makedirs(self, path: str) -> None:
        current = ""
        for part in path.split("/"):
            if not part:
                continue
            current = f"{current}/{part}"
            try:
                self._sftp.stat(current)
            except FileNotFoundError:
                self._sftp.mkdir(current)

    def list_files(self, path: str) -> dict[str, int]:
        """path直下のファイル名とサイズ。フォルダが無ければ空。"""
        try:
            entries = self._sftp.listdir_attr(path)
        except FileNotFoundError:
            return {}
        return {
            e.filename: e.st_size or 0
            for e in entries if not (e.st_mode and _stat.S_ISDIR(e.st_mode))
        }

    def list_dirs(self, path: str) -> list[str]:
        """path直下のフォルダ名。フォルダが無ければ空。"""
        try:
            entries = self._sftp.listdir_attr(path)
        except FileNotFoundError:
            return []
        return sorted(e.filename for e in entries if e.st_mode and _stat.S_ISDIR(e.st_mode))

    def walk_files(self, path: str) -> Iterator[str]:
        """path配下のファイルを再帰的に列挙する（存在しなければ何も返さない）。"""
        try:
            entries = self._sftp.listdir_attr(path)
        except FileNotFoundError:
            return
        for e in entries:
            child = f"{path}/{e.filename}"
            if e.st_mode and _stat.S_ISDIR(e.st_mode):
                yield from self.walk_files(child)
            else:
                yield child

    def upload(
        self,
        tasks: list[tuple[Path, str]],
        overwrite: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> TransferResult:
        """(ローカルパス, リモートパス) を順に転送する。overwrite=False なら同サイズのファイルは飛ばす。"""
        result = TransferResult()
        total = len(tasks)
        for i, (local, remote) in enumerate(tasks, 1):
            try:
                if not overwrite:
                    try:
                        if self._sftp.stat(remote).st_size == local.stat().st_size:
                            result.skipped += 1
                            continue
                    except FileNotFoundError:
                        pass
                self.makedirs(posixpath.dirname(remote))
                self._sftp.put(str(local), remote)
                result.transferred += 1
            except Exception as e:  # 1ファイルの失敗で全体を止めない
                result.errors.append(f"{local.name}: {e}")
            finally:
                if on_progress:
                    on_progress(i, total)
        return result

    def download(
        self,
        tasks: list[tuple[str, Path]],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> TransferResult:
        """(リモートパス, ローカルパス) を順に取得する。途中で失敗したファイルは残さない。"""
        result = TransferResult()
        total = len(tasks)
        for i, (remote, local) in enumerate(tasks, 1):
            tmp = local.with_name(local.name + ".part")
            try:
                local.parent.mkdir(parents=True, exist_ok=True)
                self._sftp.get(remote, str(tmp))
                tmp.replace(local)
                result.transferred += 1
            except Exception as e:
                tmp.unlink(missing_ok=True)
                result.errors.append(f"{posixpath.basename(remote)}: {e}")
            finally:
                if on_progress:
                    on_progress(i, total)
        return result

    def run(self, command: str, timeout: float = 30) -> tuple[int, str, str]:
        _stdin, stdout, stderr = self._ssh.exec_command(command, timeout=timeout)
        code = stdout.channel.recv_exit_status()
        return code, stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace")


@contextmanager
def open_deck(settings: SyncSettings, timeout: float = 15) -> Iterator[DeckClient]:
    if not settings.host:
        raise DeckNotConfiguredError("Steam Deckのホスト（sync.host）が設定されていません。")
    import paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=settings.host, port=settings.port,
            username=settings.username, password=settings.password,
            timeout=timeout, look_for_keys=False, allow_agent=False,
        )
        sftp = ssh.open_sftp()
    except (OSError, paramiko.SSHException) as e:
        ssh.close()
        raise DeckConnectionError(f"Steam Deck（{settings.host}）に接続できません: {e}") from e
    try:
        yield DeckClient(ssh, sftp)
    finally:
        sftp.close()
        ssh.close()


def write_with_backup(fs: RemoteFS, path: str, content: str | bytes, backup_max: int) -> None:
    """既存ファイルを `{name}.{日時}.bak` に退避してから書き込み、古いバックアップを間引く。"""
    directory, name = posixpath.split(path)
    if fs.exists(path):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fs.write_bytes(f"{directory}/{name}.{stamp}.bak", fs.read_bytes(path))
        backups = sorted(
            f for f in fs.listdir(directory) if f.startswith(f"{name}.") and f.endswith(".bak")
        )
        excess = backups[:-backup_max] if backup_max > 0 else backups
        for old in excess:
            fs.remove(f"{directory}/{old}")
    fs.write_bytes(path, content.encode("utf-8") if isinstance(content, str) else content)
