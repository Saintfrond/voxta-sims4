"""The socket to Voxta, run on a background thread.

The game's main thread must never wait on the network: on Windows, connecting to a localhost port
nobody listens on can take seconds, and that would freeze the game every retry. So a daemon thread
does all of the socket work, and the main thread only swaps messages through two queues:

    main thread  --send()-->  outbox  --thread-->  Voxta
    main thread  <--poll()--  inbox   <--thread--  Voxta

Messages are JSON objects, one per line. Nothing here imports game modules.
"""

import json
import queue
import socket
import threading
import time

from . import log

_RECV_TIMEOUT = 0.25
_CONNECT_TIMEOUT = 3.0
_RETRY_MIN = 2.0
_RETRY_MAX = 15.0
_OUTBOX_LIMIT = 200
_MAX_LINE = 1024 * 1024


class BridgeClient(object):
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self._inbox = queue.Queue()
        self._outbox = queue.Queue(maxsize=_OUTBOX_LIMIT)
        self._stop = threading.Event()
        self._reconnect = threading.Event()
        self._thread = None
        self._connected = False
        self._generation = 0
        self.last_error = None

    # ---- main thread ----

    @property
    def connected(self):
        return self._connected

    @property
    def generation(self):
        """Goes up by one on every new connection, so the main thread can tell it reconnected."""
        return self._generation

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="voxta_bridge", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._reconnect.set()

    def reconnect(self):
        """Drop the current connection (if any) and try again right away."""
        self._reconnect.set()

    def send(self, message):
        """Queue a message for Voxta. Dropped when not connected: the game state is re-sent on connect anyway."""
        if not self._connected:
            return False
        try:
            self._outbox.put_nowait(json.dumps(message, separators=(",", ":"), ensure_ascii=False))
            return True
        except queue.Full:
            log.warn("Outbox full, dropping a {} message".format(message.get("type")))
            return False

    def poll(self, limit=50):
        """Messages received from Voxta since the last call."""
        messages = []
        while len(messages) < limit:
            try:
                messages.append(self._inbox.get_nowait())
            except queue.Empty:
                break
        return messages

    # ---- background thread ----

    def _run(self):
        delay = _RETRY_MIN
        while not self._stop.is_set():
            sock = None
            try:
                sock = socket.create_connection((self.host, self.port), timeout=_CONNECT_TIMEOUT)
            except (OSError, socket.timeout) as exc:
                self.last_error = str(exc)
                self._wait(delay)
                delay = min(delay * 1.5, _RETRY_MAX)
                continue

            delay = _RETRY_MIN
            self.last_error = None
            self._reconnect.clear()
            self._drain_outbox()
            self._generation += 1
            self._connected = True
            log.info("Connected to Voxta at {}:{}".format(self.host, self.port))
            self._inbox.put({"type": "_connected"})
            try:
                self._session(sock)
            except (OSError, socket.timeout) as exc:
                self.last_error = str(exc)
                log.info("Connection to Voxta lost: {}".format(exc))
            except Exception as exc:  # never let the thread die
                self.last_error = str(exc)
                log.error("Voxta connection failed", exc)
            finally:
                self._connected = False
                self._inbox.put({"type": "_disconnected"})
                try:
                    sock.close()
                except OSError:
                    pass
            self._wait(_RETRY_MIN)

    def _session(self, sock):
        sock.settimeout(_RECV_TIMEOUT)
        pending = b""
        while not self._stop.is_set() and not self._reconnect.is_set():
            self._flush(sock)
            try:
                chunk = sock.recv(16384)
            except socket.timeout:
                continue
            if not chunk:
                log.info("Voxta closed the connection")
                return
            pending += chunk
            if len(pending) > _MAX_LINE and b"\n" not in pending:
                raise OSError("Voxta sent an over-long line")
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line.decode("utf-8"))
                except ValueError:
                    log.warn("Ignoring a line from Voxta that is not JSON")
                    continue
                if isinstance(message, dict) and isinstance(message.get("type"), str):
                    self._inbox.put(message)
        if self._reconnect.is_set():
            log.info("Reconnecting to Voxta")
            try:
                self._send_line(sock, json.dumps({"type": "bye"}))
            except OSError:
                pass

    def _flush(self, sock):
        while True:
            try:
                line = self._outbox.get_nowait()
            except queue.Empty:
                return
            self._send_line(sock, line)

    @staticmethod
    def _send_line(sock, line):
        sock.settimeout(_CONNECT_TIMEOUT)
        try:
            sock.sendall((line + "\n").encode("utf-8"))
        finally:
            sock.settimeout(_RECV_TIMEOUT)

    def _drain_outbox(self):
        while True:
            try:
                self._outbox.get_nowait()
            except queue.Empty:
                return

    def _wait(self, seconds):
        end = time.monotonic() + seconds
        while not self._stop.is_set() and not self._reconnect.is_set():
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            self._stop.wait(min(remaining, 0.5))
        self._reconnect.clear()
