from decimal import Decimal
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
import time
from sqlalchemy import func, text, inspect
from sqlalchemy import event

from config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
scheduler = BackgroundScheduler(daemon=True)

# کش برای هشدارهای جهانی جهت جلوگیری از کندی
_warning_cache = {'count': 0, 'timestamp': 0}

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

def auto_repair_db(app):
    """مکانیزم هوشمند برای افزودن خودکار ستون‌های جدید به دیتابیس SQLite"""
    with app.app_context():
        inspector = inspect(db.engine)
        # دریافت لیست تمام جداول موجود در دیتابیس
        existing_tables = inspector.get_table_names()
        
        for table_name, table_obj in db.metadata.tables.items():
            if table_name in existing_tables:
                # دریافت ستون‌های فعلی دیتابیس
                db_columns = [c['name'] for c in inspector.get_columns(table_name)]
                
                for column in table_obj.columns:
                    if column.name not in db_columns:
                        # ستون در دیتابیس نیست، پس باید اضافه شود
                        column_type = column.type.compile(db.engine.dialect)
                        default_clause = ""
                        if column.default is not None:
                            val = column.default.arg
                            if isinstance(val, str):
                                default_clause = f" DEFAULT '{val}'"
                            elif isinstance(val, bool):
                                default_clause = f" DEFAULT {1 if val else 0}"
                            else:
                                default_clause = f" DEFAULT {val}"
                        elif not column.nullable:
                            default_clause = " DEFAULT 0"
                            
                        sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {column_type}{default_clause}'
                        try:
                            db.session.execute(text(sql))
                            print(f"✅ ستون جدید '{column.name}' به جدول '{table_name}' اضافه شد.")
                        except Exception as e:
                            print(f"⚠️ خطا در افزودن ستون {column.name}: {e}")
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
        now = time.time()
        # کش کردن نتایج برای ۵ دقیقه جهت جلوگیری از گلوگاه در کوئری‌های سنگین Count
        if now - _warning_cache['timestamp'] < 300:
            return dict(global_warnings_count=_warning_cache['count'])
        try:
            from app.models import Sheep, InventoryItem, Task
            # استفاده از .count() مستقیم در دیتابیس به جای لود کردن و شمردن در پایتون
            sick_sheep = db.session.query(func.count(Sheep.id)).filter(Sheep.status == 'بیمار').scalar() or 0
            low_stock = db.session.query(func.count(InventoryItem.id)).filter(InventoryItem.quantity <= InventoryItem.min_threshold).scalar() or 0
            pending_tasks = db.session.query(func.count(Task.id)).filter(Task.task_date == datetime.now(UTC).date(), Task.is_done == False).scalar() or 0
            total = sick_sheep + low_stock + pending_tasks
            _warning_cache['count'] = total
            _warning_cache['timestamp'] = now
            return dict(global_warnings_count=total)
        except Exception:
            return dict(global_warnings_count=_warning_cache['count'])

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
        # ایجاد خودکار جداول در صورت عدم وجود (اولین اجرا)
        # این خط باعث می‌شود کوئری‌های بعدی با خطای "no such table" مواجه نشوند
        try:
            db.create_all()
            # اجرای مکانیزم خودکار برای ستون‌های جدید (مثل is_deleted)
            auto_repair_db(app)
        except Exception as e:
            app.logger.error(f"Database creation failed: {e}")

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
        
        # اطمینان از وجود حساب‌های ضروری
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

    # مکانیزم همگامی انبار و مالی: بازگرداندن موجودی در صورت حذف فاکتور خرید
    from app.models import Transaction, InventoryItem
    @event.listens_for(db.session, "before_flush")
    def observe_transaction_deletion(session, flush_context, instances):
        for obj in session.deleted:
            if isinstance(obj, Transaction) and obj.category == 'خرید انبار (خودکار)':
                import re
                # استخراج مقدار و نام کالا از شرح فاکتور
                match = re.search(r"خرید ([\d.]+) .* (.*)$", obj.description)
                if match:
                    try:
                        amount = Decimal(match.group(1))
                        item_name = match.group(2).strip()
                        item = InventoryItem.query.filter_by(name=item_name).first()
                        if item:
                            # جلوگیری از منفی شدن موجودی در صورت حذف اشتباه
                            if item.quantity >= amount:
                                item.quantity -= amount
                                # نکته حسابرسی: در سیستم‌های پیشرفته اینجا باید Recalculate Unit Price فراخوانی شود
                            else:
                                raise Exception(f"خطای حسابرسی: حذف این فاکتور باعث منفی شدن موجودی {item.name} می‌شود.")
                    except Exception as e:
                        if "خطای حسابرسی" in str(e): raise e

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
    
