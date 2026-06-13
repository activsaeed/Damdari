from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required
import logging
import functools
import traceback
import difflib
from app import db
from app.accounting_engine import AccountingEngine
from app.models import (
    Sheep, Transaction, BirthRecord, LactationRecord, InventoryLog, InventoryItem,
    JournalEntry, JournalEntryLine, Account, BreedCategory, FeedingSchedule, Worker,
    FeedRation, Unit, InventoryCategory, Pen
)
from datetime import datetime, timedelta, UTC
from sqlalchemy import or_, and_, func, cast, case
from sqlalchemy.orm import joinedload
from app.blueprints.dashboard import get_setting
from app.utils import permission_required
import jdatetime

reports_bp = Blueprint('reports', __name__)

# پیکربندی لاگر اختصاصی برای ثبت خطاهای کوئری و منطق گزارشات
reports_logger = logging.getLogger('reports_errors')
reports_logger.setLevel(logging.ERROR)
if not reports_logger.handlers:
    # ذخیره در فایل reports_errors.log در پوشه اصلی پروژه با پشتیبانی از UTF-8
    file_handler = logging.FileHandler('reports_errors.log', encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    reports_logger.addHandler(file_handler)

def log_report_errors(f):
    """دکوراتور برای لاگ کردن خطاهای احتمالی در توابع گزارش‌گیری"""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            func_name = f.__name__
            error_msg = str(e)
            reports_logger.error(f"Function: {func_name} | Error: {error_msg}\n{traceback.format_exc()}")
            # اجازه می‌دهیم خطا بالا برود تا Flask آن را مدیریت کند
            raise e
    return wrapper

@reports_bp.route('/')
@permission_required('can_view_reports')
@log_report_errors
def index():
    today = datetime.now(UTC).date()
    now_j = jdatetime.datetime.now()
    month_ago = today - timedelta(days=30)
    six_months_ago = today - timedelta(days=180)
    year_ago = today - timedelta(days=365)

    all_breeds = BreedCategory.query.all()
    ai_insights = [] # بازگردانی لیست برای جلوگیری از خطای NameError و TypeError

    # 1. آمار زایش و فرزندان - استفاده از SQL
    born_filter = or_(Sheep.mother_id != None, Sheep.gender.ilike('%بره%'))
    born_stats = db.session.query(
        Sheep.gender,
        func.count(Sheep.id).label('count')
    ).filter(born_filter).group_by(Sheep.gender).all()

    born_genders = {row[0]: row[1] for row in born_stats} if born_stats else {}

    breed_birth_stats = db.session.query(
        func.coalesce(Sheep.breed, 'نامشخص').label('breed'),
        func.count(Sheep.id).label('count')
    ).filter(born_filter).group_by(Sheep.breed).all()

    born_breeds = {row[0]: row[1] for row in breed_birth_stats} if breed_birth_stats else {}

    # 2. آمار فروش و سودآوری نژادها + sold_genders و sold_breeds
    breed_profits = db.session.query(
        Sheep.breed,
        func.count(Sheep.id).label('count'),
        func.sum(Sheep.sale_price - Sheep.purchase_price).label('total_profit')
    ).filter(Sheep.status == 'فروخته شده').group_by(Sheep.breed).all()

    avg_breed_profit = {}
    for row in breed_profits:
        b_name = row[0] or 'نامشخص'
        avg_breed_profit[b_name] = (row[2] / row[1]) if (row[1] and row[1] > 0) else 0

    avg_profit_labels = list(avg_breed_profit.keys())
    avg_profit_data = list(avg_breed_profit.values())

    # 2.1. آمار فروش بر اساس جنسیت و نژاد - SQL (بدون حلقه)
    sold_gender_stats = db.session.query(
        Sheep.gender,
        func.count(Sheep.id).label('count')
    ).filter(Sheep.status == 'فروخته شده').group_by(Sheep.gender).all()

    sold_genders = {row[0]: row[1] for row in sold_gender_stats} if sold_gender_stats else {}

    sold_breed_stats = db.session.query(
        func.coalesce(Sheep.breed, 'نامشخص').label('breed'),
        func.count(Sheep.id).label('count')
    ).filter(Sheep.status == 'فروخته شده').group_by(Sheep.breed).all()

    sold_breeds = {row[0]: row[1] for row in sold_breed_stats} if sold_breed_stats else {}

    # 3. آمار تلفات - استفاده از SQL (بدون حلقه)
    death_causes = {}
    total_financial_loss = db.session.query(
        func.sum(Sheep.purchase_price)
    ).filter(Sheep.status.in_(['تلف شده', 'مرده'])).scalar() or 0

    dead_reason_stats = db.session.query(
        func.coalesce(Sheep.death_reason, 'نامشخص').label('reason'),
        func.count(Sheep.id).label('count')
    ).filter(Sheep.status.in_(['تلف شده', 'مرده'])).group_by(Sheep.death_reason).all()

    death_causes = {row[0]: row[1] for row in dead_reason_stats} if dead_reason_stats else {}

    dead_gender_stats = db.session.query(
        Sheep.gender, func.count(Sheep.id).label('count')
    ).filter(Sheep.status.in_(['تلف شده', 'مرده'])).group_by(Sheep.gender).all()
    dead_genders = {row[0]: row[1] for row in dead_gender_stats} if dead_gender_stats else {}

    dead_breed_stats = db.session.query(
        func.coalesce(Sheep.breed, 'نامشخص').label('breed'), func.count(Sheep.id).label('count')
    ).filter(Sheep.status.in_(['تلف شده', 'مرده'])).group_by(Sheep.breed).all()
    dead_breeds = {row[0]: row[1] for row in dead_breed_stats} if dead_breed_stats else {}

    dead_sheep_count = db.session.query(func.count(Sheep.id)).filter(
        Sheep.status.in_(['تلف شده', 'مرده'])
    ).scalar() or 0

    sold_sheep_ids = db.session.query(Sheep.id).filter(Sheep.status == 'فروخته شده').all()
    sold_sheep_ids = [s[0] for s in sold_sheep_ids]

    # بهینه‌سازی: تجمیع تمام آمارهای دوره‌ای در دو کوئری واحد (حذف ۹ کوئری مجزا)
    sheep_agg = db.session.query(
        func.count(case((and_(Sheep.status.in_(['تلف شده', 'مرده']), Sheep.entry_date >= month_ago), 1))).label('d1m'),
        func.count(case((and_(Sheep.status.in_(['تلف شده', 'مرده']), Sheep.entry_date >= six_months_ago), 1))).label('d6m'),
        func.count(case((and_(Sheep.status.in_(['تلف شده', 'مرده']), Sheep.entry_date >= year_ago), 1))).label('d1y'),
        func.count(case((and_(Sheep.status == 'فروخته شده', Sheep.entry_date >= month_ago), 1))).label('s1m'),
        func.count(case((and_(Sheep.status == 'فروخته شده', Sheep.entry_date >= six_months_ago), 1))).label('s6m'),
        func.count(case((and_(Sheep.status == 'فروخته شده', Sheep.entry_date >= year_ago), 1))).label('s1y')
    ).first()

    # جلوگیری از کرش در صورت خالی بودن دیتابیس
    s_agg = sheep_agg if (sheep_agg and len(sheep_agg) >= 6) else (0,0,0,0,0,0)

    birth_agg = db.session.query(
        func.sum(case((BirthRecord.birth_date >= month_ago, BirthRecord.lambs_count), else_=0)).label('b1m'),
        func.sum(case((BirthRecord.birth_date >= six_months_ago, BirthRecord.lambs_count), else_=0)).label('b6m'),
        func.sum(case((BirthRecord.birth_date >= year_ago, BirthRecord.lambs_count), else_=0)).label('b1y')
    ).first()
    b_agg = birth_agg if (birth_agg and len(birth_agg) >= 3) else (0,0,0)

    stats_1m = {'dead': s_agg[0] or 0, 'sold': s_agg[3] or 0, 'born': b_agg[0] or 0}
    stats_6m = {'dead': s_agg[1] or 0, 'sold': s_agg[4] or 0, 'born': b_agg[1] or 0}
    stats_1y = {'dead': s_agg[2] or 0, 'sold': s_agg[5] or 0, 'born': b_agg[2] or 0}

    combined_chart_labels = ['۳۰ روز', '۶ ماه', 'یک سال']
    combined_chart_born = [stats_1m['born'], stats_6m['born'], stats_1y['born']]
    combined_chart_sold = [stats_1m['sold'], stats_6m['sold'], stats_1y['sold']]
    combined_chart_dead = [stats_1m['dead'], stats_6m['dead'], stats_1y['dead']]

    # 4. تفکیک دقیق درآمد و هزینه
    date_filter = request.args.get('date_filter', '30')
    starred_filter = request.args.get('starred', '')

    tx_filter_kwargs = {}
    if starred_filter == '1':
        tx_filter_kwargs['is_starred'] = True

    income_transactions = db.session.query(
        Transaction.category,
        func.sum(Transaction.amount).label('total')
    ).filter_by(**tx_filter_kwargs).filter(
        Transaction.t_type == 'درآمد',
        ~Transaction.category.ilike('%خرید%'),
        ~Transaction.category.ilike('%هزینه%')
    ).group_by(Transaction.category).all()

    income_breakdown = {row[0]: float(row[1]) for row in income_transactions} if income_transactions else {}
    total_income_val = sum(float(row[1]) for row in income_transactions) if income_transactions else 0

    milk_income = float(db.session.query(func.sum(Transaction.amount)).filter_by(**tx_filter_kwargs).filter(
        Transaction.t_type == 'درآمد',
        Transaction.category.ilike('%شیر%')
    ).scalar() or 0)

    expense_transactions = db.session.query(
        Transaction.category,
        func.sum(Transaction.amount).label('total')
    ).filter_by(**tx_filter_kwargs).filter(
        (Transaction.t_type == 'هزینه') | (Transaction.category.ilike('%خرید%'))
    ).group_by(Transaction.category).all()

    expense_breakdown = {row[0]: float(row[1]) for row in expense_transactions} if expense_transactions else {}

    # 5. گزارش مصرف انبار (رفع باگ صفر بودن نمودار) - استفاده از SQL بجای حلقه
    if date_filter == '30': filter_date = month_ago
    elif date_filter == '180': filter_date = six_months_ago
    elif date_filter == '365': filter_date = year_ago
    else: filter_date = datetime.strptime("2000-01-01", "%Y-%m-%d").date()

    # SQL بهینه شده برای محاسبه مصرف خوراک بدون حلقه
    feed_logs = db.session.query(
        InventoryItem.name,
        Unit.name.label('unit_name'),
        func.sum(InventoryLog.amount).label('total_amount'),
        func.coalesce(
            func.nullif(func.avg(func.nullif(InventoryLog.transaction_price, 0)), None),
            func.avg(InventoryItem.unit_price)
        ).label('avg_price')
    ).join(InventoryLog, InventoryItem.id == InventoryLog.item_id
    ).join(InventoryCategory, InventoryItem.category_id == InventoryCategory.id
    ).outerjoin(Unit, InventoryItem.unit_id == Unit.id
    ).filter(
        InventoryLog.action_type == 'خروج',
        InventoryLog.date >= filter_date,
        InventoryCategory.name.in_(['خوراک', 'علوفه'])
    ).group_by(InventoryItem.id, InventoryItem.name, Unit.name).all()

    feed_consumption = {}
    total_feed_expenses = 0

    for row in feed_logs:
        cost = float(row[2] or 0) * float(row[3] or 0)
        total_feed_expenses += cost
        unit_name = row[1] or '-'

        feed_consumption[row[0]] = {
            'amount': float(row[2] or 0),
            'unit': unit_name,
            'cost': cost
        }

    # 6. بهای تمام شده پیشرفته - استفاده از SQL
    dep_acc_ids = db.session.query(Account.id).filter(Account.code.in_(['5010'])).all()
    dep_acc_ids = [a[0] for a in dep_acc_ids] if dep_acc_ids else []
    total_depreciation = float(db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).filter(
        JournalEntryLine.account_id.in_(dep_acc_ids),
        JournalEntry.description.ilike('%استهلاک%')
    ).scalar() or 0)

    # گزارش سالانه استهلاک برای نمودار یا جدول
    annual_depreciation_report = db.session.query(
        func.strftime('%Y', JournalEntry.date).label('year'),
        func.sum(JournalEntryLine.debit).label('total_depreciation')
    ).join(JournalEntryLine, JournalEntry.id == JournalEntryLine.journal_entry_id)\
     .filter(JournalEntryLine.account_id.in_(dep_acc_ids), 
             JournalEntry.description.ilike('%استهلاک%'))\
     .group_by('year').order_by('year').all()

    total_live_weight = float(db.session.query(func.sum(Sheep.weight)).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده']),
        Sheep.weight.isnot(None)
    ).scalar() or 0)

    total_purchase_cost = float(db.session.query(func.sum(Sheep.purchase_price)).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])
    ).scalar() or 0)

    total_insurance_expenses = float(db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).filter(
        JournalEntryLine.account_id.in_(dep_acc_ids),
        JournalEntryLine.description.ilike('%بیمه سهم کارفرما%')
    ).scalar() or 0)

    insurance_cost_per_kg = (total_insurance_expenses / total_live_weight) if total_live_weight > 0 else 0
    cost_per_kg = ((0 + total_purchase_cost + total_depreciation + total_insurance_expenses) / total_live_weight) if total_live_weight > 0 else 0

    # 6.1. تفکیک بهای تمام شده بر اساس نژاد - SQL بهینه شده بجای حلقه
    breed_weights_stats = db.session.query(
        Sheep.breed,
        func.sum(Sheep.weight).label('total_weight'),
        func.sum(Sheep.purchase_price).label('total_purchase')
    ).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده']),
        Sheep.weight.isnot(None)
    ).group_by(Sheep.breed).all()

    breed_cost_analysis = []
    for row in breed_weights_stats:
        b_purchase = float(row[2] or 0)
        breed_weights = float(row[1] or 0)
        if breed_weights and breed_weights > 0:
            b_cost_per_kg = (b_purchase + total_depreciation) / breed_weights
            breed_cost_analysis.append({
                'name': row[0] or 'نامشخص',
                'cost': b_cost_per_kg,
                'weight': breed_weights
            })

    # 6.2. دیتای نمودار دایره‌ای سود (عملیاتی vs ارزیابی)
    valuation_gain = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).join(Account).filter(
        Account.code == '4010', JournalEntry.description.ilike('%تعدیل ارزش منصفانه%')
    ).scalar() or 0
    valuation_loss = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).join(Account).filter(
        Account.code == '5010', JournalEntry.description.ilike('%تعدیل ارزش منصفانه%')
    ).scalar() or 0
    
    total_rev_ledger = db.session.query(func.sum(JournalEntryLine.credit)).join(Account).filter(Account.code.startswith('4')).scalar() or 0
    total_exp_ledger = db.session.query(func.sum(JournalEntryLine.debit)).join(Account).filter(Account.code.startswith('5')).scalar() or 0
    
    net_val_profit = valuation_gain - valuation_loss
    op_profit = (total_rev_ledger - total_exp_ledger) - net_val_profit
    profit_pie_data = [float(max(0, op_profit)), float(max(0, net_val_profit))]

    # 6.3. روند تغییر ارزش منصفانه گله (۶ ماه اخیر)
    # بهینه‌سازی: استفاده از یک کوئری واحد با گروه‌بندی ماهانه برای روند ۶ ماهه
    livestock_acc = AccountingEngine.get_account('1200')
    trend_data_raw = db.session.query(
        func.strftime('%Y-%m', JournalEntry.date).label('month_key'),
        func.sum(JournalEntryLine.debit - JournalEntryLine.credit)
    ).join(JournalEntry).filter(
        JournalEntryLine.account_id == livestock_acc.id if livestock_acc else -1,
        JournalEntry.date >= six_months_ago
    ).group_by('month_key').order_by('month_key').all()

    trend_map = {row[0]: float(row[1]) for row in trend_data_raw} if trend_data_raw else {}
    trend_labels, trend_values = [], []
    running_val = 0 # در صورت نیاز به مانده تجمعی
    
    for i in range(5, -1, -1):
        d = today - timedelta(days=i*30)
        m_key = d.strftime('%Y-%m')
        trend_labels.append(jdatetime.date.fromgregorian(date=d).strftime('%B'))
        trend_values.append(trend_map.get(m_key, 0))

    # 6.4. گزارش سود و زیان مقایسه‌ای ماهانه (۶ ماه اخیر)
    # بهینه‌سازی: محاسبه درآمد و هزینه تمام ماه‌ها در یک کوئری (حذف ۱۲ کوئری)
    pnl_data_raw = db.session.query(
        func.strftime('%Y-%m', JournalEntry.date).label('month_key'),
        func.sum(case((Account.code.startswith('4'), JournalEntryLine.credit), else_=0)).label('rev'),
        func.sum(case((Account.code.startswith('5'), JournalEntryLine.debit), else_=0)).label('exp')
    ).join(JournalEntryLine, JournalEntry.id == JournalEntryLine.journal_entry_id)\
     .join(Account, JournalEntryLine.account_id == Account.id)\
     .filter(JournalEntry.date >= six_months_ago)\
     .group_by('month_key').all()

    pnl_map = {row[0]: (float(row[1]), float(row[2])) for row in pnl_data_raw} if pnl_data_raw else {}
    monthly_pnl_labels, monthly_pnl_rev, monthly_pnl_exp = [], [], []
    for i in range(5, -1, -1):
        d = today - timedelta(days=i*30)
        m_key = d.strftime('%Y-%m')
        monthly_pnl_labels.append(jdatetime.date.fromgregorian(date=d).strftime('%B'))
        rev, exp = pnl_map.get(m_key, (0, 0))
        monthly_pnl_rev.append(rev)
        monthly_pnl_exp.append(exp)

    # 6.11. روند قیمت خرید نهاده‌های استراتژیک (۶ ماه اخیر) - SQL بهینه شده
    purchase_data_raw = db.session.query(
        func.strftime('%Y-%m', InventoryLog.date).label('month_key'),
        func.avg(case((InventoryItem.name.ilike('%جو%'), InventoryLog.transaction_price))).label('barley'),
        func.avg(case((InventoryItem.name.ilike('%ذرت%'), InventoryLog.transaction_price))).label('corn')
    ).join(InventoryItem).filter(InventoryLog.action_type == 'ورود', InventoryLog.date >= six_months_ago)\
     .group_by('month_key').all()
    
    p_map = {row[0]: (row[1] or 0, row[2] or 0) for row in purchase_data_raw} if purchase_data_raw else {}
    purchase_trend_labels, barley_trend, corn_trend = [], [], []
    for i in range(5, -1, -1):
        d = today - timedelta(days=i*30)
        m_key = d.strftime('%Y-%m')
        purchase_trend_labels.append(jdatetime.date.fromgregorian(date=d).strftime('%B'))
        b, c = p_map.get(m_key, (0, 0))
        barley_trend.append(round(b))
        corn_trend.append(round(c))

    # 6.7. روند بدهی بیمه در ۱۲ ماه اخیر - SQL بهینه شده بجای حلقه
    ins_trend_labels, ins_trend_values = [], []

    # دریافت ID حساب بیمه پرداختنی
    insurance_account = Account.query.filter_by(code='2010').first()
    insurance_account_id = insurance_account.id if insurance_account else None

    if insurance_account_id:
        for i in range(11, -1, -1):
            y, m = now_j.year, now_j.month - i
            while m <= 0: m += 12; y -= 1

            # روز اول ماه بعد (برای محاسبه مانده تا انتهای ماه جاری)
            if m == 12: next_start_j = jdatetime.date(y + 1, 1, 1)
            else: next_start_j = jdatetime.date(y, m + 1, 1)
            limit_g = next_start_j.togregorian()

            # SQL یک شماره برای محاسبه بدهی
            debt = db.session.query(
                func.sum(JournalEntryLine.credit - JournalEntryLine.debit)
            ).join(JournalEntry).filter(
                JournalEntryLine.account_id == insurance_account_id,
                JournalEntryLine.description.ilike('%بیمه پرداختنی سازمان%') | (JournalEntryLine.description == None),
                JournalEntry.date < limit_g
            ).scalar() or 0.0

            ins_trend_labels.append(jdatetime.date(y, m, 1).strftime('%b %y'))
            ins_trend_values.append(debt)
    else:
        # اگر حساب موجود نیست، محتوای خالی تولید کن
        for i in range(11, -1, -1):
            y, m = now_j.year, now_j.month - i
            while m <= 0: m += 12; y -= 1
            ins_trend_labels.append(jdatetime.date(y, m, 1).strftime('%b %y'))
            ins_trend_values.append(0)

    # 6.5. ریز تراکنش‌های ماه جاری (برای جدول زیر نمودار)
    start_month_g = jdatetime.date(now_j.year, now_j.month, 1).togregorian()
    monthly_transactions = Transaction.query.filter(
        Transaction.t_date >= start_month_g
    ).order_by(Transaction.t_date.desc()).all()

    # 6.6. دیتای نمودار درختی هزینه‌ها (Tree Map)
    expense_treemap_data = [{"x": cat, "y": amt} for cat, amt in expense_breakdown.items() if amt > 0]

    # --- 6.8. گزارش مقایسه‌ای تقاضای جیره در مقابل خریدهای واقعی (Supply vs Demand) - SQL بهینه شده ---

    # دریافت تمام اسامی نهاده‌های موجود در انبار
    inventory_names = [i.name for i in InventoryItem.query.all()]

    # محاسبه تقاضای جیره بر اساس SQL - بدون حلقه روی دام‌ها
    # فرض: تقاضا = مجموع (مقدار روزانه * 30)
    ration_demand_stats = db.session.query(
        InventoryItem.name,
        func.sum(FeedingSchedule.amount_kg * 30).label('monthly_demand')
    ).join(FeedingSchedule, InventoryItem.id == FeedingSchedule.inventory_item_id)\
     .join(FeedRation, FeedingSchedule.feed_ration_id == FeedRation.id)\
     .join(Sheep, FeedRation.id == Sheep.feed_ration_id).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])
    ).group_by(InventoryItem.name).all()

    ration_demand = {row[0]: row[1] for row in ration_demand_stats} if ration_demand_stats else {}
    ration_mismatches = []

    # چک کردن تطابق نام‌ها بدون حلقه اضافی - استفاده از set difference
    feed_types_in_ration = set(ration_demand.keys())
    feed_types_in_inventory = set(inventory_names)
    mismatched_feed_types = feed_types_in_ration - feed_types_in_inventory

    for name in mismatched_feed_types:
        suggestion = difflib.get_close_matches(name, inventory_names, n=1, cutoff=0.4)
        ration_mismatches.append({
            'wrong': name,
            'suggested': suggestion[0] if suggestion else 'یافت نشد (کالا را در انبار تعریف کنید)'
        })

    # استخراج خریدهای واقعی ۳۰ روز اخیر - SQL بهینه شده بدون حلقه
    actual_purchases_stats = db.session.query(
        InventoryItem.name,
        func.sum(InventoryLog.amount).label('total_amount')
    ).join(InventoryLog).filter(
        InventoryLog.action_type == 'ورود',
        InventoryLog.date >= month_ago
    ).group_by(InventoryItem.id, InventoryItem.name).all()

    actual_purchases = {row[0]: row[1] for row in actual_purchases_stats} if actual_purchases_stats else {}

    supply_demand_labels = list(ration_demand.keys())
    supply_data = [actual_purchases.get(label, 0) for label in supply_demand_labels]
    demand_data = [ration_demand.get(label, 0) for label in supply_demand_labels]

    # --- 6.9. گزارش انحراف از بهای تمام شده (Cost Variance) - SQL بهینه شده ---
    # محاسبه تعداد روزهای بازه فیلتر شده
    num_days = 30
    if date_filter == '180': num_days = 180
    elif date_filter == '365': num_days = 365
    elif date_filter == 'all':
        first_log = InventoryLog.query.order_by(InventoryLog.date.asc()).first()
        num_days = (today - first_log.date).days if first_log else 30

    # هزینه پیش‌بینی شده بر اساس جیره - SQL بدون حلقه
    predicted_cost_stats = db.session.query(
        func.sum(FeedRation.daily_cost) * num_days
    ).join(Sheep, FeedRation.id == Sheep.feed_ration_id).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده']),
        Sheep.feed_ration_id.isnot(None)
    ).scalar() or 0

    total_predicted_feed_cost = float(predicted_cost_stats)

    # انحراف = هزینه واقعی انبار - هزینه پیش‌بینی شده جیره
    cost_variance = total_feed_expenses - total_predicted_feed_cost
    variance_pct = (cost_variance / total_predicted_feed_cost * 100) if total_predicted_feed_cost > 0 else 0

    # --- 6.10. مقایسه قیمت واحد نهاده‌های اصلی (جو، ذرت، یونجه) ---
    feed_comparison_labels = ['جو', 'ذرت', 'یونجه']
    feed_comparison_prices = []
    for f_name in feed_comparison_labels:
        # پیدا کردن کالا با جستجوی بخشی از نام
        item = InventoryItem.query.filter(InventoryItem.name.ilike(f"%{f_name}%")).first()
        feed_comparison_prices.append(float(item.unit_price) if item else 0)
    
    # اضافه کردن گندم به لیست مقایسه اگر موجود بود

    # 7. رادار سلامت بهاربندها (ویژگی پشم‌ریزون 2) - SQL بهینه شده بجای حلقه تو در تو
    pen_risks_stats = db.session.query(
        Pen.name,
        func.count(Sheep.id).label('total_in_pen'),
        func.sum(cast(case((Sheep.status == 'بیمار', 1), else_=0), db.Integer)).label('sick_count')
    ).outerjoin(Sheep, Pen.id == Sheep.pen_id).group_by(Pen.id, Pen.name).all()

    pen_risks = []
    for row in pen_risks_stats:
        if row[1] and row[1] > 0:
            risk_percent = (float(row[2] or 0) / float(row[1])) * 100
            pen_risks.append({'name': row[0], 'risk': risk_percent})

    pen_risks.sort(key=lambda x: x['risk'], reverse=True)

    # دریافت برترین دام‌ها بر اساس وزن
    top_sheep = Sheep.query.filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده']),
        Sheep.weight > 0
    ).order_by(Sheep.weight.desc()).limit(5).all()
    # ---> 1. تولید دیتای نقشه گرمایی زایش ها (Heatmap) - SQL بهینه شده <---
    # ==========================================

    # استخراج تعداد بره‌های متولد شده برای هر ماه شمسی - SQL بدون حلقه
    # اصلاح برای سازگاری با SQLite: استفاده از strftime به جای concat_ws و extract پیچیده
    birth_by_month_stats = db.session.query(
        func.strftime('%m', BirthRecord.birth_date).label('j_month'),
        func.sum(BirthRecord.lambs_count).label('total_lambs')
    ).group_by('j_month').all()

    heatmap_data = {str(i): 0 for i in range(1, 13)}
    for row in birth_by_month_stats:
        if row[0] and int(row[0]) <= 12:
            heatmap_data[str(int(row[0]))] = row[1] or 0

    heatmap_series = [{
        "name": "تعداد بره متولد شده",
        "data": [{"x": f"ماه {m}", "y": count} for m, count in heatmap_data.items()]
    }]

    # ==========================================
    # ---> 2. پیش‌بینی جریان نقدینگی (Cash Flow Forecast) - SQL بهینه شده <---
    # ==========================================
    from app.models import Cheque

    m1_end = today + timedelta(days=30)
    m2_end = today + timedelta(days=60)
    m3_end = today + timedelta(days=90)

    # محاسبه مجموع حقوق‌های فعال - SQL بدون حلقه
    total_monthly_salaries = db.session.query(
        func.sum(Worker.salary)
    ).filter_by(status='فعال').scalar() or 0

    # بهینه‌سازی Cashflow با استفاده از یک Subquery واحد برای سرعت حداکثری
    cashflow_stats = db.session.query(
        case((Cheque.due_date <= m1_end, 'm1'), (Cheque.due_date <= m2_end, 'm2'), else_='m3').label('period'),
        func.sum(case((Cheque.cheque_type == 'دریافتی (مشتری)', Cheque.amount), else_=0)).label('inflow'),
        func.sum(case((Cheque.cheque_type == 'پرداختی (خودم)', Cheque.amount), else_=0)).label('outflow')
    ).filter(Cheque.status == 'در جریان', Cheque.due_date > today, Cheque.due_date <= m3_end).group_by('period').all()
    
    def get_cashflow_data(start, end):
        """محاسبه جریان نقدینگی بر اساس چک‌ها و هزینه‌های ثابت با SQL"""
        inflow = db.session.query(func.sum(Cheque.amount)).filter(
            Cheque.cheque_type == 'دریافتی (مشتری)',
            Cheque.status == 'در جریان',
            Cheque.due_date >= start, Cheque.due_date < end
        ).scalar() or 0
        
        outflow_cheque = db.session.query(func.sum(Cheque.amount)).filter(
            Cheque.cheque_type == 'پرداختی (خودم)',
            Cheque.status == 'در جریان',
            Cheque.due_date >= start, Cheque.due_date < end
        ).scalar() or 0
        
        # افزودن حقوق‌های ماهانه به خروجی‌های ماه اول
        is_first_month = (start == today)
        fixed_costs = total_monthly_salaries if is_first_month else 0
        
        return {'in': float(inflow), 'out': float(outflow_cheque + fixed_costs)}

    cf_1m = get_cashflow_data(today, m1_end)
    cf_2m = get_cashflow_data(m1_end, m2_end)
    cf_3m = get_cashflow_data(m2_end, m3_end)

    cashflow_in = [cf_1m['in'], cf_2m['in'], cf_3m['in']]
    cashflow_out = [cf_1m['out'], cf_2m['out'], cf_3m['out']]

    # هشدار کمبود نقدینگی در ماه اول
    if cf_1m['out'] > cf_1m['in']:
        ai_insights.append({
            'icon': 'fa-triangle-exclamation',
            'color': 'danger',
            'title': 'هشدار کسری نقدینگی',
            'text': f'در ۳۰ روز آینده مبلغ {"{:,.0f}".format(cf_1m["out"] - cf_1m["in"])} تومان کسری بودجه خواهید داشت (تفاضل چک‌های پرداختی/هزینه خوراک با چک‌های دریافتی). لطفاً برای تامین نقدینگی یا فروش دام برنامه‌ریزی کنید!'
        })
    return render_template('reports/index.html',
                           stats_1m=stats_1m, stats_6m=stats_6m, stats_1y=stats_1y,
                           combined_chart_labels=combined_chart_labels,
                           combined_chart_born=combined_chart_born,
                           combined_chart_sold=combined_chart_sold,
                           combined_chart_dead=combined_chart_dead,
                           born_genders=born_genders, born_breeds=born_breeds, 
                           sold_genders=sold_genders, sold_breeds=sold_breeds, 
                           dead_genders=dead_genders, dead_breeds=dead_breeds,
                           death_causes=death_causes, total_financial_loss=total_financial_loss,
                           ai_insights=ai_insights, top_sheep=top_sheep,
                           cost_per_kg=cost_per_kg, milk_income=milk_income,
                           insurance_cost_per_kg=insurance_cost_per_kg,
                           inc_labels=list(income_breakdown.keys()), inc_data=list(income_breakdown.values()), total_income_val=total_income_val,
                           exp_labels=list(expense_breakdown.keys()), exp_data=list(expense_breakdown.values()),
                           avg_profit_labels=avg_profit_labels, avg_profit_data=avg_profit_data, pen_risks=pen_risks,
                           feed_consumption=feed_consumption, total_feed_expenses=total_feed_expenses, current_filter=date_filter,
                           heatmap_series=heatmap_series, cashflow_in=cashflow_in, cashflow_out=cashflow_out,
                           profit_pie_data=profit_pie_data, 
                           trend_labels=trend_labels, trend_values=trend_values,
                           breed_cost_analysis=breed_cost_analysis,
                           monthly_pnl_labels=monthly_pnl_labels,
                           monthly_pnl_rev=monthly_pnl_rev,
                           monthly_pnl_exp=monthly_pnl_exp,
                           expense_treemap_data=expense_treemap_data,
                           ins_trend_labels=ins_trend_labels,
                           ins_trend_values=ins_trend_values,
                           supply_demand_labels=supply_demand_labels,
                           supply_data=supply_data,
                           demand_data=demand_data,
                           ration_mismatches=ration_mismatches,
                           total_predicted_feed_cost=total_predicted_feed_cost,
                           cost_variance=cost_variance,
                           variance_pct=variance_pct,
                           annual_depreciation_report=annual_depreciation_report,
                           cost_components=[total_purchase_cost, total_feed_expenses, total_depreciation, total_insurance_expenses],
                           feed_comparison_labels=feed_comparison_labels,
                           feed_comparison_prices=feed_comparison_prices,
                            purchase_trend_labels=purchase_trend_labels,
                            barley_trend=barley_trend,
                            corn_trend=corn_trend,
                            starred_filter=starred_filter)

@reports_bp.route('/sales')
@login_required
@permission_required('can_view_reports')
@log_report_errors
def sales_report():
    return render_template('reports/sales.html')

@reports_bp.route('/api/sales_data')
@login_required
@log_report_errors
def api_sales_data():
    sold_sheep = Sheep.query.filter_by(status='فروخته شده').options(
        joinedload(Sheep.ration), joinedload(Sheep.buyer_category)
    ).all()
    data = []
    for s in sold_sheep:
        if not s.sale_date: continue
        days_alive = max((s.sale_date - (s.birth_date or s.entry_date.date())).days, 1)
        daily_cost = s.ration.daily_cost if s.ration else 0
        total_cost = (s.purchase_price or 0) + (days_alive * daily_cost)
        profit = (s.sale_price or 0) - total_cost

        data.append({
            'date': s.sale_date.strftime('%Y-%m-%d'),
            'timestamp': int(datetime.combine(s.sale_date, datetime.min.time()).timestamp() * 1000),
            'price': s.sale_price,
            'weight': s.weight or 0,
            'cost': total_cost,
            'profit': profit,
            'gender': s.gender,
            'breed': s.breed or 'نامشخص',
            'buyer_type': s.buyer_category.name if s.buyer_category else 'نامشخص'
        })
    data.sort(key=lambda x: x['timestamp'])
    return jsonify(data)

@reports_bp.route('/export_monthly_tx')
@login_required
@permission_required('can_view_reports')
@log_report_errors
def export_monthly_tx():
    """خروجی اکسل تراکنش‌های ماه جاری (شمسی)"""
    today = datetime.utcnow().date()
    now_j = jdatetime.date.fromgregorian(date=today)
    start_month_g = jdatetime.date(now_j.year, now_j.month, 1).togregorian()
    
    monthly_transactions = Transaction.query.filter(
        Transaction.t_date >= start_month_g
    ).order_by(Transaction.t_date.desc()).all()

    html_content = '<html dir="rtl"><head><meta charset="utf-8"><style>table {border-collapse: collapse; width: 100%;} th, td {border: 1px solid black; padding: 8px; text-align: center;} th {background-color: #f2f2f2; font-weight: bold;}</style></head><body>'
    html_content += f'<h2 style="text-align:center;">گزارش ریز تراکنش‌های ماه جاری ({now_j.strftime("%B %Y")})</h2>'
    html_content += '<table><thead><tr><th>تاریخ</th><th>طرف حساب</th><th>دسته‌بندی</th><th>نوع</th><th>مبلغ (تومان)</th></tr></thead><tbody>'
    for t in monthly_transactions:
        j_date = jdatetime.date.fromgregorian(date=t.t_date).strftime('%Y/%m/%d')
        html_content += f"<tr><td>{j_date}</td><td>{t.party_name or '-'}</td><td>{t.category}</td><td>{t.t_type}</td><td>{t.amount:,.0f}</td></tr>"
    html_content += '</tbody></table></body></html>'
    
    response = Response(html_content, mimetype='application/vnd.ms-excel')
    response.headers['Content-Disposition'] = f'attachment; filename=monthly_tx_{now_j.year}_{now_j.month}.xls'
    return response