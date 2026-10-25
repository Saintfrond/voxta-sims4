"""Entry point: the game imports this when it loads voxta_bridge.ts4script.

Wires the bridge into the game:
  * every time a lot finishes loading, a real-time alarm starts ticking once a second;
  * each tick (on the game's main thread) handles messages from Voxta and, every few seconds,
    sends the household snapshot and any events since the last one;
  * cheat console commands: voxta.status, voxta.reconnect, voxta.test, voxta.dump
"""

import json
import time

import alarms
import clock
import services
import sims4.commands
from zone import Zone

from . import MOD_VERSION, PROTOCOL_VERSION
from . import camera_focus, config, connection, events, log, notify, snapshot

_TICK_SECONDS = 1.0
_ERROR_LOG_INTERVAL = 60.0


class _Bridge(object):
    def __init__(self):
        self.folder = config.mod_folder(__file__)
        self.settings, problems = config.load(self.folder)
        log.configure(self.folder, config.LOG_NAME, self.settings["debug"])
        log.info("Voxta bridge {} loaded (folder: {})".format(MOD_VERSION, self.folder))
        for problem in problems:
            log.warn("{}: {}".format(config.CONFIG_NAME, problem))

        self.client = connection.BridgeClient(self.settings["host"], self.settings["port"])
        self.alarm = None
        self.zone_ready = False
        self.server_version = None
        self.previous_state = None
        self.last_sent = None
        self.last_snapshot = 0.0
        self.force_state = False
        self.last_error_logged = 0.0
        self.notifications_shown = 0

    # ---- lifecycle ----

    def on_zone_loaded(self):
        self.client.start()
        self.zone_ready = True
        # A new lot means a possibly different household: start events fresh, send state now.
        self.previous_state = None
        self.force_state = True
        self._start_alarm()

    def _start_alarm(self):
        if self.alarm is not None:
            try:
                alarms.cancel_alarm(self.alarm)
            except Exception:
                pass
            self.alarm = None
        span = clock.interval_in_real_seconds(_TICK_SECONDS)
        try:
            self.alarm = alarms.add_alarm_real_time(self, span, self.tick, repeating=True, use_sleep_time=False)
        except TypeError:
            # Older or newer signatures without use_sleep_time.
            try:
                self.alarm = alarms.add_alarm_real_time(self, span, self.tick, repeating=True)
            except Exception as exc:
                log.error("Could not start the bridge's real-time alarm", exc)
        except Exception as exc:
            log.error("Could not start the bridge's real-time alarm", exc)

    # ---- the tick, on the game's main thread ----

    def tick(self, _handle=None):
        try:
            for message in self.client.poll():
                self._handle(message)
            if self.client.connected and self.zone_ready:
                now = time.monotonic()
                if self.force_state or now - self.last_snapshot >= self.settings["state_interval"]:
                    self.last_snapshot = now
                    self._send_state()
        except Exception as exc:
            now = time.monotonic()
            if now - self.last_error_logged > _ERROR_LOG_INTERVAL:
                self.last_error_logged = now
                log.error("Bridge tick failed", exc)

    def _handle(self, message):
        kind = message.get("type")
        if kind == "_connected":
            self.client.send({"type": "hello", "protocol": PROTOCOL_VERSION, "mod_version": MOD_VERSION})
            self.previous_state = None
            self.last_sent = None
            self.force_state = True
        elif kind == "_disconnected":
            self.server_version = None
        elif kind == "hello":
            self.server_version = message.get("version")
            if message.get("protocol") != PROTOCOL_VERSION:
                log.warn("Voxta module speaks protocol {}, this mod {}. Update whichever is older.".format(
                    message.get("protocol"), PROTOCOL_VERSION))
            log.info("Voxta module {} said hello".format(self.server_version))
        elif kind == "notify":
            notify.show(message.get("title"), message.get("text"), message.get("sim_id"))
            self.notifications_shown += 1
        elif kind == "focus":
            camera_focus.focus(message.get("sim_id"), message.get("follow", False))
        elif kind == "request_state":
            self.force_state = True
        elif kind == "pong":
            pass
        else:
            log.debug("Ignoring Voxta message type {}".format(kind))

    def _send_state(self):
        force = self.force_state
        self.force_state = False
        state = snapshot.build()
        if state is None:
            return

        for event in events.diff(self.previous_state, state):
            log.debug("Event: {}".format(event["text"]))
            self.client.send(event)
        self.previous_state = state

        encoded = json.dumps(state, sort_keys=True)
        if force or encoded != self.last_sent:
            self.last_sent = encoded
            self.client.send(state)


_bridge = _Bridge()


# ---- hook into lot loading ----

def _inject(target, name):
    original = getattr(target, name)

    def decorator(replacement):
        def wrapper(*args, **kwargs):
            return replacement(original, *args, **kwargs)
        wrapper.__name__ = getattr(original, "__name__", name)
        setattr(target, name, wrapper)
        return wrapper
    return decorator


@_inject(Zone, "on_loading_screen_animation_finished")
def _on_loading_screen_animation_finished(original, self, *args, **kwargs):
    result = original(self, *args, **kwargs)
    try:
        _bridge.on_zone_loaded()
    except Exception as exc:
        log.error("Could not start the Voxta bridge on lot load", exc)
    return result


# ---- cheat console ----

@sims4.commands.Command("voxta.status", command_type=sims4.commands.CommandType.Live)
def _status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    client = _bridge.client
    output("Voxta bridge {} -> {}:{}".format(MOD_VERSION, client.host, client.port))
    if client.connected:
        output("Connected to Voxta module {}.".format(_bridge.server_version or "(waiting for hello)"))
    else:
        output("Not connected. Is Voxta Server running with The Sims 4 module added? {}".format(
            "Last error: " + client.last_error if client.last_error else ""))
    household = services.active_household()
    if household is not None:
        names = ", ".join("{} {}".format(s.first_name, s.last_name) for s in household.sim_info_gen())
        output("Household: {}".format(names))
    output("Notifications shown: {}. Log: {}".format(_bridge.notifications_shown, config.LOG_NAME))


@sims4.commands.Command("voxta.reconnect", command_type=sims4.commands.CommandType.Live)
def _reconnect(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    _bridge.client.start()
    _bridge.client.reconnect()
    output("Reconnecting to Voxta at {}:{}...".format(_bridge.client.host, _bridge.client.port))


@sims4.commands.Command("voxta.test", command_type=sims4.commands.CommandType.Live)
def _test(_connection=None):
    active = services.active_sim_info()
    notify.show(
        "Voxta bridge",
        "Notifications work. {}".format("Connected to Voxta." if _bridge.client.connected else "Not connected to Voxta yet."),
        active.sim_id if active is not None else None,
    )


@sims4.commands.Command("voxta.dump", command_type=sims4.commands.CommandType.Live)
def _dump(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    state = snapshot.build()
    log.info("Snapshot: {}".format(json.dumps(state, indent=2, ensure_ascii=False)))
    output("Wrote the current household snapshot to {}.".format(config.LOG_NAME))
