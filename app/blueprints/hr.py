from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from app import db
from app.accounting_engine import AccountingEngine
from app.utils import permission_required
from app.utils import normalize_amount_to_toman, parse_smart_date, validate_national_id
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

@hr_bp.route('/')
@login_required
@permission_required('can_view_hr')
def index():
    from app.models import Worker, Pen, Sheep
    workers = Worker.query.filter(Worker.is_deleted == False).order_by(Worker.id.desc()).all()
    pens = Pen.query.all()
    today = datetime.now(UTC).date()

    kpi_data = {}
    for w in workers:
        score = 100
        bonus = 0
        notes = []

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
    return render_template('hr/index.html', workers=workers, pens=pens, kpi_data=kpi_data, today=today, today_str=today_str)

@hr_bp.route('/add_worker', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def add_worker():
    from app.models import Worker, WorkerDocument, WorkerEvent
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    w_code = request.form.get('worker_code') or f"PR-{random.randint(1000,9999)}"

    if not validate_national_id(request.form.get('national_id')):
        flash('خطا: کد ملی وارد شده معتبر نیست (باید ۱۰ رقم باشد).', 'danger')
        return redirect(url_for('hr.index'))
    
    new_worker = Worker(
        worker_code=w_code,
        name=request.form.get('name'),
        national_id=request.form.get('national_id'),
        phone=request.form.get('phone'),
        role=request.form.get('role'),
        education=request.form.get('education'),
        address=request.form.get('address'),
        bank_account=request.form.get('bank_account'),
        
        salary=normalize_amount_to_toman(request.form.get('salary')),
        housing_allowance=normalize_amount_to_toman(request.form.get('housing_allowance')),
        food_allowance=normalize_amount_to_toman(request.form.get('food_allowance')),
        family_allowance=normalize_amount_to_toman(request.form.get('family_allowance')),
        
        insurance_status=request.form.get('insurance_status'),
        status=request.form.get('status'),
        assigned_pen_id=request.form.get('assigned_pen_id') or None,
        start_date=parse_smart_date(request.form.get('start_date'), datetime.now(UTC).date())
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
    from app.models import AuditLog
    db.session.add(AuditLog(user_name=current_user.name, action=f"ثبت پرسنل جدید: {new_worker.name} ({new_worker.worker_code})", timestamp=datetime.now(UTC)))
    db.session.commit()
    
    flash('پرسنل جدید به همراه مدارک با موفقیت ثبت شد.', 'success')
    return redirect(url_for('hr.index'))

@hr_bp.route('/profile/<int:id>')
@login_required
@permission_required('can_view_hr')
def profile(id):
    from app.models import Worker, WorkerEvent, WorkerLoan, PettyCash, Pen, WorkerContract
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    worker = Worker.query.get_or_404(id)
    events = WorkerEvent.query.filter_by(worker_id=id).order_by(WorkerEvent.event_date.desc()).all()
    loans = WorkerLoan.query.filter_by(worker_id=id).order_by(WorkerLoan.issue_date.desc()).all()
    contracts = WorkerContract.query.filter_by(worker_id=id).order_by(WorkerContract.start_date.desc()).all()
    petty_cash = PettyCash.query.filter_by(worker_id=id).order_by(PettyCash.record_date.desc()).limit(10).all()
    
    pens = Pen.query.all()
    today_str = datetime.now(UTC).strftime('%Y-%m-%d')
    return render_template('hr/profile.html', worker=worker, events=events, loans=loans, contracts=contracts, tasks=tasks, petty_cash=petty_cash, pens=pens, today_str=today_str)

@hr_bp.route('/edit_worker/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def edit_worker(id):
    from app.models import Worker, WorkerDocument
    w = Worker.query.get_or_404(id)
    if not validate_national_id(request.form.get('national_id')):
        flash('خطا: کد ملی وارد شده معتبر نیست (باید ۱۰ رقم باشد).', 'danger')
        return redirect(url_for('hr.profile', id=id))
    w.name = request.form.get('name')
    w.national_id = request.form.get('national_id')
    w.phone = request.form.get('phone')
    w.role = request.form.get('role')
    w.education = request.form.get('education')
    w.address = request.form.get('address')
    w.bank_account = request.form.get('bank_account')
    
    w.salary = normalize_amount_to_toman(request.form.get('salary'))
    w.housing_allowance = normalize_amount_to_toman(request.form.get('housing_allowance'))
    w.food_allowance = normalize_amount_to_toman(request.form.get('food_allowance'))
    w.family_allowance = normalize_amount_to_toman(request.form.get('family_allowance'))
    
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
    from app.models import AuditLog
    db.session.add(AuditLog(user_name=current_user.name, action=f"ویرایش پرسنل: {w.name} ({w.worker_code})", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash('اطلاعات و مدارک پرسنل ویرایش شد.', 'success')
    return redirect(url_for('hr.profile', id=id))

@hr_bp.route('/add_loan/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def add_loan(id):
    from app.models import Worker, WorkerLoan, WorkerEvent, Transaction
    if current_user.role != 'مدیر': return redirect(url_for('hr.profile', id=id))
    amount = normalize_amount_to_toman(request.form.get('amount'))
    loan_type = request.form.get('loan_type')
    i_date = parse_smart_date(request.form.get('issue_date'), datetime.now(UTC).date())
    
    doc_img = None
    photo = request.files.get('document_image')
    if photo and photo.filename != '':
        filename = f"loan_{int(time.time())}_{secure_filename(photo.filename)}"
        upload_folder = os.path.join('app', 'static', 'uploads', 'hr')
        os.makedirs(upload_folder, exist_ok=True)
        photo.save(os.path.join(upload_folder, filename))
        doc_img = f"uploads/hr/{filename}"
        
    loan = WorkerLoan(worker_id=id, loan_type=loan_type, amount=amount, issue_date=i_date, installment_amount=Decimal(request.form.get('installment_amount') or '0'), status="در حال پرداخت", description=request.form.get('description'), document_image=doc_img)
    db.session.add(loan)
    db.session.flush()
    db.session.add(WorkerEvent(worker_id=id, event_type="مالی", event_date=i_date, description=f"پرداخت {loan_type} به مبلغ {amount:,.0f} تومان. (شناسه وام: {loan.id})"))
    db.session.add(Transaction(t_type='هزینه', category=f"پرداخت {loan_type} پرسنل", amount=amount, t_date=i_date, description=f"پرداخت {loan_type} به پرسنل ({request.form.get('description')})"))
    db.session.commit()
    from app.models import AuditLog
    worker = Worker.query.get(id)
    db.session.add(AuditLog(user_name=current_user.name, action=f"ثبت وام {loan_type} {amount:,.0f} تومان برای {worker.name if worker else 'نامشخص'}", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash(f'{loan_type} ثبت و در دفتر کل حسابداری لحاظ شد.', 'success')
    return redirect(url_for('hr.profile', id=id))

@hr_bp.route('/add_event/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def add_event(id):
    from app.models import WorkerEvent
    e_date = parse_smart_date(request.form.get('event_date'), datetime.now(UTC).date())
    db.session.add(WorkerEvent(worker_id=id, event_type=request.form.get('event_type'), event_date=e_date, description=request.form.get('description')))
    db.session.commit()
    return redirect(url_for('hr.profile', id=id))

@hr_bp.route('/delete_worker/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def delete_worker(id):
    from app.models import Worker, WorkerEvent
    import jdatetime
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    w = Worker.query.get_or_404(id)

    # محاسبه سنوات پایان کار
    severance_amount = Decimal('0')
    if w.start_date and w.salary:
        # سنوات = (آخرین حقوق پایه / 30) × 30 × تعداد سال‌های خدمت
        # برای کسر سال: (آخرین حقوق پایه / 365) × روزهای کارکرد
        today = datetime.now(UTC).date()
        days_employed = (today - w.start_date).days
        if days_employed > 0:
            daily_wage = Decimal(str(w.salary)) / Decimal('30')
            years = days_employed / 365.0
            severance_amount = daily_wage * Decimal('30') * Decimal(str(years))
            severance_amount = severance_amount.quantize(Decimal('1000'))

    w.is_deleted = True
    w.status = 'حذف شده'
    db.session.add(w)

    if severance_amount > 0:
        db.session.add(WorkerEvent(worker_id=id, event_type='پایان کار',
            event_date=datetime.now(UTC).date(),
            description=f"پایان همکاری - سنوات پرداختی: {float(severance_amount):,.0f} تومان"))

    db.session.commit()
    from app.models import AuditLog
    db.session.add(AuditLog(user_name=current_user.name, action=f"حذف پرسنل {w.name} - سنوات: {float(severance_amount):,.0f} تومان", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash(f'{w.name} از لیست خارج شد. سنوات {float(severance_amount):,.0f} تومان محاسبه و ثبت شد.', 'warning')
    return redirect(url_for('hr.index'))

@hr_bp.route('/add_contract/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def add_contract(id):
    from app.models import Worker, WorkerContract, WorkerEvent
    import jdatetime
    worker = Worker.query.get_or_404(id)
    start = parse_smart_date(request.form.get('start_date'), datetime.now(UTC).date())
    end = parse_smart_date(request.form.get('end_date')) if request.form.get('end_date') else None
    contract = WorkerContract(
        worker_id=id,
        contract_type=request.form.get('contract_type'),
        start_date=start,
        end_date=end,
        monthly_salary=normalize_amount_to_toman(request.form.get('monthly_salary')),
        description=request.form.get('description')
    )
    db.session.add(contract)
    db.session.flush()
    db.session.add(WorkerEvent(worker_id=id, event_type='قرارداد', event_date=start,
        description=f"قرارداد {request.form.get('contract_type')} از {start.strftime('%Y-%m-%d')}" + (f" تا {end.strftime('%Y-%m-%d')}" if end else "") + (" - حقوق " + "{:,.0f}".format(contract.monthly_salary) + " تومان" if contract.monthly_salary else "") + f" (شناسه قرارداد: {contract.id})"))
    db.session.commit()
    from app.models import AuditLog
    db.session.add(AuditLog(user_name=current_user.name, action=f"ثبت قرارداد برای {worker.name}", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash(f"قرارداد {contract.contract_type} برای {worker.name} ثبت شد.", "success")
    return redirect(url_for('hr.profile', id=id))

@hr_bp.route('/delete_contract/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def delete_contract(id):
    from app.models import WorkerContract, WorkerEvent
    from sqlalchemy import or_
    contract = WorkerContract.query.get_or_404(id)
    wid = contract.worker_id
    # حذف رویداد خط خدمت مرتبط
    WorkerEvent.query.filter(
        WorkerEvent.worker_id == wid,
        WorkerEvent.event_type == 'قرارداد',
        WorkerEvent.description.ilike(f"%شناسه قرارداد: {contract.id}%")
    ).delete()
    db.session.delete(contract)
    db.session.commit()
    from app.models import AuditLog
    db.session.add(AuditLog(user_name=current_user.name, action=f"حذف قرارداد {contract.contract_type}", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash("قرارداد حذف و از خط خدمت پاک شد.", "success")
    return redirect(url_for('hr.profile', id=wid))

@hr_bp.route('/delete_loan/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def delete_loan(id):
    from app.models import WorkerLoan, WorkerEvent
    loan = WorkerLoan.query.get_or_404(id)
    wid = loan.worker_id
    # حذف رویداد خط خدمت مرتبط
    WorkerEvent.query.filter(
        WorkerEvent.worker_id == wid,
        WorkerEvent.event_type == 'مالی',
        WorkerEvent.description.ilike(f"%شناسه وام: {loan.id}%")
    ).delete()
    db.session.delete(loan)
    db.session.commit()
    from app.models import AuditLog
    db.session.add(AuditLog(user_name=current_user.name, action=f"حذف {loan.loan_type} به مبلغ {float(loan.amount):,.0f} تومان", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash(f"{loan.loan_type} از سوابق حذف و از خط خدمت پاک شد.", "success")
    return redirect(url_for('hr.profile', id=wid))

@hr_bp.route('/quick_report', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def quick_report():
    from app.models import User, Task, Sheep
    issue_type = request.form.get('issue_type')
    worker_name = current_user.name if current_user.is_authenticated else "کارگر"
    
    if issue_type == 'کمبود انبار':
        item_name = request.form.get('inventory_item') or request.form.get('custom_inventory')
        admin_user = User.query.filter_by(role='مدیر').first()
        db.session.add(Task(worker_id=admin_user.id if admin_user else 1, description=f"گزارش کارگر ({worker_name}): کمبود {item_name} در انبار", task_date=datetime.now(UTC).date()))
        send_to_telegram(f"📦 #هشدار_انبار\nکارگر {worker_name} اعلام کمبود {item_name} کرده است.")
        flash(f"گزارش کمبود {item_name} به مدیر ارسال شد.", "success")
        
    elif issue_type == 'سایر موارد':
        custom_desc = request.form.get('custom_desc')
        admin_user = User.query.filter_by(role='مدیر').first()
        db.session.add(Task(worker_id=admin_user.id if admin_user else 1, description=f"پیام از {worker_name}: {custom_desc}", task_date=datetime.now(UTC).date()))
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
# ثبت روزانه حضور و غیاب کارگران
# ==========================================
@hr_bp.route('/attendance')
@login_required
@permission_required('can_view_hr')
def attendance():
    from app.models import Worker, DailyAttendance
    from datetime import date, timedelta
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    workers = Worker.query.filter(Worker.is_deleted == False).all()
    today = date.today()
    selected_date_str = request.args.get('date', str(today))
    selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    # گرفتن ۳۱ روز قبل برای نمایش تقویم
    start = selected_date - timedelta(days=selected_date.day - 1)
    end = selected_date
    records = DailyAttendance.query.filter(
        DailyAttendance.date >= start, DailyAttendance.date <= end
    ).order_by(DailyAttendance.date.desc(), DailyAttendance.worker_id).all()
    return render_template('hr/attendance.html', workers=workers, records=records,
                          selected_date=selected_date, today=today)

@hr_bp.route('/attendance/summary')
@login_required
@permission_required('can_view_hr')
def attendance_summary():
    """JSON: جمع ساعات اضافه‌کاری و جریمه‌های یه کارگر در یه ماه شمسی"""
    from app.models import DailyAttendance
    import jdatetime, re
    worker_id = request.args.get('worker_id', type=int)
    month_name = request.args.get('month_name', '')
    if not worker_id or not month_name:
        return jsonify({'overtime': 0, 'night': 0, 'fines': 0})
    match = re.search(r'(\d{4})', month_name)
    year_str = match.group(1) if match else str(jdatetime.datetime.now().year)
    month_names_rev = {'فروردین':1,'اردیبهشت':2,'خرداد':3,'تیر':4,'مرداد':5,'شهریور':6,'مهر':7,'آبان':8,'آذر':9,'دی':10,'بهمن':11,'اسفند':12}
    month_num = None
    for m_name, m_num in month_names_rev.items():
        if m_name in month_name:
            month_num = m_num
            break
    if not month_num:
        return jsonify({'overtime': 0, 'night': 0, 'fines': 0})
    j_start = jdatetime.date(int(year_str), month_num, 1)
    if month_num == 12:
        j_end = jdatetime.date(int(year_str) + 1, 1, 1)
    else:
        j_end = jdatetime.date(int(year_str), month_num + 1, 1)
    records = DailyAttendance.query.filter(
        DailyAttendance.worker_id == worker_id,
        DailyAttendance.date >= j_start.togregorian(),
        DailyAttendance.date < j_end.togregorian()
    ).all()
    return jsonify({
        'overtime': sum(r.overtime_hours for r in records),
        'night': sum(r.night_shift_hours for r in records),
        'fines': float(sum(r.fine_amount for r in records)),
        'mission': sum(1 for r in records if r.status == 'ماموریت'),
        'absent': sum(1 for r in records if r.status == 'غایب')
    })

@hr_bp.route('/attendance/add', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def add_attendance():
    from app.models import DailyAttendance
    worker_id = request.form.get('worker_id', type=int)
    record_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
    status = request.form.get('status', 'حاضر')
    overtime = float(request.form.get('overtime_hours') or 0)
    night_shift = float(request.form.get('night_shift_hours') or 0)
    fine = float(request.form.get('fine_amount') or 0)
    notes = request.form.get('notes', '')
    existing = DailyAttendance.query.filter_by(worker_id=worker_id, date=record_date).first()
    if existing:
        existing.status = status
        existing.overtime_hours = overtime
        existing.night_shift_hours = night_shift
        existing.fine_amount = fine
        existing.notes = notes
    else:
        db.session.add(DailyAttendance(worker_id=worker_id, date=record_date, status=status,
                                       overtime_hours=overtime, night_shift_hours=night_shift,
                                       fine_amount=fine, notes=notes))
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    flash('حضور و غیاب ثبت شد.', 'success')
    return redirect(request.referrer or url_for('hr.attendance'))

# ==========================================
# سیستم حقوق و دستمزد (فیش حقوقی اتوماتیک قانون کار)
# ==========================================
@hr_bp.route('/payslips')
@login_required
@permission_required('can_view_hr')
def payslips():
    from app.models import Worker, WorkerLoan, Payslip
    from app.blueprints.dashboard import get_setting
    from sqlalchemy import func
    import jdatetime
    import json
    from decimal import Decimal
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    workers = Worker.query.filter(Worker.is_deleted == False).all()
    worker_ids = [w.id for w in workers]
    month_names = {1:'فروردین',2:'اردیبهشت',3:'خرداد',4:'تیر',5:'مرداد',6:'شهریور',7:'مهر',8:'آبان',9:'آذر',10:'دی',11:'بهمن',12:'اسفند'}
    now_j = jdatetime.datetime.now()
    year_filter = request.args.get('year', type=int)
    month_filter = request.args.get('month', type=int)
    worker_filter = request.args.get('worker_id', type=int)
    status_filter = request.args.get('status')
    query = Payslip.query.options(db.joinedload(Payslip.worker))
    if month_filter:
        query = query.filter(Payslip.month_name.ilike(f"%{month_names.get(month_filter, month_filter)}%"))
    if year_filter:
        query = query.filter(Payslip.month_name.ilike(f"%{year_filter}%"))
    if worker_filter:
        query = query.filter(Payslip.worker_id == worker_filter)
    if status_filter == 'paid':
        query = query.filter(Payslip.is_paid == True)
    elif status_filter == 'unpaid':
        query = query.filter(Payslip.is_paid == False)
    query = query.order_by(Payslip.issue_date.desc())
    # آمار کل (بدون صفحه‌بندی) برای کارت‌های بالا
    stats = db.session.query(
        func.count(Payslip.id),
        func.sum(Payslip.gross_pay),
        func.sum(Payslip.net_pay),
        func.sum(Payslip.loan_deduction + Payslip.fines + Payslip.insurance + Payslip.tax)
    ).select_from(Payslip)
    if month_filter:
        stats = stats.filter(Payslip.month_name.ilike(f"%{month_names.get(month_filter, month_filter)}%"))
    if year_filter:
        stats = stats.filter(Payslip.month_name.ilike(f"%{year_filter}%"))
    if worker_filter:
        stats = stats.filter(Payslip.worker_id == worker_filter)
    if status_filter == 'paid':
        stats = stats.filter(Payslip.is_paid == True)
    elif status_filter == 'unpaid':
        stats = stats.filter(Payslip.is_paid == False)
    stats_row = stats.first()
    total_count = stats_row[0] or 0
    total_gross = float(stats_row[1] or 0)
    total_net = float(stats_row[2] or 0)
    total_deductions = float(stats_row[3] or 0)
    paid_count = Payslip.query.filter(Payslip.is_paid == True)
    if month_filter:
        paid_count = paid_count.filter(Payslip.month_name.ilike(f"%{month_names.get(month_filter, month_filter)}%"))
    if year_filter:
        paid_count = paid_count.filter(Payslip.month_name.ilike(f"%{year_filter}%"))
    if worker_filter:
        paid_count = paid_count.filter(Payslip.worker_id == worker_filter)
    paid_count = paid_count.count()
    unpaid_count = total_count - paid_count

    page = request.args.get('page', 1, type=int)
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    all_payslips = pagination.items
    today_str = datetime.now(UTC).strftime('%Y-%m-%d')
    default_month = f"{month_names.get(now_j.month, now_j.month)} {now_j.year}"

    # بهینه‌سازی: یک کوئری برای همه وام‌های فعال و تعداد وظایف
    today = datetime.now(UTC).date()
    # کوئری دسته‌جمعی وام‌ها
    all_active_loans = WorkerLoan.query.filter(
        WorkerLoan.worker_id.in_(worker_ids),
        WorkerLoan.status == 'در حال پرداخت'
    ).all()
    loan_totals = {}
    for loan in all_active_loans:
        loan_totals[loan.worker_id] = loan_totals.get(loan.worker_id, 0) + float(loan.installment_amount or 0)
    workers_data = {}
    for w in workers:
        workers_data[w.id] = {
            'salary': float(w.salary or 0),
            'housing': float(w.housing_allowance or 0),
            'food': float(w.food_allowance or 0),
            'family': float(w.family_allowance or 0),
            'insurance': w.insurance_status or 'بدون بیمه',
            'loan': loan_totals.get(w.id, 0)
        }

    settings_data = {
        'overtime_rate': float(get_setting('overtime_rate', '1.4')),
        'night_shift_rate': float(get_setting('night_shift_rate', '0.35')),
        'working_hours': float(get_setting('working_hours', '220')),
        'tax_percent': float(get_setting('tax_percent', '0'))
    }

    return render_template('hr/payslips.html', workers=workers, payslips=all_payslips, today_str=today_str,
                          current_year=year_filter or now_j.year, current_month=month_filter,
                          current_worker_id=worker_filter, current_status=status_filter,
                          default_month=default_month, month_names=month_names,
                          workers_data_json=json.dumps(workers_data),
                          settings_data=settings_data,
                          settings_data_json=json.dumps(settings_data),
                          pagination=pagination,
                          total_count=total_count, paid_count=paid_count, unpaid_count=unpaid_count,
                          total_gross=total_gross, total_net=total_net, total_deductions=total_deductions)

@hr_bp.route('/generate_payslip', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def generate_payslip():
    from app.models import Worker, WorkerLoan, Payslip, DailyAttendance
    from app.blueprints.dashboard import get_setting
    import jdatetime
    import re
    worker_id = request.form.get('worker_id')
    month_name = request.form.get('month_name')
    worker = Worker.query.get_or_404(worker_id)

    # جلوگیری از صدور فیش تکراری برای یک کارگر در یک ماه
    existing = Payslip.query.filter_by(worker_id=worker.id, month_name=month_name).first()
    if existing:
        flash(f"فیش حقوقی برای {worker.name} در {month_name} قبلاً صادر شده است.", "warning")
        return redirect(url_for('hr.payslips'))

    # استخراج سال و ماه شمسی از month_name (مثلاً "خرداد 1404")
    match = re.search(r'(\d{4})', month_name)
    year_str = match.group(1) if match else str(jdatetime.datetime.now().year)
    month_names_rev = {'فروردین':1,'اردیبهشت':2,'خرداد':3,'تیر':4,'مرداد':5,'شهریور':6,'مهر':7,'آبان':8,'آذر':9,'دی':10,'بهمن':11,'اسفند':12}
    month_num = None
    for m_name, m_num in month_names_rev.items():
        if m_name in month_name:
            month_num = m_num
            break

    if month_num:
        j_start = jdatetime.date(int(year_str), month_num, 1)
        if month_num == 12:
            j_end = jdatetime.date(int(year_str) + 1, 1, 1)
        else:
            j_end = jdatetime.date(int(year_str), month_num + 1, 1)
        start_g = j_start.togregorian()
        end_g = j_end.togregorian()
    else:
        start_g = end_g = None

    # بارگذاری خودکار داده‌های حضور و غیاب از دیتابیس
    att = []
    if start_g and end_g:
        att = DailyAttendance.query.filter(
            DailyAttendance.worker_id == worker.id,
            DailyAttendance.date >= start_g,
            DailyAttendance.date < end_g
        ).all()
    att_overtime = sum(a.overtime_hours for a in att)
    att_night = sum(a.night_shift_hours for a in att)
    att_fines = sum(a.fine_amount for a in att)

    # اولویت با داده‌های وارد شده در فرم (برای ویرایش دستی)، در غیر این صورت از دیتابیس
    # اگر فیلد در فرم موجود باشد حتی با مقدار صفر، از مقدار دیتابیس استفاده نمی‌شود
    def form_filled(key):
        return key in request.form and request.form.get(key, '').strip() != ''
    overtime_hours = Decimal(request.form.get('overtime_hours') or '0')
    if not form_filled('overtime_hours') and overtime_hours == 0 and att_overtime > 0:
        overtime_hours = Decimal(str(att_overtime))
    night_shift_hours = Decimal(request.form.get('night_shift_hours') or '0')
    if not form_filled('night_shift_hours') and night_shift_hours == 0 and att_night > 0:
        night_shift_hours = Decimal(str(att_night))
    transportation = Decimal(request.form.get('transportation_pay') or '0')
    eydi = Decimal(request.form.get('eydi_sanavat') or '0')
    fines = Decimal(request.form.get('fines') or '0')
    if not form_filled('fines') and fines == 0 and att_fines > 0:
        fines = Decimal(str(att_fines))

    # نرخ‌های اضافه‌کاری و شب‌کاری (قابل override از فرم)
    overtime_rate = Decimal(request.form.get('overtime_rate') or get_setting('overtime_rate', '1.4'))
    night_shift_rate = Decimal(request.form.get('night_shift_rate') or get_setting('night_shift_rate', '0.35'))
    working_hours = Decimal(get_setting('working_hours', '220'))
    hourly_rate = Decimal(worker.salary or '0') / working_hours if (worker.salary and worker.salary > 0) else Decimal('0')
    overtime_pay = overtime_hours * (hourly_rate * overtime_rate)
    night_shift_pay = night_shift_hours * (hourly_rate * night_shift_rate)

    # پیدا کردن اقساط وام های فعال
    active_loans = WorkerLoan.query.filter_by(worker_id=worker.id, status='در حال پرداخت').all()
    loan_deduction = Decimal(sum(l.installment_amount for l in active_loans if l.installment_amount) or 0)

    # محاسبه ناخالص
    base_pay = Decimal(worker.salary or '0')
    housing = Decimal(worker.housing_allowance or '0')
    food = Decimal(worker.food_allowance or '0')
    family = Decimal(worker.family_allowance or '0')
    daily_wage = base_pay / Decimal('30') if base_pay > 0 else Decimal('0')

    # حق ماموریت: (پایه / 30) × تعداد روزهای ماموریت
    mission_days = sum(1 for a in att if a.status == 'ماموریت')
    mission_pay = daily_wage * mission_days

    gross_pay = base_pay + housing + food + family + overtime_pay + night_shift_pay + transportation + eydi + mission_pay

    # محاسبه خودکار جریمه غیبت: (پایه / 30) × تعداد روزهای غیبت
    absent_count = sum(1 for a in att if a.status == 'غایب')
    auto_absence_fine = daily_wage * absent_count
    absence_note = ''
    if absent_count > 0 and fines == 0:
        fines = auto_absence_fine
        absence_note = f" (شامل {absent_count} روز غیبت)"
    elif absent_count > 0 and fines > 0:
        absence_note = f" | {absent_count} روز غیبت = {auto_absence_fine:,.0f} تومان"

    # تشخیص مرخصی بیش از ۳۰ روز در سال جاری
    excess_leave_fine = Decimal('0')
    if month_num and att:
        leave_this_month = sum(1 for a in att if a.status == 'مرخصی')
        # مجموع مرخصی‌های این کارگر در کل سال جاری شمسی
        j_year_start = jdatetime.date(int(year_str), 1, 1)
        j_year_end = jdatetime.date(int(year_str) + 1, 1, 1)
        year_records = DailyAttendance.query.filter(
            DailyAttendance.worker_id == worker.id,
            DailyAttendance.date >= j_year_start.togregorian(),
            DailyAttendance.date < j_year_end.togregorian(),
            DailyAttendance.status == 'مرخصی'
        ).all()
        total_leave = len(year_records)
        if total_leave > 30:
            excess = total_leave - 30
            excess_leave_fine = daily_wage * excess
            fines += excess_leave_fine
            absence_note += f" | {excess} روز مرخصی بیش از سقف = {excess_leave_fine:,.0f} تومان"

    # بیمه سهم کارگر: 7% از کل دریافتی ناخالص (مطابق قانون تأمین اجتماعی)
    has_insurance = worker.insurance_status in ('بیمه اجباری', 'فعال')
    insurance_worker_share = gross_pay * Decimal('0.07') if has_insurance else Decimal('0')

    # مالیات (درصدی از ناخالص، پیش‌فرض صفر — قابل تنظیم در تنظیمات)
    tax_percent = Decimal(get_setting('tax_percent', '0'))
    tax = gross_pay * (tax_percent / Decimal('100'))

    # سقف برای قسط وام: حداکثر ۵۰٪ از خالص حقوق بعد از کسر بیمه و مالیات
    max_loan_cap = (gross_pay - insurance_worker_share - tax) * Decimal('0.5')
    if loan_deduction > max_loan_cap:
        loan_deduction = max_loan_cap

    net_pay = gross_pay - (loan_deduction + fines + insurance_worker_share + tax)

    new_payslip = Payslip(
        worker_id=worker.id, month_name=month_name, base_salary=worker.salary,
        housing_allowance=worker.housing_allowance, food_allowance=worker.food_allowance, family_allowance=worker.family_allowance,
        overtime_pay=overtime_pay, night_shift_pay=night_shift_pay, transportation_pay=transportation,
        mission_pay=mission_pay, eydi_sanavat=eydi, loan_deduction=loan_deduction, fines=fines,
        insurance=insurance_worker_share, tax=tax, gross_pay=gross_pay, net_pay=net_pay
    )

    with db.session.begin_nested():
        db.session.add(new_payslip)
        db.session.flush()
        if att:
            for a in att:
                a.payslip_id = new_payslip.id
        AccountingEngine.record_payroll(new_payslip)

    db.session.commit()
    from app.models import AuditLog
    db.session.add(AuditLog(user_name=current_user.name, action=f"صدور فیش حقوقی {worker.name} بابت {month_name}", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash_msg = f"فیش حقوقی {worker.name} صادر و سند مالی ثبت شد.{absence_note}"
    flash(flash_msg, "success")
    return redirect(url_for('hr.payslips'))

@hr_bp.route('/pay_payslip/<int:id>')
@login_required
@permission_required('can_view_hr')
def pay_payslip(id):
    from app.models import Payslip, JournalEntry, JournalEntryLine, Account
    from app.accounting_engine import AccountingEngine
    p = Payslip.query.get_or_404(id)
    p.is_paid = True
    entry = JournalEntry(
        entry_number=AccountingEngine.generate_entry_number(),
        date=datetime.now(UTC).date(),
        description=f"تسویه فیش حقوقی {p.worker.name} بابت {p.month_name}"
    )
    db.session.add(entry)
    db.session.flush()
    acc_payable = Account.query.filter_by(code='2010').first()
    acc_bank = Account.query.filter_by(code='1010').first()
    if acc_payable and acc_bank:
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, debit=p.net_pay, credit=0.0, description=f"کاهش حساب پرداختنی - تسویه حقوق {p.worker.name}"))
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=0.0, credit=p.net_pay, description=f"پرداخت نقدی حقوق {p.worker.name}"))
    db.session.commit()

    # ارسال خلاصه فیش به تلگرام
    total_deductions = (p.loan_deduction or 0) + (p.fines or 0) + (p.insurance or 0) + (p.tax or 0)
    msg = (
        f"📄 *تسویه فیش حقوقی*\n"
        f"👤 {p.worker.name}\n"
        f"📅 {p.month_name}\n"
        f"💰 ناخالص: {float(p.gross_pay or 0):,.0f} تومان\n"
        f"📉 کسورات: {float(total_deductions):,.0f} تومان\n"
        f"✅ *خالص پرداختی: {float(p.net_pay or 0):,.0f} تومان*"
    )
    send_to_telegram(msg)

    # ثبت رویداد در پروفایل کارگر
    from app.models import WorkerEvent
    db.session.add(WorkerEvent(worker_id=p.worker_id, event_type='پرداخت حقوق',
        event_date=datetime.now(UTC).date(),
        description=f"تسویه فیش {p.month_name} — مبلغ {float(p.net_pay or 0):,.0f} تومان"))
    db.session.commit()

    flash("حقوق تسویه و در دفتر کل مالی ثبت شد. خلاصه فیش در تلگرام ارسال شد.", "success")
    return redirect(url_for('hr.payslips'))

@hr_bp.route('/payslip/print/<int:id>')
@login_required
@permission_required('can_view_hr')
def payslip_print(id):
    from app.models import Payslip, DailyAttendance
    from app.blueprints.dashboard import get_setting
    import jdatetime, re
    p = Payslip.query.get_or_404(id)
    # استخراج آمار حضور و غیاب این کارگر در ماه فیش
    match = re.search(r'(\d{4})', p.month_name)
    year_str = match.group(1) if match else str(jdatetime.datetime.now().year)
    month_names_rev = {'فروردین':1,'اردیبهشت':2,'خرداد':3,'تیر':4,'مرداد':5,'شهریور':6,'مهر':7,'آبان':8,'آذر':9,'دی':10,'بهمن':11,'اسفند':12}
    month_num = None
    for mn, mn_num in month_names_rev.items():
        if mn in p.month_name:
            month_num = mn_num
            break
    att_summary = {'present':0,'absent':0,'leave':0,'mission':0,'overtime':0.0,'night':0.0, 'absence_fine':0.0, 'excess_leave_fine':0.0}
    if month_num and p.worker_id:
        j_start = jdatetime.date(int(year_str), month_num, 1)
        j_end = jdatetime.date(int(year_str) + 1, 1, 1) if month_num == 12 else jdatetime.date(int(year_str), month_num + 1, 1)
        records = DailyAttendance.query.filter(
            DailyAttendance.worker_id == p.worker_id,
            DailyAttendance.date >= j_start.togregorian(),
            DailyAttendance.date < j_end.togregorian()
        ).all()
        for r in records:
            if r.status == 'حاضر': att_summary['present'] += 1
            elif r.status == 'غایب': att_summary['absent'] += 1
            elif r.status == 'مرخصی': att_summary['leave'] += 1
            elif r.status == 'ماموریت': att_summary['mission'] += 1
            att_summary['overtime'] += float(r.overtime_hours or 0)
            att_summary['night'] += float(r.night_shift_hours or 0)
        # محاسبه جریمه غیبت و مرخصی مازاد روی بک‌اند (Decimal درست)
        base = float(p.base_salary or 0)
        daily = base / 30.0 if base > 0 else 0
        att_summary['absence_fine'] = round(daily * att_summary['absent'], 0)
        if att_summary['absence_fine'] > float(p.fines or 0):
            att_summary['absence_fine'] = float(p.fines or 0)
        # مرخصی مازاد بر ۳۰ روز در کل سال
        j_year_start = jdatetime.date(int(year_str), 1, 1)
        j_year_end = jdatetime.date(int(year_str) + 1, 1, 1)
        total_leave = DailyAttendance.query.filter(
            DailyAttendance.worker_id == p.worker_id,
            DailyAttendance.date >= j_year_start.togregorian(),
            DailyAttendance.date < j_year_end.togregorian(),
            DailyAttendance.status == 'مرخصی'
        ).count()
        if total_leave > 30:
            att_summary['excess_leave_fine'] = round(daily * (total_leave - 30), 0)
    system_settings = {
        'farm_logo_path': get_setting('farm_logo_path', None),
        'farm_name': get_setting('farm_name', 'شرکت'),
        'currency_unit': get_setting('currency_unit', 'تومان')
    }
    return render_template('hr/payslip_print.html', p=p, system_settings=system_settings, att=att_summary)

@hr_bp.route('/payroll-dashboard')
@login_required
@permission_required('can_view_hr')
def payroll_dashboard():
    from app.models import Payslip, Worker, WorkerLoan
    from sqlalchemy import func
    import jdatetime
    import json
    from decimal import Decimal
    now_j = jdatetime.datetime.now()
    current_year = now_j.year
    current_month = now_j.month
    month_names = ['فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند']

    all_payslips = Payslip.query.order_by(Payslip.issue_date.desc()).all()
    total_gross = sum(float(p.gross_pay or 0) for p in all_payslips)
    total_net = sum(float(p.net_pay or 0) for p in all_payslips)
    total_insurance = sum(float(p.insurance or 0) for p in all_payslips)
    total_tax = sum(float(p.tax or 0) for p in all_payslips)
    unpaid_count = sum(1 for p in all_payslips if not p.is_paid)
    paid_count = sum(1 for p in all_payslips if p.is_paid)
    total_paid_amount = sum(float(p.net_pay or 0) for p in all_payslips if p.is_paid)

    # روند ۶ ماه اخیر
    monthly_trend = []
    for i in range(5, -1, -1):
        m = current_month - i
        y = current_year
        if m < 1: m += 12; y -= 1
        mn = month_names[m - 1]
        label = f"{mn} {y}"
        slips = [p for p in all_payslips if mn in p.month_name and str(y) in p.month_name]
        month_gross = sum(float(p.gross_pay or 0) for p in slips)
        month_net = sum(float(p.net_pay or 0) for p in slips)
        monthly_trend.append({'label': label, 'gross': month_gross, 'net': month_net})

    # توزیع مزایا (از آخرین فیش هر کارگر یا میانگین)
    avg_base = sum(float(w.salary or 0) for w in Worker.query.filter(Worker.is_deleted == False).all())
    worker_count = Worker.query.filter(Worker.is_deleted == False).count() or 1
    avg_base /= worker_count
    avg_housing = sum(float(w.housing_allowance or 0) for w in Worker.query.filter(Worker.is_deleted == False).all()) / worker_count
    avg_food = sum(float(w.food_allowance or 0) for w in Worker.query.filter(Worker.is_deleted == False).all()) / worker_count
    avg_family = sum(float(w.family_allowance or 0) for w in Worker.query.filter(Worker.is_deleted == False).all()) / worker_count
    avg_overtime = sum(float(p.overtime_pay or 0) for p in all_payslips) / max(len(all_payslips), 1)

    active_loans = WorkerLoan.query.filter_by(status='در حال پرداخت').all()
    total_loan_debt = sum(float(l.installment_amount or 0) for l in active_loans)

    return render_template('hr/payroll_dashboard.html',
        total_gross=total_gross, total_net=total_net, total_insurance=total_insurance,
        total_tax=total_tax, unpaid_count=unpaid_count, paid_count=paid_count,
        total_paid_amount=total_paid_amount, monthly_trend_json=json.dumps(monthly_trend),
        avg_base=avg_base, avg_housing=avg_housing, avg_food=avg_food,
        avg_family=avg_family, avg_overtime=avg_overtime, active_loans=active_loans,
        total_loan_debt=total_loan_debt, worker_count=worker_count)

@hr_bp.route('/attendance/calendar')
@login_required
@permission_required('can_view_hr')
def attendance_calendar():
    from app.models import Worker, DailyAttendance
    import jdatetime
    now_j = jdatetime.datetime.now()
    year = request.args.get('year', now_j.year, type=int)
    month = request.args.get('month', now_j.month, type=int)
    worker_filter_id = request.args.get('worker_id', type=int)
    month_names = {1:'فروردین',2:'اردیبهشت',3:'خرداد',4:'تیر',5:'مرداد',6:'شهریور',7:'مهر',8:'آبان',9:'آذر',10:'دی',11:'بهمن',12:'اسفند'}
    month_name = month_names.get(month, '')

    j_first = jdatetime.date(year, month, 1)
    if month == 12: j_last = jdatetime.date(year + 1, 1, 1)
    else: j_last = jdatetime.date(year, month + 1, 1)
    g_first = j_first.togregorian()
    g_last = j_last.togregorian()

    from datetime import timedelta
    days_in_month = (g_last - g_first).days
    # day_list: لیست تاپل‌های (تاریخ میلادی, روز شمسی)
    day_list = []
    for i in range(days_in_month):
        gd = g_first + timedelta(days=i)
        jd = jdatetime.date.fromgregorian(date=gd)
        day_list.append((gd, jd.day))

    workers = Worker.query.filter(Worker.is_deleted == False).order_by(Worker.name).all()
    if worker_filter_id:
        workers = [w for w in workers if w.id == worker_filter_id]
    attendances = DailyAttendance.query.filter(
        DailyAttendance.date >= g_first,
        DailyAttendance.date < g_last
    ).all()

    # att_map: worker_id → {date_str: record}
    att_map = {}
    att_sums = {}
    for a in attendances:
        att_map.setdefault(a.worker_id, {})[a.date.isoformat()] = a
    for w in workers:
        wa = [a for a in attendances if a.worker_id == w.id]
        present_count = sum(1 for a in wa if a.status == 'حاضر')
        absent_count = sum(1 for a in wa if a.status == 'غایب')
        leave_count = sum(1 for a in wa if a.status in ('مرخصی', 'ماموریت'))
        att_sums[w.id] = {
            'overtime': sum(a.overtime_hours for a in wa),
            'night': sum(a.night_shift_hours for a in wa),
            'fines': sum(float(a.fine_amount or 0) for a in wa),
            'present': present_count,
            'absent': absent_count,
            'leave': leave_count
        }

    # start_dates: تاریخ شروع به کار هر کارگر (برای نمایش روزهای قبل از استخدام)
    start_dates = {}
    for w in workers:
        if w.start_date:
            start_dates[w.id] = w.start_date.isoformat()

    return render_template('hr/attendance_calendar.html',
        workers=workers, year=year, month=month, month_name=month_name,
        day_list=day_list, g_first=g_first, att_map=att_map, att_sums=att_sums,
        month_names=month_names, start_dates=start_dates)

@hr_bp.route('/attendance/calendar/bulk', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def attendance_calendar_bulk():
    from app.models import Worker, DailyAttendance
    from datetime import date
    record_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
    year = request.form.get('year', type=int)
    month = request.form.get('month', type=int)
    workers = Worker.query.filter(Worker.is_deleted == False).all()
    count = 0
    for w in workers:
        existing = DailyAttendance.query.filter_by(worker_id=w.id, date=record_date).first()
        if not existing:
            db.session.add(DailyAttendance(worker_id=w.id, date=record_date, status='حاضر'))
            count += 1
    db.session.commit()
    flash(f'حضور {count} نفر برای تاریخ {record_date} ثبت شد.', 'success')
    return redirect(url_for('hr.attendance_calendar', year=year, month=month))

@hr_bp.route('/loans')
@login_required
@permission_required('can_view_hr')
def loans():
    from app.models import WorkerLoan, Worker
    loans_all = WorkerLoan.query.order_by(WorkerLoan.issue_date.desc()).all()
    workers = Worker.query.filter(Worker.is_deleted == False).all()
    active_total = sum(float(l.amount or 0) for l in loans_all if l.status == 'در حال پرداخت')
    settled_total = sum(float(l.amount or 0) for l in loans_all if l.status != 'در حال پرداخت')
    return render_template('hr/loans.html', loans=loans_all, workers=workers,
        active_total=active_total, settled_total=settled_total)

@hr_bp.route('/add_loan_global', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def add_loan_global():
    from app.models import WorkerLoan, WorkerEvent
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    worker_id = request.form.get('worker_id', type=int)
    loan_type = request.form.get('loan_type', 'مساعده')
    amount = normalize_amount_to_toman(request.form.get('amount'))
    installment = normalize_amount_to_toman(request.form.get('installment_amount')) or 0
    description = request.form.get('description', '')
    document = request.files.get('document')

    new_loan = WorkerLoan(
        worker_id=worker_id, loan_type=loan_type, amount=amount,
        installment_amount=installment, description=description,
        status='در حال پرداخت'
    )

    if document and document.filename:
        upload_folder = os.path.join('app', 'static', 'uploads', 'hr')
        os.makedirs(upload_folder, exist_ok=True)
        filename = f"loan_{worker_id}_{int(time.time())}_{secure_filename(document.filename)}"
        document.save(os.path.join(upload_folder, filename))
        new_loan.document_image = f"uploads/hr/{filename}"

    db.session.add(new_loan)
    db.session.add(WorkerEvent(worker_id=worker_id, event_type="وام", description=f"ثبت {loan_type} به مبلغ {amount:,.0f} تومان - {description}"))
    db.session.commit()
    from app.models import AuditLog
    db.session.add(AuditLog(user_name=current_user.name, action=f"ثبت وام/مساعده برای کارگر {worker_id} به مبلغ {amount:,.0f}", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash(f"{loan_type} به مبلغ {amount:,.0f} تومان ثبت شد.", "success")
    return redirect(url_for('hr.loans'))

@hr_bp.route('/delete_payslip/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def delete_payslip(id):
    from app.models import Payslip, AuditLog
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    p = Payslip.query.get_or_404(id)
    name = p.worker.name
    month = p.month_name
    db.session.delete(p)
    db.session.commit()
    db.session.add(AuditLog(user_name=current_user.name, action=f"حذف فیش حقوقی {name} بابت {month}", timestamp=datetime.now(UTC)))
    db.session.commit()
    flash(f"فیش حقوقی {month} - {name} حذف شد.", "warning")
    return redirect(url_for('hr.payslips'))

@hr_bp.route('/insurance_report')
@login_required
@permission_required('can_view_hr')
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
@permission_required('can_view_hr')
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
@permission_required('can_view_hr')
def pay_insurance():
    """ثبت سند واریز بیمه در دفتر کل"""
    if current_user.role != 'مدیر': return redirect(url_for('hr.index'))
    
    amount = normalize_amount_to_toman(request.form.get('amount'))
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


@hr_bp.route('/delete_document/<int:doc_id>', methods=['POST'])
@login_required
@permission_required('can_view_hr')
def delete_document(doc_id):
    from app.models import WorkerDocument
    doc = WorkerDocument.query.get_or_404(doc_id)
    worker_id = doc.worker_id
    try:
        os.remove(os.path.join('app', 'static', doc.file_path))
    except:
        pass
    db.session.delete(doc)
    db.session.commit()
    flash(f'مدرک {doc.doc_title} حذف شد.', 'warning')
    return redirect(url_for('hr.profile', id=worker_id))