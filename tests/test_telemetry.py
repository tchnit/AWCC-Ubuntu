from __future__ import annotations

import threading
import unittest
from unittest.mock import Mock

from awcc_linux.telemetry import SnapshotPoller


class SnapshotPollerTests(unittest.TestCase):
    def test_slow_reader_is_background_and_single_flight(self):
        started, release, delivered = threading.Event(), threading.Event(), threading.Event()
        queued = []
        def reader():
            started.set()
            release.wait(2)
            return "snapshot"
        def dispatch(callback):
            queued.append(callback)
            delivered.set()
        poller = SnapshotPoller(reader, dispatch)
        success, failure = Mock(), Mock()
        self.assertTrue(poller.request(success, failure))
        self.assertTrue(started.wait(2))
        self.assertFalse(poller.request(success, failure))
        release.set()
        self.assertTrue(delivered.wait(2))
        success.assert_not_called()
        queued[0]()
        success.assert_called_once_with("snapshot")
        failure.assert_not_called()

    def test_closing_discards_pending_delivery(self):
        delivered, queued = threading.Event(), []
        def dispatch(callback):
            queued.append(callback)
            delivered.set()
        success, failure = Mock(), Mock()
        poller = SnapshotPoller(lambda: "snapshot", dispatch)
        poller.request(success, failure)
        self.assertTrue(delivered.wait(2))
        poller.close()
        queued[0]()
        success.assert_not_called()
        failure.assert_not_called()
        self.assertFalse(poller.request(success, failure))

    def test_reader_error_is_reported_and_releases_busy(self):
        delivered, queued = threading.Event(), []
        def dispatch(callback):
            queued.append(callback)
            delivered.set()
        def reader():
            raise OSError("sensor unavailable")
        success, failure = Mock(), Mock()
        poller = SnapshotPoller(reader, dispatch)
        poller.request(success, failure)
        self.assertTrue(delivered.wait(2))
        queued[0]()
        failure.assert_called_once_with("sensor unavailable")
        self.assertTrue(poller.request(success, failure))
        poller.close()
