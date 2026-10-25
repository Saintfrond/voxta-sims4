"""Voxta bridge for The Sims 4.

Connects the running game to a Voxta Server that has the "The Sims 4" module installed, so you can
chat with your household members. Python 3.7, like the game.

Only main.py touches the game at import time; the rest can be imported (and tested) outside it.
"""

MOD_VERSION = "0.1.0-alpha.2"
PROTOCOL_VERSION = 1


# The game imports the package; start the bridge only when actually running inside the game
# (`services` exists only there), so the other modules stay importable for tests and tooling.
try:
    import services as _game_services  # noqa: F401
except ImportError:
    _game_services = None

if _game_services is not None:
    from . import main  # noqa: F401,E402
