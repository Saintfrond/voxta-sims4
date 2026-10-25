"""Settings from voxta_bridge.cfg, which sits next to voxta_bridge.ts4script in the Mods folder.

The file is optional: every setting has a default that works with Voxta on the same PC.
"""

import os

DEFAULTS = {
    # Where Voxta Server runs. 127.0.0.1 = this computer.
    "host": "127.0.0.1",
    # Must match "Game connection port" in the Voxta module settings.
    "port": 5385,
    # Seconds (real time) between household snapshots. Unchanged snapshots are not sent.
    "state_interval": 2.0,
    # Write extra detail to voxta_bridge.log.
    "debug": False,
}

CONFIG_NAME = "voxta_bridge.cfg"
LOG_NAME = "voxta_bridge.log"


def mod_folder(module_file=None):
    """The folder that holds voxta_bridge.ts4script (where the config and log live).

    Inside the game this module is loaded from a zip, so __file__ looks like
    ...\\Mods\\Voxta\\voxta_bridge.ts4script\\voxta_bridge\\config.pyc. Walk up to the .ts4script
    and take its folder. Loose (unzipped) development copies just use the package's parent folder.
    """
    path = os.path.abspath(module_file or __file__)
    current = path
    while True:
        parent = os.path.dirname(current)
        if current.lower().endswith(".ts4script"):
            return parent
        if parent == current:
            break
        current = parent
    return os.path.dirname(os.path.dirname(path))


def _parse_value(default, raw):
    raw = raw.strip()
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


def parse(text):
    """Reads `key = value` lines; `#` starts a comment. Unknown keys and bad values are ignored."""
    settings = dict(DEFAULTS)
    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            problems.append("line {}: expected key = value".format(number))
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        if key not in DEFAULTS:
            problems.append("line {}: unknown setting '{}'".format(number, key))
            continue
        try:
            settings[key] = _parse_value(DEFAULTS[key], value)
        except ValueError:
            problems.append("line {}: '{}' is not a valid value for {}".format(number, value.strip(), key))
    if not (1 <= settings["port"] <= 65535):
        problems.append("port {} is out of range, using {}".format(settings["port"], DEFAULTS["port"]))
        settings["port"] = DEFAULTS["port"]
    settings["state_interval"] = max(0.5, settings["state_interval"])
    return settings, problems


def load(folder):
    path = os.path.join(folder, CONFIG_NAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return parse(handle.read())
    except FileNotFoundError:
        return dict(DEFAULTS), []
    except OSError as exc:
        return dict(DEFAULTS), ["could not read {}: {}".format(path, exc)]
