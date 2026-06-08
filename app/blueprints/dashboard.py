import requests
from decimal import Decimal
import os
from flask_login import current_user, login_required
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app, jsonify
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, UTC
from app import db
from sqlalchemy import text, func, case
import jdatetime
from app.models import InventoryLog, InventoryCategory, TelegramBot
from app.accounting_engine import AccountingEngine
from app import get_system_setting, set_system_setting
from app.models import (Sheep, Transaction, InventoryItem, Task, WeightRecord, User, Pen, Medicine, BreedCategory, PurposeCategory, StatusCategory, FeedRation, FeedingSchedule, TreatmentTemplate, AuditLog, Cheque, MedicalRecord, SystemSetting, Unit, MedicineCategory, BuyerCategory, TransactionCategory, InventoryCategory)

dashboard_bp = Blueprint('dashboard', __name__)

# تابع کمکی برای مدیریت آپلود فایل
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ['png', 'jpg', 'jpeg', 'gif']

def get_setting(key, default):
    setting = SystemSetting.query.filter_by(key=key).first()
    return setting.value if setting else default

# اضافه کردن تنظیمات به صورت سراسری برای تمام تمپلیت‌ها (جهت نمایش در سایدبار و پاسپورت)
@dashboard_bp.app_context_processor
def inject_settings():
    try:
        all_settings = {s.key: s.value for s in SystemSetting.query.all()}
    except:
        all_settings = {}
    return dict(system_settings=all_settings)

@dashboard_bp.route('/')
@login_required
def index():
    if current_user.role == 'کارگر':
        return redirect(url_for('hr.index'))

    from app.models import Account, JournalEntryLine, JournalEntry

    # استفاده از SQL برای محاسبات بدون بارگذاری تمام دام‌ها
    gender_stats_raw = db.session.query(
        func.coalesce(Sheep.gender, 'نامشخص').label('gender'),
        func.count(Sheep.id).label('total'),
        func.sum(func.cast(Sheep.status == 'زنده و سالم', db.Integer)).label('سالم'),
        func.sum(func.cast(Sheep.status == 'بیمار', db.Integer)).label('بیمار'),
        func.sum(func.cast((Sheep.status.in_(['قرنطینه'])) | (Sheep.status.contains('تحت درمان')), db.Integer)).label('قرنطینه'),
        func.sum(func.cast((Sheep.status == 'آبستن') & (Sheep.gender.like('%میش%')), db.Integer)).label('آبستن')
    ).filter(Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).group_by(Sheep.gender).all()

    # مقداردهی اولیه برای جلوگیری از خطای UndefinedError در Jinja2 (زمانی که دیتابیس خالی است)
    gender_stats = {
        'میش': {'total': 0, 'سالم': 0, 'بیمار': 0, 'قرنطینه': 0, 'آبستن': 0},
        'قوچ': {'total': 0, 'سالم': 0, 'بیمار': 0, 'قرنطینه': 0, 'آبستن': 0},
        'بره': {'total': 0, 'سالم': 0, 'بیمار': 0, 'قرنطینه': 0, 'آبستن': 0}
    }

    for gender, total, healthy, sick, quarantine, pregnant in gender_stats_raw:
        g_name = 'بره' if gender and 'بره' in gender else gender
        if g_name not in gender_stats:
            gender_stats[g_name] = {'total': 0, 'سالم': 0, 'بیمار': 0, 'قرنطینه': 0, 'آبستن': 0}
        
        gender_stats[g_name]['total'] += total or 0
        gender_stats[g_name]['سالم'] += healthy or 0
        gender_stats[g_name]['بیمار'] += sick or 0
        gender_stats[g_name]['قرنطینه'] += quarantine or 0
        gender_stats[g_name]['آبستن'] += pregnant or 0

    breed_stats_raw = db.session.query(
        func.coalesce(Sheep.breed, 'نامشخص').label('breed'),
        func.count(Sheep.id).label('count')
    ).filter(Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).group_by(Sheep.breed).all()

    breed_stats = {b: cnt for b, cnt in breed_stats_raw}

    weight_ranges_data = db.session.query(
        func.count(Sheep.id).label('cnt'),
        case(
            (Sheep.weight < 20, '10-20'),
            (Sheep.weight < 30, '20-30'),
            (Sheep.weight < 40, '30-40'),
            (Sheep.weight < 50, '40-50'),
            (Sheep.weight < 60, '50-60'),
            (Sheep.weight < 70, '60-70'),
            (Sheep.weight < 80, '70-80'),
            (Sheep.weight < 90, '80-90'),
            (Sheep.weight < 100, '90-100'),
            (Sheep.weight < 110, '100-110'),
            (Sheep.weight < 120, '110-120'),
            else_='120-130'
        ).label('range')
    ).filter(Sheep.weight.isnot(None), Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).group_by('range').all()

    weight_ranges = {'10-20':0, '20-30':0, '30-40':0, '40-50':0, '50-60':0, '60-70':0, '70-80':0, '80-90':0, '90-100':0, '100-110':0, '110-120':0, '120-130':0}
    for cnt, rng in weight_ranges_data:
        weight_ranges[rng] = cnt or 0

    total_sheep = sum(breed_stats.values())
    total_live_weight = db.session.query(func.sum(Sheep.weight)).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده']),
        Sheep.weight.isnot(None)
    ).scalar() or 0

    weight_above = {'بالای 50':0, 'بالای 60':0, 'بالای 70':0, 'بالای 80':0, 'بالای 90':0, 'بالای 100':0, 'بالای 110':0}
    
    # بهینه‌سازی: محاسبه تمام آمارهای وزنی در یک کوئری واحد جهت افزایش سرعت
    above_data = db.session.query(
        func.sum(case((Sheep.weight >= 50, 1), else_=0)),
        func.sum(case((Sheep.weight >= 60, 1), else_=0)),
        func.sum(case((Sheep.weight >= 70, 1), else_=0)),
        func.sum(case((Sheep.weight >= 80, 1), else_=0)),
        func.sum(case((Sheep.weight >= 90, 1), else_=0)),
        func.sum(case((Sheep.weight >= 100, 1), else_=0)),
        func.sum(case((Sheep.weight >= 110, 1), else_=0))
    ).filter(Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).first()

    if above_data:
        keys = ['بالای 50', 'بالای 60', 'بالای 70', 'بالای 80', 'بالای 90', 'بالای 100', 'بالای 110']
        for i, key in enumerate(keys):
            weight_above[key] = above_data[i] or 0

    inventory_items = InventoryItem.query.all()
    transactions = Transaction.query.order_by(Transaction.t_date.desc()).limit(5).all()
    total_expense = db.session.query(func.sum(Transaction.amount)).filter_by(t_type='هزینه').scalar() or 0
    total_income = db.session.query(func.sum(Transaction.amount)).filter_by(t_type='درآمد').scalar() or 0

    # بهینه‌سازی: محاسبه مجموع ارزش دفتری با یک کوئری واحد (حذف حلقه پایتونی و N+1)
    from app.models import Equipment, JournalEntryLine
    total_purchase_price = db.session.query(func.sum(Equipment.purchase_price)).scalar() or 0
    total_accumulated_depreciation = db.session.query(func.sum(JournalEntryLine.credit)).filter(
        JournalEntryLine.description.ilike('%ذخیره استهلاک انباشته%')
    ).scalar() or 0
    total_assets_book_value = total_purchase_price - total_accumulated_depreciation

    # محاسبات سود - استفاده از SQL بجای حلقه
    total_rev_ledger = db.session.query(func.sum(JournalEntryLine.credit)).join(Account).filter(Account.code.startswith('4')).scalar() or 0
    total_exp_ledger = db.session.query(func.sum(JournalEntryLine.debit)).join(Account).filter(Account.code.startswith('5')).scalar() or 0
    net_income = total_rev_ledger - total_exp_ledger

    valuation_gain = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).join(Account).filter(
        Account.code == '4101', JournalEntry.description.ilike('%تعدیل ارزش منصفانه%')
    ).scalar() or 0
    valuation_loss = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).join(Account).filter(
        Account.code == '5101', JournalEntry.description.ilike('%تعدیل ارزش منصفانه%')
    ).scalar() or 0

    net_valuation_profit = valuation_gain - valuation_loss
    operational_profit = net_income - net_valuation_profit

    # --- محاسبات رشد سود ماهانه (ویجت جدید) ---
    now_j = jdatetime.datetime.now()
    start_curr_g = jdatetime.date(now_j.year, now_j.month, 1).togregorian()
    if now_j.month == 12: end_curr_g = jdatetime.date(now_j.year + 1, 1, 1).togregorian()
    else: end_curr_g = jdatetime.date(now_j.year, now_j.month + 1, 1).togregorian()

    if now_j.month == 1: start_prev_g = jdatetime.date(now_j.year - 1, 12, 1).togregorian()
    else: start_prev_g = jdatetime.date(now_j.year, now_j.month - 1, 1).togregorian()
    end_prev_g = start_curr_g

    def get_monthly_net(s, e):
        rev = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).join(Account).filter(
            Account.code.startswith('4'), JournalEntry.date >= s, JournalEntry.date < e
        ).scalar() or 0
        exp = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).join(Account).filter(
            Account.code.startswith('5'), JournalEntry.date >= s, JournalEntry.date < e
        ).scalar() or 0
        return rev - exp

    curr_month_profit = get_monthly_net(start_curr_g, end_curr_g)
    prev_month_profit = get_monthly_net(start_prev_g, end_prev_g)
    
    profit_growth = 0
    if prev_month_profit != 0:
        profit_growth = ((curr_month_profit - prev_month_profit) / abs(prev_month_profit)) * 100
    elif curr_month_profit > 0:
        profit_growth = 100

    # سیستم هشدار بحران مالی (هزینه + استهلاک > درآمد)
    financial_alert = False
    # کل هزینه های عملیاتی (کد 5) شامل خوراک و استهلاک
    if total_exp_ledger > total_rev_ledger and total_rev_ledger > 0:
        financial_alert = True

    # محاسبه مجموع بدهی بیمه پرداختنی سازمان (کد 2101 با شرح بیمه)
    insurance_debt = db.session.query(
        func.sum(JournalEntryLine.credit - JournalEntryLine.debit)
    ).join(Account).filter(
        Account.code == '2101',
        JournalEntryLine.description.ilike('%بیمه پرداختنی سازمان%')
    ).scalar() or 0

    # --- پیش‌بینی اتمام موجودی انبار خوراک ---
    thirty_days_ago = datetime.now(UTC).date() - timedelta(days=30)
    total_consumed_30d = db.session.query(func.sum(InventoryLog.amount)).join(InventoryItem).join(InventoryCategory).filter(
        InventoryLog.action_type == 'خروج',
        InventoryLog.date >= thirty_days_ago,
        InventoryCategory.name.in_(['خوراک', 'علوفه'])
    ).scalar() or 0
    
    avg_daily_consumption = total_consumed_30d / 30
    current_feed_inv = db.session.query(func.sum(InventoryItem.quantity)).join(InventoryCategory).filter(InventoryCategory.name.in_(['خوراک', 'علوفه'])).scalar() or 0
    days_until_empty = int(current_feed_inv / avg_daily_consumption) if avg_daily_consumption > 0 else 999

    # --- سیستم خودکار گزارش روزانه موجودی بحرانی به تلگرام ---
    if current_user.role == 'مدیر':
        last_stock_rep = get_setting('last_daily_stock_rep', '2000-01-01')
        last_stock_date = datetime.strptime(last_stock_rep, '%Y-%m-%d').date()

        if (datetime.now(UTC).date() - last_stock_date).days >= 1:
            low_stock = InventoryItem.query.filter(InventoryItem.quantity <= InventoryItem.min_threshold).all()
            if low_stock:
                token = os.getenv('TELEGRAM_API_KEY') or get_setting('sms_api_key', '')
                chat_id = os.getenv('TELEGRAM_CHAT_ID') or "6690587060"

                if token:
                    msg = "⚠️ #گزارش_بحرانی_انبار\n\nمدیریت محترم، موجودی اقلام زیر به حداقل مجاز رسیده است:\n\n"
                    for item in low_stock:
                        msg += f"📦 {item.name}: {item.quantity:,.1f} {item.unit.name if item.unit else ''}\n"
                    msg += "\n🔔 لطفا نسبت به تامین نهاده اقدام فرمایید."

                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={'chat_id': chat_id, 'text': msg}, timeout=5)
                    except: pass

            setting = SystemSetting.query.filter_by(key='last_daily_stock_rep').first()
            if not setting:
                db.session.add(SystemSetting(key='last_daily_stock_rep', value=datetime.now(UTC).strftime('%Y-%m-%d')))
            else:
                setting.value = datetime.now(UTC).strftime('%Y-%m-%d')
            db.session.commit()

    today_str = jdatetime.date.today().strftime('%Y/%m/%d')

    return render_template('dashboard/index.html', 
                           total_sheep=total_sheep, total_live_weight=total_live_weight,
                           gender_stats=gender_stats, breed_stats=breed_stats, weight_ranges=weight_ranges, weight_above=weight_above,
                           inventory_items=inventory_items, total_expense=total_expense, total_income=total_income,
                           transactions=transactions, 
                           operational_profit=operational_profit, 
                           net_valuation_profit=net_valuation_profit, 
                           curr_month_profit=curr_month_profit,
                           total_assets_book_value=total_assets_book_value,
                           profit_growth=round(profit_growth, 1),
                           financial_alert=financial_alert,
                           insurance_debt=insurance_debt,
                           feed_days_left=days_until_empty,
                           today_str=today_str)


@dashboard_bp.route('/warnings')
@login_required
def warnings():
    from app.models import Sheep, WeightRecord, InventoryItem, Task
    # بهینه‌سازی: دریافت مستقیم فقط دام‌های بیمار (نه همه ۷۰۰۰ تا)
    sick_sheep = Sheep.query.filter_by(status='بیمار').all()
    
    weight_loss_sheep = []
    recent_limit = datetime.now(UTC).date() - timedelta(days=45)

    # بهینه‌سازی نهایی: استفاده از یک کوئری واحد و پیشرفته برای پیدا کردن کاهش وزن‌ها بدون حلقه تکراری
    sql = text("""
        WITH RankedWeights AS (
            SELECT 
                sheep_id, 
                weight, 
                record_date,
                ROW_NUMBER() OVER (PARTITION BY sheep_id ORDER BY record_date DESC) as rn
            FROM weight_record
        )
        SELECT rw1.sheep_id, rw1.weight, rw2.weight, rw1.record_date
        FROM RankedWeights rw1
        JOIN RankedWeights rw2 ON rw1.sheep_id = rw2.sheep_id
        WHERE rw1.rn = 1 AND rw2.rn = 2 
          AND rw1.weight < rw2.weight
          AND rw1.record_date >= :limit
    """)
    
    results = db.session.execute(sql, {"limit": recent_limit}).fetchall()
    
    if results:
        target_sheep_ids = [r[0] for r in results]
        # دریافت اطلاعات دام‌ها به صورت یکجا
        sheep_map = {s.id: s for s in Sheep.query.filter(Sheep.id.in_(target_sheep_ids)).all()}
        
        for s_id, current_w, prev_w, r_date in results:
            sheep_obj = sheep_map.get(s_id)
            if sheep_obj:
                # تبدیل تاریخ از رشته (در SQLite) به شیء date برای جلوگیری از خطای strftime در قالب
                if isinstance(r_date, str):
                    try:
                        r_date = datetime.strptime(r_date[:10], '%Y-%m-%d').date()
                    except:
                        pass

                weight_loss_sheep.append({
                    'sheep': sheep_obj, 
                    'lost': round(prev_w - current_w, 2), 
                    'date': r_date
                })

    # درخواست 2: اگر دامپزشک بود، فقط کاهش وزن و بیمار برایش ارسال میشود
    if current_user.role == 'دامپزشک':
        return render_template('dashboard/warnings.html', sick_sheep=sick_sheep, weight_loss_sheep=weight_loss_sheep, low_stock_items=[], pending_tasks=[])
    
    # بهینه‌سازی کوئری انبار
    low_stock_items = InventoryItem.query.filter(InventoryItem.quantity <= InventoryItem.min_threshold).all()
    pending_tasks = Task.query.filter_by(task_date=datetime.now(UTC).date(), is_done=False).all()
    return render_template('dashboard/warnings.html', sick_sheep=sick_sheep, low_stock_items=low_stock_items, pending_tasks=pending_tasks, weight_loss_sheep=weight_loss_sheep)

# ... (کدهای ابتدای فایل dashboard.py شامل ایمپورت ها و توابع index و warnings دست نخورده باقی بماند) ...

@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_pen':
            db.session.add(Pen(name=request.form.get('name'), capacity=request.form.get('capacity'), pen_type=request.form.get('pen_type')))
            flash('بهاربند جدید اضافه شد.', 'success')
        elif action == 'add_medicine':
            db.session.add(Medicine(name=request.form.get('name'), medicine_category_id=request.form.get('medicine_category_id')))
            flash('داروی جدید اضافه شد.', 'success')
        elif action == 'add_ration':
            daily_cost_val = request.form.get('daily_cost')
            db.session.add(FeedRation(name=request.form.get('name'), daily_cost=float(daily_cost_val) if daily_cost_val else 0.0, description=request.form.get('description')))
            flash('جیره جدید اضافه شد.', 'success')
        elif action == 'add_breed':
            db.session.add(BreedCategory(name=request.form.get('name')))
            flash('نژاد جدید اضافه شد.', 'success')
        elif action == 'add_purpose':
            db.session.add(PurposeCategory(name=request.form.get('name')))
            flash('هدف پرورش اضافه شد.', 'success')
        elif action == 'add_status':
            db.session.add(StatusCategory(name=request.form.get('name'), type=request.form.get('type')))
            flash('وضعیت جدید اضافه شد.', 'success')
        elif action == 'add_protocol':
            db.session.add(TreatmentTemplate(name=request.form.get('name'), medicines=request.form.get('medicines'), description=request.form.get('description')))
            flash('پروتکل درمانی جدید اضافه شد.', 'success')
        elif action == 'add_schedule':
            amount_val = request.form.get('amount_kg')
            db.session.add(FeedingSchedule(
                feed_ration_id=request.form.get('feed_ration_id'), 
                time_of_day=request.form.get('time_of_day'), 
                inventory_item_id=request.form.get('inventory_item_id'), 
                amount_kg=float(amount_val) if amount_val else 0.0
            ))
            flash('برنامه تغذیه ثبت شد.', 'success')
            db.session.commit()
            return redirect(url_for('dashboard.feeding_schedule'))
        elif action == 'add_unit':
            db.session.add(Unit(name=request.form.get('name'), description=request.form.get('description')))
            db.session.commit()
            flash('واحد اندازه‌گیری جدید اضافه شد.', 'success')
        elif action == 'add_med_cat':
            db.session.add(MedicineCategory(name=request.form.get('name')))
            db.session.commit()
            flash('دسته‌بندی دارویی اضافه شد.', 'success')
        elif action == 'add_inv_cat':
            db.session.add(InventoryCategory(name=request.form.get('name')))
            db.session.commit()
            flash('دسته‌بندی جدید انبار اضافه شد.', 'success')
        elif action == 'add_trans_cat':
            db.session.add(TransactionCategory(name=request.form.get('name'), type=request.form.get('type')))
            db.session.commit()
            flash('دسته‌بندی مالی جدید (درآمد/هزینه) اضافه شد.', 'success')
        elif action == 'add_buyer_cat':
            db.session.add(BuyerCategory(name=request.form.get('name')))
            db.session.commit()
            flash('نوع خریدار جدید اضافه شد.', 'success')
        elif action == 'update_constants':
            for key in ['market_price', 'vat_rate', 'maturity_days', 'birth_weight', 'daily_feed_est', 'page_size', 'sms_api_key', 'sms_sender_number', 'sms_service_provider', 'farm_name', 'backup_hour', 'backup_minute']:
                val = request.form.get(key)
                if val:
                    setting = SystemSetting.query.filter_by(key=key).first()
                    if not setting: setting = SystemSetting(key=key)
                    setting.value = val
                    db.session.add(setting)
            
            # بروزرسانی زمان‌بندی بک‌آپ
            if hasattr(current_app, 'refresh_backup_scheduler'):
                current_app.refresh_backup_scheduler()
                
            # مدیریت آپلود لوگو
            if 'farm_logo' in request.files:
                logo_file = request.files['farm_logo']
                if logo_file and allowed_file(logo_file.filename):
                    filename = secure_filename(logo_file.filename)
                    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'logo')
                    os.makedirs(upload_dir, exist_ok=True)
                    logo_path = os.path.join(upload_dir, filename)
                    logo_file.save(logo_path)

                    setting = SystemSetting.query.filter_by(key='farm_logo_path').first()
                    if not setting: setting = SystemSetting(key='farm_logo_path')
                    setting.value = f'uploads/logo/{filename}' # ذخیره مسیر نسبی
                    db.session.add(setting)
            db.session.commit()
            flash('ثوابت سیستمی و اقتصادی با موفقیت بروزرسانی شدند.', 'success')

        # مدیریت ربات‌های تلگرام
        elif action == 'add_tg_bot':
            db.session.add(TelegramBot(
                bot_name=request.form.get('bot_name'),
                bot_token=request.form.get('bot_token'),
                chat_id=request.form.get('chat_id')
            ))
            flash('ربات جدید به لیست بک‌آپ اضافه شد.', 'success')

        # ---> بخش جدید ساخت کاربر سیستم <---
        elif action == 'add_user':
            username = request.form.get('username')
            if User.query.filter_by(username=username).first():
                flash('این نام کاربری از قبل وجود دارد!', 'danger')
            else:
                perms = request.form.getlist('permissions')
                db.session.add(User(
                    username=username, name=request.form.get('name'), password_hash=generate_password_hash(request.form.get('password')), role=request.form.get('role'),
                    can_view_livestock='livestock' in perms, can_view_finance='finance' in perms,
                    can_view_inventory='inventory' in perms, can_view_hr='hr' in perms,
                    can_view_reports='reports' in perms, can_view_settings='settings' in perms
                ))
                flash('کاربر جدید با دسترسی‌های تعیین شده ساخته شد.', 'success')

        elif action == 'edit_user':
            user_id = request.form.get('user_id')
            u = User.query.get_or_404(user_id)
            u.name = request.form.get('name')
            u.role = request.form.get('role')
            
            # بروزرسانی رمز عبور فقط در صورت وارد کردن مقدار جدید
            new_password = request.form.get('password')
            if new_password:
                u.password_hash = generate_password_hash(new_password)
                
            perms = request.form.getlist('permissions')
            u.can_view_livestock = 'livestock' in perms
            u.can_view_finance = 'finance' in perms
            u.can_view_inventory = 'inventory' in perms
            u.can_view_hr = 'hr' in perms
            u.can_view_reports = 'reports' in perms
            u.can_view_settings = 'settings' in perms
            flash(f'اطلاعات کاربر {u.username} بروزرسانی شد.', 'info')
                
        db.session.commit()
        return redirect(url_for('dashboard.settings'))
        
    return render_template('dashboard/settings.html', 
                           units=Unit.query.all(),
                           pens=Pen.query.all(), medicines=Medicine.query.order_by(Medicine.name).all(),
                           medicine_categories=MedicineCategory.query.all(),
                           buyer_categories=BuyerCategory.query.all(),
                           transaction_categories=TransactionCategory.query.all(),
                           rations=FeedRation.query.all(), breeds=BreedCategory.query.all(),
                           tg_bots=TelegramBot.query.all(),
                           purposes=PurposeCategory.query.all(), statuses=StatusCategory.query.all(),
                           protocols=TreatmentTemplate.query.all(), users=User.query.all(),
                           settings={s.key: s.value for s in SystemSetting.query.all()},
                           weight_count=WeightRecord.query.count(),
                           audit_count=AuditLog.query.count(),
                           # آمار تفکیکی جداول برای گزارش حجم
                           db_stats = [
                               {'name': 'سوابق وزن‌کشی', 'count': WeightRecord.query.count(), 'icon': 'fa-weight-scale', 'size_mb': WeightRecord.query.count() * 0.00004},
                               {'name': 'لاگ‌های امنیتی', 'count': AuditLog.query.count(), 'icon': 'fa-user-secret', 'size_mb': AuditLog.query.count() * 0.00008},
                               {'name': 'فاکتورهای بایگانی', 'count': Transaction.query.filter_by(is_archived=True).count(), 'icon': 'fa-box-archive', 'size_mb': Transaction.query.filter_by(is_archived=True).count() * 0.00015},
                               {'name': 'چک‌های مختومه', 'count': Cheque.query.filter(Cheque.status != 'در جریان').count(), 'icon': 'fa-file-circle-check', 'size_mb': Cheque.query.filter(Cheque.status != 'در جریان').count() * 0.00020},
                               {'name': 'دام‌های خارج شده', 'count': Sheep.query.filter(Sheep.status.in_(['فروخته شده', 'تلف شده', 'مرده'])).count(), 'icon': 'fa-skull-crossbones', 'size_mb': Sheep.query.filter(Sheep.status.in_(['فروخته شده', 'تلف شده', 'مرده'])).count() * 0.00025},
                               {'name': 'کل شناسنامه‌ها', 'count': Sheep.query.count(), 'icon': 'fa-sheep', 'size_mb': Sheep.query.count() * 0.00030}
                           ], # مقادیر ضرب شده میانگین حجم هر ردیف به مگابایت هستند
                           # محاسبه حجم کل فایل دیتابیس
                           db_file_mb = os.path.getsize(os.path.join(current_app.root_path, 'damdari.db')) / (1024 * 1024)
                           if os.path.exists(os.path.join(current_app.root_path, 'damdari.db')) else 0
                           )

@dashboard_bp.route('/run_valuation', methods=['POST'])
@login_required
def run_valuation():
    """اجرای عملیات ارزیابی ارزش منصفانه گله (استاندارد ۲۶)"""
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    # دریافت قیمت جدید از فرم ارسالی کاربر
    raw_price = request.form.get('market_price', '0').replace(',', '')
    try:
        market_price = Decimal(raw_price)
    except ValueError:
        market_price = Decimal('0')

    if market_price <= 0:
        flash('لطفاً قیمت معتبری برای هر کیلوگرم وارد کنید.', 'warning')
        return redirect(url_for('dashboard.index'))
    
    # محاسبه کل وزن زنده گله فعلی (بدون حذف شده‌ها)
    total_live_weight = db.session.query(func.sum(Sheep.weight)).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])
    ).scalar() or 0
    
    total_fair_value = total_live_weight * market_price
    
    try:
        # بروزرسانی آخرین قیمت در تنظیمات جهت استفاده‌های بعدی
        set_system_setting('market_price', str(int(market_price)))
        
        unit = get_system_setting('currency_unit', 'تومان')
        factor = 10 if unit == 'ریال' else 1
        display_total = total_fair_value * factor

        db.session.commit()
        flash(f'قیمت روز بازار بروزرسانی شد. ارزش برآوردی کل گله: {display_total:,.0f} {unit}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در ثبت سند ارزیابی: {str(e)}', 'danger')
        
    return redirect(request.referrer or url_for('dashboard.index'))

@dashboard_bp.route('/maintenance/close_fiscal_year', methods=['POST'])
@login_required
def close_fiscal_year():
    """بستن حساب‌های موقت در پایان سال مالی"""
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        AccountingEngine.close_temporary_accounts()
        db.session.commit()
        flash('حساب‌های موقت با موفقیت بسته شدند و سود/زیان به حساب دائم منتقل گردید. دفتار برای سال مالی جدید آماده است.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در بستن حساب‌ها: {str(e)}', 'danger')

    return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/maintenance/opening_entry', methods=['POST'])
@login_required
def issue_opening_entry():
    """صدور سند افتتاحیه جهت انتقال مانده‌ها به سال جدید"""
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    try:
        AccountingEngine.record_opening_entry()
        db.session.commit()
        flash('سند افتتاحیه صادر شد. مانده حساب‌های دائمی به عنوان موجودی اول دوره جدید ثبت گردید.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در صدور سند افتتاحیه: {str(e)}', 'danger')
    return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/run_depreciation', methods=['POST'])
@login_required
def run_depreciation():
    """ثبت هزینه استهلاک تجهیزات و ساختمان"""
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    
    asset_name = request.form.get('asset_name')
    amount = float(request.form.get('amount', '0').replace(',', ''))
    
    if amount <= 0:
        flash('مبلغ استهلاک باید بیشتر از صفر باشد.', 'warning')
        return redirect(url_for('dashboard.settings'))

    try:
        AccountingEngine.record_depreciation(asset_name, amount)
        db.session.commit()
        flash(f'هزینه استهلاک برای {asset_name} با موفقیت در دفاتر ثبت شد.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در ثبت استهلاک: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/maintenance/sync_inventory', methods=['POST'])
@login_required
def sync_inventory():
    """تطبیق انبار و دفتر کل جهت انتقال به سال جدید"""
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        entry = AccountingEngine.sync_inventory_ledger()
        db.session.commit()
        if entry:
            flash('تطبیق انبار انجام شد. هزینه مصرف کالا شناسایی و سند مالی صادر گردید.', 'success')
        else:
            flash('مانده انبار و دفتر کل از قبل کاملاً تراز هستند.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در تطبیق انبار: {str(e)}', 'danger')

    return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/run_daily_feed', methods=['POST'])
@login_required
def run_daily_feed():
    """ثبت خودکار مصرف خوراک بر اساس برنامه تغذیه (FeedingSchedule)"""
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    
    today = datetime.now(UTC).date()

    # 1. دریافت تعداد دام‌های متصل به هر جیره با یک کوئری بهینه
    ration_counts = db.session.query(
        Sheep.feed_ration_id, func.count(Sheep.id)
    ).filter(Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده']), Sheep.feed_ration_id.isnot(None))\
     .group_by(Sheep.feed_ration_id).all()

    consumption_map = {}
    for ration_id, sheep_count in ration_counts:
        schedules = FeedingSchedule.query.filter_by(feed_ration_id=ration_id).all()
        for sched in schedules:
            item_id = sched.inventory_item_id
            total_needed = float(sched.amount_kg) * sheep_count
            consumption_map[item_id] = consumption_map.get(item_id, 0) + total_needed

    try:
        total_cost = 0
        for item_id, qty in consumption_map.items():
            item = InventoryItem.query.get(item_id)
            if item and item.quantity >= qty:
                item.quantity -= qty
                total_cost += qty * (item.unit_price or 0)
                db.session.add(InventoryLog(
                    item_id=item.id, action_type='خروج', amount=qty, 
                    transaction_price=item.unit_price, date=today, 
                    notes="کسر اتوماتیک جیره روزانه سیستم"
                ))
        
        if total_cost > 0:
            AccountingEngine.record_feed_consumption(total_cost)
            db.session.commit()
            flash('مصرف روزانه بر اساس برنامه تغذیه با موفقیت کسر شد.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در ثبت خودکار: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/maintenance/fix_ration_names', methods=['POST'])
@login_required
def fix_ration_names():
    # این متد با توجه به جایگزینی FK با String Matching دیگر کاربردی ندارد.
    return redirect(url_for('reports.index'))

@dashboard_bp.route('/maintenance/fix_all_ration_names', methods=['POST'])
@login_required
def fix_all_ration_names():
    flash('با توجه به سیستم جدید انتخاب کالا از انبار، دیگر نیازی به اصلاح نام‌ها نیست.', 'info')
    return redirect(url_for('reports.index'))

@dashboard_bp.route('/maintenance/cleanup_transactions', methods=['POST'])
@login_required
def cleanup_transactions():
    """حذف فاکتورهای بایگانی شده قدیمی (بیش از ۲ سال) جهت سبک سازی"""
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('dashboard.index'))

    cutoff_date = datetime.now(UTC).date() - timedelta(days=730)
    # تضمین حذف فقط داده‌های غیرحساس و بایگانی شده در یک تراکنش واحد
    with db.session.begin_nested():
        deleted_count = Transaction.query.filter(
            Transaction.is_archived == True, 
            Transaction.t_date < cutoff_date, 
            Transaction.is_starred == False
        ).delete(synchronize_session=False)

    db.session.commit()
    flash(f'پاکسازی فاکتورهای بایگانی قدیمی (قبل از ۲ سال) انجام شد. {deleted_count} مورد حذف گردید.', 'success')
    return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/maintenance/cleanup_cheques', methods=['POST'])
@login_required
def cleanup_cheques():
    """حذف چک‌های پاس شده قدیمی (بیش از ۲ سال)"""
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('dashboard.index'))

    cutoff_date = datetime.now(UTC).date() - timedelta(days=730)
    deleted_count = Cheque.query.filter(Cheque.status == 'پاس شده', Cheque.due_date < cutoff_date).delete()
    db.session.commit()
    flash(f'پاکسازی چک‌های قدیمی انجام شد. {deleted_count} مورد از دیتابیس حذف گردید.', 'success')
    return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/maintenance/cleanup_removed_sheep', methods=['POST'])
@login_required
def cleanup_removed_sheep():
    """حذف شناسنامه دام‌های خارج شده قدیمی (بیش از ۲ سال)"""
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('dashboard.index'))

    cutoff_date = datetime.now(UTC).date() - timedelta(days=730)
    # حذف دام‌های فروخته شده قدیمی (تاریخ فروش ملاک است)
    sold_deleted = Sheep.query.filter(Sheep.status == 'فروخته شده', Sheep.sale_date < cutoff_date).delete()
    # توجه: دام‌های تلف شده فیلد تاریخ خروج ندارند، لذا بر اساس entry_date حذف میشوند
    dead_deleted = Sheep.query.filter(Sheep.status.in_(['تلف شده', 'مرده']), Sheep.entry_date < cutoff_date).delete()
    
    db.session.commit()
    flash(f'پاکسازی انجام شد. {sold_deleted + dead_deleted} شناسنامه قدیمی از سیستم حذف گردید.', 'success')
    return redirect(url_for('dashboard.settings'))

# ---> اضافه شدن مجدد صفحه مدیریت تغذیه <---
@dashboard_bp.route('/feeding_schedule')
def feeding_schedule():
    from app.models import FeedRation
    return render_template('dashboard/feeding.html', rations=FeedRation.query.all())

@dashboard_bp.route('/delete_setting/<type>/<int:id>')
@login_required
def delete_setting(type, id):
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    from app.models import Pen, Medicine, FeedRation, BreedCategory, TreatmentTemplate, PurposeCategory, StatusCategory, FeedingSchedule, MedicineCategory, InventoryCategory, BuyerCategory, TransactionCategory
    obj = None
    if type == 'pen': 
        obj = Pen.query.get_or_404(id)
        for s in obj.sheep_list: s.pen_id = None
    elif type == 'medicine': obj = Medicine.query.get_or_404(id)
    elif type == 'med_cat': obj = MedicineCategory.query.get_or_404(id)
    elif type == 'inv_cat': obj = InventoryCategory.query.get_or_404(id)
    elif type == 'trans_cat': obj = TransactionCategory.query.get_or_404(id)
    elif type == 'buyer_cat': obj = BuyerCategory.query.get_or_404(id)
    elif type == 'ration': 
        obj = FeedRation.query.get_or_404(id)
        for s in obj.sheep_list: s.feed_ration_id = None
    elif type == 'breed': obj = BreedCategory.query.get_or_404(id)
    elif type == 'protocol': obj = TreatmentTemplate.query.get_or_404(id)
    elif type == 'purpose': obj = PurposeCategory.query.get_or_404(id)
    elif type == 'status': obj = StatusCategory.query.get_or_404(id)
    elif type == 'tg_bot': obj = TelegramBot.query.get_or_404(id)
    # ---> اضافه شدن مجدد قابلیت حذف برنامه تغذیه <---
    elif type == 'schedule': obj = FeedingSchedule.query.get_or_404(id)
    
    db.session.delete(obj)
    db.session.commit()
    flash('آیتم با موفقیت حذف شد.', 'warning')
    return redirect(request.referrer)

@dashboard_bp.route('/delete_unit/<int:id>')
@login_required
def delete_unit(id):
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    unit = Unit.query.get_or_404(id)
    db.session.delete(unit)
    db.session.commit()
    flash('واحد اندازه‌گیری با موفقیت حذف شد.', 'warning')
    return redirect(request.referrer)



@dashboard_bp.route('/delete_user/<int:id>')
def delete_user(id):
    from app.models import User
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    u = User.query.get_or_404(id)
    if u.username == 'admin':
        flash('اکانت ادمین اصلی قابل حذف نیست!', 'danger')
    else:
        db.session.delete(u)
        db.session.commit()
        flash('اکانت کاربر با موفقیت مسدود و حذف شد.', 'warning')
    return redirect(request.referrer)



# ==========================================
# سیستم بک آپ گیری دیتابیس (Import/Export/Telegram)
# ==========================================
@dashboard_bp.route('/backup/download')
@login_required
def backup_download():
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    db_path = os.path.join(current_app.root_path, 'damdari.db')
    return send_file(db_path, as_attachment=True, download_name=f"Damdari_Backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")

@dashboard_bp.route('/backup/telegram')
@login_required
def backup_telegram():
    """ارسال دستی بک‌آپ به تمامی ربات‌های فعال تلگرام"""
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    db_path = os.path.join(current_app.root_path, 'damdari.db')
    bots = TelegramBot.query.filter_by(is_active=True).all()
    if not bots:
        flash('ابتدا باید حداقل یک ربات فعال در تنظیمات تعریف کنید.', 'warning')
        return redirect(url_for('dashboard.settings'))

    success_count = 0
    for bot in bots:
        url = f"https://api.telegram.org/bot{bot.bot_token}/sendDocument"
        try:
            with open(db_path, 'rb') as f:
                requests.post(url, data={'chat_id': bot.chat_id, 'caption': f"📦 بک‌آپ دستی - {bot.bot_name}\n📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}"}, files={'document': f}, timeout=15)
            success_count += 1
        except: 
            pass
        
    flash(f'بک‌آپ به {success_count} ربات تلگرام با موفقیت ارسال شد.', 'success')
    return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/backup/restore', methods=['POST'])
@login_required
def backup_restore():
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    file = request.files.get('backup_file')
    if file and file.filename.endswith('.db'):
        db_path = os.path.join(current_app.root_path, 'damdari.db')
        file.save(db_path) # اوررایت کردن فایل فعلی با فایل بک آپ
        flash('دیتابیس با موفقیت بازگردانی شد. اطلاعات سیستم بروز شد.', 'success')
    else:
        flash('فایل نامعتبر است. فقط فایل های .db پذیرفته میشوند.', 'danger')
    return redirect(url_for('dashboard.settings'))

# ==========================================
# سیستم مچ‌گیری و حسابرسی (Audit Trail)
# ==========================================
@dashboard_bp.route('/audit_logs')
@login_required
def audit_logs():
    from app.models import AuditLog
    if not current_user.can_view_settings and current_user.role != 'مدیر': 
        return redirect(url_for('dashboard.index'))
    
    target = request.args.get('filter_target')
    query = AuditLog.query
    if target:
        query = query.filter(AuditLog.action.ilike(f"%{target}%"))
        
    logs = query.order_by(AuditLog.timestamp.desc()).limit(200).all()
    return render_template('dashboard/audit.html', logs=logs)

@dashboard_bp.route('/maintenance/cleanup_logs', methods=['POST'])
@login_required
def cleanup_audit_logs():
    """حذف لاگ‌های امنیتی قدیمی‌تر از یک سال"""
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('dashboard.index'))

    cutoff_date = datetime.utcnow() - timedelta(days=365)
    deleted_count = AuditLog.query.filter(AuditLog.timestamp < cutoff_date).delete()
    db.session.commit()

    flash(f'عملیات سبک‌سازی لاگ‌ها انجام شد. {deleted_count} مورد قدیمی حذف گردید.', 'success')
    return redirect(url_for('dashboard.settings'))


@dashboard_bp.route('/toggle_currency')
@login_required
def toggle_currency():
    """تغییر سریع واحد پول سیستم بین تومان و ریال"""
    if current_user.role != 'مدیر':
        return redirect(request.referrer or url_for('dashboard.index'))
    
    current_unit = get_system_setting('currency_unit', 'تومان')
    new_unit = 'ریال' if current_unit == 'تومان' else 'تومان'
    set_system_setting('currency_unit', new_unit)
    
    flash(f'واحد پول سیستم به {new_unit} تغییر یافت.', 'info')
    return redirect(request.referrer or url_for('dashboard.index'))