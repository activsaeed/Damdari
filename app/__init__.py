from flask import Flask, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash
import jdatetime
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, UTC
import os
import requests
from sqlalchemy import func, text, inspect

from config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
scheduler = BackgroundScheduler(daemon=True)

def get_system_setting(key, default):
    from app.models import SystemSetting
    s = SystemSetting.query.filter_by(key=key).first()
    return s.value if s else default

def set_system_setting(key, value):
    from app.models import SystemSetting
    s = SystemSetting.query.filter_by(key=key).first()
    if not s:
        s = SystemSetting(key=key, value=str(value))
        db.session.add(s)
    else:
        s.value = str(value)
    db.session.commit()

def create_app():
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    from app.models import User, TransactionCategory, FeedRation, Medicine, BreedCategory, PurposeCategory, StatusCategory, TelegramBot
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # اینجکت کردن تنظیمات عمومی سیستم به تمامی قالب‌ها
    @app.context_processor
    def inject_global_settings():
        return dict(get_system_currency_from_settings=lambda: get_system_setting('currency_unit', 'تومان'))

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

    @app.context_processor
    def inject_global_warnings():
        try:
            from app.models import Sheep, InventoryItem, Task
            # استفاده از .count() مستقیم در دیتابیس به جای لود کردن و شمردن در پایتون
            sick_sheep = db.session.query(func.count(Sheep.id)).filter(Sheep.status == 'بیمار').scalar() or 0
            low_stock = db.session.query(func.count(InventoryItem.id)).filter(InventoryItem.quantity <= InventoryItem.min_threshold).scalar() or 0
            pending_tasks = db.session.query(func.count(Task.id)).filter(Task.task_date == datetime.now(UTC).date(), Task.is_done == False).scalar() or 0
            return dict(global_warnings_count=(sick_sheep + low_stock + pending_tasks))
        except:
            return dict(global_warnings_count=0)

    # ---> فیلتر هوشمند تاریخ شمسی برای قالب های HTML <---
    @app.template_filter('jalali')
    def format_jalali(dt):
        if not dt: return '-'
        # اگر ورودی از قبل شیء jdatetime (شمسی) باشد، فقط فرمت کن
        if hasattr(dt, 'togregorian') and not hasattr(dt, 'date'): 
            return dt.strftime('%Y/%m/%d')
        try:
            # تبدیل از میلادی به شمسی
            target_dt = dt.date() if hasattr(dt, 'date') else dt
            jdate = jdatetime.date.fromgregorian(date=target_dt)
            return jdate.strftime('%Y/%m/%d')
        except Exception:
            return str(dt) # Fallback if conversion fails

    # ---> فیلتر هوشمند تبدیل واحد پول (تومان/ریال) <---
    @app.template_filter('currency')
    def currency_filter(amount):
        if amount is None: amount = 0
        # دریافت واحد پول از تنظیمات سیستم # ۱. حل بحران واحد پول و هاردکد مالیات (Data Integrity & VAT)
        unit = get_system_setting('currency_unit', 'تومان')
        factor = 10 if unit == 'ریال' else 1
        
        converted_amount = amount * factor
        formatted = "{:,.0f}".format(converted_amount)
        return f"{formatted} {unit}"

    with app.app_context():
        # استفاده از db.create_all() تنها برای جداول غیر موجود
        # ایده‌آل: از Flask-Migrate برای migrations استفاده کنید
        try:
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()

            # اگر اساساً دیتابیس خالی است، بسازید
            if not existing_tables or 'user' not in existing_tables:
                db.create_all()
        except Exception as e:
            print(f"Warning: Could not check existing tables: {e}")
            db.create_all()

        # مدیریت دیتابیس به Flask-Migrate منتقل شد.
        # تمامی ALTER TABLE های دستی حذف شدند تا از تداخل و فساد داده جلوگیری شود.
        
        # ---> رفع باگ: ساخت ادمین با نقش دقیق "مدیر" و تمام دسترسی‌های True <---
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
        
        pass # تمامی داده های پایه و بذرپاشی اکنون از طریق seed.py مدیریت می شوند
    # ---> سیستم بک آپ گیری اتوماتیک ساعت 12 شب <---
    def scheduled_telegram_backup_task():
        with app.app_context():
            from app.models import TelegramBot
            bots = TelegramBot.query.filter_by(is_active=True).all()
            if not bots: return
            
            db_path = os.path.join(current_app.root_path, 'damdari.db')
            for bot in bots:
                url = f"https://api.telegram.org/bot{bot.bot_token}/sendDocument"
                try:
                    with open(db_path, 'rb') as f:
                        requests.post(url, data={'chat_id': bot.chat_id, 'caption': f"🤖 بک‌آپ خودکار سیستم\n📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n👤 گیرنده: {bot.bot_name}"}, files={'document': f}, timeout=20)
                except: pass

    def refresh_scheduler():
        """بروزرسانی زمان‌بندی بک‌آپ بر اساس تنظیمات جدید"""
        with app.app_context():
            h = int(get_system_setting('backup_hour', 0))
            m = int(get_system_setting('backup_minute', 0))
            
            # حذف جاب قبلی اگر وجود داشت
            try: scheduler.remove_job('daily_backup')
            except: pass
            
            scheduler.add_job(
                id='daily_backup',
                func=scheduled_telegram_backup_task,
                trigger="cron",
                hour=h,
                minute=m
            )
            if not scheduler.running:
                scheduler.start()

    # استارت اولیه زمان‌بند
    refresh_scheduler()
    # اتچ کردن تابع رفرش به اپلیکیشن برای استفاده در بلوپرینت تنظیمات
    app.refresh_backup_scheduler = refresh_scheduler

    return app    
    
