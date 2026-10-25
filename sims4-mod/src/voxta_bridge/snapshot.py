"""Reads the active household from the running game into a plain dict (see docs/PROTOCOL.md).

Everything that reaches into the game is guarded field by field: a patch that renames one internal
should cost us that one field, not the whole snapshot. Game modules are imported inside functions
so this file can be imported outside the game.

Names come from tuning ("trait_Cheerful", "Mood_Happy"), not from the game's translated strings,
which Python cannot read. pretty() turns them into words.
"""

import re

from . import log

_AGE_NAMES = {
    "BABY": "Baby",
    "INFANT": "Infant",
    "TODDLER": "Toddler",
    "CHILD": "Child",
    "TEEN": "Teen",
    "YOUNGADULT": "Young Adult",
    "ADULT": "Adult",
    "ELDER": "Elder",
}

_DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

# Need name on the wire -> tuning name of the commodity.
_MOTIVES = {
    "hunger": "motive_Hunger",
    "energy": "motive_Energy",
    "bladder": "motive_Bladder",
    "hygiene": "motive_Hygiene",
    "social": "motive_Social",
    "fun": "motive_Fun",
}

_FRIENDSHIP_TRACK = "LTR_Friendship_Main"
_ROMANCE_TRACK = "LTR_Romance_Main"

# Relationship bits are tuned with prefixes like family_, romantic-, friendship-.
_BIT_PREFIXES = ("family", "romantic", "friendship")

# Interactions that are not "doing something" from a person's point of view.
_IDLE_WORDS = ("idle", "stand", "wander", "socialpicker", "_carry", "pickup", "putdown", "route", "sit_")

_SKIPPED_WARNINGS = set()


def _warn_once(key, exc):
    if key in _SKIPPED_WARNINGS:
        return
    _SKIPPED_WARNINGS.add(key)
    log.error("Could not read {} (further errors of this kind are not logged)".format(key), exc)


def pretty(tuning_name, drop_prefixes=()):
    """'trait_Cheerful' -> 'Cheerful', 'career_Adult_TechGuru' -> 'Tech Guru', 'romantic-Married' -> 'Married'."""
    if not tuning_name:
        return None
    name = tuning_name
    for prefix in drop_prefixes:
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):]
            break
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    words = [w for w in name.split() if w]
    return " ".join(w[0].upper() + w[1:] for w in words) or None


def _type_name(tuning):
    return getattr(tuning, "__name__", None) or type(tuning).__name__


# ---- tuning lookups, cached per game session ----

_statistic_cache = {}


def _statistic(tuning_name):
    """Commodities and relationship tracks live in the STATISTIC instance manager; find one by name."""
    if tuning_name in _statistic_cache:
        return _statistic_cache[tuning_name]
    import services
    import sims4.resources

    found = None
    manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)
    for tuning in manager.types.values():
        if getattr(tuning, "__name__", None) == tuning_name:
            found = tuning
            break
    _statistic_cache[tuning_name] = found
    if found is None:
        log.warn("No statistic tuning named {}".format(tuning_name))
    return found


def clear_caches():
    _statistic_cache.clear()


# ---- the snapshot ----

def build():
    """The active household as a "state" message, or None while no household is loaded (main menu, CAS)."""
    import services

    household = services.active_household()
    if household is None:
        return None
    try:
        active = services.active_sim_info()
    except Exception:
        active = None

    members = list(household.sim_info_gen())
    sims = []
    for sim_info in members:
        try:
            sims.append(_sim(sim_info, active, members))
        except Exception as exc:
            _warn_once("a Sim", exc)

    return {
        "type": "state",
        "household": _household(household),
        "world": _world(),
        "active_sim_id": str(active.sim_id) if active is not None else None,
        "sims": sims,
    }


def _household(household):
    result = {"name": None, "funds": None}
    try:
        result["name"] = household.name
    except Exception as exc:
        _warn_once("household name", exc)
    try:
        result["funds"] = int(household.funds.money)
    except Exception as exc:
        _warn_once("household funds", exc)
    return result


def _world():
    import services

    world = {}
    try:
        now = services.time_service().sim_now
        world["day"] = _DAY_NAMES[int(now.day()) % 7]
        world["time"] = "{:02d}:{:02d}".format(int(now.hour()), int(now.minute()))
    except Exception as exc:
        _warn_once("game time", exc)
    try:
        season_service = services.season_service()
        if season_service is not None and season_service.season is not None:
            world["season"] = pretty(season_service.season.name.lower())
    except Exception as exc:
        _warn_once("season", exc)
    try:
        zone_data = services.get_persistence_service().get_zone_proto_buff(services.current_zone_id())
        if zone_data is not None and zone_data.name:
            world["lot"] = zone_data.name
    except Exception as exc:
        _warn_once("lot name", exc)
    try:
        from clock import ClockSpeedMode
        world["paused"] = services.game_clock_service().clock_speed == ClockSpeedMode.PAUSED
    except Exception as exc:
        _warn_once("clock speed", exc)
    return world


def _sim(sim_info, active, members):
    sim = {
        "id": str(sim_info.sim_id),
        "first_name": sim_info.first_name or "",
        "last_name": sim_info.last_name or "",
        "is_active": active is not None and sim_info.sim_id == active.sim_id,
    }
    _field(sim, "age", lambda: _AGE_NAMES.get(sim_info.age.name, pretty(sim_info.age.name.lower())))
    _field(sim, "gender", lambda: sim_info.gender.name.title())
    _field(sim, "on_lot", lambda: bool(sim_info.is_instanced()))
    _field(sim, "mood", lambda: pretty(_type_name(sim_info.get_mood()), ("Mood_",)))
    _field(sim, "mood_intensity", lambda: int(sim_info.get_mood_intensity()))
    _field(sim, "needs", lambda: _needs(sim_info))
    _field(sim, "traits", lambda: _traits(sim_info))
    _field(sim, "career", lambda: _career(sim_info))
    _field(sim, "activity", lambda: _activity(sim_info))
    _field(sim, "relationships", lambda: _relationships(sim_info, active, members))
    return sim


def _field(target, key, read):
    try:
        target[key] = read()
    except Exception as exc:
        _warn_once(key, exc)


def _needs(sim_info):
    tracker = sim_info.commodity_tracker
    if tracker is None:
        return None
    needs = {}
    for key, tuning_name in _MOTIVES.items():
        stat_type = _statistic(tuning_name)
        if stat_type is None:
            continue
        stat = tracker.get_statistic(stat_type)
        if stat is None:
            continue  # e.g. toddlers and pets have different motives
        value = stat.get_value()
        # Motives run -100 (empty) .. 100 (full); send 0..100.
        needs[key] = round((float(value) + 100.0) / 2.0, 1)
    return needs


def _traits(sim_info):
    from traits.trait_type import TraitType

    names = []
    for trait in sim_info.trait_tracker.equipped_traits:
        if getattr(trait, "trait_type", None) != TraitType.PERSONALITY:
            continue
        name = pretty(_type_name(trait), ("trait_",))
        if name:
            names.append(name)
    return names


def _career(sim_info):
    tracker = sim_info.career_tracker
    if tracker is None or not tracker.careers:
        return None
    career = next(iter(tracker.careers.values()))
    name = pretty(_type_name(type(career)), ("career_Adult_", "career_Teen_", "career_Child_", "career_"))
    level = None
    try:
        level = int(career.user_level)
    except Exception:
        pass
    return {"name": name, "level": level}


def _activity(sim_info):
    sim = sim_info.get_sim_instance()
    if sim is None:
        return None
    interaction = sim.queue.running
    if interaction is None:
        return None
    # A mixer (one line of a conversation) belongs to a bigger interaction; describe that.
    parent = getattr(interaction, "super_interaction", None)
    if parent is not None:
        interaction = parent
    name = _type_name(interaction.affordance)
    if not name or any(word in name.lower() for word in _IDLE_WORDS):
        return None
    words = pretty(name)
    if not words:
        return None
    # Affordances start with the object they belong to ("stove Cook ..."), which reads badly.
    parts = words.split()
    if len(parts) > 1 and parts[0].lower() in ("sim", "si", "mixer", "social", "object", "terrain"):
        parts = parts[1:]
    return " ".join(parts)


def _relationships(sim_info, active, members):
    tracker = sim_info.relationship_tracker
    friendship = _statistic(_FRIENDSHIP_TRACK)
    romance = _statistic(_ROMANCE_TRACK)

    others = [m for m in members if m.sim_id != sim_info.sim_id]
    if active is not None and active.sim_id != sim_info.sim_id and all(m.sim_id != active.sim_id for m in others):
        others.append(active)

    result = []
    for other in others:
        rel = {"id": str(other.sim_id), "name": "{} {}".format(other.first_name, other.last_name).strip()}
        if not tracker.has_relationship(other.sim_id):
            rel["bits"] = []
            result.append(rel)
            continue
        if friendship is not None:
            rel["friendship"] = round(float(tracker.get_relationship_score(other.sim_id, friendship)), 1)
        if romance is not None:
            rel["romance"] = round(float(tracker.get_relationship_score(other.sim_id, romance)), 1)
        bits = []
        for bit in tracker.get_all_bits(other.sim_id):
            raw = _type_name(bit)
            if not raw or not raw.lower().startswith(_BIT_PREFIXES):
                continue
            name = pretty(re.sub(r"^(family|romantic|friendship)[-_]?", "", raw, flags=re.I))
            if name and name not in bits:
                bits.append(name)
        rel["bits"] = bits
        result.append(rel)
    return result
