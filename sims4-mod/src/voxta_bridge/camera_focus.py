"""Points the game camera at a Sim. Must run on the game's main thread (main.py calls it from the alarm)."""

from . import log

_failed_once = False


def focus(sim_id, follow=False):
    """Pans (or, with follow, locks) the camera onto a Sim on the current lot. Returns False if that's not possible."""
    global _failed_once
    import camera
    import services

    try:
        sim_info = services.sim_info_manager().get(int(sim_id))
    except (TypeError, ValueError):
        return False
    if sim_info is None:
        return False
    sim = sim_info.get_sim_instance()
    if sim is None:
        return False  # not on this lot: nothing to look at

    try:
        camera.focus_on_sim(sim=sim, follow=bool(follow))
        return True
    except Exception as exc:
        if not _failed_once:
            _failed_once = True
            log.error("Could not move the camera (further camera errors are not logged)", exc)
        return False
