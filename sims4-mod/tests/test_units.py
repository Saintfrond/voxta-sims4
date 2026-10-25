import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from voxta_bridge import config, events  # noqa: E402
from voxta_bridge.snapshot import pretty  # noqa: E402


# ---- config ----

def test_defaults_when_empty():
    settings, problems = config.parse("")
    assert settings == config.DEFAULTS
    assert problems == []


def test_parse_values_and_comments():
    settings, problems = config.parse("host = 192.168.1.20  # my PC\nport=6000\ndebug = yes\nstate_interval = 0.1\n")
    assert settings["host"] == "192.168.1.20"
    assert settings["port"] == 6000
    assert settings["debug"] is True
    assert settings["state_interval"] == 0.5  # clamped
    assert problems == []


def test_bad_lines_are_reported_not_fatal():
    settings, problems = config.parse("port = lots\ncolour = green\nnonsense\nport = 99999")
    assert settings["port"] == 5385
    assert len(problems) == 4


def test_mod_folder_inside_ts4script():
    path = os.path.join("C:" + os.sep, "Mods", "Voxta", "voxta_bridge.ts4script", "voxta_bridge", "config.pyc")
    assert config.mod_folder(path) == os.path.abspath(os.path.join("C:" + os.sep, "Mods", "Voxta"))


# ---- names ----

def test_pretty():
    assert pretty("trait_Cheerful", ("trait_",)) == "Cheerful"
    assert pretty("career_Adult_TechGuru", ("career_Adult_",)) == "Tech Guru"
    assert pretty("Mood_Happy", ("Mood_",)) == "Happy"
    assert pretty("stove_CookDinner") == "Stove Cook Dinner"
    assert pretty("") is None


# ---- events ----

def sim(sim_id="1", **kw):
    base = {
        "id": sim_id, "first_name": "Bella", "last_name": "Goth", "age": "Adult",
        "mood": "Fine", "mood_intensity": 1, "needs": {"hunger": 60, "energy": 60},
        "career": {"name": "Business", "level": 4}, "relationships": [],
    }
    base.update(kw)
    return base


def state(*sims, active=None):
    return {"type": "state", "active_sim_id": active, "sims": list(sims)}


def kinds(evts):
    return sorted(e["kind"] for e in evts)


def test_no_events_without_a_previous_snapshot():
    assert events.diff(None, state(sim())) == []


def test_no_events_when_nothing_changed():
    assert events.diff(state(sim()), state(sim())) == []


def test_strong_mood_is_an_event_mild_is_not():
    assert events.diff(state(sim()), state(sim(mood="Sad", mood_intensity=1))) == []
    evts = events.diff(state(sim()), state(sim(mood="Angry", mood_intensity=3)))
    assert kinds(evts) == ["mood_changed"]
    assert evts[0]["text"] == "Bella Goth is now very angry (was fine)."
    assert evts[0]["importance"] == 1


def test_need_crossing_critical_once():
    hungry = sim(needs={"hunger": 10, "energy": 60})
    evts = events.diff(state(sim()), state(hungry))
    assert kinds(evts) == ["need_critical"]
    assert evts[0]["text"] == "Bella Goth is starving."
    # still starving next snapshot: no repeat
    assert events.diff(state(hungry), state(sim(needs={"hunger": 8, "energy": 60}))) == []


def test_age_career_household_changes():
    evts = events.diff(
        state(sim(), sim("2", first_name="Mortimer")),
        state(sim(age="Elder", career={"name": "Business", "level": 5}), sim("3", first_name="Cassandra")),
    )
    assert kinds(evts) == ["aged_up", "career_changed", "joined_household", "left_household"]
    texts = " ".join(e["text"] for e in evts)
    assert "promoted to level 5 in Business" in texts
    assert "Cassandra Goth joined the household." in texts


def test_new_marriage_announced_once_per_pair():
    bella_before = sim("1", relationships=[{"id": "2", "name": "Mortimer Goth", "bits": []}])
    mort_before = sim("2", first_name="Mortimer", relationships=[{"id": "1", "name": "Bella Goth", "bits": []}])
    bella_after = sim("1", relationships=[{"id": "2", "name": "Mortimer Goth", "bits": ["Married"]}])
    mort_after = sim("2", first_name="Mortimer", relationships=[{"id": "1", "name": "Bella Goth", "bits": ["Married"]}])
    evts = events.diff(state(bella_before, mort_before), state(bella_after, mort_after))
    assert kinds(evts) == ["relationship_changed"]
    assert evts[0]["text"] == "Bella Goth and Mortimer Goth are now married."
    assert evts[0]["importance"] == 2


def test_active_sim_switch_is_trivia():
    evts = events.diff(state(sim(), sim("2", first_name="Mortimer"), active="1"),
                       state(sim(), sim("2", first_name="Mortimer"), active="2"))
    assert kinds(evts) == ["active_sim_changed"]
    assert evts[0]["importance"] == 0
