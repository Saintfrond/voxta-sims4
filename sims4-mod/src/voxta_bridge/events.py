"""Turns two household snapshots into the events worth telling a character about.

Working from snapshots rather than hooking game internals means a game patch can break how a value
is read (snapshot.py), but not this. Pure Python, no game imports.

Importance: 0 = trivia, 1 = notable (a character may react), 2 = big news for the whole household.
"""

# Moods that are news when they get strong. "Fine", "Happy" at mild levels are not.
_NOTABLE_MOODS = {
    "angry", "sad", "tense", "embarrassed", "uncomfortable", "scared", "bored",
    "confident", "energized", "flirty", "focused", "inspired", "playful", "happy", "dazed",
}

_NEED_CRITICAL = 15.0

_NEED_WORDS = {
    "hunger": "is starving",
    "energy": "is exhausted",
    "bladder": "desperately needs the bathroom",
    "hygiene": "badly needs a shower",
    "social": "is desperately lonely",
    "fun": "is bored out of their mind",
}

_INTENSITY_WORDS = {1: "slightly ", 2: "", 3: "very "}

# Relationship bits worth announcing when they appear. Matched case-insensitively against the
# readable bit names snapshot.py produces.
_BIG_BITS = {
    "married": "{a} and {b} are now married",
    "engaged": "{a} and {b} are now engaged",
    "boyfriend girlfriend": "{a} and {b} are now a couple",
    "significant other": "{a} and {b} are now a couple",
    "best friends": "{a} and {b} are now best friends",
    "bff": "{a} and {b} are now best friends",
    "divorced": "{a} and {b} are now divorced",
    "broken up": "{a} and {b} have broken up",
    "enemy": "{a} and {b} are now enemies",
}


def _by_id(state):
    if not state:
        return {}
    return {sim["id"]: sim for sim in state.get("sims", [])}


def _name(sim):
    return (sim.get("first_name", "") + " " + sim.get("last_name", "")).strip() or "A Sim"


def _event(sim, kind, text, importance):
    return {
        "type": "event",
        "sim_id": sim["id"] if sim else None,
        "sim_name": _name(sim) if sim else None,
        "kind": kind,
        "text": text,
        "importance": importance,
    }


def diff(old, new):
    """Events between two snapshots. The first snapshot after a (re)connect has no "old": no events."""
    if not old or not new:
        return []

    events = []
    before = _by_id(old)
    after = _by_id(new)

    for sim_id, sim in after.items():
        if sim_id not in before:
            events.append(_event(sim, "joined_household", "{} joined the household.".format(_name(sim)), 2))
    for sim_id, sim in before.items():
        if sim_id not in after:
            events.append(_event(sim, "left_household", "{} is no longer part of the household.".format(_name(sim)), 2))

    for sim_id, sim in after.items():
        prev = before.get(sim_id)
        if prev is None:
            continue
        name = _name(sim)
        events.extend(_mood(prev, sim, name))
        events.extend(_needs(prev, sim, name))
        events.extend(_age(prev, sim, name))
        events.extend(_career(prev, sim, name))
        events.extend(_bits(prev, sim, name, after))

    old_active = old.get("active_sim_id")
    new_active = new.get("active_sim_id")
    if new_active and new_active != old_active and new_active in after:
        sim = after[new_active]
        events.append(_event(sim, "active_sim_changed", "The player is now controlling {}.".format(_name(sim)), 0))

    return events


def _mood(prev, sim, name):
    mood = sim.get("mood")
    intensity = sim.get("mood_intensity") or 0
    if not mood or mood == prev.get("mood"):
        return []
    if mood.lower() not in _NOTABLE_MOODS or intensity < 2:
        return []
    was = prev.get("mood")
    text = "{} is now {}{}".format(name, _INTENSITY_WORDS.get(min(intensity, 3), ""), mood.lower())
    if was:
        text += " (was {})".format(was.lower())
    return [_event(sim, "mood_changed", text + ".", 1)]


def _needs(prev, sim, name):
    events = []
    old_needs = prev.get("needs") or {}
    for need, value in (sim.get("needs") or {}).items():
        old_value = old_needs.get(need)
        if old_value is None or value is None:
            continue
        if value < _NEED_CRITICAL <= old_value:
            phrase = _NEED_WORDS.get(need, "is very low on {}".format(need))
            events.append(_event(sim, "need_critical", "{} {}.".format(name, phrase), 1))
    return events


def _age(prev, sim, name):
    if prev.get("age") and sim.get("age") and prev["age"] != sim["age"]:
        return [_event(sim, "aged_up", "{} just aged up to {}!".format(name, sim["age"].lower()), 2)]
    return []


def _career(prev, sim, name):
    old = prev.get("career") or {}
    new = sim.get("career") or {}
    old_name, new_name = old.get("name"), new.get("name")
    if old_name == new_name:
        old_level, new_level = old.get("level"), new.get("level")
        if new_name and old_level is not None and new_level is not None:
            if new_level > old_level:
                return [_event(sim, "career_changed", "{} was promoted to level {} in {}!".format(name, new_level, new_name), 1)]
            if new_level < old_level:
                return [_event(sim, "career_changed", "{} was demoted to level {} in {}.".format(name, new_level, new_name), 1)]
        return []
    if new_name and not old_name:
        return [_event(sim, "career_changed", "{} started a career in {}.".format(name, new_name), 1)]
    if old_name and not new_name:
        return [_event(sim, "career_changed", "{} left their {} career.".format(name, old_name), 1)]
    return [_event(sim, "career_changed", "{} switched careers from {} to {}.".format(name, old_name, new_name), 1)]


def _bits(prev, sim, name, sims_by_id):
    events = []
    old_rels = {r["id"]: r for r in prev.get("relationships", [])}
    for rel in sim.get("relationships", []):
        # Each pair shows up twice (A→B and B→A); announce it from the lower id only.
        if rel["id"] < sim["id"] and rel["id"] in sims_by_id:
            continue
        old_bits = {b.lower() for b in old_rels.get(rel["id"], {}).get("bits", [])}
        for bit in rel.get("bits", []):
            key = bit.lower()
            if key in old_bits or key not in _BIG_BITS:
                continue
            other = rel.get("name") or "someone"
            events.append(_event(sim, "relationship_changed", _BIG_BITS[key].format(a=name, b=other) + ".", 2))
    return events
