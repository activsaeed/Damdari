from flask import Blueprint, render_template, request, jsonify, Response
import difflib
from app import db
from app.models import Sheep, Transaction, BirthRecord, LactationRecord, InventoryLog, InventoryItem, JournalEntry, JournalEntryLine, Account, BreedCategory, FeedingSchedule, Worker
from datetime import datetime, timedelta
from sqlalchemy import or_, func
from app.blueprints.dashboard import get_setting
import jdatetime

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/')
def index():
    from app.models import Pen # اضافه کردن ایمپورت بهاربند
    today = datetime.utcnow().date()
    now_j = jdatetime.datetime.now()
    month_ago = today - timedelta(days=30)
    six_months_ago = today - timedelta(days=180)
    year_ago = today - timedelta(days=365)
    
    all_breeds = BreedCategory.query.all()
    all_sheep = Sheep.query.all()
    all_births = BirthRecord.query.filter_by(status='موفق').all()
    ai_insights = [] # مقداردهی اولیه در ابتدای تابع برای جلوگیری از خطای UnboundLocalError

    # 1. آمار زایش و فرزندان
    born_sheep = Sheep.query.filter(Sheep.mother_id != None).all()
    born_genders, born_breeds = {}, {}
    for s in born_sheep:
        born_genders[s.gender] = born_genders.get(s.gender, 0) + 1
        born_breeds[s.breed or 'نامشخص'] = born_breeds.get(s.breed or 'نامشخص', 0) + 1

    # 2. آمار فروش و سودآوری نژادها (ویژگی پشم‌ریزون 1)
    sold_sheep = [s for s in all_sheep if s.status == 'فروخته شده']
    sold_genders, sold_breeds = {}, {}
    breed_profit_calc = {} # محاسبه سود خالص هر نژاد
    
    for s in sold_sheep: 
        sold_genders[s.gender] = sold_genders.get(s.gender, 0) + 1
        b = s.breed or 'نامشخص'
        sold_breeds[b] = sold_breeds.get(b, 0) + 1
        
        # محاسبه سود این دام
        days_alive = max((s.sale_date - (s.birth_date or s.entry_date.date())).days, 1) if s.sale_date else 1
        daily_cost = s.ration.daily_cost if s.ration else 0
        profit = (s.sale_price or 0) - ((s.purchase_price or 0) + (days_alive * daily_cost))
        
        if b not in breed_profit_calc: breed_profit_calc[b] = {'profit': 0, 'count': 0}
        breed_profit_calc[b]['profit'] += profit
        breed_profit_calc[b]['count'] += 1

    # میانگین سود هر نژاد
    avg_breed_profit = {b: data['profit']/data['count'] for b, data in breed_profit_calc.items() if data['count'] > 0}
    avg_profit_labels = list(avg_breed_profit.keys())
    avg_profit_data = list(avg_breed_profit.values())

    # 3. آمار تلفات
    dead_sheep = [s for s in all_sheep if s.status in ['تلف شده', 'مرده']]
    death_causes = {}
    total_financial_loss = sum(s.purchase_price or 0 for s in dead_sheep)
    for s in dead_sheep:
        reason = s.death_reason or 'نامشخص'
        death_causes[reason] = death_causes.get(reason, 0) + 1

    def get_stats(target_date):
        dead = [s for s in dead_sheep if (s.entry_date.date() >= target_date or (s.birth_date and s.birth_date >= target_date))]
        sold = [s for s in sold_sheep if s.entry_date.date() >= target_date]
        born = sum(b.lambs_count for b in all_births if b.birth_date >= target_date)
        return {'dead': len(dead), 'sold': len(sold), 'born': born}

    stats_1m, stats_6m, stats_1y = get_stats(month_ago), get_stats(six_months_ago), get_stats(year_ago)

    # 4. تفکیک دقیق درآمد و هزینه (با سپر امنیتی علیه خطای کاربری)
    all_transactions = Transaction.query.all()
    income_breakdown, expense_breakdown = {}, {}
    total_income_val, milk_income = 0, 0
    
    for t in all_transactions:
        # اگر نوع درآمد است، کلمات "خرید" یا "هزینه" نباید در دسته بندی آن باشد!
        if t.t_type == 'درآمد' and 'خرید' not in t.category and 'هزینه' not in t.category:
            income_breakdown[t.category] = income_breakdown.get(t.category, 0) + t.amount
            total_income_val += t.amount
            if 'شیر' in t.category: milk_income += t.amount
            
        elif t.t_type == 'هزینه' or 'خرید' in t.category:
            expense_breakdown[t.category] = expense_breakdown.get(t.category, 0) + t.amount

    # 5. گزارش مصرف انبار (رفع باگ صفر بودن نمودار)
    date_filter = request.args.get('date_filter', '30')
    if date_filter == '30': filter_date = month_ago
    elif date_filter == '180': filter_date = six_months_ago
    elif date_filter == '365': filter_date = year_ago
    else: filter_date = datetime.strptime("2000-01-01", "%Y-%m-%d").date()

    inventory_logs = InventoryLog.query.filter(InventoryLog.action_type == 'خروج', InventoryLog.date >= filter_date).all()
    feed_consumption, total_feed_expenses = {}, 0

    for log in inventory_logs:
        item = InventoryItem.query.get(log.item_id)
        if item and item.category and item.category.name in ['خوراک', 'علوفه']:
            # اگر قیمت در لاگ صفر بود (دیتای فیک قدیمی)، از قیمت روز کالا استفاده کن
            used_price = log.transaction_price if log.transaction_price > 0 else item.unit_price
            cost = log.amount * used_price
            total_feed_expenses += cost
            if item.name in feed_consumption:
                feed_consumption[item.name]['amount'] += log.amount
                feed_consumption[item.name]['cost'] += cost
            else:
                feed_consumption[item.name] = {'amount': log.amount, 'unit': item.unit.name if item.unit else '-', 'cost': cost}

    # 6. بهای تمام شده پیشرفته (با احتساب استهلاک و جیره)
    # استخراج مجموع هزینه استهلاک ثبت شده در دفتر کل
    dep_acc_ids = [a.id for a in Account.query.filter(Account.code.in_(['5102', '5101'])).all()]
    total_depreciation = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).filter(
        JournalEntryLine.account_id.in_(dep_acc_ids),
        JournalEntry.description.ilike('%استهلاک%')
    ).scalar() or 0.0

    total_live_weight = sum(s.weight for s in all_sheep if s.status not in ['تلف شده', 'مرده', 'فروخته شده'] and s.weight)
    total_purchase_cost = sum(s.purchase_price for s in all_sheep if s.status not in ['تلف شده', 'مرده', 'فروخته شده'])

    # استخراج مجموع هزینه بیمه (سهم کارفرما) از دفتر کل
    total_insurance_expenses = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).filter(
        JournalEntryLine.account_id.in_(dep_acc_ids),
        JournalEntryLine.description.ilike('%بیمه سهم کارفرما%')
    ).scalar() or 0.0

    insurance_cost_per_kg = (total_insurance_expenses / total_live_weight) if total_live_weight > 0 else 0

    # فرمول نهایی بهای تمام شده: (خرید + خوراک + استهلاک + بیمه) ÷ وزن زنده
    cost_per_kg = ((total_feed_expenses + total_purchase_cost + total_depreciation + total_insurance_expenses) / total_live_weight) if total_live_weight > 0 else 0

    # 6.1. تفکیک بهای تمام شده بر اساس نژاد (تحلیل FCR)
    breed_cost_analysis = []
    for breed in all_breeds:
        breed_sheep = [s for s in all_sheep if s.breed == breed.name and s.status not in ['تلف شده', 'مرده', 'فروخته شده']]
        b_weight = sum(s.weight for s in breed_sheep if s.weight)
        if b_weight > 0:
            b_purchase = sum(s.purchase_price for s in breed_sheep if s.purchase_price)
            # تخمین هزینه خوراک نژاد بر اساس جیره تخصیصی
            b_feed = sum((datetime.now().date() - (s.birth_date or s.entry_date.date())).days * (s.ration.daily_cost if s.ration else 0) for s in breed_sheep)
            b_dep_share = (len(breed_sheep) / len(all_sheep)) * total_depreciation if len(all_sheep) > 0 else 0
            b_cost_per_kg = (b_purchase + b_feed + b_dep_share) / b_weight
            breed_cost_analysis.append({'name': breed.name, 'cost': b_cost_per_kg, 'weight': b_weight})

    # 6.2. دیتای نمودار دایره‌ای سود (عملیاتی vs ارزیابی)
    valuation_gain = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).join(Account).filter(
        Account.code == '4101', JournalEntry.description.ilike('%تعدیل ارزش منصفانه%')
    ).scalar() or 0.0
    valuation_loss = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).join(Account).filter(
        Account.code == '5101', JournalEntry.description.ilike('%تعدیل ارزش منصفانه%')
    ).scalar() or 0.0
    
    total_rev_ledger = db.session.query(func.sum(JournalEntryLine.credit)).join(Account).filter(Account.code.startswith('4')).scalar() or 0.0
    total_exp_ledger = db.session.query(func.sum(JournalEntryLine.debit)).join(Account).filter(Account.code.startswith('5')).scalar() or 0.0
    
    net_val_profit = valuation_gain - valuation_loss
    op_profit = (total_rev_ledger - total_exp_ledger) - net_val_profit
    profit_pie_data = [max(0, op_profit), max(0, net_val_profit)]

    # 6.3. روند تغییر ارزش منصفانه گله (۶ ماه اخیر)
    trend_labels, trend_values = [], []
    for i in range(5, -1, -1):
        m_date = today - timedelta(days=i*30)
        j_month = jdatetime.date.fromgregorian(date=m_date).strftime('%B')
        trend_labels.append(j_month)
        
        # استخراج ارزش گله در انتهای هر ماه از حساب ۱۲۰۲
        v_debits = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).filter(
            JournalEntryLine.account_id == Account.query.filter_by(code='1202').first().id, JournalEntry.date <= m_date).scalar() or 0
        v_credits = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).filter(
            JournalEntryLine.account_id == Account.query.filter_by(code='1202').first().id, JournalEntry.date <= m_date).scalar() or 0
        trend_values.append(v_debits - v_credits)

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

    # 6.11. روند قیمت خرید نهاده‌های استراتژیک (۶ ماه اخیر)
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
        
        # میانگین قیمت خرید جو
        b_avg = db.session.query(func.avg(InventoryLog.transaction_price)).join(InventoryItem).filter(
            InventoryLog.action_type == 'ورود', InventoryItem.name.ilike('%جو%'),
            InventoryLog.date >= start_g, InventoryLog.date < end_g).scalar() or 0
        barley_trend.append(round(float(b_avg)))

        # میانگین قیمت خرید ذرت
        c_avg = db.session.query(func.avg(InventoryLog.transaction_price)).join(InventoryItem).filter(
            InventoryLog.action_type == 'ورود', InventoryItem.name.ilike('%ذرت%'),
            InventoryLog.date >= start_g, InventoryLog.date < end_g).scalar() or 0
        corn_trend.append(round(float(c_avg)))

    # 6.7. روند بدهی بیمه در ۱۲ ماه اخیر
    ins_trend_labels, ins_trend_values = [], []
    for i in range(11, -1, -1):
        y, m = now_j.year, now_j.month - i
        while m <= 0: m += 12; y -= 1
        
        # روز اول ماه بعد (برای محاسبه مانده تا انتهای ماه جاری)
        if m == 12: next_start_j = jdatetime.date(y + 1, 1, 1)
        else: next_start_j = jdatetime.date(y, m + 1, 1)
        limit_g = next_start_j.togregorian()
        
        debt = db.session.query(
            func.sum(JournalEntryLine.credit - JournalEntryLine.debit)
        ).join(JournalEntry).join(Account).filter(
            Account.code == '2101',
            JournalEntryLine.description.ilike('%بیمه پرداختنی سازمان%'),
            JournalEntry.date < limit_g
        ).scalar() or 0.0
        
        ins_trend_labels.append(jdatetime.date(y, m, 1).strftime('%b %y'))
        ins_trend_values.append(debt)

    # 6.5. ریز تراکنش‌های ماه جاری (برای جدول زیر نمودار)
    start_month_g = jdatetime.date(now_j.year, now_j.month, 1).togregorian()
    monthly_transactions = Transaction.query.filter(
        Transaction.t_date >= start_month_g
    ).order_by(Transaction.t_date.desc()).all()

    # 6.6. دیتای نمودار درختی هزینه‌ها (Tree Map)
    expense_treemap_data = [{"x": cat, "y": amt} for cat, amt in expense_breakdown.items() if amt > 0]

    # --- 6.8. گزارش مقایسه‌ای تقاضای جیره در مقابل خریدهای واقعی (Supply vs Demand) ---
    inventory_names = [i.name for i in InventoryItem.query.all()]
    ration_demand = {} # نام نهاده -> مقدار مورد نیاز ماهیانه (kg)
    ration_mismatches = [] # موارد مغایرت نام

    active_sheep = [s for s in all_sheep if s.status not in ['تلف شده', 'مرده', 'فروخته شده']]
    for s in active_sheep:
        if s.ration:
            for sched in s.ration.schedules:
                name = sched.feed_type
                # محاسبه نیاز ۳۰ روزه
                ration_demand[name] = ration_demand.get(name, 0) + (sched.amount_kg * 30)
                
                # چک کردن تطابق نام با انبار
                if name not in inventory_names and name not in [m['wrong'] for m in ration_mismatches]:
                    # پیدا کردن نزدیک ترین پیشنهاد
                    suggestion = difflib.get_close_matches(name, inventory_names, n=1, cutoff=0.4)
                    ration_mismatches.append({
                        'wrong': name,
                        'suggested': suggestion[0] if suggestion else 'یافت نشد (کالا را در انبار تعریف کنید)'
                    })

    # استخراج خریدهای واقعی ۳۰ روز اخیر از انبار
    actual_purchases = {}
    purchase_logs = InventoryLog.query.filter(InventoryLog.action_type == 'ورود', InventoryLog.date >= month_ago).all()
    for log in purchase_logs:
        actual_purchases[log.item.name] = actual_purchases.get(log.item.name, 0) + log.amount

    supply_demand_labels = list(ration_demand.keys())
    supply_data = [actual_purchases.get(label, 0) for label in supply_demand_labels]
    demand_data = [ration_demand.get(label, 0) for label in supply_demand_labels]

    # --- 6.9. گزارش انحراف از بهای تمام شده (Cost Variance) ---
    # محاسبه تعداد روزهای بازه فیلتر شده
    num_days = 30
    if date_filter == '180': num_days = 180
    elif date_filter == '365': num_days = 365
    elif date_filter == 'all':
        first_log = InventoryLog.query.order_by(InventoryLog.date.asc()).first()
        num_days = (today - first_log.date).days if first_log else 30
    
    # هزینه پیش‌بینی شده بر اساس جیره = مجموع (هزینه روزانه جیره هر دام) * تعداد روز
    total_predicted_feed_cost = sum((s.ration.daily_cost if s.ration else 0) for s in active_sheep) * num_days
    # انحراف = هزینه واقعی انبار - هزینه پیش‌بینی شده جیره
    cost_variance = total_feed_expenses - total_predicted_feed_cost
    variance_pct = (cost_variance / total_predicted_feed_cost * 100) if total_predicted_feed_cost > 0 else 0
    if cost_variance > 0: ai_insights.append({'icon':'fa-money-bill-trend-up','color':'danger','title':'انحراف هزینه خوراک','text':f'هزینه واقعی خوراک در این بازه {abs(variance_pct):.1f}% بالاتر از پیش‌بینی جیره‌نویسی بوده است. علت را در قیمت خرید یا هدررفت جستجو کنید.'})
    elif cost_variance < 0: ai_insights.append({'icon':'fa-sack-arrow-trend-up','color':'success','title':'صرفه‌جویی در هزینه','text':f'هزینه خرید نهاده‌ها {abs(variance_pct):.1f}% کمتر از بودجه پیش‌بینی شده بوده است.'})

    # --- 6.10. مقایسه قیمت واحد نهاده‌های اصلی (جو، ذرت، یونجه) ---
    feed_comparison_labels = ['جو', 'ذرت', 'یونجه']
    feed_comparison_prices = []
    for f_name in feed_comparison_labels:
        # پیدا کردن کالا با جستجوی بخشی از نام
        item = InventoryItem.query.filter(InventoryItem.name.ilike(f"%{f_name}%")).first()
        feed_comparison_prices.append(float(item.unit_price) if item else 0)
    
    # اضافه کردن گندم به لیست مقایسه اگر موجود بود

    # 7. رادار سلامت بهاربندها (ویژگی پشم‌ریزون 2)
    pen_risks = []
    for p in Pen.query.all():
        total_in_pen = len(p.sheep_list)
        sick_in_pen = sum(1 for s in p.sheep_list if s.status == 'بیمار')
        if total_in_pen > 0:
            pen_risks.append({'name': p.name, 'risk': (sick_in_pen/total_in_pen)*100})
    pen_risks.sort(key=lambda x: x['risk'], reverse=True)

    # 8. هوش مصنوعی
    if cost_per_kg > 0: ai_insights.append({'icon':'fa-scale-balanced','color':'info','title':'بهای تمام‌شده واقعی','text':f'بهای تمام‌شده تولید هر کیلوگرم وزن زنده با احتساب هزینه‌های جانبی و بیمه {"{:,.0f}".format(cost_per_kg)} تومان است.'})
    
    if insurance_cost_per_kg > 0:
        share_pct = (insurance_cost_per_kg / cost_per_kg * 100) if cost_per_kg > 0 else 0
        ai_insights.append({
            'icon': 'fa-shield-heart', 
            'color': 'primary', 
            'title': 'آنالیز سهم بیمه', 
            'text': f'هزینه بیمه سهم کارفرما به ازای هر کیلوگرم گوشت تولیدی {"{:,.0f}".format(insurance_cost_per_kg)} تومان ({share_pct:.1f}% از کل) می‌باشد.'
        })

    mortality_rate = (len(dead_sheep) / len(all_sheep) * 100) if len(all_sheep) > 0 else 0
    if mortality_rate > 5: ai_insights.append({'icon':'fa-skull-crossbones','color':'danger','title':'هشدار بحران سلامت','text':f'نرخ تلفات ({mortality_rate:.1f}%) بالا است! تاکنون مبلغ {"{:,.0f}".format(total_financial_loss)} تومان سرمایه از بین رفته است.'})

    top_sheep = Sheep.query.filter(Sheep.status.notin_(['تلف شده','مرده','فروخته شده']), Sheep.weight > 0).order_by(Sheep.weight.desc()).limit(5).all()
     # ==========================================
    # ---> 1. تولید دیتای نقشه گرمایی زایش ها (Heatmap) <---
    # ==========================================
    heatmap_data = {str(i): 0 for i in range(1, 13)} # 12 ماه سال شمسی
    for b in all_births:
        if b.birth_date:
            j_month = jdatetime.date.fromgregorian(date=b.birth_date).month
            heatmap_data[str(j_month)] += b.lambs_count
            
    heatmap_series = [{"name": "تعداد بره متولد شده", "data": [{"x": f"ماه {m}", "y": count} for m, count in heatmap_data.items()]}]

    # ==========================================
    # ---> 2. پیش‌بینی جریان نقدینگی (Cash Flow Forecast) <---
    # ==========================================
    from app.models import Cheque
    m1_end = today + timedelta(days=30)
    m2_end = today + timedelta(days=60)
    m3_end = today + timedelta(days=90)
    total_monthly_salaries = sum(w.salary for w in Worker.query.filter_by(status='فعال').all())

    def get_cashflow(start_date, end_date):
        in_chq = sum(c.amount for c in Cheque.query.filter(Cheque.cheque_type=='دریافتی (مشتری)', Cheque.status=='در جریان', Cheque.due_date > start_date, Cheque.due_date <= end_date).all())
        out_chq = sum(c.amount for c in Cheque.query.filter(Cheque.cheque_type=='پرداختی (خودم)', Cheque.status=='در جریان', Cheque.due_date > start_date, Cheque.due_date <= end_date).all())
        
        # تخمین هزینه خوراک بر اساس متغیر تنظیمات داینامیک
        daily_feed_unit = float(get_setting('daily_feed_est', 15000))
        est_feed_cost = len(all_sheep) * daily_feed_unit * (end_date - start_date).days
        return {'in': in_chq, 'out': out_chq + est_feed_cost + total_monthly_salaries}

    cf_1m = get_cashflow(today, m1_end)
    cf_2m = get_cashflow(m1_end, m2_end)
    cf_3m = get_cashflow(m2_end, m3_end)
    
    cashflow_in = [cf_1m['in'], cf_2m['in'], cf_3m['in']]
    cashflow_out = [cf_1m['out'], cf_2m['out'], cf_3m['out']]
    
    # هشدار کمبود نقدینگی در ماه اول
    if cf_1m['out'] > cf_1m['in']:
        ai_insights.insert(0, {'icon':'fa-triangle-exclamation','color':'danger','title':'هشدار کسری نقدینگی','text':f'در ۳۰ روز آینده مبلغ {"{:,.0f}".format(cf_1m["out"] - cf_1m["in"])} تومان کسری بودجه خواهید داشت (تفاضل چک‌های پرداختی/هزینه خوراک با چک‌های دریافتی). لطفاً برای تامین نقدینگی یا فروش دام برنامه‌ریزی کنید!'})
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