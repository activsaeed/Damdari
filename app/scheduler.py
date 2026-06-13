import os
import requests
from datetime import datetime
from flask import current_app
from app.extensions import db, scheduler
from app.utils import get_system_setting


def scheduled_telegram_backup_task(app):
    with app.app_context():
        from app.models import TelegramBot
        bots = TelegramBot.query.filter_by(is_active=True).all()
        if not bots:
            return

        db_path = os.path.join(current_app.root_path, 'damdari.db')
        for bot in bots:
            url = f"https://api.telegram.org/bot{bot.bot_token}/sendDocument"
            try:
                with open(db_path, 'rb') as f:
                    requests.post(
                        url,
                        data={
                            'chat_id': bot.chat_id,
                            'caption': f"بک‌آپ خودکار سیستم\nتاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}\nگیرنده: {bot.bot_name}"
                        },
                        files={'document': f},
                        timeout=20
                    )
            except Exception:
                pass


def refresh_scheduler(app):
    h = int(get_system_setting('backup_hour', 0))
    m = int(get_system_setting('backup_minute', 0))

    try:
        scheduler.remove_job('daily_backup')
    except Exception:
        pass

    scheduler.add_job(
        id='daily_backup',
        func=lambda: scheduled_telegram_backup_task(app),
        trigger="cron",
        hour=h,
        minute=m
    )
    if not scheduler.running:
        scheduler.start()