"""アプリ全体で共有する設定とサービスの組み立て。API と MCP の両方から使う。"""
from __future__ import annotations

from contextlib import AbstractContextManager
from functools import cached_property

from kakehashi.config import Config, load_config, save_config
from kakehashi.infra.deck import RemoteFS, open_deck
from kakehashi.services.esde import EsdeService


class AppContext:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or load_config()

    @property
    def config(self) -> Config:
        return self._config

    def update_config(self, config: Config) -> None:
        save_config(config)
        self._config = config

    def connect(self) -> AbstractContextManager[RemoteFS]:
        return open_deck(self._config.sync)

    @cached_property
    def esde(self) -> EsdeService:
        return EsdeService(lambda: self._config, self.connect)
