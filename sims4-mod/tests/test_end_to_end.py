"""Runs the real mod, built into a real .ts4script and imported from it the way the game does,
against fake game modules and a fake Voxta module speaking the same protocol as SimsBridge.cs."""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
REPO = os.path.dirname(MOD)
sys.path.insert(0, HERE)

import fake_game  # noqa: E402

COMPILED = os.environ.get("VOXTA_BRIDGE_COMPILED") == "1"
VERSION = re.search(r'MOD_VERSION = "([^"]+)"', open(os.path.join(MOD, "src", "voxta_bridge", "__init__.py")).read()).group(1)


class FakeVoxta(object):
    """The Voxta side of the protocol: listens, says hello, records what the game sends."""

    def __init__(self):
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.received = []
        self.connections = 0
        self.conn = None
        self.lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.connections += 1
            self.conn = conn
            conn.sendall((json.dumps({"type": "hello", "protocol": 1, "server": "Voxta.Modules.Sims4", "version": "0.1.0"}) + "\n").encode())
            threading.Thread(target=self._read, args=(conn,), daemon=True).start()

    def _read(self, conn):
        pending = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                with self.lock:
                    self.received.append(json.loads(line.decode("utf-8")))

    def send(self, message):
        self.conn.sendall((json.dumps(message) + "\n").encode("utf-8"))

    def of_type(self, kind):
        with self.lock:
            return [m for m in self.received if m.get("type") == kind]

    def drop(self):
        self.conn.shutdown(socket.SHUT_RDWR)
        self.conn.close()


def wait_for(game, condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        game.run_alarms()
        if condition():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    # CI on Python 3.7 sets VOXTA_BRIDGE_COMPILED=1: the test then imports the real release build,
    # sourceless .pyc files from a zip, which is exactly how the game loads it.
    build = [sys.executable, os.path.join(MOD, "build.py")]
    if not COMPILED:
        build.append("--source")
    subprocess.check_call(build)
    voxta = FakeVoxta()

    mods = tmp_path_factory.mktemp("Mods")
    folder = mods / "Voxta"
    folder.mkdir()
    script = folder / "voxta_bridge.ts4script"
    script.write_bytes(open(os.path.join(MOD, "dist", "voxta_bridge.ts4script"), "rb").read())
    (folder / "voxta_bridge.cfg").write_text("port = {}\nstate_interval = 0.5\ndebug = true\n".format(voxta.port))

    game = fake_game.install()
    bella, mortimer, alexander = fake_game.goth_household(game)

    sys.path.insert(0, str(script))  # zipimport, like the game
    for name in [n for n in sys.modules if n == "voxta_bridge" or n.startswith("voxta_bridge.")]:
        del sys.modules[name]  # the unit tests imported it from src/
    import voxta_bridge  # noqa: F401  (imports main because `services` exists)
    import zone

    assert voxta_bridge.__file__.startswith(str(script)), "must be imported from the .ts4script"
    zone.Zone().on_loading_screen_animation_finished()
    return game, voxta, folder, (bella, mortimer, alexander)


def test_build_contents(setup):
    import importlib.util
    import zipfile

    names = zipfile.ZipFile(os.path.join(MOD, "dist", "voxta_bridge.ts4script")).namelist()
    assert "voxta_bridge/__init__.py" + ("c" if COMPILED else "") in names
    assert "voxta_bridge/main.py" + ("c" if COMPILED else "") in names
    if COMPILED:
        archive = zipfile.ZipFile(os.path.join(MOD, "dist", "voxta_bridge.ts4script"))
        assert all(n.endswith(".pyc") for n in names), names
        assert all(archive.read(n)[:4] == importlib.util.MAGIC_NUMBER for n in names)
        assert sys.version_info[:2] == (3, 7), "compiled builds must come from Python 3.7"


def test_connects_and_says_hello(setup):
    game, voxta, folder, _ = setup
    assert wait_for(game, lambda: voxta.of_type("hello"))
    hello = voxta.of_type("hello")[0]
    assert hello == {"type": "hello", "protocol": 1, "mod_version": VERSION}


def test_sends_household_state(setup):
    game, voxta, folder, _ = setup
    assert wait_for(game, lambda: voxta.of_type("state"))
    state = voxta.of_type("state")[-1]
    assert state["household"] == {"name": "Goth", "funds": 34500}
    assert state["world"]["day"] == "Tuesday" and state["world"]["time"] == "14:05"
    assert state["world"]["lot"] == "Willow Creek Home"
    assert state["active_sim_id"] == "101"

    sims = {s["first_name"]: s for s in state["sims"]}
    bella = sims["Bella"]
    assert bella["is_active"] and bella["on_lot"]
    assert bella["age"] == "Adult" and bella["gender"] == "Female"
    assert bella["mood"] == "Fine"
    assert bella["needs"]["hunger"] == 60.0
    assert bella["traits"] == ["Romantic", "Snob"]  # gameplay trait filtered out
    assert bella["career"] == {"name": "Business", "level": 4}
    assert bella["activity"] == "Stove Cook Dinner"
    rels = {r["name"]: r for r in bella["relationships"]}
    assert rels["Mortimer Goth"]["bits"] == ["Married"]
    assert rels["Mortimer Goth"]["romance"] == 90
    assert rels["Alexander Goth"]["bits"] == ["Son"]

    assert sims["Mortimer"]["on_lot"] is False and sims["Mortimer"]["activity"] is None
    assert sims["Alexander"]["age"] == "Child"


def test_state_keys_match_the_voxta_module(setup):
    """Every key the mod sends must exist on the C# records in Bridge/Messages.cs (snake_case)."""
    game, voxta, folder, _ = setup
    source = open(os.path.join(REPO, "Voxta.Modules.Sims4", "Bridge", "Messages.cs"), encoding="utf-8").read()

    def props(record):
        body = re.search(r"record " + record + r"\b.*?\n\{(.*?)\n\}", source, re.S).group(1)
        names = re.findall(r"public (?:required )?[\w<>\[\]?, ]+ (\w+) \{", body)
        return {re.sub(r"(?<!^)(?=[A-Z])", "_", n).lower() for n in names} | {"type"}

    state = voxta.of_type("state")[-1]
    assert set(state) <= props("GameState")
    assert set(state["household"]) <= props("HouseholdInfo")
    assert set(state["world"]) <= props("WorldInfo")
    for sim in state["sims"]:
        assert set(sim) <= props("SimInfo"), set(sim) - props("SimInfo")
        if sim.get("career"):
            assert set(sim["career"]) <= props("CareerInfo")
        for rel in sim["relationships"]:
            assert set(rel) <= props("RelationshipInfo")
    assert set(voxta.of_type("hello")[0]) <= props("GameHello")


def test_notification_from_voxta_shows_with_portrait(setup):
    game, voxta, folder, (bella, _, _) = setup
    voxta.send({"type": "notify", "sim_id": "101", "title": "Bella Goth", "text": "Dinner's almost ready, dear."})
    assert wait_for(game, lambda: game.notifications)
    title, text, icon = game.notifications[-1]
    assert (title, text) == ("Bella Goth", "Dinner's almost ready, dear.")
    assert icon is bella


def test_game_changes_become_events_and_new_state(setup):
    game, voxta, folder, (bella, _, _) = setup
    states_before = len(voxta.of_type("state"))
    bella.mood = fake_game.tuning("Mood_Angry")
    bella.mood_intensity = 2
    bella.set_need("hunger", 5)
    assert wait_for(game, lambda: len(voxta.of_type("event")) >= 2)
    texts = sorted(e["text"] for e in voxta.of_type("event"))
    assert texts == ["Bella Goth is now angry (was fine).", "Bella Goth is starving."]
    assert len(voxta.of_type("state")) > states_before
    assert voxta.of_type("state")[-1]["sims"][0]["mood"] == "Angry"


def test_unchanged_state_is_not_resent(setup):
    game, voxta, folder, _ = setup
    count = len(voxta.of_type("state"))
    end = time.time() + 1.5
    while time.time() < end:
        game.run_alarms()
        time.sleep(0.05)
    assert len(voxta.of_type("state")) == count


def test_request_state_forces_a_resend(setup):
    game, voxta, folder, _ = setup
    count = len(voxta.of_type("state"))
    voxta.send({"type": "request_state"})
    assert wait_for(game, lambda: len(voxta.of_type("state")) > count)


def test_status_command(setup):
    game, voxta, folder, _ = setup
    output = "\n".join(game.run_command("voxta.status"))
    assert "Connected to Voxta module 0.1.0" in output
    assert "Bella Goth, Mortimer Goth, Alexander Goth" in output


def test_test_command_shows_a_notification(setup):
    game, voxta, folder, _ = setup
    game.run_command("voxta.test")
    assert game.notifications[-1][0] == "Voxta bridge"


def test_reconnects_after_voxta_drops(setup):
    game, voxta, folder, _ = setup
    hellos = len(voxta.of_type("hello"))
    states = len(voxta.of_type("state"))
    voxta.drop()
    assert wait_for(game, lambda: len(voxta.of_type("hello")) > hellos, timeout=10)
    # A fresh connection gets the full state again, even though nothing changed.
    assert wait_for(game, lambda: len(voxta.of_type("state")) > states)
    assert voxta.connections == 2


def test_log_file_written(setup):
    game, voxta, folder, _ = setup
    log_text = (folder / "voxta_bridge.log").read_text(encoding="utf-8")
    assert "Voxta bridge {} loaded".format(VERSION) in log_text
    assert "Connected to Voxta" in log_text
    assert "ERROR" not in log_text, log_text
