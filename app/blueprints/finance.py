from decimal import Decimal
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify, make_response, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Transaction, TransactionCategory, TransactionDocument, Cheque, Contact, ContactDocument, SensorData, Sheep, WeightRecord
from sqlalchemy import func, case
from datetime import datetime, timedelta, UTC
from app.accounting_engine import AccountingEngine
import os
import time
import csv
import io
import xlsxwriter
import jdatetime
try:
    import pdfkit
except ImportError:
    pdfkit = None
from app.blueprints.dashboard import get_setting  # این تابع در داشبورد تعریف شده
 

finance_bp = Blueprint('finance', __name__)

def permission_required(permission_name):
    """دکوراتور چک کردن دسترسی‌های داینامیک بر اساس فیلدهای مدل User"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if not getattr(current_user, permission_name, False) and current_user.role != 'مدیر':
                flash('شما دسترسی لازم برای مشاهده این بخش را ندارید.', 'danger')
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_api_token(f):
    """دکوراتور امنیتی برای کنترل دسترسی API سنسورها و باسکول"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('X-API-TOKEN')
        expected_token = get_setting('api_token', 'SECRET_KEY_123')
        if not token or token != expected_token:
            return jsonify({"status": "error", "message": "Unauthorized access"}), 401
        return f(*args, **kwargs)
    return decorated_function

# ۱. حل بحران واحد پول و هاردکد مالیات (Data Integrity & VAT)
# توضیح: ما یک تابع کمکی می‌نویسیم که تمام ورودی‌ها را به "تومان" تبدیل می‌کند و نرخ مالیات را از دیتابیس می‌خواند.
# فایل: app/blueprints/finance.py
# در بالای فایل، زیر ایمپورت‌ها، این توابع را اضافه کنید:
def normalize_amount_to_toman(amount_str):
    """تبدیل تمام ورودی ها به تومان بر اساس تنظیمات فعلی کاربر"""
    if not amount_str: 
        return 0.0
    try:
        # پاکسازی کاراکترهای غیرعددی و تبدیل اعداد فارسی/عربی
        persian_digits = '۰۱۲۳۴۵۶۷۸۹'
        arabic_digits = '٠١٢٣٤٥٦٧٨٩'
        english_digits = '0123456789'
        translation_table = str.maketrans(persian_digits + arabic_digits, english_digits + english_digits)
        clean_str = str(amount_str).translate(translation_table).replace(',', '').strip()

        amount = Decimal(clean_str)
        if get_setting('currency_unit', 'تومان') == 'ریال':
            return amount / Decimal('10')
        return amount
    except Exception:
        return Decimal('0')

def parse_smart_date(date_str, default_val=None):
    """تبدیل هوشمند تاریخ شمسی/میلادی با پشتیبانی از اعداد فارسی و مقادیر خالی"""
    if not date_str or str(date_str).strip() in ['', 'None']:
        return default_val
    
    # تبدیل اعداد فارسی/عربی به انگلیسی برای پردازش صحیح در پایتون
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    english_digits = '0123456789'
    translation_table = str.maketrans(persian_digits + arabic_digits, english_digits + english_digits)
    date_str = str(date_str).translate(translation_table)

    date_str = date_str.replace('/', '-').strip()
    try:
        # اگر تاریخ شمسی بود
        if date_str.startswith(('13', '14')):
            p = date_str.split('-')
            return jdatetime.date(int(p[0]), int(p[1]), int(p[2])).togregorian()
        # اگر تاریخ میلادی بود
        return datetime.strptime(date_str[:10], '%Y-%m-%d').date()
    except Exception:
        return default_val

# ==========================================
# دفتر کل (فاکتورها)
# ==========================================
@finance_bp.route('/')
@login_required
@permission_required('can_view_finance')
def index():
    page = request.args.get('page', 1, type=int)
    
    # فیلترهای جدید
    search_q = request.args.get('search', '').strip()
    date_from_q = request.args.get('date_from')
    date_to_q = request.args.get('date_to')
    starred_q = request.args.get('starred')
    show_archived = request.args.get('archived') == '1'

    query = Transaction.query.filter_by(is_archived=show_archived, is_deleted=False)
    
    if search_q:
        query = query.filter(
            (Transaction.invoice_number.ilike(f"%{search_q}%")) |
            (Transaction.party_name.ilike(f"%{search_q}%")) |
            (Transaction.description.ilike(f"%{search_q}%"))
        )
    
    if date_from_q:
        try:
            date_obj = datetime.strptime(date_from_q, '%Y-%m-%d').date()
            query = query.filter(Transaction.t_date >= date_obj)
        except ValueError:
            pass
        
    if date_to_q:
        try:
            date_obj = datetime.strptime(date_to_q, '%Y-%m-%d').date()
            query = query.filter(Transaction.t_date <= date_obj)
        except ValueError:
            pass
        
    if starred_q == '1':
        query = query.filter(Transaction.is_starred == True)

    # بهینه‌سازی آمار: استفاده از ساب‌کوئری برای سرعت بیشتر در دیتای حجیم
    tx_ids = query.with_entities(Transaction.id).subquery()
    total_income = db.session.query(func.sum(Transaction.amount)).filter(Transaction.id.in_(tx_ids), Transaction.t_type == 'درآمد').scalar() or Decimal('0')
    total_expense = db.session.query(func.sum(Transaction.amount)).filter(Transaction.id.in_(tx_ids), Transaction.t_type == 'هزینه').scalar() or Decimal('0')
    net_profit = total_income - total_expense
    
    # صفحه‌بندی بر اساس تنظیمات مدیر
    page_size = int(get_setting('page_size', 50))
    transactions_paginated = query.order_by(Transaction.t_date.desc(), Transaction.id.desc()).paginate(page=page, per_page=page_size, error_out=False)

    return render_template('finance/index.html', 
                           transactions=transactions_paginated, total_income=total_income,
                           total_expense=total_expense, net_profit=net_profit,
                           current_search=search_q, current_from=date_from_q, 
                           current_to=date_to_q, current_starred=starred_q,
                           show_archived=show_archived)

@finance_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_transaction():
    if request.method == 'POST':
        t_type = request.form.get('t_type')
        if t_type not in ['درآمد', 'هزینه']:
            flash('نوع تراکنش نامعتبر است.', 'danger')
            return redirect(request.referrer)
        category_name = request.form.get('category')
        if not category_name or not category_name.strip():
            flash('دسته‌بندی تراکنش الزامی است.', 'danger')
            return redirect(request.referrer)
        category_name = category_name.strip()
        raw_amount = request.form.get('amount', '0')
        invoice_number = request.form.get('invoice_number')
        description = request.form.get('description')
        party_name = request.form.get('party_name') # فیلد جدید شخص/شرکت
        contact_id = request.form.get('contact_id')
        payment_method = request.form.get('payment_method', 'نقدی')
        cost_center = request.form.get('cost_center')
        due_date = parse_smart_date(request.form.get('due_date'))
        discount_val = normalize_amount_to_toman(request.form.get('discount_amount', '0'))
        
        amount_val = normalize_amount_to_toman(raw_amount)
        
        # منطق نهایی مالیات: اولویت با عدد وارد شده در فرم (حتی اگر صفر باشد)
        form_vat = request.form.get('vat_amount')
        if form_vat is not None and form_vat.strip() != "":
            vat_val = Decimal(form_vat.replace(',', ''))
        else:
            # اگر فیلد کلا خالی بود (مثلا در نسخه های قدیمی فرانت)، طبق تنظیمات حساب کن
            vat_rate_setting = Decimal(get_setting('vat_rate', '10'))
            vat_val = (amount_val - discount_val) * (vat_rate_setting / Decimal('100'))
        
        # استفاده از تابع پارسر هوشمند برای جلوگیری از خطا در تاریخ‌های شمسی/خالی
        t_date = parse_smart_date(request.form.get('t_date'), datetime.now(UTC).date())
        
        existing_cat = TransactionCategory.query.filter_by(name=category_name, t_type=t_type).first()
        if not existing_cat:
            db.session.add(TransactionCategory(name=category_name, t_type=t_type))
            db.session.flush()

        # --- منطق هوشمند اتصال یا ساخت حساب شخص ---
        linked_contact = None        

        try:
            if contact_id:
                linked_contact = Contact.query.get(contact_id)
            elif party_name:
                linked_contact = Contact.query.filter_by(name=party_name).first()
                if not linked_contact:
                    linked_contact = Contact(name=party_name, contact_type='عمومی', balance=0.0)
                    db.session.add(linked_contact)
                    db.session.flush()

            with db.session.begin_nested():
                new_transaction = Transaction(
                    t_type=t_type, category=category_name, amount=amount_val,
                    invoice_number=invoice_number, t_date=t_date, description=description,
                    party_name=linked_contact.name if linked_contact else party_name,
                    contact_id=linked_contact.id if linked_contact else None,
                    payment_method=payment_method,
                    cost_center=cost_center,
                    due_date=due_date if payment_method == 'نسیه' else None,
                    discount_amount=discount_val,
                    vat_amount=vat_val
                )
                db.session.add(new_transaction)
                db.session.flush()

                # فقط در معاملات نسیه تراز حساب شخص تغییر می‌کند
                if linked_contact and payment_method == 'نسیه':
                    change = amount_val if t_type == 'درآمد' else -amount_val
                    db.session.query(Contact).filter_by(id=linked_contact.id).update({Contact.balance: Contact.balance + change})
                    db.session.flush()

                if t_type == 'درآمد':
                    AccountingEngine.record_sale(new_transaction, include_vat=True)
                elif t_type == 'هزینه':
                    AccountingEngine.record_expense(new_transaction, include_vat=True)
                db.session.flush() # اطمینان از صحت اسناد قبل از اتمام بلاک
        except Exception as e:
            db.session.rollback()
            flash(f'خطای بحرانی در ثبت مالی: {str(e)}', 'danger')
            return redirect(url_for('finance.index'))

        documents = request.files.getlist('documents')
        upload_folder = os.path.join('app', 'static', 'uploads', 'documents')
        os.makedirs(upload_folder, exist_ok=True)
        for doc in documents:
            if doc and doc.filename != '':
                filename = secure_filename(doc.filename)
                unique_filename = f"{int(time.time())}_{filename}"
                doc.save(os.path.join(upload_folder, unique_filename))
                db.session.add(TransactionDocument(transaction_id=new_transaction.id, file_path=f"uploads/documents/{unique_filename}"))
        db.session.commit()
        flash('فاکتور با موفقیت ثبت شد.', 'success')
        return redirect(url_for('finance.index'))
        
    income_cats = TransactionCategory.query.filter_by(t_type='درآمد').all()
    expense_cats = TransactionCategory.query.filter_by(t_type='هزینه').all()
    all_contacts = Contact.query.order_by(Contact.name).all()
    today_str = datetime.now(UTC).strftime('%Y-%m-%d')
    vat_rate = get_setting('vat_rate', '10')
    return render_template('finance/add.html', income_cats=income_cats, expense_cats=expense_cats, 
                           contacts=all_contacts, today_str=today_str, vat_rate=vat_rate)

@finance_bp.route('/toggle_star_tx/<int:id>', methods=['POST'])
@login_required
def toggle_star_tx(id):
    tx = Transaction.query.get_or_404(id)
    tx.is_starred = not tx.is_starred
    db.session.commit()
    return jsonify({'success': True, 'is_starred': tx.is_starred})

@finance_bp.route('/archive_tx/<int:id>', methods=['POST'])
@login_required
def archive_tx(id):
    tx = Transaction.query.get_or_404(id)
    tx.is_archived = True
    db.session.commit()
    flash('فاکتور بایگانی شد و دیگر در محاسبات روزمره لحاظ نمی‌شود.', 'warning')
    return redirect(request.referrer)

@finance_bp.route('/delete_tx/<int:id>', methods=['POST'])
@login_required
def delete_tx(id):
    tx = Transaction.query.get_or_404(id)
    tx.is_deleted = True # جایگزینی حذف فیزیکی
    db.session.commit()
    flash('فاکتور ابطال شد. سند از محاسبات خارج شد اما در تاریخچه باقی ماند.', 'warning')
    return redirect(request.referrer)

@finance_bp.route('/export_tx')
@login_required
def export_tx():
    search_q = request.args.get('search', '')
    date_from_q = request.args.get('date_from')
    date_to_q = request.args.get('date_to')
    starred_q = request.args.get('starred') # رفع باگ ستاره فاکتورها
    
    query = Transaction.query.filter_by(is_archived=False)
    if search_q: query = query.filter((Transaction.invoice_number.ilike(f"%{search_q}%")) | (Transaction.party_name.ilike(f"%{search_q}%")))
    if date_from_q: query = query.filter(Transaction.t_date >= parse_smart_date(date_from_q))
    if date_to_q: query = query.filter(Transaction.t_date <= parse_smart_date(date_to_q))
    if starred_q == '1': query = query.filter(Transaction.is_starred == True)
    
    unit = get_setting('currency_unit', 'تومان')
    factor = 10 if unit == 'ریال' else 1
    transactions = query.order_by(Transaction.t_date.asc()).all()

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()
    worksheet.right_to_left()
    header_format = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1})

    headers = ['تاریخ', 'شماره فاکتور', 'شخص/شرکت', 'نوع', 'دسته‌بندی', f'مبلغ ({unit})', 'توضیحات']
    for col, h in enumerate(headers): worksheet.write(0, col, h, header_format)

    for row, t in enumerate(transactions, 1):
        worksheet.write(row, 0, str(t.t_date))
        worksheet.write(row, 1, t.invoice_number or '-')
        worksheet.write(row, 2, t.party_name or '-')
        worksheet.write(row, 3, t.t_type)
        worksheet.write(row, 4, t.category)
        worksheet.write(row, 5, t.amount * factor)
        worksheet.write(row, 6, t.description or '-')

    workbook.close()
    output.seek(0)
    return Response(output.read(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=transactions.xlsx"})

@finance_bp.route('/export_cheques')
@login_required
def export_cheques():
    search_q = request.args.get('search', '').strip()
    type_q = request.args.get('type', 'همه')
    status_q = request.args.get('status', 'همه')
    starred_q = request.args.get('starred')
    
    query = Cheque.query
    if search_q: query = query.filter((Cheque.cheque_number.contains(search_q)) | (Cheque.issuer_national_id.contains(search_q)) | (Cheque.issuer_name.contains(search_q)))
    if type_q != 'همه': query = query.filter(Cheque.cheque_type == type_q)
    if status_q != 'همه': query = query.filter(Cheque.status == status_q)
    if starred_q == '1': query = query.filter(Cheque.is_starred == True)
    
    unit = get_setting('currency_unit', 'تومان')
    factor = 10 if unit == 'ریال' else 1
    cheques = query.order_by(Cheque.due_date.asc()).all()

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()
    worksheet.right_to_left()
    header_format = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1})

    headers = ['نوع چک', 'شماره چک', f'مبلغ ({unit})', 'سررسید', 'وضعیت', 'بانک', 'صادرکننده', 'بابت']
    for col, h in enumerate(headers): worksheet.write(0, col, h, header_format)

    for row, c in enumerate(cheques, 1):
        worksheet.write(row, 0, c.cheque_type)
        worksheet.write(row, 1, c.cheque_number)
        worksheet.write(row, 2, c.amount * factor)
        worksheet.write(row, 3, str(c.due_date))
        worksheet.write(row, 4, c.status)
        worksheet.write(row, 5, c.bank_name or '-')
        worksheet.write(row, 6, c.issuer_name or '-')
        worksheet.write(row, 7, c.reason)

    workbook.close()
    output.seek(0)
    return Response(output.read(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=cheques.xlsx"})

@finance_bp.route('/api/iot/weight_status', methods=['GET'])
@login_required
def get_weight_status():
    """دریافت وضعیت وزن لحظه‌ای برای نمایش در رابط کاربری بدون رفرش"""
    ear_tag = request.args.get('ear_tag')
    sheep = Sheep.query.filter_by(ear_tag=ear_tag).first()
    return jsonify({"weight": sheep.weight if sheep else None})

@finance_bp.route('/print_tx')
@login_required
def print_tx():
    search_q = request.args.get('search', '')
    date_from_q = request.args.get('date_from')
    date_to_q = request.args.get('date_to')
    starred_q = request.args.get('starred')
    show_archived = request.args.get('archived') == '1'
    
    query = Transaction.query.filter_by(is_archived=show_archived)
    
    if search_q: query = query.filter((Transaction.invoice_number.ilike(f"%{search_q}%")) | (Transaction.party_name.ilike(f"%{search_q}%")))
    if date_from_q: query = query.filter(Transaction.t_date >= parse_smart_date(date_from_q))
    if date_to_q: query = query.filter(Transaction.t_date <= parse_smart_date(date_to_q))
    if starred_q == '1': query = query.filter(Transaction.is_starred == True)
    
    transactions = query.order_by(Transaction.t_date.asc()).all()
    today_date = datetime.now(UTC).date()
    return render_template('finance/print_tx.html', transactions=transactions, today_date=today_date)

@finance_bp.route('/print_cheques')
@login_required
def print_cheques():
    search_q = request.args.get('search', '').strip()
    type_q = request.args.get('type', 'همه')
    status_q = request.args.get('status', 'همه')
    starred_q = request.args.get('starred')
    
    query = Cheque.query
    if search_q: query = query.filter((Cheque.cheque_number.contains(search_q)) | (Cheque.issuer_national_id.contains(search_q)) | (Cheque.issuer_name.contains(search_q)))
    if type_q != 'همه': query = query.filter(Cheque.cheque_type == type_q)
    if status_q != 'همه': query = query.filter(Cheque.status == status_q)
    if starred_q == '1': query = query.filter(Cheque.is_starred == True)
    
    cheques = query.order_by(Cheque.due_date.asc()).all()
    today_date = datetime.now(UTC).date()
    return render_template('finance/print_cheques.html', cheques=cheques, today_date=today_date)



# ==========================================
# مدیریت چک ها
# ==========================================
@finance_bp.route('/cheques')
@login_required
def cheques():
    page = request.args.get('page', 1, type=int)
    search_q = request.args.get('search', '').strip()
    type_q = request.args.get('type', 'همه')
    status_q = request.args.get('status', 'در جریان')
    starred_q = request.args.get('starred')
    
    query = Cheque.query
    if search_q: query = query.filter((Cheque.cheque_number.contains(search_q)) | (Cheque.issuer_national_id.contains(search_q)) | (Cheque.issuer_name.contains(search_q)))
    if type_q != 'همه': query = query.filter(Cheque.cheque_type == type_q)
    if status_q != 'همه': query = query.filter(Cheque.status == status_q)
    if starred_q == '1': query = query.filter(Cheque.is_starred == True)

    # صفحه‌بندی چک‌ها (۵۰ مورد در هر صفحه)
    cheques_paginated = query.order_by(Cheque.due_date.asc()).paginate(page=page, per_page=50, error_out=False)

    total_payable = sum(c.amount for c in Cheque.query.filter_by(cheque_type='پرداختی (خودم)', status='در جریان').all())
    total_receivable = sum(c.amount for c in Cheque.query.filter_by(cheque_type='دریافتی (مشتری)', status='در جریان').all())
    total_bounced = sum(c.amount for c in Cheque.query.filter_by(status='برگشت خورده').all())
    
    # آمار تعداد چک ها (درخواست شما)
    pending_count = Cheque.query.filter_by(status='در جریان').count()
    cleared_count = Cheque.query.filter_by(status='پاس شده').count()
    bounced_count = Cheque.query.filter_by(status='برگشت خورده').count()
    
    today = datetime.now(UTC).date()
    warning_date = today + timedelta(days=5)
    urgent_cheques = Cheque.query.filter(Cheque.status == 'در جریان', Cheque.due_date <= warning_date).all()

    return render_template('finance/cheques.html', 
                           cheques=cheques_paginated, total_payable=total_payable, 
                           total_receivable=total_receivable, total_bounced=total_bounced,
                           pending_count=pending_count, cleared_count=cleared_count, bounced_count=bounced_count,
                           urgent_cheques=urgent_cheques, today=today,
                           current_search=search_q, current_type=type_q, current_status=status_q, current_starred=starred_q)

# تابع جدید برای ویرایش چک
@finance_bp.route('/edit_cheque/<int:id>', methods=['POST'])
@login_required
def edit_cheque(id):
    c = Cheque.query.get_or_404(id)
    c.cheque_type = request.form.get('cheque_type')
    c.cheque_number = request.form.get('cheque_number')
    c.amount = float(request.form.get('amount') or 0)
    c.due_date = parse_smart_date(request.form.get('due_date')) # رفع خطای تاریخ
    c.bank_name = request.form.get('bank_name')
    c.issuer_name = request.form.get('issuer_name')
    c.issuer_national_id = request.form.get('issuer_national_id')
    c.registered_to = request.form.get('registered_to')
    c.registrar_national_id = request.form.get('registrar_national_id')
    c.reason = request.form.get('reason')
    c.notes = request.form.get('notes')
    db.session.commit()
    flash('اطلاعات چک با موفقیت ویرایش شد.', 'success')
    return redirect(url_for('finance.cheques'))


@finance_bp.route('/add_cheque', methods=['GET', 'POST'])
@login_required
def add_cheque():
    if request.method == 'GET':
        return redirect(url_for('finance.cheques'))
    due_date = parse_smart_date(request.form.get('due_date')) # رفع خطای تاریخ
    
    image_path = None    
    photo = request.files.get('image')
    if photo and photo.filename != '':
        filename = f"cheque_{int(time.time())}_{secure_filename(photo.filename)}"
        upload_folder = os.path.join('app', 'static', 'uploads', 'cheques')
        os.makedirs(upload_folder, exist_ok=True)
        photo.save(os.path.join(upload_folder, filename))
        image_path = f"uploads/cheques/{filename}"

    new_cheque = Cheque(
        cheque_type=request.form.get('cheque_type'), cheque_number=request.form.get('cheque_number'),        
        amount=normalize_amount_to_toman(request.form.get('amount')), due_date=due_date, bank_name=request.form.get('bank_name'),
        issuer_name=request.form.get('issuer_name'), issuer_national_id=request.form.get('issuer_national_id'),
        registered_to=request.form.get('registered_to'), registrar_national_id=request.form.get('registrar_national_id'),
        reason=request.form.get('reason'), notes=request.form.get('notes'), image_path=image_path
    )
    db.session.add(new_cheque)
    db.session.commit()
    flash('چک جدید با موفقیت ثبت شد.', 'success')
    return redirect(url_for('finance.cheques'))

@finance_bp.route('/toggle_star_cheque/<int:id>', methods=['POST'])
@login_required
def toggle_star_cheque(id):
    c = Cheque.query.get_or_404(id)
    c.is_starred = not c.is_starred
    db.session.commit()
    return jsonify({'success': True, 'is_starred': c.is_starred})

@finance_bp.route('/update_cheque_status/<int:id>', methods=['POST'])
@login_required
def update_cheque_status(id):
    cheque = Cheque.query.get_or_404(id)
    new_status = request.form.get('status')
    cheque.status = new_status
    
    if new_status == 'پاس شده':
        try:
            AccountingEngine.record_cheque_clearing(cheque)
            t_type = 'هزینه' if cheque.cheque_type == 'پرداختی (خودم)' else 'درآمد'
            cat_name = f"تسویه چک {cheque.reason}"
            if not TransactionCategory.query.filter_by(name=cat_name, t_type=t_type).first():
                db.session.add(TransactionCategory(name=cat_name, t_type=t_type))
            db.session.add(Transaction(
                t_type=t_type, category=cat_name, amount=cheque.amount, 
                t_date=datetime.now(UTC).date(), invoice_number=cheque.cheque_number,
                description=f"تسویه چک {cheque.cheque_number} بابت {cheque.reason}", party_name=cheque.issuer_name
            ))
            db.session.commit()
            flash(f"چک با موفقیت پاس شد و سند حسابداری جابجایی وجه در دفتر کل صادر گردید.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"خطا در ثبت سند حسابداری تسویه: {str(e)}", "danger")
    else:
        flash(f"وضعیت چک به {new_status} تغییر یافت.", "warning")
        
    return redirect(request.referrer)

@finance_bp.route('/delete_cheque/<int:id>', methods=['POST'])
@login_required
def delete_cheque(id):
    cheque = Cheque.query.get_or_404(id)
    db.session.delete(cheque)
    db.session.commit()
    flash('چک به طور کامل حذف شد.', 'danger')
    return redirect(url_for('finance.cheques'))


# ==========================================
# سیستم تنخواه گردان (Petty Cash)
# ==========================================
@finance_bp.route('/petty_cash')
@login_required
def petty_cash():
    from app.models import PettyCash, Worker
    workers = Worker.query.all()
    records = PettyCash.query.order_by(PettyCash.record_date.desc(), PettyCash.id.desc()).all()
    
    # محاسبه موجودی تنخواه هر کارگر
    worker_balances = {}
    for w in workers:
        charges = sum(r.amount for r in w.petty_cash_records if r.action_type == 'شارژ تنخواه')
        expenses = sum(r.amount for r in w.petty_cash_records if r.action_type == 'هزینه تنخواه')
        worker_balances[w.name] = charges - expenses

    return render_template('finance/petty_cash.html', records=records, workers=workers, worker_balances=worker_balances)

@finance_bp.route('/add_petty_cash', methods=['POST'])
@login_required
def add_petty_cash():
    from app.models import PettyCash, Transaction
    worker_id = request.form.get('worker_id')
    amount = normalize_amount_to_toman(request.form.get('amount'))
    action_type = request.form.get('action_type')
    description = request.form.get('description')
    
    date_str = request.form.get('record_date')
    r_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now(UTC).date()
    
    # ثبت در جدول تنخواه
    db.session.add(PettyCash(worker_id=worker_id, amount=amount, action_type=action_type, record_date=r_date, description=description))
    
    # ---> حل مشکل دوبار حساب شدن (اصول حسابداری) <---
    # شارژ تنخواه فقط انتقال پول است و نباید به عنوان هزینه در دفتر کل ثبت شود.
    # اما اگر کارگر خرید کرد (هزینه تنخواه)، باید در دفتر کل ثبت شود:
    if action_type == 'هزینه تنخواه':
        db.session.add(Transaction(
            t_type='هزینه', 
            category='هزینه‌های تنخواه (گوناگون)', 
            amount=amount, 
            t_date=r_date, 
            description=f"خرید توسط تنخواه‌دار: {description}"
        ))
        
    db.session.commit()
    flash(f"تراکنش تنخواه با موفقیت ثبت شد.", "success")
    return redirect(url_for('finance.petty_cash'))

@finance_bp.route('/cheque_profile/<int:id>')
@login_required
def cheque_profile(id):
    cheque = Cheque.query.get_or_404(id)
    return render_template('finance/cheque_profile.html', c=cheque)

# ---> پروفایل و ویرایش فاکتورها <---
@finance_bp.route('/tx_profile/<int:id>')
@login_required
def tx_profile(id):
    tx = Transaction.query.get_or_404(id)
    return render_template('finance/tx_profile.html', t=tx)

@finance_bp.route('/edit_tx/<int:id>', methods=['POST'])
@login_required
def edit_tx(id):
    from werkzeug.utils import secure_filename
    import time
    
    tx = Transaction.query.get_or_404(id)
    tx.t_type = request.form.get('t_type')
    tx.category = request.form.get('category')    
    tx.amount = normalize_amount_to_toman(request.form.get('amount')) # اینجا مبلغ بدون کاما که از هیدن فیلد میاد دریافت میشه
    tx.t_date = parse_smart_date(request.form.get('t_date'))
    tx.invoice_number = request.form.get('invoice_number')
    tx.party_name = request.form.get('party_name')
    tx.description = request.form.get('description')
    # افزودن عکس جدید به فاکتور قبلی
    documents = request.files.getlist('documents')
    upload_folder = os.path.join('app', 'static', 'uploads', 'documents')
    os.makedirs(upload_folder, exist_ok=True)
    for doc in documents:
        if doc and doc.filename != '':
            filename = secure_filename(doc.filename)
            unique_filename = f"{int(time.time())}_{filename}"
            doc.save(os.path.join(upload_folder, unique_filename))
            db.session.add(TransactionDocument(transaction_id=tx.id, file_path=f"uploads/documents/{unique_filename}"))
            
    db.session.commit()
    flash('فاکتور با موفقیت ویرایش شد.', 'success')
    return redirect(url_for('finance.tx_profile', id=tx.id))

# ==========================================
# سیستم دفتر کل اشخاص (نسیه، طلب و بدهی)
# ==========================================
@finance_bp.route('/contacts')
@login_required
def contacts():
    from app.models import Contact
    search_q = request.args.get('search', '').strip()
    type_q = request.args.get('type', 'همه')
    
    query = Contact.query
    
    if search_q:
        query = query.filter(
            (Contact.name.ilike(f"%{search_q}%")) |
            (Contact.phone.ilike(f"%{search_q}%")) |
            (Contact.economic_code.ilike(f"%{search_q}%"))
        )
    
    if type_q != 'همه':
        query = query.filter(Contact.contact_type == type_q)
        
    all_contacts = query.order_by(Contact.name).all()
    total_debt = db.session.query(func.sum(Contact.balance)).filter(Contact.balance < 0).scalar() or 0
    total_credit = db.session.query(func.sum(Contact.balance)).filter(Contact.balance > 0).scalar() or 0
    
    return render_template('finance/contacts.html', contacts=all_contacts, 
                           total_debt=total_debt, total_credit=total_credit,
                           current_search=search_q, current_type=type_q)

@finance_bp.route('/add_contact', methods=['POST'])
@login_required
def add_contact():
    from app.models import Contact
    init_balance = float(request.form.get('balance') or 0)
    b_type = request.form.get('balance_type')
    bank_card = str(request.form.get('bank_card', '')).replace(' ', '').strip()
    economic_code = str(request.form.get('economic_code', '')).strip()
    
    # اگر ما بدهکاریم (تامین کننده)، تراز منفی میشود. اگر طلبکاریم مثبت.
    if b_type == 'بدهکاریم': init_balance = -abs(init_balance)
    
    if bank_card and len(bank_card) != 16:
        flash('خطا: شماره کارت بانکی باید دقیقاً ۱۶ رقم باشد.', 'danger')
        return redirect(url_for('finance.contacts'))

    if economic_code and len(economic_code) not in [10, 14]:
        flash('خطا: کد اقتصادی باید ۱۰ یا ۱۴ رقم باشد.', 'danger')
        return redirect(url_for('finance.contacts'))

    db.session.add(Contact(
        name=request.form.get('name'), phone=request.form.get('phone'),
        contact_type=request.form.get('contact_type'), balance=init_balance,
        economic_code=economic_code,
        bank_card=bank_card
    ))
    db.session.commit()
    flash('شخص/شرکت جدید به دفتر اضافه شد.', 'success')
    return redirect(url_for('finance.contacts'))

@finance_bp.route('/edit_contact/<int:id>', methods=['POST'])
@login_required
def edit_contact(id):
    c = Contact.query.get_or_404(id)
    # دریافت مقادیر و حذف فضاهای خالی (بدون تبدیل مستقیم به رشته None)
    bank_card = request.form.get('bank_card', '').replace(' ', '').strip()
    economic_code = request.form.get('economic_code', '').strip()

    # اعتبارسنجی فقط در صورت پر بودن فیلد
    if bank_card and len(bank_card) != 16 and bank_card != '':
        flash('خطا: شماره کارت بانکی باید دقیقاً ۱۶ رقم باشد.', 'danger')
        return redirect(url_for('finance.contact_profile', id=c.id))

    if economic_code and len(economic_code) not in [10, 14] and economic_code != '':
        flash('خطا: کد اقتصادی باید ۱۰ یا ۱۴ رقم باشد.', 'danger')
        return redirect(url_for('finance.contact_profile', id=c.id))

    c.name = request.form.get('name')
    c.phone = request.form.get('phone')
    c.contact_type = request.form.get('contact_type')
    c.economic_code = economic_code
    c.bank_card = bank_card
    db.session.commit()
    flash('اطلاعات شخص با موفقیت بروزرسانی شد.', 'success')
    return redirect(url_for('finance.contact_profile', id=c.id))

@finance_bp.route('/contact/<int:id>')
@login_required
def contact_profile(id):
    c = Contact.query.get_or_404(id)
    
    # دریافت پارامترها با اولویت فیلد مخفی (میلادی) و سپس فیلد متنی (شمسی)
    # Explicitly try to parse gregorian first, then jalali
    start_date_greg_str = request.args.get('date_from', '').strip()
    start_date_jalali_str = request.args.get('date_from_jalali', '').strip()

    # منطق اصلاح شده اولویت‌بندی تاریخ
    start_date_filter = parse_smart_date(start_date_greg_str) or parse_smart_date(start_date_jalali_str)

    end_date_greg_str = request.args.get('date_to', '').strip()
    end_date_jalali_str = request.args.get('date_to_jalali', '').strip()
    end_date_filter = parse_smart_date(end_date_greg_str) or parse_smart_date(end_date_jalali_str)

    show_archived = request.args.get('show_archived') == '1'
    moadian_only = request.args.get('moadian') == '1'
    starred_only = request.args.get('starred') == '1'

    # تعریف متغیرهای خام برای ارسال به قالب جهت جلوگیری از NameError
    raw_from = start_date_jalali_str or start_date_greg_str
    raw_to = end_date_jalali_str or end_date_greg_str

    query = db.session.query(Transaction).filter(Transaction.contact_id == id)
    
    # اعمال فیلتر بایگانی
    query = query.filter(Transaction.is_archived == show_archived)
    
    # اعمال فیلتر بازه زمانی
    start_g = start_date_filter or datetime(1900,1,1).date() # اگر شروع نبود، از ابتدا
    end_g = end_date_filter or datetime.now(UTC).date() # اگر پایان نبود، تا امروز
    
    # اطمینان از اینکه تاریخ شروع بعد از تاریخ پایان نباشد
    if start_g > end_g:
        flash('خطا: تاریخ شروع نمی‌تواند بعد از تاریخ پایان باشد. فیلترها جابجا شدند.', 'danger')
        start_g, end_g = end_g, start_g # Swap them to avoid empty results

    query = query.filter(Transaction.t_date >= start_g, Transaction.t_date <= end_g)

    # اعمال فیلتر مودیان
    if moadian_only:
        query = query.filter(Transaction.invoice_number != None, Transaction.invoice_number != '')

    # اعمال فیلتر ستاره‌دار
    if starred_only:
        query = query.filter(Transaction.is_starred == True)

    transactions = query.order_by(Transaction.t_date.desc(), Transaction.id.desc()).all()
    today_str = datetime.now(UTC).strftime('%Y-%m-%d')
    
    return render_template('finance/contact_profile.html', c=c, transactions=transactions,
                           current_from=raw_from, current_to=raw_to, today_str=today_str, 
                           show_archived=show_archived, moadian_only=moadian_only, starred_only=starred_only)

@finance_bp.route('/contact_add_tx/<int:id>', methods=['POST'])
@login_required
def contact_add_tx(id):
    from app.models import Contact, Transaction, TransactionCategory, TransactionDocument
    c = Contact.query.get_or_404(id)
    # جلوگیری از خطای ValueError در صورت خالی بودن مبلغ    
    amount = normalize_amount_to_toman(request.form.get('amount'))
    
    if amount <= 0:
        flash('خطا: مبلغ وارد شده باید بیشتر از صفر باشد.', 'contact_tx_error')
        return redirect(url_for('finance.contact_profile', id=id, _anchor='actions'))

    tx_type = request.form.get('tx_type') # پرداخت به شخص (بدهی کم میشود) یا دریافت از شخص
    # اولویت با تاریخ شمسی تایپ شده (برای حل مشکل دکمه امروز)
    t_date = parse_smart_date(request.form.get('t_date_jalali') or request.form.get('t_date'), datetime.now(UTC).date())

    new_tx = None
    if tx_type == 'پرداخت به شخص (تسویه بدهی)':
        db.session.query(Contact).filter_by(id=c.id).update({Contact.balance: Contact.balance + amount})
        db.session.flush()
        db.session.refresh(c) # همگام‌سازی شیء با مقدار جدید دیتابیس
        new_tx = Transaction(t_type='هزینه', category='تسویه حساب اشخاص', amount=amount, party_name=c.name, t_date=t_date, description=f"تسویه بدهی به {c.name}", contact_id=c.id, is_archived=False)
        AccountingEngine.record_contact_settlement(c, amount, "پرداخت وجه", t_date)
    else:
        db.session.query(Contact).filter_by(id=c.id).update({Contact.balance: Contact.balance - amount})
        db.session.flush()
        db.session.refresh(c)
        new_tx = Transaction(t_type='درآمد', category='تسویه حساب اشخاص', amount=amount, party_name=c.name, t_date=t_date, description=f"دریافت مطالبات از {c.name}", contact_id=c.id, is_archived=False)
        AccountingEngine.record_contact_settlement(c, amount, "دریافت وجه", t_date)
        
    # ثبت تراکنش در نشست دیتابیس
    db.session.add(new_tx)

    # اطمینان از وجود دسته بندی
    if not TransactionCategory.query.filter_by(name='تسویه حساب اشخاص').first():
        db.session.add(TransactionCategory(name='تسویه حساب اشخاص', t_type='هزینه'))
        db.session.add(TransactionCategory(name='تسویه حساب اشخاص', t_type='درآمد'))
        
    db.session.flush() # دریافت ID تراکنش برای اتصال به فایل

    # منطق آپلود عکس رسید
    file = request.files.get('receipt')
    if file and file.filename != '' and new_tx:
        filename = secure_filename(file.filename)
        unique_filename = f"receipt_{new_tx.id}_{int(time.time())}_{filename}"
        upload_folder = os.path.join('app', 'static', 'uploads', 'documents')
        os.makedirs(upload_folder, exist_ok=True)
        file.save(os.path.join(upload_folder, unique_filename))
        db.session.add(TransactionDocument(transaction_id=new_tx.id, file_path=f"uploads/documents/{unique_filename}"))

    db.session.commit()
    flash('تراکنش مالی ثبت و تراز شخص بروزرسانی شد.', 'success')
    return redirect(url_for('finance.contact_profile', id=c.id, _anchor='ledger'))


# ==========================================
# صورت های مالی (ترازنامه و سود و زیان استاندارد)
# ==========================================
@finance_bp.route('/statements')
@login_required
def statements():
    from app.models import Account, JournalEntryLine, JournalEntry
    from sqlalchemy import func
    
    accounts = Account.query.all()
    balances = {}
    
    total_assets = 0
    total_liabilities = 0
    total_equity = 0
    total_revenue = 0
    total_expense = 0
    
    for acc in accounts:
        # جمع مبالغ بدهکار و بستانکار هر حساب در دفتر کل
        debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc.id).scalar() or 0.0
        credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc.id).scalar() or 0.0
        
        # محاسبه مانده حساب بر اساس ماهیت
        if acc.type.nature == 'بدهکار':
            bal = debits - credits
        else:
            bal = credits - debits
            
        balances[acc.code] = {'name': acc.name, 'balance': bal, 'type': acc.type.name}
        
        # طبقه بندی در صورت های مالی
        if acc.code.startswith('1'): total_assets += bal
        elif acc.code.startswith('2'): total_liabilities += bal
        elif acc.code.startswith('3'): total_equity += bal
        elif acc.code.startswith('4'): total_revenue += bal
        elif acc.code.startswith('5'): total_expense += bal

    net_income = total_revenue - total_expense
    
    # تفکیک سود حاصل از ارزیابی (استاندارد 26) از سود عملیاتی (فروش)
    valuation_gain = db.session.query(func.sum(JournalEntryLine.credit)).join(JournalEntry).join(Account).filter(
        Account.code == '4101', JournalEntry.description.ilike('%تعدیل ارزش منصفانه گله%')
    ).scalar() or 0.0
    
    valuation_loss = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).join(Account).filter(
        Account.code == '5101', JournalEntry.description.ilike('%تعدیل ارزش منصفانه گله%')
    ).scalar() or 0.0
    
    net_valuation_profit = valuation_gain - valuation_loss
    operational_profit = net_income - net_valuation_profit
    
    # تفکیک سهم هزینه‌های جیره (خوراک)
    feed_costs_total = db.session.query(func.sum(JournalEntryLine.debit)).join(JournalEntry).join(Account).filter(
        Account.code == '5101', JournalEntry.description.ilike('%مصرف خوراک%')
    ).scalar() or 0.0
    
    # استخراج تفکیکی بدهی به پرسنل (حقوق پرداختنی)
    salary_acc = Account.query.filter_by(code='2101').first()
    salary_breakdown = []
    if salary_acc:
        salary_breakdown = db.session.query(
            JournalEntryLine.description,
            func.sum(JournalEntryLine.credit - JournalEntryLine.debit).label('balance')
        ).filter(JournalEntryLine.account_id == salary_acc.id, JournalEntryLine.description.ilike('%خالص حقوق پرداختنی%')
        ).group_by(JournalEntryLine.description).having(func.sum(JournalEntryLine.credit - JournalEntryLine.debit) != 0).all()

    total_equity_with_income = total_equity + net_income # حقوق صاحبان سهام + سود انباشته
    
    # فرمول طلایی حسابداری: دارایی = بدهی + سرمایه
    is_balanced = round(total_assets, 2) == round(total_liabilities + total_equity_with_income, 2)

    return render_template('finance/statements.html', 
                           balances=balances,
                           total_assets=total_assets,
                           total_liabilities=total_liabilities,
                           total_equity=total_equity_with_income,
                           net_income=net_income,
                           feed_costs_total=feed_costs_total,
                           net_valuation_profit=net_valuation_profit,
                           operational_profit=operational_profit,
                           total_revenue=total_revenue,
                           total_expense=total_expense,
                           salary_breakdown=salary_breakdown,
                           is_balanced=is_balanced)

@finance_bp.route('/official_balance_sheet')
@login_required
def official_balance_sheet():
    """تولید ترازنامه رسمی جهت ارائه به بانک و شرکا"""
    from app.models import Account, JournalEntryLine, JournalEntry
    from sqlalchemy import func
    
    accounts = Account.query.all()
    asset_accounts = []
    liability_equity_accounts = []
    
    total_assets = 0
    total_liabilities = 0
    total_equity = 0
    total_revenue = 0
    total_expense = 0
    
    for acc in accounts:
        debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc.id).scalar() or 0.0
        credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc.id).scalar() or 0.0
        
        if acc.type.nature == 'بدهکار':
            bal = debits - credits
        else:
            bal = credits - debits
            
        if acc.code.startswith('1'):
            total_assets += bal
            if bal != 0: asset_accounts.append({'name': acc.name, 'balance': bal})
        elif acc.code.startswith('2'):
            total_liabilities += bal
            if bal != 0: liability_equity_accounts.append({'name': acc.name, 'balance': bal})
        elif acc.code.startswith('3'):
            total_equity += bal
            if bal != 0: liability_equity_accounts.append({'name': acc.name, 'balance': bal})
        elif acc.code.startswith('4'): total_revenue += bal
        elif acc.code.startswith('5'): total_expense += bal

    net_income = total_revenue - total_expense
    # سود در ترازنامه به عنوان بخشی از حقوق صاحبان سهام نمایش داده می‌شود
    liability_equity_accounts.append({'name': 'سود (زیان) انباشته و جاری', 'balance': net_income})
    
    return render_template('finance/opening_statement_print.html',
                           asset_accounts=asset_accounts,
                           liability_equity_accounts=liability_equity_accounts,
                           total_assets=total_assets,
                           total_liability_equity=total_liabilities + total_equity + net_income,
                           today=jdatetime.date.today())


# ==========================================
# سیستم مدیریت مالیات و سامانه مودیان
# ==========================================
@finance_bp.route('/tax_management')
@login_required
def tax_management():
    # دسترسی فقط برای مدیر
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    
    from app.models import Account, JournalEntryLine, Transaction
    from sqlalchemy import func
    
    # 1. محاسبه مالیات پرداختنی (فروش ما به مشتریان) - کد حساب 2103
    vat_payable_acc = Account.query.filter_by(code='2103').first()
    vat_payable = 0
    if vat_payable_acc:
        credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=vat_payable_acc.id).scalar() or 0.0
        debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=vat_payable_acc.id).scalar() or 0.0
        vat_payable = credits - debits # ماهیت بستانکار
        
    # 2. محاسبه اعتبار مالیاتی (خریدهای ما از تامین کنندگان) - کد حساب 1104
    vat_receivable_acc = Account.query.filter_by(code='1104').first()
    vat_receivable = 0
    if vat_receivable_acc:
        debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=vat_receivable_acc.id).scalar() or 0.0
        credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=vat_receivable_acc.id).scalar() or 0.0
        vat_receivable = debits - credits # ماهیت بدهکار

    # 3. تراز نهایی مالیات (اگر مثبت باشد باید به دارایی بدهیم، اگر منفی باشد از دارایی طلبکاریم)
    net_tax_due = vat_payable - vat_receivable
    
    # دریافت فاکتورهای اخیر برای جدول سامانه مودیان
    recent_transactions = Transaction.query.order_by(Transaction.t_date.desc()).limit(50).all()
    vat_rate = float(get_setting('vat_rate', 10)) / 100

    return render_template('finance/tax_management.html', 
                           vat_payable=vat_payable, 
                           vat_receivable=vat_receivable, 
                           net_tax_due=net_tax_due,
                           transactions=recent_transactions,
                           vat_rate=vat_rate)

# روت شبیه ساز ارسال به سامانه مودیان
@finance_bp.route('/send_to_moadian', methods=['POST'])
@login_required
def send_to_moadian():
    # در دنیای واقعی اینجا کدهای API اتصال به my.tax.gov.ir قرار میگیرد
    import time
    time.sleep(1) # شبیه سازی تاخیر ارسال شبکه
    flash('فاکتورهای انتخاب شده با موفقیت به کارپوشه سامانه مودیان مالیاتی ارسال شدند و شماره منحصر بفرد مالیاتی (Tax ID) دریافت گردید.', 'success')
    return redirect(url_for('finance.tax_management'))


@finance_bp.route('/export_vat_return')
@login_required
def export_vat_return():
    if current_user.role != 'مدیر': return redirect(url_for('dashboard.index'))
    
    import io
    import csv
    from flask import Response
    
    transactions = Transaction.query.order_by(Transaction.t_date.asc()).all()
    vat_rate = float(get_setting('vat_rate', 10)) / 100
    unit = get_setting('currency_unit', 'تومان')
    factor = 10 if unit == 'ریال' else 1
    
    output = io.StringIO()
    writer = csv.writer(output)
    output.write('\ufeff')
    writer.writerow(['تاریخ', 'شماره فاکتور', 'طرف حساب', 'نوع سند', f'مبلغ خالص ({unit})', f'مالیات ارزش افزوده ({int(vat_rate*100)}%)', 'مبلغ کل فاکتور'])
    
    total_vat_payable = 0
    total_vat_receivable = 0
    
    for t in transactions:
        vat = t.amount * vat_rate
        total = t.amount + vat
        writer.writerow([t.t_date, t.invoice_number or '-', t.party_name or 'عمومی', t.t_type, f"{t.amount * factor:,.0f}", f"{vat * factor:,.0f}", f"{total * factor:,.0f}"])
        if t.t_type == 'درآمد': total_vat_payable += vat
        else: total_vat_receivable += vat
        
    writer.writerow([])
    writer.writerow(['جمع کل مالیات فروش (بدهی به دولت)', f"{total_vat_payable * factor:,.0f}"])
    writer.writerow(['جمع کل مالیات خرید (طلب از دولت)', f"{total_vat_receivable * factor:,.0f}"])
    writer.writerow(['تراز نهایی ارزش افزوده این فصل', f"{abs(total_vat_payable - total_vat_receivable) * factor:,.0f}", 'بدهکار' if total_vat_payable > total_vat_receivable else 'بستانکار'])
    
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=VAT_Return_Report.csv'
    return response

@finance_bp.route('/contact/<int:id>/statement')
@login_required
def contact_statement(id):
    from app.models import Contact, Transaction
    contact = Contact.query.get_or_404(id)

    # تبدیل اعداد فارسی به انگلیسی برای پارامترهای عددی
    def clean_num(s):
        if not s: return ""
        t = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
        return str(s).translate(t)

    # منطق بهبود یافته دریافت تاریخ‌ها
    start_date_greg_str = clean_num(request.args.get('date_from', '').strip())
    start_date_jalali_str = clean_num(request.args.get('date_from_jalali', '').strip())
    start_date_filter = parse_smart_date(start_date_greg_str) or parse_smart_date(start_date_jalali_str)

    end_date_greg_str = clean_num(request.args.get('date_to', '').strip())
    end_date_jalali_str = clean_num(request.args.get('date_to_jalali', '').strip())
    end_date_filter = parse_smart_date(end_date_greg_str) or parse_smart_date(end_date_jalali_str)

    starred_only = request.args.get('starred') == '1'
    moadian_only = request.args.get('moadian') == '1'
    show_archived = request.args.get('show_archived') == '1'
    report_type = request.args.get('report_type', 'seasonal')

    # تصمیم‌گیری نهایی برای بازه زمانی
    if report_type == 'custom' or (not report_type and (start_date_filter or end_date_filter)):
        start_g = start_date_filter or datetime(1900,1,1).date() # اگر شروع نبود، از ابتدا
        end_g = end_date_filter or datetime.now(UTC).date() # اگر پایان نبود، تا امروز
        # For display purposes, use the original raw strings
        display_raw_from = start_date_jalali_str or start_date_greg_str
        display_raw_to = end_date_jalali_str or end_date_greg_str

        # اصلاح سربرگ: نمایش چپ به راست تاریخ شمسی در محیط راست‌چین
        from_str = f"\u200E{display_raw_from.replace('-', '/')}\u200E" if display_raw_from else 'ابتدا'
        to_str = f"\u200E{display_raw_to.replace('-', '/')}\u200E" if display_raw_to else 'پایان'
        quarter_name = f"بازه انتخابی ({from_str} تا {to_str})"
        year = ""
        if start_g > end_g: start_g, end_g = end_g, start_g
    else: # اگر هیچ تاریخی انتخاب نشده بود، از منطق فصلی استفاده کن
        now_j = jdatetime.datetime.now()
        year = int(clean_num(request.args.get('year'))) if request.args.get('year') else now_j.year
        quarter = int(clean_num(request.args.get('quarter'))) if request.args.get('quarter') else 1

        ranges = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
        start_month, end_month = ranges.get(quarter)
        start_date_j = jdatetime.date(year, start_month, 1)
        last_day = 31 if end_month <= 6 else (30 if end_month <= 11 else (29 if not jdatetime.date(year, 1, 1).isleap() else 30)) # اصلاح برای سال کبیسه
        end_date_j = jdatetime.date(year, end_month, last_day)
        start_g = start_date_j.togregorian()
        end_g = end_date_j.togregorian()
        quarter_name = {1: 'بهار', 2: 'تابستان', 3: 'پاییز', 4: 'زمستان'}[quarter]
    
    # فیلتر بر اساس وضعیت بایگانی و بازه زمانی انتخابی
    q = Transaction.query.filter(
        Transaction.contact_id == id, 
        Transaction.t_date >= start_g, 
        Transaction.t_date <= end_g,
        Transaction.is_archived == show_archived
    )
    
    if starred_only:
        q = q.filter(Transaction.is_starred == True)
    if moadian_only:
        q = q.filter(Transaction.invoice_number != None, Transaction.invoice_number != '')
        
    transactions = q.order_by(Transaction.t_date.asc()).all()

    opening_income = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.contact_id == id, Transaction.t_type == 'درآمد', Transaction.t_date < start_g
    ).scalar() or 0.0
    opening_expense = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.contact_id == id, Transaction.t_type == 'هزینه', Transaction.t_date < start_g
    ).scalar() or 0.0
    opening_balance = opening_income - opening_expense
    
    period_income = sum(t.amount for t in transactions if t.t_type == 'درآمد')
    period_expense = sum(t.amount for t in transactions if t.t_type == 'هزینه')
    
    # دریافت تنظیمات هویت بصری
    system_settings = {
        'farm_name': get_setting('farm_name', 'مجتمع دامپروری هوشمند'),
        'farm_logo_path': get_setting('farm_logo_path', None)
    }

    return render_template('finance/quarterly_statement.html',
                           contact=contact, transactions=transactions,
                           year=year, quarter_name=quarter_name,
                           opening_balance=opening_balance, system_settings=system_settings,
                           period_income=period_income, period_expense=period_expense,
                           today=jdatetime.date.today())

@finance_bp.route('/contact/<int:id>/statement/pdf')
@login_required
def export_contact_statement_pdf(id):
    """تولید و دانلود فایل PDF صورت‌حساب فصلی"""
    if pdfkit is None:
        flash('کتابخانه تولید PDF (pdfkit) نصب نیست. لطفا دستور pip install pdfkit را اجرا کنید.', 'danger')
        return redirect(url_for('finance.contact_profile', id=id))

    contact = Contact.query.get_or_404(id)

    def clean_num(s):
        if not s: return ""
        t = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
        return str(s).translate(t)

    start_date_greg_str = clean_num(request.args.get('date_from', '').strip())
    start_date_jalali_str = clean_num(request.args.get('date_from_jalali', '').strip())
    start_date_filter = parse_smart_date(start_date_greg_str) or parse_smart_date(start_date_jalali_str)

    end_date_greg_str = clean_num(request.args.get('date_to', '').strip())
    end_date_jalali_str = clean_num(request.args.get('date_to_jalali', '').strip())
    end_date_filter = parse_smart_date(end_date_greg_str) or parse_smart_date(end_date_jalali_str)

    starred_only = request.args.get('starred') == '1'
    moadian_only = request.args.get('moadian') == '1'
    show_archived = request.args.get('show_archived') == '1'
    report_type = request.args.get('report_type', 'seasonal')

    if report_type == 'custom' or (not report_type and (start_date_filter or end_date_filter)):
        start_g = start_date_filter or datetime(1900,1,1).date()
        end_g = end_date_filter or datetime.now(UTC).date()
        display_raw_from = start_date_jalali_str or start_date_greg_str
        display_raw_to = end_date_jalali_str or end_date_greg_str
        
        from_str = f"\u200E{display_raw_from.replace('-', '/')}\u200E" if display_raw_from else 'ابتدا'
        to_str = f"\u200E{display_raw_to.replace('-', '/')}\u200E" if display_raw_to else 'پایان'
        quarter_name = f"بازه انتخابی ({from_str} تا {to_str})"
        year, quarter = "", ""
        if start_g > end_g: start_g, end_g = end_g, start_g
    else:
        now_j = jdatetime.datetime.now()
        year = int(clean_num(request.args.get('year'))) if request.args.get('year') else now_j.year
        quarter = int(clean_num(request.args.get('quarter'))) if request.args.get('quarter') else 1
        ranges = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
        start_month, end_month = ranges.get(quarter)
        start_date_j = jdatetime.date(year, start_month, 1)
        last_day = 31 if end_month <= 6 else (30 if end_month <= 11 else (29 if not jdatetime.date(year, 1, 1).isleap() else 30))
        end_date_j = jdatetime.date(year, end_month, last_day)
        start_g = start_date_j.togregorian()
        end_g = end_date_j.togregorian()
        quarter_name = {1: 'بهار', 2: 'تابستان', 3: 'پاییز', 4: 'زمستان'}[quarter]
    
    q = Transaction.query.filter(
        Transaction.contact_id == id, 
        Transaction.t_date >= start_g, 
        Transaction.t_date <= end_g,
        Transaction.is_archived == show_archived
    )
    
    if starred_only:
        q = q.filter(Transaction.is_starred == True)
    if moadian_only:
        q = q.filter(Transaction.invoice_number != None, Transaction.invoice_number != '')
        
    transactions = q.order_by(Transaction.t_date.asc()).all()
    
    opening_income = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.contact_id == id, Transaction.t_type == 'درآمد', Transaction.t_date < start_g
    ).scalar() or 0.0
    opening_expense = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.contact_id == id, Transaction.t_type == 'هزینه', Transaction.t_date < start_g
    ).scalar() or 0.0
    opening_balance = opening_income - opening_expense
    
    period_income = sum(t.amount for t in transactions if t.t_type == 'درآمد')
    period_expense = sum(t.amount for t in transactions if t.t_type == 'هزینه')
    
    # دریافت تنظیمات هویت بصری جهت نمایش در PDF
    system_settings = {
        'farm_name': get_setting('farm_name', 'مجتمع دامپروری هوشمند'),
        'farm_logo_path': get_setting('farm_logo_path', None)
    }

    # رندر کردن تمپلیت به رشته HTML
    html = render_template('finance/quarterly_statement.html',
                           contact=contact, transactions=transactions,
                           year=year, quarter_name=quarter_name,
                           opening_balance=opening_balance, system_settings=system_settings,
                           period_income=period_income, period_expense=period_expense,
                           today=jdatetime.date.today())

    # تنظیمات خروجی PDF (پشتیبانی از UTF-8 و RTL)
    options = {
        'encoding': "UTF-8",
        'enable-local-file-access': None,
        'print-media-type': '',
        'quiet': ''
    }

    # شناسایی هوشمند مسیر wkhtmltopdf (رفع هاردکد درایو C)
    path_wk = None
    import shutil
    path_wk = shutil.which("wkhtmltopdf") # جستجو در System PATH
    if not path_wk:
        for p in [r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe', r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe', '/usr/bin/wkhtmltopdf', '/usr/local/bin/wkhtmltopdf']:
            if os.path.exists(p):
                path_wk = p
                break

    config = pdfkit.configuration(wkhtmltopdf=path_wk) if path_wk else None

    try:
        pdf = pdfkit.from_string(html, False, options=options, configuration=config)
    except OSError:
        flash('خطا: ابزار تولید PDF در سرور یافت نشد. لطفاً wkhtmltopdf را نصب و به PATH اضافه کنید.', 'danger')
        return redirect(url_for('finance.contact_profile', id=id))

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    filename_suffix = f"{year}_{quarter}" if report_type == 'seasonal' else "Custom_Range"
    response.headers['Content-Disposition'] = f'attachment; filename=Statement_{id}_{filename_suffix}.pdf'
    return response

@finance_bp.route('/contacts/ledger')
@login_required
def contacts_ledger():
    """گزارش تراز معین اشخاص - تفکیک طلبکاران و بدهکاران بازار"""
    all_contacts = Contact.query.all()
    debtors = [c for c in all_contacts if c.balance > 0] # کسانی که به ما بدهکارند (طلب ما)
    creditors = [c for c in all_contacts if c.balance < 0] # کسانی که ما به آنها بدهکاریم
    
    total_debtors = sum(c.balance for c in debtors)
    total_creditors = abs(sum(c.balance for c in creditors))
    
    return render_template('finance/ledger_balance.html', 
                           debtors=debtors, creditors=creditors,
                           total_debtors=total_debtors, total_creditors=total_creditors)

@finance_bp.route('/contact/<int:id>/export_tx')
@login_required
def contact_export_tx(id):
    """خروجی اکسل تراکنش‌های یک شخص با رعایت فیلترهای زمانی"""
    c = Contact.query.get_or_404(id)

    # Explicitly try to parse gregorian first, then jalali
    start_date_greg_str = request.args.get('date_from', '').strip()
    start_date_jalali_str = request.args.get('date_from_jalali', '').strip()
    start_date_filter = parse_smart_date(start_date_greg_str) or parse_smart_date(start_date_jalali_str)

    end_date_greg_str = request.args.get('date_to', '').strip()
    end_date_jalali_str = request.args.get('date_to_jalali', '').strip()
    end_date_filter = parse_smart_date(end_date_greg_str) or parse_smart_date(end_date_jalali_str)

    date_from_q = start_date_filter
    date_to_q = end_date_filter
    moadian_only = request.args.get('moadian') == '1'
    starred_only = request.args.get('starred') == '1'
    show_archived = request.args.get('show_archived') == '1'
    
    query = db.session.query(Transaction).filter(Transaction.contact_id == id)
    
    # اعمال فیلتر بایگانی
    query = query.filter(Transaction.is_archived == show_archived)

    # اعمال فیلتر بازه زمانی با مقادیر پارس شده
    start_g = date_from_q or datetime(1900, 1, 1).date()
    end_g = date_to_q or datetime.now(UTC).date()
    
    # Ensure start_g is not after end_g
    if start_g > end_g:
        start_g, end_g = end_g, start_g # Swap them

    query = query.filter(Transaction.t_date >= start_g, Transaction.t_date <= end_g)
    
    if starred_only:
        query = query.filter(Transaction.is_starred == True)

    # فیلتر سامانه مودیان (فاکتورهایی که شماره فاکتور دارند)
    if moadian_only:
        query = query.filter(Transaction.invoice_number != None, Transaction.invoice_number != '')
        
    transactions = query.order_by(Transaction.t_date.asc()).all()
    unit = get_setting('currency_unit', 'تومان')
    factor = 10 if unit == 'ریال' else 1
    
    html_content = '<html dir="rtl"><head><meta charset="utf-8"><style>table {border-collapse: collapse; width: 100%;} th, td {border: 1px solid black; padding: 8px; text-align: center;} th {background-color: #f2f2f2; font-weight: bold;}</style></head><body>'
    html_content += f'<h2 style="text-align:center;">گزارش ریز تراکنش‌های: {c.name}</h2>'
    
    # For display purposes, use the original raw strings
    display_raw_from = start_date_jalali_str or start_date_greg_str
    display_raw_to = end_date_jalali_str or end_date_greg_str
    if display_raw_from or display_raw_to:
        html_content += f'<p style="text-align:center;">بازه زمانی فیلتر شده: {display_raw_from or "ابتدا"} تا {display_raw_to or "پایان"}</p>'
    
    html_content += f'<table><thead><tr><th>تاریخ (شمسی)</th><th>نوع</th><th>دسته‌بندی</th><th>مبلغ ({unit})</th><th>شرح فاکتور</th></tr></thead><tbody>'
    for t in transactions:
        try:
            # اطمینان از تبدیل صحیح تاریخ برای اکسل
            j_date = jdatetime.date.fromgregorian(date=t.t_date).strftime('%Y/%m/%d')
        except:
            j_date = str(t.t_date)
        
        # پاکسازی متن شرح برای جلوگیری از به هم ریختن اکسل
        clean_desc = (t.description or '-').replace('\n', ' ').replace('\r', '')
        
        html_content += f"<tr><td>{j_date}</td><td>{t.t_type}</td><td>{t.category}</td><td>{t.amount * factor:,.0f}</td><td>{clean_desc}</td></tr>"
    html_content += '</tbody></table></body></html>'
    
    response = Response(html_content, mimetype='application/vnd.ms-excel')
    response.headers['Content-Disposition'] = f'attachment; filename=Transactions_Contact_{id}.xls'
    return response

@finance_bp.route('/contact/<int:id>/upload_doc', methods=['POST'])
@login_required
def upload_contact_doc(id):
    """آپلود قرارداد و مدارک پیوست برای اشخاص"""
    c = Contact.query.get_or_404(id)
    doc_title = request.form.get('doc_title', 'مدرک پیوست')
    files = request.files.getlist('documents')
    
    upload_folder = os.path.join('app', 'static', 'uploads', 'contacts')
    os.makedirs(upload_folder, exist_ok=True)
    
    uploaded_count = 0
    for file in files:
        if file and file.filename != '':
            filename = f"contact_{c.id}_{int(time.time())}_{secure_filename(file.filename)}"
            file.save(os.path.join(upload_folder, filename))
            db.session.add(ContactDocument(contact_id=c.id, doc_title=doc_title, file_path=f"uploads/contacts/{filename}"))
            uploaded_count += 1
            
    db.session.commit()
    flash(f'{uploaded_count} مدرک آپلود شد.', 'success')
    return redirect(url_for('finance.contact_profile', id=id, _anchor='docs'))

@finance_bp.route('/contact/bulk_action', methods=['POST'])
@login_required
def contact_bulk_action():
    """عملیات گروهی روی تراکنش‌های یک شخص"""
    contact_id = request.form.get('contact_id')
    tx_ids = request.form.getlist('tx_ids')
    action = request.form.get('action')
    
    if tx_ids:
        if action == 'archive':
            Transaction.query.filter(Transaction.id.in_(tx_ids)).update({Transaction.is_archived: True}, synchronize_session=False)
        elif action == 'delete':
            Transaction.query.filter(Transaction.id.in_(tx_ids)).delete(synchronize_session=False)
        
        db.session.commit()
        flash(f'عملیات {action} روی {len(tx_ids)} ردیف انجام شد.', 'success')
    
    return redirect(url_for('finance.contact_profile', id=contact_id, _anchor='ledger'))

@finance_bp.route('/contact/delete_doc/<int:doc_id>', methods=['POST'])
@login_required
def delete_contact_doc(doc_id):
    """حذف مدرک پیوست شخص"""
    doc = ContactDocument.query.get_or_404(doc_id)
    contact_id = doc.contact_id
    db.session.delete(doc)
    db.session.commit()
    flash('مدرک از پرونده حذف شد.', 'warning')
    return redirect(url_for('finance.contact_profile', id=contact_id))

@finance_bp.route('/contact/update_followup/<int:tx_id>', methods=['POST'])
@login_required
def update_followup(tx_id):
    """بروزرسانی یا ثبت یادداشت پیگیری برای یک تراکنش"""
    tx = Transaction.query.get_or_404(tx_id)
    tx.follow_up_note = request.form.get('follow_up_note')
    db.session.commit()
    # استفاده از _anchor برای بازگشت دقیق به تب ریزتراکنش‌ها
    flash('یادداشت پیگیری بروزرسانی شد.', 'success')
    return redirect(url_for('finance.contact_profile', id=tx.contact_id, _anchor='ledger'))

@finance_bp.route('/api/sensors/update', methods=['POST'])
@require_api_token
def update_sensors():
    """دریافت داده‌های زنده از سخت‌افزار ESP32 و ذخیره در دیتابیس"""

    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON data provided"}), 400
    
    pen_id = data.get('pen_id')
    temp = data.get('temperature')
    hum = data.get('humidity')
    
    if pen_id is None or temp is None or hum is None:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400
        
    try:
        new_reading = SensorData(
            pen_id=int(pen_id),
            temperature=float(temp),
            humidity=float(hum),
            recorded_at=datetime.now(UTC)
        )
        db.session.add(new_reading)
        db.session.commit()
        return jsonify({"status": "success", "recorded_id": new_reading.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@finance_bp.route('/api/iot/weight', methods=['POST'])
@require_api_token
def update_weight_iot():
    """دریافت وزن از باسکول هوشمند و بروزرسانی پرونده دام"""
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
    ear_tag = data.get('ear_tag')
    weight = data.get('weight')
    
    if not ear_tag or weight is None:
        return jsonify({"status": "error", "message": "Missing ear_tag or weight"}), 400
        
    sheep = Sheep.query.filter_by(ear_tag=str(ear_tag).strip()).first()
    if not sheep:
        return jsonify({"status": "error", "message": f"Sheep with tag {ear_tag} not found"}), 404
        
    try:
        new_weight = float(weight)
        sheep.weight = new_weight
        
        # ثبت در تاریخچه وزن کشی
        db.session.add(WeightRecord(
            sheep_id=sheep.id, 
            weight=new_weight, 
            notes="ثبت خودکار (باسکول دیجیتال API)",
            record_date=datetime.now(UTC).date()
        ))
        
        db.session.commit()
        return jsonify({"status": "success", "ear_tag": sheep.ear_tag, "new_weight": new_weight}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500