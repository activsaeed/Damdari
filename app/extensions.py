from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from apscheduler.schedulers.background import BackgroundScheduler
from functools import wraps
from flask import request, session, jsonify
import time

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
scheduler = BackgroundScheduler(daemon=True)

_warning_cache = {'count': 0, 'timestamp': 0}


def rate_limit(limit=10, per=60):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = f"rl_{f.__name__}_{request.remote_addr or 'local'}"
            now = time.time()
            hits = session.get(key, [])
            hits = [t for t in hits if now - t < per]
            if len(hits) >= limit:
                return jsonify({'error': f'محدودیت نرخ: حداکثر {limit} درخواست در {per} ثانیه'}), 429
            hits.append(now)
            session[key] = hits
            return f(*args, **kwargs)
        return wrapper
    return decorator