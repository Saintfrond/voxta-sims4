"""A small log file next to the mod. The game swallows print() and most exceptions, so when
something doesn't work, voxta_bridge.log is where the answer is."""

import datetime
import os
import threading
import traceback

_MAX_BYTES = 512 * 1024

_lock = threading.Lock()
_path = None
_debug = False


def configure(folder, file_name, debug=False):
    global _path, _debug
    _debug = debug
    _path = os.path.join(folder, file_name)
    try:
        # Keep one previous log; never let the file grow without bound.
        if os.path.exists(_path) and os.path.getsize(_path) > _MAX_BYTES:
            old = _path + ".old"
            if os.path.exists(old):
                os.remove(old)
            os.rename(_path, old)
    except OSError:
        pass


def _write(level, message):
    line = "{} [{}] {}\n".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), level, message)
    if _path is None:
        return
    with _lock:
        try:
            with open(_path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass


def debug(message):
    if _debug:
        _write("DEBUG", message)


def info(message):
    _write("INFO", message)


def warn(message):
    _write("WARN", message)


def error(message, exc=None):
    if exc is not None:
        message = "{}\n{}".format(message, "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())
    _write("ERROR", message)
