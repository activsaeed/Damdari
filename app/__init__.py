from flask import Flask, request, redirect, url_for, session, current_app
from flask_login import current_user
from werkzeug.security import generate_password_hash
import jdatetime
from datetime import datetime, UTC
import os
import time
from sqlalchemy import text, inspect, func

from config import Config
from app.extensions import db, migrate, login_manager, csrf, scheduler, rate_limit, _warning_cache
from app.utils import get_system_setting, set_system_setting
from app.events import observe_transaction_deletion
import app.scheduler as scheduler_module


def auto_repair_db(app):
    is_dev = os.getenv('FLASK_ENV', 'development') == 'development'
    if not is_dev:
        return

    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()

        for table_name, table_obj in db.metadata.tables.items():
            if table_name not in existing_tables:
                continue
            db_columns = {c['name'] for c in inspector.get_columns(table_name)}

            for column in table_obj.columns:
                if column.name not in db_columns:
                    column_type = column.type.compile(db.engine.dialect)
                    parts = [
                        f'ALTER TABLE "{table_name}"',
                        f'ADD COLUMN "{column.name}"',
                        column_type,
                    ]
                    if column.default is not None:
                        val = column.default.arg
                        if isinstance(val, str):
                            parts.append(f"DEFAULT '{val}'")
                        elif isinstance(val, bool):
                            parts.append(f"DEFAULT {1 if val else 0}")
                        else:
                            parts.append(f"DEFAULT {val}")
                    elif not column.nullable:
                        parts.append("DEFAULT 0")

                    sql = " ".join(parts)
                    try:
                        db.session.execute(text(sql))
                        print(f"✅ ستون جدید '{column.name}' به جدول '{table_name}' اضافه شد.")
                    except Exception as e:
                        print(f"⚠️ خطا در افزودن ستون {column.name}: {e}")
        db.session.commit()


def create_app(config_class=None):
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config.from_object(config_class or Config)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    from app.models import User, TransactionCategory, FeedRation, Medicine, BreedCategory, PurposeCategory, StatusCategory, TelegramBot

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_global_settings():
        return dict(get_system_currency_from_settings=lambda: get_system_setting('currency_unit', 'تومان'))

    @app.errorhandler(404)
    def not_found(e):
        return '<div style="text-align:center;padding:80px 20px;font-family:Vazirmatn,sans-serif"><h1 style="font-size:80px;color:#dc3545">۴۰۴</h1><p style="font-size:20px;color:#666">صفحه مورد نظر یافت نشد</p><a href="/" style="color:#0d6efd;text-decoration:none">← بازگشت به داشبورد</a></div>', 404

    @app.errorhandler(500)
    def server_error(e):
        return '<div style="text-align:center;padding:80px 20px;font-family:Vazirmatn,sans-serif"><h1 style="font-size:80px;color:#dc3545">۵۰۰</h1><p style="font-size:20px;color:#666">خطای داخلی سرور</p><a href="/" style="color:#0d6efd;text-decoration:none">← بازگشت به داشبورد</a></div>', 500

    @app.before_request
    def check_valid_login():
        if request.endpoint in ['finance.update_sensors', 'finance.update_weight_iot']:
            return
        if request.endpoint and 'static' not in request.endpoint and 'auth.' not in request.endpoint:
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))

    from app.blueprints.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    from app.blueprints.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)
    from app.blueprints.livestock import livestock_bp
    app.register_blueprint(livestock_bp, url_prefix='/livestock')
    from app.blueprints.finance import finance_bp
    app.register_blueprint(finance_bp, url_prefix='/finance')
    from app.blueprints.inventory import inventory_bp
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    from app.blueprints.hr import hr_bp
    app.register_blueprint(hr_bp, url_prefix='/hr')
    from app.blueprints.reports import reports_bp
    app.register_blueprint(reports_bp, url_prefix='/reports')
    from app.blueprints.assets import assets_bp
    app.register_blueprint(assets_bp, url_prefix='/assets')
    from app.blueprints.audit import audit_bp
    app.register_blueprint(audit_bp, url_prefix='/audit')

    @app.context_processor
    def inject_global_warnings():
        now = time.time()
        if now - _warning_cache['timestamp'] < 300:
            return dict(global_warnings_count=_warning_cache['count'])
        try:
            from app.models import Sheep, InventoryItem, Task
            sick_sheep = db.session.query(func.count(Sheep.id)).filter(Sheep.status == 'بیمار').scalar() or 0
            low_stock = db.session.query(func.count(InventoryItem.id)).filter(InventoryItem.quantity <= InventoryItem.min_threshold).scalar() or 0
            pending_tasks = db.session.query(func.count(Task.id)).filter(Task.task_date == datetime.now(UTC).date(), Task.is_done == False).scalar() or 0
            total = sick_sheep + low_stock + pending_tasks
            _warning_cache['count'] = total
            _warning_cache['timestamp'] = now
            return dict(global_warnings_count=total)
        except Exception:
            return dict(global_warnings_count=_warning_cache['count'])

    @app.template_filter('jalali')
    def format_jalali(dt):
        if not dt: return '-'
        if hasattr(dt, 'togregorian') and not hasattr(dt, 'date'):
            return dt.strftime('%Y/%m/%d')
        try:
            target_dt = dt.date() if hasattr(dt, 'date') else dt
            jdate = jdatetime.date.fromgregorian(date=target_dt)
            return jdate.strftime('%Y/%m/%d')
        except Exception:
            return str(dt)

    @app.template_filter('currency')
    def currency_filter(amount):
        if amount is None: amount = 0
        from decimal import Decimal
        try:
            amount = Decimal(str(amount))
        except Exception:
            amount = Decimal('0')
        unit = get_system_setting('currency_unit', 'تومان')
        factor = Decimal('10') if unit == 'ریال' else Decimal('1')
        converted_amount = amount * factor
        formatted = "{:,.0f}".format(converted_amount)
        return f"{formatted} {unit}"

    with app.app_context():
        try:
            db.create_all()
            auto_repair_db(app)
        except Exception as e:
            app.logger.error(f"Database creation failed: {e}")

        if not User.query.filter_by(username=app.config['ADMIN_USERNAME']).first():
            admin_user = User(
                username=app.config['ADMIN_USERNAME'],
                name=app.config['ADMIN_NAME'],
                password_hash=generate_password_hash(app.config['ADMIN_PASSWORD']),
                role='مدیر',
                can_view_livestock=True,
                can_view_finance=True,
                can_view_inventory=True,
                can_view_hr=True,
                can_view_reports=True,
                can_view_settings=True
            )
            db.session.add(admin_user)

        from app.models import Account, AccountType
        t_asset = AccountType.query.filter_by(name='دارایی').first()
        t_liability = AccountType.query.filter_by(name='بدهی').first()
        t_equity = AccountType.query.filter_by(name='حقوق صاحبان سهام').first()
        required_accounts = [
            {'code': '3010', 'name': 'مانده افتتاحیه (سرمایه)', 'type': t_equity},
            {'code': '3020', 'name': 'سود و زیان انباشته', 'type': t_equity},
            {'code': '1050', 'name': 'اسناد دریافتنی', 'type': t_asset},
            {'code': '2020', 'name': 'اسناد پرداختنی', 'type': t_liability},
        ]
        for ra in required_accounts:
            if ra['type'] and not Account.query.filter_by(code=ra['code']).first():
                db.session.add(Account(code=ra['code'], name=ra['name'], account_type_id=ra['type'].id))
        db.session.commit()

        scheduler_module.refresh_scheduler(app)
        app.refresh_backup_scheduler = lambda: scheduler_module.refresh_scheduler(app)

    return app