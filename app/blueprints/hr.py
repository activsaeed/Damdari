from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from app import db
from app.accounting_engine import AccountingEngine
from datetime import datetime, timedelta, UTC
import requests
import os
import time
import random
import jdatetime

hr_bp = Blueprint('hr', __name__)

def send_to_telegram(message):
    from app.models import TelegramBot
    bot = TelegramBot.query.filter_by(is_active=True).first()
    if not bot: return
    url = f"https://api.telegram.org/bot{bot.bot_token}/sendMessage"
    try: requests.post(url, data={'chat_id': bot.chat_id, 'text': message})
    except: pass

def parse_smart_date(date_str):
    if not date_str: return datetime.now(UTC).date()
    date_str = date_str.replace('/', '-')
    if date_str.startswith('13') or date_str.startswith('14'):
        parts = date_str.split('-')
        return jdatetime.date(int(parts[0]), int(parts[1]), int(parts[2])).togregorian()
    return datetime.strptime(date_str, '%Y-%m-%d').date()

@hr_bp.route('/')
@login_required
def index():
    from app.models import Worker, Task, Pen, Sheep
    workers = Worker.query.order_by(Worker.id.desc()).all()
    pens = Pen.query.all()
    today = datetime.now(UTC).date()
    thirty_days_ago = today - timedelta(days=30)
    
    if current_user.role == 'کارگر':
        tasks = Task.query.filter_by(task_date=today).order_by(Task.is_done.asc(), Task.id.desc()).all()
    else:
        tasks = Task.query.filter_by(task_date=today).order_by(Task.is_done.asc(), Task.id.desc()).all()

    kpi_data = {}
    for w in workers:
        score = 100
        bonus = 0
        notes = []
        
        total_tasks = Task.query.filter_by(worker_id=w.id).filter(Task.task_date >= thirty_days_ago).count()
        done_tasks = Task.query.filter_by(worker_id=w.id, is_done=True).filter(Task.task_date >= thirty_days_ago).count()
        
        if total_tasks > 0:
            task_rate = (done_tasks / total_tasks) * 100
            if task_rate < 50:
                score -= 30
                notes.append("انجام ضعیف وظایف")
            elif task_rate >= 90:
                bonus += 500000 
                notes.append("انجام عالی وظایف")
                
        if w.assigned_pen_id:
            dead_in_pen = Sheep.query.filter_by(pen_id=w.assigned_pen_id).filter(Sheep.status.in_(['تلف شده', 'مرده'])).count()
            if dead_in_pen == 0:
                bonus += 1000000 
                notes.append("تلفات صفر در سالن اختصاصی")
            else:
                score -= (dead_in_pen * 10)
                notes.append(f"{dead_in_pen} تلفات در سالن اختصاصی")
                
        kpi_data[w.id] = {'score': max(0, score), 'bonus': bonus, 'notes': " | ".join(notes) if notes else "عملکرد نرمال"}

    today_str = datetime.now(UTC).strftime('%Y-%m-%d')
    return render_template('hr/index.html', workers=workers, tasks=tasks, pens=pens, kpi_data=kpi_data, today=today, today_str=today_str)

@hr_bp.route('/add_worker', methods=['POST'])
@login_required
def add_worker():
    from app.models import Worker, WorkerDocument, WorkerEvent
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    w_code = request.form.get('worker_code') or f"PR-{random.randint(1000,9999)}"
    
    new_worker = Worker(
        worker_code=w_code,
        name=request.form.get('name'),
        national_id=request.form.get('national_id'),
        phone=request.form.get('phone'),
        role=request.form.get('role'),
        education=request.form.get('education'),
        address=request.form.get('address'),
        bank_account=request.form.get('bank_account'),
        
        salary=float(request.form.get('salary') or 0),
        housing_allowance=float(request.form.get('housing_allowance') or 0),
        food_allowance=float(request.form.get('food_allowance') or 0),
        family_allowance=float(request.form.get('family_allowance') or 0),
        
        insurance_status=request.form.get('insurance_status'),
        status=request.form.get('status'),
        assigned_pen_id=request.form.get('assigned_pen_id') or None,
        start_date=parse_smart_date(request.form.get('start_date'))
    )
    db.session.add(new_worker)
    db.session.commit() # ثبت برای دریافت آی دی
    
    # آپلود گالری مدارک پرسنلی
    documents = request.files.getlist('documents')
    upload_folder = os.path.join('app', 'static', 'uploads', 'hr')
    os.makedirs(upload_folder, exist_ok=True)
    
    for doc in documents:
        if doc and doc.filename != '':
            filename = f"doc_{new_worker.id}_{int(time.time())}_{secure_filename(doc.filename)}"
            doc.save(os.path.join(upload_folder, filename))
            db.session.add(WorkerDocument(worker_id=new_worker.id, doc_title="مدرک پرسنلی", file_path=f"uploads/hr/{filename}"))
            
    db.session.add(WorkerEvent(worker_id=new_worker.id, event_type="استخدام", event_date=new_worker.start_date, description=f"شروع به کار با سمت {new_worker.role}"))
    db.session.commit()
    
    flash('پرسنل جدید به همراه مدارک با موفقیت ثبت شد.', 'success')
    return redirect(url_for('hr.index'))

@hr_bp.route('/profile/<int:id>')
@login_required
def profile(id):
    from app.models import Worker, WorkerEvent, WorkerLoan, Task, PettyCash, Pen
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    worker = Worker.query.get_or_404(id)
    events = WorkerEvent.query.filter_by(worker_id=id).order_by(WorkerEvent.event_date.desc()).all()
    loans = WorkerLoan.query.filter_by(worker_id=id).order_by(WorkerLoan.issue_date.desc()).all()
    tasks = Task.query.filter_by(worker_id=id).order_by(Task.task_date.desc()).limit(20).all()
    petty_cash = PettyCash.query.filter_by(worker_id=id).order_by(PettyCash.record_date.desc()).limit(10).all()
    
    pens = Pen.query.all()
    today_str = datetime.now(UTC).strftime('%Y-%m-%d')
    return render_template('hr/profile.html', worker=worker, events=events, loans=loans, tasks=tasks, petty_cash=petty_cash, pens=pens, today_str=today_str)

@hr_bp.route('/edit_worker/<int:id>', methods=['POST'])
@login_required
def edit_worker(id):
    from app.models import Worker, WorkerDocument
    w = Worker.query.get_or_404(id)
    w.name = request.form.get('name')
    w.national_id = request.form.get('national_id')
    w.phone = request.form.get('phone')
    w.role = request.form.get('role')
    w.education = request.form.get('education')
    w.address = request.form.get('address')
    w.bank_account = request.form.get('bank_account')
    
    w.salary = float(request.form.get('salary') or 0)
    w.housing_allowance = float(request.form.get('housing_allowance') or 0)
    w.food_allowance = float(request.form.get('food_allowance') or 0)
    w.family_allowance = float(request.form.get('family_allowance') or 0)
    
    w.insurance_status = request.form.get('insurance_status')
    w.status = request.form.get('status')
    w.assigned_pen_id = request.form.get('assigned_pen_id') or None
    
    # افزودن مدرک جدید به پرونده
    documents = request.files.getlist('documents')
    upload_folder = os.path.join('app', 'static', 'uploads', 'hr')
    os.makedirs(upload_folder, exist_ok=True)
    for doc in documents:
        if doc and doc.filename != '':
            filename = f"doc_{w.id}_{int(time.time())}_{secure_filename(doc.filename)}"
            doc.save(os.path.join(upload_folder, filename))
            db.session.add(WorkerDocument(worker_id=w.id, doc_title="مدرک پرسنلی (افزوده شده)", file_path=f"uploads/hr/{filename}"))

    db.session.commit()
    flash('اطلاعات و مدارک پرسنل ویرایش شد.', 'success')
    return redirect(url_for('hr.profile', id=id))

@hr_bp.route('/add_loan/<int:id>', methods=['POST'])
@login_required
def add_loan(id):
    from app.models import WorkerLoan, WorkerEvent, Transaction
    if current_user.role != 'مدیر': return redirect(url_for('hr.profile', id=id))
    amount = float(request.form.get('amount') or 0)
    loan_type = request.form.get('loan_type')
    i_date = parse_smart_date(request.form.get('issue_date'))
    
    doc_img = None
    photo = request.files.get('document_image')
    if photo and photo.filename != '':
        filename = f"loan_{int(time.time())}_{secure_filename(photo.filename)}"
        upload_folder = os.path.join('app', 'static', 'uploads', 'hr')
        os.makedirs(upload_folder, exist_ok=True)
        photo.save(os.path.join(upload_folder, filename))
        doc_img = f"uploads/hr/{filename}"
        
    db.session.add(WorkerLoan(worker_id=id, loan_type=loan_type, amount=amount, issue_date=i_date, installment_amount=float(request.form.get('installment_amount') or 0), status="در حال پرداخت", description=request.form.get('description'), document_image=doc_img))
    db.session.add(WorkerEvent(worker_id=id, event_type="مالی", event_date=i_date, description=f"پرداخت {loan_type} به مبلغ {amount:,.0f} تومان."))
    db.session.add(Transaction(t_type='هزینه', category=f"پرداخت {loan_type} پرسنل", amount=amount, t_date=i_date, description=f"پرداخت {loan_type} به پرسنل ({request.form.get('description')})"))
    db.session.commit()
    flash(f'{loan_type} ثبت و در دفتر کل حسابداری لحاظ شد.', 'success')
    return redirect(url_for('hr.profile', id=id))

@hr_bp.route('/add_event/<int:id>', methods=['POST'])
@login_required
def add_event(id):
    from app.models import WorkerEvent
    e_date = parse_smart_date(request.form.get('event_date'))
    db.session.add(WorkerEvent(worker_id=id, event_type=request.form.get('event_type'), event_date=e_date, description=request.form.get('description')))
    db.session.commit()
    return redirect(url_for('hr.profile', id=id))

@hr_bp.route('/delete_worker/<int:id>', methods=['POST'])
@login_required
def delete_worker(id):
    from app.models import Worker
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    w = Worker.query.get_or_404(id)
    db.session.delete(w)
    db.session.commit()
    flash('پرسنل و تمام سوابق وی حذف شد.', 'danger')
    return redirect(url_for('hr.index'))

@hr_bp.route('/add_task', methods=['POST'])
@login_required
def add_task():
    from app.models import Task
    db.session.add(Task(worker_id=request.form.get('worker_id'), description=request.form.get('description')))
    db.session.commit()
    return redirect(url_for('hr.index'))

@hr_bp.route('/toggle_task/<int:task_id>', methods=['POST'])
@login_required
def toggle_task(task_id):
    from app.models import Task
    task = Task.query.get_or_404(task_id)
    task.is_done = not task.is_done
    db.session.commit()
    return redirect(url_for('hr.index'))

@hr_bp.route('/quick_report', methods=['POST'])
@login_required
def quick_report():
    from app.models import User, Task, Sheep
    issue_type = request.form.get('issue_type')
    worker_name = current_user.name if current_user.is_authenticated else "کارگر"
    
    if issue_type == 'کمبود انبار':
        item_name = request.form.get('inventory_item') or request.form.get('custom_inventory')
        admin_user = User.query.filter_by(role='مدیر').first()
        db.session.add(Task(worker_id=admin_user.id if admin_user else 1, description=f"گزارش کارگر ({worker_name}): کمبود {item_name} در انبار", task_date=datetime.utcnow().date()))
        send_to_telegram(f"📦 #هشدار_انبار\nکارگر {worker_name} اعلام کمبود {item_name} کرده است.")
        flash(f"گزارش کمبود {item_name} به مدیر ارسال شد.", "success")
        
    elif issue_type == 'سایر موارد':
        custom_desc = request.form.get('custom_desc')
        admin_user = User.query.filter_by(role='مدیر').first()
        db.session.add(Task(worker_id=admin_user.id if admin_user else 1, description=f"پیام از {worker_name}: {custom_desc}", task_date=datetime.utcnow().date()))
        send_to_telegram(f"💬 #پیام_کارگر\nاز طرف {worker_name}:\n{custom_desc}")
        flash("گزارش متفرقه ارسال شد.", "success")
        
    else:
        ear_tag = request.form.get('ear_tag')
        sheep = Sheep.query.filter_by(ear_tag=ear_tag).first()
        if sheep:
            sheep.status = 'بیمار'
            vet_user = User.query.filter_by(role='دامپزشک').first()
            db.session.add(Task(worker_id=vet_user.id if vet_user else 1, description=f"گزارش فوری از {worker_name}: دام {ear_tag} دچار {issue_type} شده!", task_date=datetime.now(UTC).date(), livestock_id=sheep.id))
            send_to_telegram(f"🚨 #اورژانس_دامپزشکی\nپلاک: {ear_tag}\nمشکل: {issue_type}\nگزارشگر: {worker_name}")
            flash(f"گزارش خطر برای پلاک {ear_tag} ارسال شد.", "danger")
        else:
            flash("پلاک وارد شده یافت نشد.", "warning")
            
    db.session.commit()
    return redirect(url_for('hr.index'))

# ==========================================
# سیستم حقوق و دستمزد (فیش حقوقی اتوماتیک قانون کار)
# ==========================================
@hr_bp.route('/payslips')
@login_required
def payslips():
    from app.models import Worker, Payslip
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    workers = Worker.query.filter_by(status='فعال').all()
    all_payslips = Payslip.query.order_by(Payslip.issue_date.desc()).all()
    today_str = datetime.now(UTC).strftime('%Y-%m-%d')
    return render_template('hr/payslips.html', workers=workers, payslips=all_payslips, today_str=today_str)

@hr_bp.route('/generate_payslip', methods=['POST'])
@login_required
def generate_payslip():
    from app.models import Worker, WorkerLoan, Task, Payslip
    worker_id = request.form.get('worker_id')
    month_name = request.form.get('month_name')
    worker = Worker.query.get_or_404(worker_id)
    
    # دریافت نرخ‌ها از تنظیمات (رفع هاردکد نرخ اضافه کار و شب کاری)
    overtime_rate = float(get_setting('overtime_rate', 1.4))
    night_shift_rate = float(get_setting('night_shift_rate', 0.35))
    
    overtime_hours = float(request.form.get('overtime_hours') or 0)
    night_shift_hours = float(request.form.get('night_shift_hours') or 0)
    transportation = float(request.form.get('transportation_pay') or 0)
    eydi = float(request.form.get('eydi_sanavat') or 0)
    
    from app.blueprints.dashboard import get_setting
    working_hours = float(get_setting('working_hours', 220))
    hourly_rate = float(worker.salary or 0) / working_hours if (worker.salary and worker.salary > 0) else 0
    overtime_pay = overtime_hours * (hourly_rate * overtime_rate)
    night_shift_pay = night_shift_hours * (hourly_rate * night_shift_rate)
    
    # پیدا کردن اقساط وام های فعال
    active_loans = WorkerLoan.query.filter_by(worker_id=worker.id, status='در حال پرداخت').all()
    loan_deduction = float(sum(l.installment_amount for l in active_loans if l.installment_amount) or 0)
    
    # محاسبه پاداش هوشمند (بر اساس وظایف انجام شده در 30 روز اخیر)
    today = datetime.now(UTC).date()
    done_tasks = Task.query.filter_by(worker_id=worker.id, is_done=True).filter(Task.task_date >= today - timedelta(days=30)).count()
    kpi_bonus = 500000 if done_tasks > 10 else 0
    
    fines = float(request.form.get('fines') or 0)
    
    # محاسبه ناخالص و خالص
    base_pay = float(worker.salary or 0)
    housing = float(worker.housing_allowance or 0)
    food = float(worker.food_allowance or 0)
    family = float(worker.family_allowance or 0)
    
    gross_pay = base_pay + housing + food + family + overtime_pay + night_shift_pay + transportation + kpi_bonus + eydi
    net_pay = gross_pay - (loan_deduction + fines)
    
    new_payslip = Payslip(
        worker_id=worker.id, month_name=month_name, base_salary=worker.salary,
        housing_allowance=worker.housing_allowance, food_allowance=worker.food_allowance, family_allowance=worker.family_allowance,
        overtime_pay=overtime_pay, night_shift_pay=night_shift_pay, transportation_pay=transportation,
        kpi_bonus=kpi_bonus, eydi_sanavat=eydi, loan_deduction=loan_deduction, fines=fines, gross_pay=gross_pay, net_pay=net_pay
    )
    
    with db.session.begin_nested():
        db.session.add(new_payslip)
        db.session.flush()
        # صدور همزمان سند حسابداری در دفتر کل
        AccountingEngine.record_payroll(new_payslip)

    db.session.commit()
    flash(f"فیش حقوقی {worker.name} صادر و سند مالی ثبت شد.", "success")
    return redirect(url_for('hr.payslips'))

@hr_bp.route('/pay_payslip/<int:id>')
@login_required
def pay_payslip(id):
    from app.models import Payslip, Transaction
    p = Payslip.query.get_or_404(id)
    p.is_paid = True
    db.session.add(Transaction(t_type='هزینه', category='حقوق کارگران', amount=p.net_pay, t_date=datetime.now(UTC).date(), description=f"تسویه فیش حقوقی {p.worker.name} بابت {p.month_name}"))
    db.session.commit()
    flash("حقوق تسویه و در دفتر کل مالی ثبت شد.", "success")
    return redirect(url_for('hr.payslips'))

@hr_bp.route('/insurance_report')
@login_required
def insurance_report():
    """گزارش لیست بیمه ماهانه بر اساس اسناد حسابداری با قابلیت فیلتر"""
    from app.models import JournalEntry, JournalEntryLine, Account
    
    year_j = request.args.get('year', jdatetime.datetime.now().year, type=int)
    month_j = request.args.get('month', type=int)
    
    # پیدا کردن آرتیکل‌های مربوط به بیمه (کد ۲۱۰۱ و شرح بیمه)
    query = db.session.query(
        JournalEntry.date,
        JournalEntryLine.description,
        JournalEntryLine.credit
    ).join(JournalEntry).join(Account).filter(
        Account.code == '2101',
        JournalEntryLine.description.ilike('%بیمه پرداختنی سازمان%')
    )

    if month_j:
        # تبدیل محدوده ماه شمسی به میلادی برای فیلتر دیتابیس
        start_date_j = jdatetime.date(year_j, month_j, 1)
        if month_j == 12: end_date_j = jdatetime.date(year_j + 1, 1, 1)
        else: end_date_j = jdatetime.date(year_j, month_j + 1, 1)
        query = query.filter(JournalEntry.date >= start_date_j.togregorian(), 
                             JournalEntry.date < end_date_j.togregorian())
    elif year_j:
        # فیلتر کل سال شمسی
        start_date_j = jdatetime.date(year_j, 1, 1)
        end_date_j = jdatetime.date(year_j + 1, 1, 1)
        query = query.filter(JournalEntry.date >= start_date_j.togregorian(), 
                             JournalEntry.date < end_date_j.togregorian())

    insurance_lines = query.order_by(JournalEntry.date.desc()).all()
    
    # جمع کل بیمه پرداختنی
    total_insurance = sum(line.credit for line in insurance_lines)
    
    return render_template('hr/insurance_report.html', 
                           lines=insurance_lines, 
                           total_insurance=total_insurance,
                           current_year=year_j,
                           current_month=month_j)

@hr_bp.route('/export_insurance_excel')
@login_required
def export_insurance_excel():
    """خروجی اکسل لیست بیمه با تاریخ شمسی و رعایت فیلترها"""
    from app.models import JournalEntry, JournalEntryLine, Account
    
    year_j = request.args.get('year', jdatetime.datetime.now().year, type=int)
    month_j = request.args.get('month', type=int)
    
    query = db.session.query(
        JournalEntry.date,
        JournalEntryLine.description,
        JournalEntryLine.credit
    ).join(JournalEntry).join(Account).filter(
        Account.code == '2101',
        JournalEntryLine.description.ilike('%بیمه پرداختنی سازمان%')
    )

    if month_j:
        start_date_j = jdatetime.date(year_j, month_j, 1)
        if month_j == 12: end_date_j = jdatetime.date(year_j + 1, 1, 1)
        else: end_date_j = jdatetime.date(year_j, month_j + 1, 1)
        query = query.filter(JournalEntry.date >= start_date_j.togregorian(), 
                             JournalEntry.date < end_date_j.togregorian())
    elif year_j:
        start_date_j = jdatetime.date(year_j, 1, 1)
        end_date_j = jdatetime.date(year_j + 1, 1, 1)
        query = query.filter(JournalEntry.date >= start_date_j.togregorian(), 
                             JournalEntry.date < end_date_j.togregorian())

    lines = query.order_by(JournalEntry.date.asc()).all()
    
    # تولید محتوای HTML برای اکسل
    month_name = jdatetime.date(year_j, month_j, 1).strftime('%B') if month_j else "کل سال"
    html_content = f'<html dir="rtl"><head><meta charset="utf-8"></head><body>'
    html_content += f'<h3 style="text-align:center;">گزارش حق بیمه - {month_name} {year_j}</h3>'
    html_content += '<table border="1"><thead><tr style="background-color:#eee;">'
    html_content += '<th>ردیف</th><th>تاریخ سند</th><th>شرح (نام پرسنل)</th><th>مبلغ کل (۳۰٪)</th><th>سهم کارگر (۷٪)</th><th>سهم کارفرما (۲۳٪)</th></tr></thead><tbody>'
    
    for i, line in enumerate(lines, 1):
        j_date = jdatetime.date.fromgregorian(date=line.date).strftime('%Y/%m/%d')
        worker_name = line.description.replace('بیمه پرداختنی سازمان (30%) - ', '')
        s_7 = line.credit * 7 / 30
        s_23 = line.credit * 23 / 30
        html_content += f'<tr><td>{i}</td><td>{j_date}</td><td>{worker_name}</td><td>{line.credit:,.0f}</td><td>{s_7:,.0f}</td><td>{s_23:,.0f}</td></tr>'
    
    html_content += '</tbody></table></body></html>'
    
    response = Response(html_content, mimetype='application/vnd.ms-excel')
    response.headers['Content-Disposition'] = f'attachment; filename=Insurance_Report_{year_j}_{month_j or "Full"}.xls'
    return response

@hr_bp.route('/pay_insurance', methods=['POST'])
@login_required
def pay_insurance():
    """ثبت سند واریز بیمه در دفتر کل"""
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    
    amount = float(request.form.get('amount', '0').replace(',', ''))
    description = request.form.get('description')
    pay_date = parse_smart_date(request.form.get('pay_date'))

    try:
        AccountingEngine.record_insurance_payment(amount, description, pay_date) # ۲. رفع ضعف موتور حسابداری (حذف String Matching)
        db.session.commit()
        flash(f'سند واریز بیمه به مبلغ {amount:,.0f} تومان با موفقیت ثبت شد و از بدهی جاری کسر گردید.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در ثبت سند واریز: {str(e)}', 'danger')

    return redirect(url_for('hr.insurance_report'))