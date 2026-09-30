"""アプリ全体で共有する設定とサービスの組み立て。API と MCP の両方から使う。"""
from __future__ import annotations

from contextlib import AbstractContextManager
from functools import cached_property

from kakehashi.config import Config, data_dir, load_config, save_config
from kakehashi.infra.deck import TransferFS, open_deck
from kakehashi.infra.doujin_db import DoujinDB
from kakehashi.infra.media_store import PendingDeletions
from kakehashi.services.doujin import DoujinService
from kakehashi.services.esde import EsdeService
from kakehashi.services.jobs import JobManager
from kakehashi.services.media import MediaService
from kakehashi.services.previews import PreviewStore


class AppContext:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or load_config()

    @property
    def config(self) -> Config:
        return self._config

    def update_config(self, config: Config) -> None:
        save_config(config)
        self._config = config

    def connect(self) -> AbstractContextManager[TransferFS]:
        return open_deck(self._config.sync)

    # connect はテストで差し替えられるため、サービスには束縛済みメソッドではなく
    # 呼び出し時に解決するラムダを渡す
    def _connector(self):
        return lambda: self.connect()

    @cached_property
    def jobs(self) -> JobManager:
        return JobManager()

    @cached_property
    def esde(self) -> EsdeService:
        return EsdeService(lambda: self._config, self._connector())

    @cached_property
    def media(self) -> MediaService:
        return MediaService(
            lambda: self._config, self._connector(),
            PendingDeletions(data_dir() / "pending_media_deletions.json"),
            PreviewStore(),
        )

    @cached_property
    def doujin(self) -> DoujinService:
        return DoujinService(
            lambda: self._config, self._connector(),
            DoujinDB(data_dir() / "doujin.db"), data_dir() / "doujin_images",
        )
