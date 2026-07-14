from apscheduler.schedulers.background import BackgroundScheduler
import config
import reply_tracker
import sender

_scheduler = None


def start():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler()

    _scheduler.add_job(
        reply_tracker.poll_all_accounts,
        "interval",
        seconds=config.REPLY_POLL_INTERVAL_SECONDS,
        id="reply_poll",
        max_instances=1,
    )

    if config.AUTO_AUTOMATION_ENABLED:
        # Full automation: every AUTO_SEND_INTERVAL_SECONDS, send a bounded
        # batch for every campaign currently set to 'running'. Set a
        # campaign to 'running' (via the Campaigns page) and it'll keep
        # being worked through automatically without you clicking "Send 50".
        _scheduler.add_job(
            sender.run_all_running_campaigns,
            "interval",
            seconds=config.AUTO_SEND_INTERVAL_SECONDS,
            id="auto_send",
            max_instances=1,
        )

    _scheduler.start()
    return _scheduler