"""Shows a chat line in the game as a notification (the toasts in the top-right corner).

Must run on the game's main thread; main.py only calls it from the game alarm.
"""

from . import log


def show(title, text, sim_id=None):
    import services
    from distributor.shared_messages import IconInfoData
    from sims4.localization import LocalizationHelperTuning
    from ui.ui_dialog_notification import UiDialogNotification

    sim_info = None
    if sim_id:
        try:
            sim_info = services.sim_info_manager().get(int(sim_id))
        except (TypeError, ValueError):
            sim_info = None

    owner = services.active_sim_info()
    title_text = str(title or "")
    body_text = str(text or "")

    dialog = UiDialogNotification.TunableFactory().default(
        owner,
        text=lambda *_, **__: LocalizationHelperTuning.get_raw_text(body_text),
        title=lambda *_, **__: LocalizationHelperTuning.get_raw_text(title_text),
    )
    if sim_info is not None:
        try:
            dialog.show_dialog(icon_override=IconInfoData(obj_instance=sim_info))
            return
        except Exception as exc:
            # A portrait is nice to have; the words are what matter.
            log.error("Could not show the notification with a portrait, showing it without", exc)
    dialog.show_dialog()
