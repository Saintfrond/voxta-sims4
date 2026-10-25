"""Just enough of The Sims 4's Python API to run the mod outside the game.

install() puts fake `services`, `alarms`, `clock`, `zone`, `sims4.*`, ... modules into sys.modules
and returns a FakeGame to steer: a household, the clock, recorded notifications and commands.
The shapes follow the game's own modules as far as the mod uses them.
"""

import enum
import sys
import types


class Age(enum.Enum):
    CHILD = 4
    TEEN = 8
    YOUNGADULT = 16
    ADULT = 32
    ELDER = 64


class Gender(enum.Enum):
    MALE = 4096
    FEMALE = 8192


class TraitType(enum.Enum):
    PERSONALITY = 0
    GAMEPLAY = 1


class ClockSpeedMode(enum.Enum):
    PAUSED = 0
    NORMAL = 1


def tuning(name, **attrs):
    """A tuning class: the game's tuning instances are classes named after their tuning file."""
    return type(name, (), attrs)


MOTIVES = {n: tuning(n) for n in ("motive_Hunger", "motive_Energy", "motive_Bladder", "motive_Hygiene", "motive_Social", "motive_Fun")}
TRACKS = {n: tuning(n) for n in ("LTR_Friendship_Main", "LTR_Romance_Main")}


class Stat(object):
    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value


class CommodityTracker(object):
    def __init__(self, values):
        self.values = values  # tuning name -> -100..100

    def get_statistic(self, stat_type):
        value = self.values.get(stat_type.__name__)
        return None if value is None else Stat(value)


class TraitTracker(object):
    def __init__(self, traits):
        self.equipped_traits = traits


class CareerTracker(object):
    def __init__(self, career):
        self.careers = {1: career} if career else {}


class RelationshipTracker(object):
    def __init__(self):
        self.scores = {}  # (sim_id, track name) -> score
        self.bits = {}  # sim_id -> [bit tuning]

    def has_relationship(self, sim_id):
        return any(k[0] == sim_id for k in self.scores) or sim_id in self.bits

    def get_relationship_score(self, sim_id, track):
        return self.scores.get((sim_id, track.__name__), 0)

    def get_all_bits(self, sim_id):
        return self.bits.get(sim_id, [])


class Queue(object):
    def __init__(self):
        self.running = None


class Interaction(object):
    def __init__(self, affordance_name, super_interaction=None):
        self.affordance = tuning(affordance_name)
        self.super_interaction = super_interaction


class SimInstance(object):
    def __init__(self):
        self.queue = Queue()


class SimInfo(object):
    def __init__(self, sim_id, first, last, age=Age.ADULT, gender=Gender.FEMALE):
        self.sim_id = sim_id
        self.first_name = first
        self.last_name = last
        self.age = age
        self.gender = gender
        self.mood = tuning("Mood_Fine")
        self.mood_intensity = 1
        self.commodity_tracker = CommodityTracker({name: 20 for name in MOTIVES})  # 20 on -100..100 = 60%
        self.trait_tracker = TraitTracker([])
        self.career_tracker = CareerTracker(None)
        self.relationship_tracker = RelationshipTracker()
        self.instance = SimInstance()

    def get_mood(self):
        return self.mood

    def get_mood_intensity(self):
        return self.mood_intensity

    def is_instanced(self):
        return self.instance is not None

    def get_sim_instance(self):
        return self.instance

    # helpers for tests
    def set_need(self, short, value_0_100):
        self.commodity_tracker.values["motive_" + short.capitalize()] = value_0_100 * 2 - 100


class Funds(object):
    def __init__(self, money):
        self.money = money


class Household(object):
    def __init__(self, name, members, money=20000):
        self.name = name
        self.members = members
        self.funds = Funds(money)

    def sim_info_gen(self):
        return iter(self.members)


class SimNow(object):
    def __init__(self, day=2, hour=14, minute=5):
        self._day, self._hour, self._minute = day, hour, minute

    def day(self):
        return self._day

    def hour(self):
        return self._hour

    def minute(self):
        return self._minute


class FakeGame(object):
    def __init__(self):
        self.household = None
        self.active = None
        self.now = SimNow()
        self.season = None
        self.lot_name = "Willow Creek Home"
        self.notifications = []  # (title, text, icon sim_info or None)
        self.alarms = []  # [owner, callback, repeating, cancelled]
        self.commands = {}
        self.command_output = []

    def run_alarms(self):
        for alarm in list(self.alarms):
            if not alarm["cancelled"]:
                alarm["callback"](alarm)

    def run_command(self, name):
        self.command_output = []
        self.commands[name](_connection=None)
        return list(self.command_output)


def install():
    game = FakeGame()

    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        sys.modules[name] = mod
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(sys.modules[parent], child, mod)
        return mod

    # services
    stat_manager = types.SimpleNamespace(types={i: t for i, t in enumerate(list(MOTIVES.values()) + list(TRACKS.values()))})

    class PersistenceService(object):
        def get_zone_proto_buff(self, zone_id):
            return types.SimpleNamespace(name=game.lot_name)

    class SimInfoManager(object):
        def get(self, sim_id):
            if game.household:
                for member in game.household.members:
                    if member.sim_id == sim_id:
                        return member
            return None

    module(
        "services",
        active_household=lambda: game.household,
        active_sim_info=lambda: game.active,
        time_service=lambda: types.SimpleNamespace(sim_now=game.now),
        season_service=lambda: types.SimpleNamespace(season=game.season) if game.season else None,
        current_zone_id=lambda: 1,
        get_persistence_service=lambda: PersistenceService(),
        game_clock_service=lambda: types.SimpleNamespace(clock_speed=ClockSpeedMode.NORMAL),
        get_instance_manager=lambda kind: stat_manager,
        sim_info_manager=lambda: SimInfoManager(),
    )

    # sims4.*
    module("sims4")
    module("sims4.resources", Types=types.SimpleNamespace(STATISTIC="STATISTIC"))

    class CommandType(enum.Enum):
        Live = 4

    def command(name, command_type=None):
        def decorator(fn):
            game.commands[name] = fn
            return fn
        return decorator

    module(
        "sims4.commands",
        Command=command,
        CommandType=CommandType,
        CheatOutput=lambda connection: game.command_output.append,
    )
    module("sims4.localization", LocalizationHelperTuning=types.SimpleNamespace(get_raw_text=lambda text: ("raw", text)))

    # alarms / clock
    def add_alarm_real_time(owner, span, callback, repeating=False, use_sleep_time=True):
        alarm = {"owner": owner, "callback": callback, "repeating": repeating, "cancelled": False, "span": span}
        game.alarms.append(alarm)
        return alarm

    def cancel_alarm(alarm):
        alarm["cancelled"] = True

    module("alarms", add_alarm_real_time=add_alarm_real_time, cancel_alarm=cancel_alarm)
    module("clock", interval_in_real_seconds=lambda s: ("real_seconds", s), ClockSpeedMode=ClockSpeedMode)

    # zone
    class Zone(object):
        def on_loading_screen_animation_finished(self):
            return "loaded"

    module("zone", Zone=Zone)

    # traits
    module("traits")
    module("traits.trait_type", TraitType=TraitType)

    # notifications
    class Dialog(object):
        def __init__(self, owner, text, title):
            self.text, self.title = text, title

        def show_dialog(self, icon_override=None):
            game.notifications.append((self.title()[1], self.text()[1], getattr(icon_override, "obj_instance", None)))

    class Factory(object):
        def default(self, owner, text=None, title=None):
            return Dialog(owner, text, title)

    module("ui")
    module("ui.ui_dialog_notification", UiDialogNotification=types.SimpleNamespace(TunableFactory=lambda: Factory()))
    module("distributor")
    module("distributor.shared_messages", IconInfoData=lambda obj_instance=None: types.SimpleNamespace(obj_instance=obj_instance))

    return game


def goth_household(game):
    """Bella and Mortimer Goth with their son Cassandra's brother Alexander, roughly."""
    bella = SimInfo(101, "Bella", "Goth", Age.ADULT, Gender.FEMALE)
    mortimer = SimInfo(102, "Mortimer", "Goth", Age.ADULT, Gender.MALE)
    alexander = SimInfo(103, "Alexander", "Goth", Age.CHILD, Gender.MALE)

    bella.trait_tracker = TraitTracker([
        tuning("trait_Romantic", trait_type=TraitType.PERSONALITY),
        tuning("trait_Snob", trait_type=TraitType.PERSONALITY),
        tuning("trait_HiddenLikesWater", trait_type=TraitType.GAMEPLAY),
    ])
    bella.career_tracker = CareerTracker(type("career_Adult_Business", (), {"user_level": 4})())
    bella.relationship_tracker.scores[(102, "LTR_Friendship_Main")] = 80
    bella.relationship_tracker.scores[(102, "LTR_Romance_Main")] = 90
    bella.relationship_tracker.bits[102] = [tuning("romantic-Married")]
    bella.relationship_tracker.bits[103] = [tuning("family_Son"), tuning("hidden_RelBit")]
    bella.instance.queue.running = Interaction("stove_CookDinner")

    mortimer.relationship_tracker.scores[(101, "LTR_Friendship_Main")] = 75
    mortimer.relationship_tracker.bits[101] = [tuning("romantic-Married")]
    mortimer.instance = None  # away from the lot

    game.household = Household("Goth", [bella, mortimer, alexander], money=34500)
    game.active = bella
    return bella, mortimer, alexander
