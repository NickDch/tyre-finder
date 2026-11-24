"""Asynchronous thumbnail loader with memory and disk cache."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import shiboken6
from platformdirs import user_cache_dir
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkDiskCache,
    QNetworkReply,
    QNetworkRequest,
)

from tyre_finder.data.http import USER_AGENT

log = logging.getLogger(__name__)

ImageCallback = Callable[[QImage], None]
_Waiter = tuple[ImageCallback, QObject | None]


class ImageLoader(QObject):
    """Loads images on the GUI thread without blocking (Qt network stack)."""

    image_ready = Signal(str, QImage)

    def __init__(self, parent: QObject | None = None, cache_dir: Path | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        disk = QNetworkDiskCache(self)
        directory = cache_dir or Path(user_cache_dir("tyre-finder", appauthor=False)) / "images"
        directory.mkdir(parents=True, exist_ok=True)
        disk.setCacheDirectory(str(directory))
        disk.setMaximumCacheSize(200 * 1024 * 1024)
        self._nam.setCache(disk)
        self._memory: dict[str, QImage] = {}
        self._waiting: dict[str, list[_Waiter]] = {}

    def request(self, url: str, callback: ImageCallback, owner: QObject | None = None) -> None:
        """Call *callback* with the image once available (skipped if *owner* was deleted)."""
        if not url:
            return
        cached = self._memory.get(url)
        if cached is not None:
            callback(cached)
            return
        if url in self._waiting:
            self._waiting[url].append((callback, owner))
            return
        self._waiting[url] = [(callback, owner)]
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", USER_AGENT.encode())
        req.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.PreferCache,
        )
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        req.setTransferTimeout(15000)
        reply = self._nam.get(req)
        reply.finished.connect(lambda r=reply, u=url: self._on_finished(u, r))

    def _on_finished(self, url: str, reply: QNetworkReply) -> None:
        callbacks = self._waiting.pop(url, [])
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                log.debug("Image failed %s: %s", url, reply.errorString())
                return
            image = QImage()
            if not image.loadFromData(reply.readAll()):
                log.debug("Image not decodable: %s", url)
                return
            self._memory[url] = image
            for cb, owner in callbacks:
                if owner is None or shiboken6.isValid(owner):
                    cb(image)
            self.image_ready.emit(url, image)
        finally:
            reply.deleteLater()
