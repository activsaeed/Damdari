from flask import Blueprint, render_template, request, jsonify, Response
import difflib
from app import db
from app.models import (
    Sheep, Transaction, BirthRecord, LactationRecord, InventoryLog, InventoryItem,
    JournalEntry, JournalEntryLine, Account, BreedCategory, FeedingSchedule, Worker,
    FeedRation, Unit, InventoryCategory, Pen
)
from datetime import datetime, timedelta
from sqlalchemy import or_, func, cast, case
from app.blueprints.dashboard import get_setting
import jdatetime

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/')
def index():
    from app.models import Pen
    today = datetime.utcnow().date()
    now_j = jdatetime.datetime.now()
    month_ago = today - timedelta(days=30)
    six_months_ago = today - timedelta(days=180)
    year_ago = today - timedelta(days=365)

    all_breeds = BreedCategory.query.all()
    ai_insights = []

    # 1. آمار زایش و فرزندان - استفاده از SQL
    born_stats = db.session.query(
        Sheep.gender,
        func.count(Sheep.id).label('count')
    ).filter(Sheep.mother_id != None).group_by(Sheep.gender).all()

    born_genders = {g: cnt for g, cnt in born_stats}

    breed_birth_stats = db.session.query(
        func.coalesce(Sheep.breed, 'نامشخص').label('breed'),
        func.count(Sheep.id).label('count')
    ).filter(Sheep.mother_id != None).group_by(Sheep.breed).all()

    born_breeds = {b: cnt for b, cnt in breed_birth_stats}

    # 2. آمار فروش و سودآوری نژادها + sold_genders و sold_breeds
    breed_profits = db.session.query(
        Sheep.breed,
        func.count(Sheep.id).label('count'),
        func.sum(Sheep.sale_price - Sheep.purchase_price).label('total_profit')
    ).filter(Sheep.status == 'فروخته شده').group_by(Sheep.breed).all()

    avg_breed_profit = {}
    for breed, count, total_profit in breed_profits:
        b_name = breed or 'نامشخص'
        avg_breed_profit[b_name] = (total_profit / count) if count > 0 else 0

    avg_profit_labels = list(avg_breed_profit.keys())
    avg_profit_data = list(avg_breed_profit.values())

    # 2.1. آمار فروش بر اساس جنسیت و نژاد - SQL (بدون حلقه)
    sold_gender_stats = db.session.query(
        Sheep.gender,
        func.count(Sheep.id).label('count')
    ).filter(Sheep.status == 'فروخته شده').group_by(Sheep.gender).all()

    sold_genders = {g: cnt for g, cnt in sold_gender_stats}

    sold_breed_stats = db.session.query(
        func.coalesce(Sheep.breed, 'نامشخص').label('breed'),
        func.count(Sheep.id).label('count')
    ).filter(Sheep.status == 'فروخته شده').group_by(Sheep.breed).all()

    sold_breeds = {b: cnt for b, cnt in sold_breed_stats}

    # 3. آمار تلفات - استفاده از SQL (بدون حلقه)
    death_causes = {}
    total_financial_loss = db.session.query(
        func.sum(Sheep.purchase_price)
    ).filter(Sheep.status.in_(['تلف شده', 'مرده'])).scalar() or 0

    dead_reason_stats = db.session.query(
        func.coalesce(Sheep.death_reason, 'نامشخص').label('reason'),
        func.count(Sheep.id).label('count')
    ).filter(Sheep.status.in_(['تلف شده', 'مرده'])).group_by(Sheep.death_reason).all()

    death_causes = {reason: cnt for reason, cnt in dead_reason_stats}

    dead_sheep_count = db.session.query(func.count(Sheep.id)).filter(
        Sheep.status.in_(['تلف شده', 'مرده'])
    ).scalar() or 0

    sold_sheep_ids = db.session.query(Sheep.id).filter(Sheep.status == 'فروخته شده').all()
    sold_sheep_ids = [s[0] for s in sold_sheep_ids]

    def get_stats(target_date):
        dead = db.session.query(func.count(Sheep.id)).filter(
            Sheep.status.in_(['تلف شده', 'مرده']),
            (Sheep.entry_date >= target_date) | (Sheep.birth_date >= target_date)
        ).scalar() or 0

        sold = db.session.query(func.count(Sheep.id)).filter(
            Sheep.status == 'فروخته شده',
            Sheep.entry_date >= target_date
        ).scalar() or 0

        born = db.session.query(func.sum(BirthRecord.lambs_count)).filter(
            BirthRecord.birth_date >= target_date
        ).scalar() or 0

        return {'dead': dead, 'sold': sold, 'born': born}

    stats_1m, stats_6m, stats_1y = get_stats(month_ago), get_stats(six_months_ago), get_stats(year_ago)

    # 4. تفکیک دقیق درآمد و هزینه
    income_transactions = db.session.query(
        Transaction.category,
        func.sum(Transaction.amount).label('total')
    ).filter(
        Transaction.t_type == 'درآمد',
        ~Transaction.category.ilike('%خرید%'),
        ~Transaction.category.ilike('%هزینه%')
    ).group_by(Transaction.category).all()

    income_breakdown = {cat: amt for cat, amt in income_transactions}
    total_income_val = sum(amt for _, amt in income_transactions)

    milk_income = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.t_type == 'درآمد',
        Transaction.category.ilike('%شیر%')
    ).scalar() or 0

    expense_transactions = db.session.query(
        Transaction.category,
        func.sum(Transaction.amount).label('total')
    ).filter(
        (Transaction.t_type == 'هزینه') | (Transaction.category.ilike('%خرید%'))
    ).group_by(Transaction.category).all()

    expense_breakdown = {cat: amt for cat, amt in expense_transactions}

    # 5. گزارش مصرف انبار (رفع باگ صفر بودن نمودار) - استفاده از SQL بجای حلقه
    date_filter = request.args.get('date_filter', '30')
    if date_filter == '30': filter_date = month_ago
    elif date_filter == '180': filter_date = six_months_ago
    elif date_filter == '365': filter_date = year_ago
    else: filter_date = datetime.strptime("2000-01-01", "%Y-%m-%d").date()

    # SQL بهینه شده برای محاسبه مصرف خوراک بدون حلقه
    feed_logs = db.session.query(
        InventoryItem.name,
        InventoryItem.unit_id,
        func.sum(InventoryLog.amount).label('total_amount'),
        func.coalesce(
            func.nullif(func.avg(func.nullif(InventoryLog.transaction_price, 0)), None),
            func.avg(InventoryItem.unit_price)
        ).label('avg_price')
    ).join(InventoryLog, InventoryItem.id == InventoryLog.item_id
    ).join(InventoryCategory, InventoryItem.category_id == InventoryCategory.id
    ).filter(
        InventoryLog.action_type == 'خروج',
        InventoryLog.date >= filter_date,
        InventoryCategory.name.in_(['خوراک', 'علوفه'])
    ).group_by(InventoryItem.id, InventoryItem.name, InventoryItem.unit_id).all()

    feed_consumption = {}
    total_feed_expenses = 0

    for item_name, unit_id, total_amount, avg_price in feed_logs:
        cost = (total_amount or 0) * (avg_price or 0)
        total_feed_expenses += cost
        unit_obj = db.session.query(Unit).filter_by(id=unit_id).first() if unit_id else None
        unit_name = unit_obj.name if unit_obj else '-'

        feed_consumption[item_name] = {
            'amount': total_amount or 0,
            'unit': unit_name,
            'cost': cost
        }

    # 6. بهای تمام شده پیشرفته - استفاده از SQL
    dep_acc_ids = db.session.query(Account.id).filter(Account.code.in_(['5010'])).all()
    dep_acc_ids = [a[0] for a in dep_acc_ids] if dep_acc_ids else []
    total_depreciation = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).filter(
        JournalEntryLine.account_id.in_(dep_acc_ids),
        JournalEntry.description.ilike('%استهلاک%')
    ).scalar() or 0.0

    total_live_weight = db.session.query(func.sum(Sheep.weight)).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده']),
        Sheep.weight.isnot(None)
    ).scalar() or 0

    total_purchase_cost = db.session.query(func.sum(Sheep.purchase_price)).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])
    ).scalar() or 0

    total_insurance_expenses = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).filter(
        JournalEntryLine.account_id.in_(dep_acc_ids),
        JournalEntryLine.description.ilike('%بیمه سهم کارفرما%')
    ).scalar() or 0.0

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
    for breed_name, breed_weights, b_purchase in breed_weights_stats:
        if breed_weights and breed_weights > 0:
            b_cost_per_kg = (b_purchase + total_depreciation) / breed_weights
            breed_cost_analysis.append({
                'name': breed_name or 'نامشخص',
                'cost': b_cost_per_kg,
                'weight': breed_weights
            })

    # 6.2. دیتای نمودار دایره‌ای سود (عملیاتی vs ارزیابی)
    valuation_gain = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).join(Account).filter(
        Account.code == '4010', JournalEntry.description.ilike('%تعدیل ارزش منصفانه%')
    ).scalar() or 0.0
    valuation_loss = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).join(Account).filter(
        Account.code == '5010', JournalEntry.description.ilike('%تعدیل ارزش منصفانه%')
    ).scalar() or 0.0
    
    total_rev_ledger = db.session.query(func.sum(JournalEntryLine.credit)).join(Account).filter(Account.code.startswith('4')).scalar() or 0.0
    total_exp_ledger = db.session.query(func.sum(JournalEntryLine.debit)).join(Account).filter(Account.code.startswith('5')).scalar() or 0.0
    
    net_val_profit = valuation_gain - valuation_loss
    op_profit = (total_rev_ledger - total_exp_ledger) - net_val_profit
    profit_pie_data = [max(0, op_profit), max(0, net_val_profit)]

    # 6.3. روند تغییر ارزش منصفانه گله (۶ ماه اخیر)
    trend_labels, trend_values = [], []
    livestock_acc = Account.query.filter_by(code='1200').first()

    for i in range(5, -1, -1):
        m_date = today - timedelta(days=i*30)
        j_month = jdatetime.date.fromgregorian(date=m_date).strftime('%B')
        trend_labels.append(j_month)
        
        if livestock_acc:
            # استخراج ارزش گله در انتهای هر ماه از حساب ۱۲۰۰
            v_debits = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).filter(
                JournalEntryLine.account_id == livestock_acc.id, JournalEntry.date <= m_date).scalar() or 0
            v_credits = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).filter(
                JournalEntryLine.account_id == livestock_acc.id, JournalEntry.date <= m_date).scalar() or 0
            trend_values.append(v_debits - v_credits)
        else:
            trend_values.append(0)

    # 6.4. گزارش سود و زیان مقایسه‌ای ماهانه (۶ ماه اخیر)
    monthly_pnl_labels, monthly_pnl_rev, monthly_pnl_exp = [], [], []
    for i in range(5, -1, -1):
        # محاسبه سال و ماه شمسی برای i ماه قبل
        y, m = now_j.year, now_j.month - i
        while m <= 0: m += 12; y -= 1
        
        start_j = jdatetime.date(y, m, 1)
        end_j = jdatetime.date(y + (1 if m==12 else 0), 1 if m==12 else m+1, 1)
        
        monthly_pnl_labels.append(start_j.strftime('%B'))
        start_g, end_g = start_j.togregorian(), end_j.togregorian()

        # مجموع درآمدها (کد 4)
        m_rev = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).join(Account).filter(
            Account.code.startswith('4'), JournalEntry.date >= start_g, JournalEntry.date < end_g
        ).scalar() or 0.0
        monthly_pnl_rev.append(m_rev)

        # مجموع هزینه‌ها (کد 5)
        m_exp = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).join(Account).filter(
            Account.code.startswith('5'), JournalEntry.date >= start_g, JournalEntry.date < end_g
        ).scalar() or 0.0
        monthly_pnl_exp.append(m_exp)

    # 6.11. روند قیمت خرید نهاده‌های استراتژیک (۶ ماه اخیر) - SQL بهینه شده
    purchase_trend_labels = []
    barley_trend, corn_trend = [], []

    for i in range(5, -1, -1):
        y, m = now_j.year, now_j.month - i
        while m <= 0: m += 12; y -= 1

        start_j = jdatetime.date(y, m, 1)
        if m == 12: end_j = jdatetime.date(y + 1, 1, 1)
        else: end_j = jdatetime.date(y, m + 1, 1)

        purchase_trend_labels.append(start_j.strftime('%B'))
        start_g, end_g = start_j.togregorian(), end_j.togregorian()

        # میانگین قیمت خرید جو - SQL یک شماره
        b_avg = db.session.query(
            func.avg(InventoryLog.transaction_price)
        ).join(InventoryItem).filter(
            InventoryLog.action_type == 'ورود',
            InventoryItem.name.ilike('%جو%'),
            InventoryLog.date >= start_g,
            InventoryLog.date < end_g
        ).scalar() or 0
        barley_trend.append(round(float(b_avg)))

        # میانگین قیمت خرید ذرت - SQL یک شماره
        c_avg = db.session.query(
            func.avg(InventoryLog.transaction_price)
        ).join(InventoryItem).filter(
            InventoryLog.action_type == 'ورود',
            InventoryItem.name.ilike('%ذرت%'),
            InventoryLog.date >= start_g,
            InventoryLog.date < end_g
        ).scalar() or 0
        corn_trend.append(round(float(c_avg)))

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
        FeedingSchedule.feed_type,
        func.sum(FeedingSchedule.amount_kg * 30).label('monthly_demand')
    ).join(FeedRation).join(Sheep, FeedRation.id == Sheep.feed_ration_id).filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])
    ).group_by(FeedingSchedule.feed_type).all()

    ration_demand = {feed_type: demand for feed_type, demand in ration_demand_stats}
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

    actual_purchases = {name: amount for name, amount in actual_purchases_stats}

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

    if cost_variance > 0:
        ai_insights.append({
            'icon': 'fa-money-bill-trend-up',
            'color': 'danger',
            'title': 'انحراف هزینه خوراک',
            'text': f'هزینه واقعی خوراک در این بازه {abs(variance_pct):.1f}% بالاتر از پیش‌بینی جیره‌نویسی بوده است. علت را در قیمت خرید یا هدررفت جستجو کنید.'
        })
    elif cost_variance < 0:
        ai_insights.append({
            'icon': 'fa-sack-arrow-trend-up',
            'color': 'success',
            'title': 'صرفه‌جویی در هزینه',
            'text': f'هزینه خرید نهاده‌ها {abs(variance_pct):.1f}% کمتر از بودجه پیش‌بینی شده بوده است.'
        })

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
    for pen_name, total_in_pen, sick_count in pen_risks_stats:
        if total_in_pen and total_in_pen > 0:
            risk_percent = (float(sick_count or 0) / float(total_in_pen)) * 100
            pen_risks.append({'name': pen_name, 'risk': risk_percent})

    pen_risks.sort(key=lambda x: x['risk'], reverse=True)

    # 8. هوش مصنوعی و محاسبات آماری - SQL بهینه شده

    # دریافت تعداد کل دام‌ها
    total_sheep_count = db.session.query(func.count(Sheep.id)).scalar() or 1

    # محاسبه نرخ تلفات - SQL بدون حلقه
    mortality_rate = (dead_sheep_count / total_sheep_count * 100) if total_sheep_count > 0 else 0

    if mortality_rate > 5:
        ai_insights.append({
            'icon': 'fa-skull-crossbones',
            'color': 'danger',
            'title': 'هشدار بحران سلامت',
            'text': f'نرخ تلفات ({mortality_rate:.1f}%) بالا است! تاکنون مبلغ {"{:,.0f}".format(total_financial_loss)} تومان سرمایه از بین رفته است.'
        })

    # دریافت برترین دام‌ها بر اساس وزن
    top_sheep = Sheep.query.filter(
        Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده']),
        Sheep.weight > 0
    ).order_by(Sheep.weight.desc()).limit(5).all()
    # 8.1. بهای تمام شده واقعی
    if cost_per_kg > 0:
        ai_insights.append({
            'icon': 'fa-scale-balanced',
            'color': 'info',
            'title': 'بهای تمام‌شده واقعی',
            'text': f'بهای تمام‌شده تولید هر کیلوگرم وزن زنده با احتساب هزینه‌های جانبی و بیمه {"{:,.0f}".format(cost_per_kg)} تومان است.'
        })

    if insurance_cost_per_kg > 0:
        share_pct = (insurance_cost_per_kg / cost_per_kg * 100) if cost_per_kg > 0 else 0
        ai_insights.append({
            'icon': 'fa-shield-heart',
            'color': 'primary',
            'title': 'آنالیز سهم بیمه',
            'text': f'هزینه بیمه سهم کارفرما به ازای هر کیلوگرم گوشت تولیدی {"{:,.0f}".format(insurance_cost_per_kg)} تومان ({share_pct:.1f}% از کل) می‌باشد.'
        })

    # ==========================================
    # ---> 1. تولید دیتای نقشه گرمایی زایش ها (Heatmap) - SQL بهینه شده <---
    # ==========================================

    # استخراج تعداد بره‌های متولد شده برای هر ماه شمسی - SQL بدون حلقه
    birth_by_month_stats = db.session.query(
        func.extract('month', func.cast(
            func.concat_ws('-',
                func.cast(func.extract('year', BirthRecord.birth_date), db.String),
                func.cast(func.extract('month', BirthRecord.birth_date), db.String),
                '1'
            ), db.Date
        )).label('j_month'),
        func.sum(BirthRecord.lambs_count).label('total_lambs')
    ).group_by('j_month').all()

    heatmap_data = {str(i): 0 for i in range(1, 13)}
    for m, lambs in birth_by_month_stats:
        if m and int(m) <= 12:
            heatmap_data[str(int(m))] = lambs or 0

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

    def get_cashflow(start_date, end_date):
        # دریافتی چک‌های مشتری - SQL یک شماره
        in_chq = db.session.query(
            func.sum(Cheque.amount)
        ).filter(
            Cheque.cheque_type == 'دریافتی (مشتری)',
            Cheque.status == 'در جریان',
            Cheque.due_date > start_date,
            Cheque.due_date <= end_date
        ).scalar() or 0

        # پرداختی چک‌های شخصی - SQL یک شماره
        out_chq = db.session.query(
            func.sum(Cheque.amount)
        ).filter(
            Cheque.cheque_type == 'پرداختی (خودم)',
            Cheque.status == 'در جریان',
            Cheque.due_date > start_date,
            Cheque.due_date <= end_date
        ).scalar() or 0

        # تخمین هزینه خوراک بر اساس متغیر تنظیمات داینامیک
        daily_feed_unit = float(get_setting('daily_feed_est', 15000))
        # محاسبه تعداد دام‌های فعال - SQL
        active_sheep_count = db.session.query(
            func.count(Sheep.id)
        ).filter(Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).scalar() or 0

        est_feed_cost = active_sheep_count * daily_feed_unit * (end_date - start_date).days

        return {'in': in_chq or 0, 'out': (out_chq or 0) + est_feed_cost + total_monthly_salaries}

    cf_1m = get_cashflow(today, m1_end)
    cf_2m = get_cashflow(m1_end, m2_end)
    cf_3m = get_cashflow(m2_end, m3_end)

    cashflow_in = [cf_1m['in'], cf_2m['in'], cf_3m['in']]
    cashflow_out = [cf_1m['out'], cf_2m['out'], cf_3m['out']]

    # هشدار کمبود نقدینگی در ماه اول
    if cf_1m['out'] > cf_1m['in']:
        ai_insights.insert(0, {
            'icon': 'fa-triangle-exclamation',
            'color': 'danger',
            'title': 'هشدار کسری نقدینگی',
            'text': f'در ۳۰ روز آینده مبلغ {"{:,.0f}".format(cf_1m["out"] - cf_1m["in"])} تومان کسری بودجه خواهید داشت (تفاضل چک‌های پرداختی/هزینه خوراک با چک‌های دریافتی). لطفاً برای تامین نقدینگی یا فروش دام برنامه‌ریزی کنید!'
        })
    return render_template('reports/index.html',
                           stats_1m=stats_1m, stats_6m=stats_6m, stats_1y=stats_1y,
                           born_genders=born_genders, born_breeds=born_breeds, 
                           sold_genders=sold_genders, sold_breeds=sold_breeds, 
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
                           cost_components=[total_purchase_cost, total_feed_expenses, total_depreciation, total_insurance_expenses],
                           feed_comparison_labels=feed_comparison_labels,
                           feed_comparison_prices=feed_comparison_prices,
                           purchase_trend_labels=purchase_trend_labels,
                           barley_trend=barley_trend,
                           corn_trend=corn_trend)

@reports_bp.route('/sales')
def sales_report():
    return render_template('reports/sales.html')

@reports_bp.route('/api/sales_data')
def api_sales_data():
    sold_sheep = Sheep.query.filter_by(status='فروخته شده').all()
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
            'buyer_type': s.buyer_type or 'نامشخص'
        })
    data.sort(key=lambda x: x['timestamp'])
    return jsonify(data)

@reports_bp.route('/export_monthly_tx')
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