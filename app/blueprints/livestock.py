from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify, current_app
from werkzeug.utils import secure_filename
from app import db
from sqlalchemy import func, case
from app.models import Sheep, WeightRecord, MedicalRecord, MedicalPhoto, BirthRecord, FeedRation, Pen, TreatmentTemplate, Medicine, BreedCategory, PurposeCategory, StatusCategory, Transaction, TransactionCategory, AuditLog
from datetime import datetime, timedelta, UTC
from app.accounting_engine import AccountingEngine
import qrcode
import jdatetime
import os
import csv
import io
import xlsxwriter
import time
import random
from flask_login import current_user, login_required
from app.blueprints.dashboard import get_setting

livestock_bp = Blueprint('livestock', __name__)

def parse_smart_date(date_str, default=None):
    """پشتیبانی از تاریخ شمسی و میلادی در بک‌اند (مستقل از JS فرانت)"""
    if not date_str or str(date_str).strip() in ['', 'None']:
        return default
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    english_digits = '0123456789'
    translation_table = str.maketrans(persian_digits + arabic_digits, english_digits + english_digits)
    date_str = str(date_str).translate(translation_table).replace('/', '-').strip()
    try:
        if date_str.startswith(('13', '14')):
            p = date_str.split('-')
            return jdatetime.date(int(p[0]), int(p[1]), int(p[2])).togregorian()
        return datetime.strptime(date_str[:10], '%Y-%m-%d').date()
    except Exception:
        return default

def log_audit(action):
    try:
        user = current_user.name if current_user.is_authenticated else "سیستم/ناشناس"
        ip = request.remote_addr
        from app.models import AuditLog
        db.session.add(AuditLog(user_name=user, action=action, ip_address=ip))
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Audit log failed: {e}")

@livestock_bp.route('/')
@login_required
def index():
    today = datetime.now(UTC).date()
    maturity_days = int(get_setting('maturity_days', 240))
    maturity_date = today - timedelta(days=maturity_days)
    lambs_to_update = Sheep.query.filter(
        Sheep.gender.in_(['بره ماده', 'بره نر', 'نامشخص']),
        Sheep.birth_date <= maturity_date
    ).all()
    if lambs_to_update:
        for lamb in lambs_to_update:
            if 'ماده' in lamb.gender:
                lamb.gender = 'میش'
            else:
                lamb.gender = 'قوچ'
        db.session.commit()
    
    rations = FeedRation.query.all()
    pens = Pen.query.all()
    breeds = BreedCategory.query.all()
    statuses = StatusCategory.query.all()
    
    from sqlalchemy import func
    total_sheep = Sheep.query.filter(Sheep.is_deleted == False, Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).count()
    sick_count = Sheep.query.filter_by(status='بیمار').count()
    pregnant_count = Sheep.query.filter_by(status='آبستن').count()
    total_live_weight = db.session.query(func.sum(Sheep.weight)).filter(Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).scalar() or 0.0

    query = Sheep.query.filter(Sheep.is_deleted == False)
    search_q = request.args.get('search', '').strip()
    gender_q = request.args.get('gender', 'همه')
    breed_q = request.args.get('breed', 'همه')
    status_q = request.args.get('status', 'فعال')
    min_w = request.args.get('min_weight', type=float)
    max_w = request.args.get('max_weight', type=float)
    starred_q = request.args.get('starred')

    if search_q: query = query.filter(Sheep.ear_tag.ilike(f"%{search_q}%"))
    if gender_q != 'همه': query = query.filter(Sheep.gender == gender_q)
    if breed_q != 'همه': query = query.filter(Sheep.breed == breed_q)
    if status_q == 'فعال': query = query.filter(Sheep.status.notin_(['فروخته شده', 'تلف شده', 'مرده']))
    elif status_q == 'بایگانی': query = query.filter(Sheep.status.in_(['فروخته شده', 'تلف شده', 'مرده']))
    elif status_q != 'همه': query = query.filter(Sheep.status == status_q)
    if min_w is not None: query = query.filter(Sheep.weight >= min_w)
    if max_w is not None: query = query.filter(Sheep.weight <= max_w)
    if starred_q == '1': query = query.filter(Sheep.is_starred.is_(True))

    page = request.args.get('page', 1, type=int)
    page_size = int(get_setting('page_size', 50))
    sheeps_pagination = query.order_by(Sheep.id.desc()).paginate(page=page, per_page=page_size)

    return render_template('livestock/index.html', 
                           sheeps=sheeps_pagination, rations=rations, pens=pens, breeds=breeds, statuses=statuses,
                           total_sheep=total_sheep, sick_count=sick_count, pregnant_count=pregnant_count, total_live_weight=total_live_weight,
                           current_search=search_q, current_gender=gender_q, current_breed=breed_q, current_status=status_q, 
                           current_min_w=min_w, current_max_w=max_w, current_starred=starred_q)

@livestock_bp.route('/export')
@login_required
def export_sheep():
    query = Sheep.query.filter(Sheep.is_deleted == False)
    search_q = request.args.get('search', '').strip()
    gender_q = request.args.get('gender', 'همه')
    breed_q = request.args.get('breed', 'همه')
    status_q = request.args.get('status', 'فعال')
    min_w = request.args.get('min_weight', type=float)
    max_w = request.args.get('max_weight', type=float)
    starred_q = request.args.get('starred')
    pen_id_q = request.args.get('pen_id', type=int)
    if pen_id_q: query = query.filter(Sheep.pen_id == pen_id_q)
    if search_q: query = query.filter(Sheep.ear_tag.ilike(f"%{search_q}%"))
    if gender_q != 'همه': query = query.filter(Sheep.gender == gender_q)
    if breed_q != 'همه': query = query.filter(Sheep.breed == breed_q)
    if status_q == 'فعال': query = query.filter(Sheep.status.notin_(['فروخته شده', 'تلف شده', 'مرده']))
    elif status_q == 'بایگانی': query = query.filter(Sheep.status.in_(['فروخته شده', 'تلف شده', 'مرده']))
    elif status_q != 'همه': query = query.filter(Sheep.status == status_q)
    if min_w is not None: query = query.filter(Sheep.weight >= min_w)
    if max_w is not None: query = query.filter(Sheep.weight <= max_w)
    if starred_q == '1': query = query.filter(Sheep.is_starred.is_(True))

    sheeps = query.all()

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()
    worksheet.right_to_left()

    headers = ['پلاک', 'نژاد', 'جنسیت', 'وزن (kg)', 'وضعیت', 'هدف', 'جیره', 'بهاربند']
    header_format = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1})
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)

    for row, s in enumerate(sheeps, 1):
        worksheet.write(row, 0, s.ear_tag)
        worksheet.write(row, 1, s.breed or '-')
        worksheet.write(row, 2, s.gender)
        worksheet.write(row, 3, s.weight)
        worksheet.write(row, 4, s.status)
        worksheet.write(row, 5, s.purpose or '-')
        worksheet.write(row, 6, s.ration.name if s.ration else 'ندارد')
        worksheet.write(row, 7, s.pen.name if s.pen else 'نامشخص')

    workbook.close()
    output.seek(0)

    return Response(
        output.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=livestock_export.xlsx"}
    )

@livestock_bp.route('/print')
@login_required
def print_sheep():
    query = Sheep.query.filter(Sheep.is_deleted == False)
    search_q = request.args.get('search', '').strip()
    gender_q = request.args.get('gender', 'همه')
    breed_q = request.args.get('breed', 'همه')
    status_q = request.args.get('status', 'فعال')
    starred_q = request.args.get('starred')
    min_w = request.args.get('min_weight', type=float)
    max_w = request.args.get('max_weight', type=float)
    pen_id_q = request.args.get('pen_id', type=int)
    if pen_id_q: query = query.filter(Sheep.pen_id == pen_id_q)
    if search_q: query = query.filter(Sheep.ear_tag.ilike(f"%{search_q}%"))
    if gender_q != 'همه': query = query.filter(Sheep.gender == gender_q)
    if breed_q != 'همه': query = query.filter(Sheep.breed == breed_q)
    if status_q == 'فعال': query = query.filter(Sheep.status.notin_(['فروخته شده', 'تلف شده', 'مرده']))
    elif status_q == 'بایگانی': query = query.filter(Sheep.status.in_(['فروخته شده', 'تلف شده', 'مرده']))
    elif status_q != 'همه': query = query.filter(Sheep.status == status_q)
    if min_w is not None: query = query.filter(Sheep.weight >= min_w)
    if max_w is not None: query = query.filter(Sheep.weight <= max_w)
    if starred_q == '1': query = query.filter(Sheep.is_starred.is_(True))

    sheeps = query.all()
    today_date = datetime.now(UTC).date()
    return render_template('livestock/print.html', sheeps=sheeps, today_date=today_date)


@livestock_bp.route('/quick_weight', methods=['POST'])
@login_required
def quick_weight():
    sheep = Sheep.query.filter_by(ear_tag=request.form.get('ear_tag').strip()).first()
    if sheep:
        new_weight = Decimal(request.form.get('weight') or '0')
        sheep.weight = new_weight
        db.session.add(WeightRecord(sheep_id=sheep.id, weight=new_weight, notes="ثبت سریع"))
        db.session.commit()
    return redirect(url_for('livestock.index'))

@livestock_bp.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    sheep_ids = request.form.getlist('sheep_ids')
    action_type = request.form.get('bulk_action_type')

    if sheep_ids:
        with db.session.begin_nested():
            if action_type == 'change_status':
                new_status = request.form.get('new_status')
                # بروزرسانی وضعیت دام‌ها
                Sheep.query.filter(Sheep.id.in_(sheep_ids)).update({Sheep.status: new_status}, synchronize_session=False)

                if new_status == 'فروخته شده':
                    bulk_sale_price = request.form.get('bulk_sale_price', '0').replace(',', '').strip()
                    bulk_sale_date = request.form.get('bulk_sale_date')
                    sale_price = Decimal(bulk_sale_price) if bulk_sale_price else Decimal('0')
                    sale_date = parse_smart_date(bulk_sale_date, datetime.now(UTC).date())

                    selected_sheeps = Sheep.query.filter(Sheep.id.in_(sheep_ids)).all()
                    transaction_count = 0

                    for sheep in selected_sheeps:
                        sheep.sale_price = sale_price
                        sheep.sale_date = sale_date
                        if sale_price > 0:
                            # جلوگیری از ثبت فاکتور تکراری برای یک پلاک
                            existing_tx = Transaction.query.filter(Transaction.description.ilike(f"%پلاک: {sheep.ear_tag}%"), Transaction.category == 'فروش دام').first()
                            if not existing_tx:
                                from app.models import BuyerCategory
                                buyer_name = 'فروش گروهی'
                                if sheep.buyer_category_id:
                                    bc = db.session.get(BuyerCategory, sheep.buyer_category_id)
                                    if bc: buyer_name = bc.name

                                new_tx = Transaction(
                                    t_type='درآمد', category='فروش دام', amount=sale_price, t_date=sale_date,
                                    is_archived=False, party_name=buyer_name,
                                    description=f"فروش سیستمی - پلاک: {sheep.ear_tag} - خریدار: {sheep.buyer_category.name if sheep.buyer_category else 'نامشخص'}"
                                )
                                db.session.add(new_tx)
                                db.session.flush()
                                AccountingEngine.record_sale(new_tx, include_vat=True)
                                transaction_count += 1

                    if transaction_count > 0:
                        flash(f'✅ {transaction_count} فاکتور فروش صادر و ثبت شد.', 'success')

            elif action_type == 'change_ration':
                Sheep.query.filter(Sheep.id.in_(sheep_ids)).update({Sheep.feed_ration_id: request.form.get('new_ration_id')}, synchronize_session=False)
            
            elif action_type == 'change_pen':
                Sheep.query.filter(Sheep.id.in_(sheep_ids)).update({Sheep.pen_id: request.form.get('new_pen_id')}, synchronize_session=False)

        db.session.commit()
        log_audit(f"عملیات گروهی {action_type} روی {len(sheep_ids)} دام")
        flash('عملیات گروهی با موفقیت انجام شد.', 'success')

    return redirect(url_for('livestock.index'))

@livestock_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_sheep():
    if request.method == 'POST':
        ear_tag = request.form.get('ear_tag').strip()
        
        # ---> رفع باگ: بازگشت به صفحه ثبت و نمایش هشدار پلاک تکراری <---
        if Sheep.query.filter_by(ear_tag=ear_tag).first():
            flash(f'خطا! پلاک {ear_tag} قبلاً در سیستم ثبت شده است.', 'danger')
            return redirect(url_for('livestock.add_sheep'))
            
        weight = Decimal(request.form.get('weight') or '0')
        purchase_price = request.form.get('purchase_price')
        b_date_str = request.form.get('birth_date')
        
        qr = qrcode.make(f"پلاک: {ear_tag}")
        upload_dir = os.path.join('app', 'static', 'uploads', 'qrcodes')
        os.makedirs(upload_dir, exist_ok=True)
        qr_path = f"uploads/qrcodes/qr_{ear_tag}.png"
        qr.save(os.path.join('app', 'static', qr_path))

        new_sheep = Sheep(
            ear_tag=ear_tag, breed=request.form.get('breed'), gender=request.form.get('gender'), 
            weight=weight, purpose=request.form.get('purpose'), status=request.form.get('status'),
            feed_ration_id=request.form.get('feed_ration_id') or None, pen_id=request.form.get('pen_id') or None, 
            birth_date=parse_smart_date(b_date_str),
            qr_code_path=qr_path, purchase_price=Decimal(purchase_price or '0')
        )
        db.session.add(new_sheep)
        db.session.commit()
        if weight > 0: db.session.add(WeightRecord(sheep_id=new_sheep.id, weight=weight, notes="وزن اولیه"))
        db.session.commit()
        flash('دام جدید با موفقیت ثبت شد.', 'success')
        return redirect(url_for('livestock.index'))
    return render_template('livestock/add.html', rations=FeedRation.query.all(), pens=Pen.query.all(), breeds=BreedCategory.query.all(), purposes=PurposeCategory.query.all(), statuses=StatusCategory.query.all())

@livestock_bp.route('/profile/<int:id>')
@login_required
def profile(id):
    today = datetime.now(UTC).date()
    sheep = Sheep.query.get_or_404(id)
    weight_history = WeightRecord.query.filter_by(sheep_id=id).order_by(WeightRecord.record_date.asc()).all()
    medical_history = MedicalRecord.query.filter_by(sheep_id=id).order_by(MedicalRecord.record_date.desc()).all()
    birth_history = BirthRecord.query.filter_by(mother_id=id).order_by(BirthRecord.birth_date.desc()).all()
    
    chart_labels = [w.record_date.strftime('%Y-%m-%d') for w in weight_history]
    chart_data = [w.weight for w in weight_history]
    
    adg, days_to_target = 0, None
    if len(weight_history) >= 2:
        w1, w2 = weight_history[-2], weight_history[-1]
        days = (w2.record_date - w1.record_date).days
        if days > 0: 
            adg = (w2.weight - w1.weight) / days * 1000
            if sheep.target_weight and adg > 0 and sheep.weight < sheep.target_weight:
                days_to_target = int((sheep.target_weight - sheep.weight) / (adg / 1000))
            
    next_heat_date = sheep.last_heat_date + timedelta(days=17) if sheep.gender == 'میش' and sheep.last_heat_date else None
            
    total_lambs_born = sum(b.lambs_count for b in birth_history)
    successful_lambs = sum(b.lambs_count for b in birth_history if b.status == 'موفق')
    dead_lambs = total_lambs_born - successful_lambs
    twins_count = sum(1 for b in birth_history if b.lambs_count >= 2)
    
    birth_stats = {'تک‌قلو': 0, 'دوقلو': 0, 'سه‌قلو و بیشتر': 0, 'مرده‌زایی/سقط': 0}
    for b in birth_history:
        if b.status != 'موفق': birth_stats['مرده‌زایی/سقط'] += 1
        else:
            if b.lambs_count == 1: birth_stats['تک‌قلو'] += 1
            elif b.lambs_count == 2: birth_stats['دوقلو'] += 1
            else: birth_stats['سه‌قلو و بیشتر'] += 1
            
    offsprings = Sheep.query.filter_by(mother_id=id).all()
    age_in_months = int((datetime.now(UTC).date() - sheep.birth_date).days / 30) if sheep.birth_date else 0

    mother = Sheep.query.get(sheep.mother_id) if sheep.mother_id else None
    father = Sheep.query.get(sheep.father_id) if sheep.father_id else None

    # --- محاسبات اقتصادی و هشدارهای هوشمند (رفع نقص متغیرهای قالب) ---
    birth_weight = float(get_setting('birth_weight', 3.5))
    weight_gained = float(sheep.weight or 0) - birth_weight
    days_alive = max((today - (sheep.birth_date or sheep.entry_date.date())).days, 1)
    daily_feed_cost = float(sheep.ration.daily_cost or 0) if sheep.ration else 0.0
    estimated_feed_cost = days_alive * daily_feed_cost
    
    # محاسبه بهای هر کیلو رشد (FCR Cost)
    fcr_cost = estimated_feed_cost / weight_gained if weight_gained > 0 else 0
    
    smart_alerts = []
    if adg < 0: 
        smart_alerts.append(f"🔴 هشدار بحرانی: این دام در بازه اخیر {abs(adg):.0f} گرم کاهش وزن روزانه داشته است!")
    
    # بررسی پرهیز دارویی
    for med in medical_history:
        if med.withdrawal_end_date and med.withdrawal_end_date > today:
            smart_alerts.append(f"⚠️ پرهیز دارویی: ذبح یا مصرف شیر تا {med.withdrawal_end_date} ممنوع است ({med.medicine_name}).")

    # استخراج تاریخچه تغییرات مخصوص این دام (Audit Trail)
    # اصلاح باگ target_id: جستجو بر اساس شماره پلاک در متن عملیات
    audit_history = AuditLog.query.filter(
        AuditLog.action.ilike(f"%{sheep.ear_tag}%")
    ).order_by(AuditLog.timestamp.desc()).all()

    timeline_events = []
    if sheep.birth_date: timeline_events.append({'date': sheep.birth_date, 'title': 'تولد', 'desc': 'تولد دام', 'icon': 'fa-baby', 'color': 'success'})
    elif sheep.entry_date: timeline_events.append({'date': sheep.entry_date.date(), 'title': 'ورود به گله', 'desc': 'ثبت اولیه', 'icon': 'fa-right-to-bracket', 'color': 'primary'})
    for w in weight_history: timeline_events.append({'date': w.record_date, 'title': f'وزن ({w.weight} کیلو)', 'desc': w.notes or 'ثبت روتین', 'icon': 'fa-weight-scale', 'color': 'info'})
    for m in medical_history: timeline_events.append({'date': m.record_date, 'title': f'درمان ({m.action_type})', 'desc': f"{m.medicine_name} - {m.notes or ''}", 'icon': 'fa-syringe', 'color': 'danger', 'img': m.photos})
    for b in birth_history: timeline_events.append({'date': b.birth_date, 'title': f'زایش ({b.lambs_count} بره)', 'desc': b.status, 'icon': 'fa-child', 'color': 'warning'})
    timeline_events.sort(key=lambda x: x['date'], reverse=True)

    from app.models import Medicine, BreedCategory, PurposeCategory, StatusCategory, BuyerCategory
    return render_template('livestock/profile.html', 
                           sheep=sheep, chart_labels=chart_labels, chart_data=chart_data, adg=adg,
                           medical_history=medical_history, birth_history=birth_history, timeline_events=timeline_events,
                           total_lambs=total_lambs_born, successful_lambs=successful_lambs, dead_lambs=dead_lambs, twins_count=twins_count,
                           birth_stats=birth_stats, offsprings=offsprings, fcr_cost=fcr_cost,
                           estimated_feed_cost=estimated_feed_cost, smart_alerts=smart_alerts, age_in_months=age_in_months,
                           days_to_target=days_to_target, next_heat_date=next_heat_date,
                           rams=Sheep.query.filter_by(gender='قوچ').all(), rations=FeedRation.query.all(),
                           pens=Pen.query.all(), medicines=Medicine.query.all(), breeds=BreedCategory.query.all(),
                           audit_history=audit_history,
                           purposes=PurposeCategory.query.all(), statuses=StatusCategory.query.all(),
                           buyer_categories=BuyerCategory.query.all(),
                           mother=mother, father=father, today_str=today.strftime('%Y-%m-%d'))

@livestock_bp.route('/edit/<int:id>', methods=['POST'])
@login_required
def edit_sheep(id):
    sheep = Sheep.query.get_or_404(id)
    sheep.ear_tag = request.form.get('ear_tag', sheep.ear_tag)
    sheep.breed = request.form.get('breed', sheep.breed)
    sheep.gender = request.form.get('gender', sheep.gender)
    sheep.purpose = request.form.get('purpose', sheep.purpose)
    sheep.status = request.form.get('status', sheep.status)
    sheep.death_reason = request.form.get('death_reason') if sheep.status in ['تلف شده', 'مرده'] else None
    sheep.feed_ration_id = request.form.get('feed_ration_id') or None
    sheep.pen_id = request.form.get('pen_id') or None
    
    t_weight = request.form.get('target_weight')
    sheep.target_weight = Decimal(t_weight) if t_weight else None
    
    heat_str = request.form.get('last_heat_date')
    sheep.last_heat_date = parse_smart_date(heat_str)

    with db.session.begin_nested():
        # منطق ثبت خودکار فاکتور فروش در دفتر کل
        if sheep.status == 'فروخته شده':
            raw_price = request.form.get('sale_price', '0').replace(',', '').strip()
            try:
                sheep.sale_price = Decimal(raw_price) if raw_price else Decimal('0')
            except ValueError:
                sheep.sale_price = Decimal('0')

            s_date_str = request.form.get('sale_date')
            try:
                sheep.sale_date = parse_smart_date(s_date_str, datetime.now(UTC).date())
            except ValueError:
                sheep.sale_date = datetime.now(UTC).date()

            buyer_cat_id = request.form.get('buyer_category_id')
            sheep.buyer_category_id = int(buyer_cat_id) if (buyer_cat_id and buyer_cat_id.isdigit()) else None
            db.session.flush()
            
            if sheep.sale_price > 0:
                from app.models import BuyerCategory
                buyer_name = 'فروش نقدی'
                if sheep.buyer_category_id:
                    bc = db.session.get(BuyerCategory, sheep.buyer_category_id)
                    if bc: buyer_name = bc.name

                # بهبود شناسایی فاکتور با تطبیق دقیق شرح
                search_desc = f"فروش سیستمی - پلاک: {sheep.ear_tag}"
                existing_tx = Transaction.query.filter(
                    Transaction.description.ilike(f"{search_desc}%"),
                    Transaction.category == 'فروش دام'
                ).first()

                if not existing_tx:
                    new_tx = Transaction(
                        t_type='درآمد',
                        category='فروش دام',
                        amount=sheep.sale_price,
                        t_date=sheep.sale_date,
                        is_archived=False,
                        party_name=buyer_name,
                        description=f"فروش سیستمی - پلاک: {sheep.ear_tag} - خریدار: {sheep.buyer_category.name if sheep.buyer_category else 'نامشخص'}"
                    )
                    db.session.add(new_tx)
                    db.session.flush()
                    AccountingEngine.record_sale(new_tx, include_vat=True)
                    flash(f'✅ فروش دام (پلاک {sheep.ear_tag}) ثبت شد.', 'success')
                else:
                    existing_tx.amount = sheep.sale_price
                    existing_tx.t_date = sheep.sale_date
                    existing_tx.party_name = buyer_name
                    flash(f'ℹ️ فاکتور قبلی پلاک {sheep.ear_tag} بروز شد.', 'info')

            s_weight = request.form.get('sale_weight')
            if s_weight:
                sheep.weight = Decimal(s_weight)
                db.session.add(WeightRecord(sheep_id=sheep.id, weight=Decimal(s_weight), notes="وزن زمان فروش"))
        else:
            # سناریوی حیاتی: اگر دام قبلاً فروخته شده بود و حالا وضعیت تغییر کرد، فاکتور ابطال شود
            search_desc = f"فروش سیستمی - پلاک: {sheep.ear_tag}"
            old_tx = Transaction.query.filter(
                Transaction.description.ilike(f"{search_desc}%"),
                Transaction.category == 'فروش دام',
                Transaction.is_deleted == False
            ).first()
            if old_tx:
                old_tx.is_deleted = True
                flash(f'فاکتور فروش قبلی پلاک {sheep.ear_tag} به دلیل تغییر وضعیت دام ابطال شد.', 'info')

            sheep.sale_price = 0.0
            sheep.sale_date = None
     
    # ثبت سند حسابداری تلفات دام (کاهش دارایی زیستی)
    old_status = Sheep.query.filter_by(id=sheep.id).with_for_update().first().status if hasattr(sheep, 'id') and sheep.id else sheep.status
    if sheep.status in ['تلف شده', 'مرده'] and old_status not in ['تلف شده', 'مرده', 'فروخته شده']:
        from app.accounting_engine import AccountingEngine
        from app.models import JournalEntry, JournalEntryLine, Account
        loss_value = sheep.purchase_price or (sheep.weight * 50000 if sheep.weight else 500000)
        acc_expense = Account.query.filter_by(code='5010').first()
        acc_asset = Account.query.filter_by(code='1200').first()
        if acc_expense and acc_asset:
            entry = JournalEntry(
                entry_number=AccountingEngine.generate_entry_number(),
                date=datetime.now(UTC).date(),
                description=f"تلفات دام - پلاک {sheep.ear_tag} - {sheep.death_reason or 'نامشخص'}"
            )
            db.session.add(entry)
            db.session.flush()
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=loss_value, credit=0.0, description=f"هزینه تلفات دام پلاک {sheep.ear_tag}"))
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_asset.id, debit=0.0, credit=loss_value, description=f"کاهش دارایی زیستی - پلاک {sheep.ear_tag}"))

    log_audit(f"ویرایش اطلاعات پروفایل دام پلاک {sheep.ear_tag}") 
    db.session.commit()
    return redirect(url_for('livestock.profile', id=id))

@livestock_bp.route('/add_weight/<int:id>', methods=['POST'])
@login_required
def add_weight(id):
    sheep = Sheep.query.get_or_404(id)
    new_weight = float(request.form.get('weight'))
    date_str = request.form.get('record_date')
    r_date = parse_smart_date(date_str, datetime.now(UTC).date())
    
    # دریافت نمره BCS
    bcs_val = request.form.get('bcs')
    bcs = float(bcs_val) if bcs_val else None
    
    sheep.weight = new_weight
    db.session.add(WeightRecord(sheep_id=id, weight=new_weight, bcs=bcs, notes=request.form.get('notes'), record_date=r_date))
    db.session.commit()
    
    # اعمال اتوماتیک تغییر جیره اگر دام لاغر است (BCS زیر 2.5)
    if bcs and bcs <= 2.5 and sheep.status != 'بیمار':
        flash('هشدار: نمره وضعیت بدنی (BCS) دام پایین است. سیستم پیشنهاد می‌کند جیره پرانرژی (پرواری) به این دام اختصاص دهید.', 'warning')
        
    return redirect(url_for('livestock.profile', id=id))

@livestock_bp.route('/add_medical/<int:id>', methods=['POST'])
@login_required
def add_medical(id):
    r_date = parse_smart_date(request.form.get('record_date'), datetime.now(UTC).date())
    n_date = parse_smart_date(request.form.get('next_date'))
    w_date = parse_smart_date(request.form.get('withdrawal_end_date'))
    
    action_type = request.form.get('action_type', 'درمان') 
    record = MedicalRecord(
        sheep_id=id, action_type=action_type, 
        medicine_name=request.form.get('medicine_name', 'نامشخص'), 
        notes=request.form.get('notes'), record_date=r_date, 
        next_date=n_date, withdrawal_end_date=w_date
    )
    db.session.add(record)
    db.session.commit()
    
    photos = request.files.getlist('photos')
    upload_folder = os.path.join('app', 'static', 'uploads', 'medical')
    os.makedirs(upload_folder, exist_ok=True)
    for photo in photos:
        if photo and photo.filename != '':
            filename = f"{int(time.time())}_{secure_filename(photo.filename)}"
            photo.save(os.path.join(upload_folder, filename))
            db.session.add(MedicalPhoto(medical_record_id=record.id, image_path=f"uploads/medical/{filename}"))
    db.session.commit()
    return redirect(url_for('livestock.profile', id=id))

@livestock_bp.route('/add_birth/<int:id>', methods=['POST'])
@login_required
def add_birth(id):
    r_date = parse_smart_date(request.form.get('record_date'), datetime.now(UTC).date())
    father_id = request.form.get('father_id')
    lambs_count = int(request.form.get('lambs_count', 1))
    status = request.form.get('status', 'موفق')
    
    db.session.add(BirthRecord(mother_id=id, father_id=father_id or None, lambs_count=lambs_count, status=status, notes=request.form.get('notes'), birth_date=r_date))
    db.session.commit()
    
    if status == 'موفق':
        mother = Sheep.query.get(id)
        b_weight = float(get_setting('birth_weight', 3.5))
        lamb_value = Decimal(str(get_setting('market_price', '0'))) * Decimal(str(b_weight)) if get_setting('market_price', '0') != '0' else Decimal('500000')
        from app.models import JournalEntry, JournalEntryLine, Account
        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=r_date,
            description=f"زایش دام - پلاک مادر: {mother.ear_tag} - تعداد بره: {lambs_count}"
        )
        db.session.add(entry)
        db.session.flush()
        acc_asset = Account.query.filter_by(code='1200').first()
        acc_income = Account.query.filter_by(code='4010').first()
        if acc_asset and acc_income:
            for i in range(lambs_count):
                tag = f"LMB-{mother.ear_tag}-{random.randint(100, 9999)}"
                db.session.add(Sheep(ear_tag=tag, breed=mother.breed, gender="نامشخص", weight=b_weight, status="زنده و سالم", purpose="پرواربندی", birth_date=r_date, mother_id=mother.id, father_id=father_id or None))
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_asset.id, debit=lamb_value * lambs_count, credit=0.0, description=f"افزایش دارایی زیستی - {lambs_count} راس بره متولد شده از {mother.ear_tag}"))
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_income.id, debit=0.0, credit=lamb_value * lambs_count, description=f"درآمد حاصل از زایش - {lambs_count} راس بره"))
        else:
            for i in range(lambs_count):
                tag = f"LMB-{mother.ear_tag}-{random.randint(100, 9999)}"
                db.session.add(Sheep(ear_tag=tag, breed=mother.breed, gender="نامشخص", weight=b_weight, status="زنده و سالم", purpose="پرواربندی", birth_date=r_date, mother_id=mother.id, father_id=father_id or None))
        db.session.commit()
    return redirect(url_for('livestock.profile', id=id))

@livestock_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_sheep(id):
    sheep = Sheep.query.get_or_404(id)
    sheep.is_deleted = True
    sheep.status = 'حذف شده'
    db.session.commit()
    flash(f'دام پلاک {sheep.ear_tag} از لیست خارج شد.', 'warning')
    return redirect(url_for('livestock.index'))

@livestock_bp.route('/vet_queue')
@login_required
def vet_queue():
    today = datetime.now(UTC).date()
    today = datetime.now(UTC).date()
    sick_sheep = Sheep.query.filter_by(status='بیمار').all()
    due_meds = MedicalRecord.query.filter(MedicalRecord.next_date != None, MedicalRecord.next_date <= today).all()
    due_ids = [m.sheep_id for m in due_meds]
    med_sheep = Sheep.query.filter(Sheep.id.in_(due_ids)).all() if due_ids else []
    newborns = [s for s in Sheep.query.filter(Sheep.birth_date >= today - timedelta(days=7)).all() if not MedicalRecord.query.filter_by(sheep_id=s.id, medicine_name="چکاپ سلامت نوزاد").first()]
    return render_template('livestock/vet_queue.html', sick_sheep=sick_sheep, med_sheep=med_sheep, newborns=newborns, templates=TreatmentTemplate.query.all(), today=today)

@livestock_bp.route('/apply_protocol/<int:id>', methods=['POST'])
@login_required
def apply_protocol(id):
    template = TreatmentTemplate.query.get_or_404(request.form.get('template_id'))
    today = datetime.now(UTC).date()
    for med in template.medicines.split(','):
        db.session.add(MedicalRecord(sheep_id=id, action_type="پروتکل", medicine_name=med.strip(), record_date=today, operator="سیستم", notes=f"پروتکل: {template.name}"))
    sheep = Sheep.query.get(id)
    if sheep.status == 'بیمار': sheep.status = 'تحت درمان'
    db.session.commit()
    flash(f"پروتکل روی دام اعمال شد.", "success")
    return redirect(request.referrer)

@livestock_bp.route('/medical')
@login_required
def medical_overview():
    today = datetime.now(UTC).date()
    sick_sheep = Sheep.query.filter_by(status='بیمار').all()
    upcoming_meds = MedicalRecord.query.filter(MedicalRecord.next_date != None, MedicalRecord.next_date <= today + timedelta(days=7)).order_by(MedicalRecord.next_date.asc()).all()
    return render_template('livestock/medical.html', sick_sheep=sick_sheep, upcoming_meds=upcoming_meds, today=today)

@livestock_bp.route('/mark_healthy/<int:id>')
@login_required
def mark_healthy(id):
    sheep = Sheep.query.get_or_404(id)
    sheep.status = 'زنده و سالم'
    db.session.commit()
    flash(f"دام {sheep.ear_tag} ترخیص شد.", "success")
    return redirect(request.referrer)

@livestock_bp.route('/mark_med_done/<int:med_id>')
@login_required
def mark_med_done(med_id):
    old_med = MedicalRecord.query.get_or_404(med_id)
    db.session.add(MedicalRecord(sheep_id=old_med.sheep_id, action_type=old_med.action_type, medicine_name=old_med.medicine_name, record_date=datetime.now(UTC).date(), operator="سیستم", notes="تکرار نوبت قبلی انجام شد."))
    old_med.next_date = None
    db.session.commit()
    flash(f"داروی {old_med.medicine_name} ثبت شد و از صف حذف گردید.", "success")
    return redirect(request.referrer)

@livestock_bp.route('/mark_newborn_checked/<int:id>')
@login_required
def mark_newborn_checked(id):
    db.session.add(MedicalRecord(sheep_id=id, action_type="ویزیت", medicine_name="چکاپ سلامت نوزاد", record_date=datetime.now(UTC).date(), operator="سیستم", notes="ویزیت اولیه ثبت شد."))
    db.session.commit()
    flash("چکاپ نوزاد ثبت شد و از صف حذف گردید.", "success")
    return redirect(request.referrer)

@livestock_bp.route('/toggle_star/<int:id>', methods=['POST'])
@login_required
def toggle_star(id):
    sheep = Sheep.query.get_or_404(id)
    sheep.is_starred = not sheep.is_starred
    db.session.commit()
    return jsonify({'success': True, 'is_starred': sheep.is_starred})

@livestock_bp.route('/passport/<ear_tag>')
def public_passport(ear_tag):
    sheep = Sheep.query.filter_by(ear_tag=ear_tag).first_or_404()
    from app.models import SystemSetting
    # فقط تنظیمات غیرحساس برای نمایش عمومی
    safe_keys = ['farm_name', 'farm_logo_path', 'currency_unit']
    safe_settings = {}
    for key in safe_keys:
        s = SystemSetting.query.filter_by(key=key).first()
        if s: safe_settings[key] = s.value
    
    # محاسبه سن
    age = "نامشخص"
    if sheep.birth_date:
        age_days = (datetime.now(UTC).date() - sheep.birth_date).days
        age = f"{age_days // 30} ماه"
        
    return render_template('livestock/passport.html', sheep=sheep, age=age, settings=safe_settings)


# ==========================================
# مانیتورینگ هوشمند و اینترنت اشیا (IoT) بهاربندها
# ==========================================
@livestock_bp.route('/pens')
@login_required
def pen_dashboard():
    from app.models import Pen, SensorData
    pens = Pen.query.all()
    selected_pen_id = request.args.get('pen_id', type=int)
    
    selected_pen = None
    stats = {'total': 0, 'avg_weight': 0.0, 'capacity': 0, 'fill_percentage': 0.0}
    sensor = None
    thi = 0
    thi_status = "نرمال"
    sheeps_pagination = None
    
    # متغیرهای فیلتر
    search_q = request.args.get('search', '').strip()
    gender_q = request.args.get('gender', 'همه')
    status_q = request.args.get('status', 'همه')
    starred_q = request.args.get('starred')
    min_w = request.args.get('min_weight', type=float)
    max_w = request.args.get('max_weight', type=float)
    
    if not selected_pen_id and pens:
        selected_pen_id = pens[0].id
        
    if selected_pen_id:
        selected_pen = Pen.query.get_or_404(selected_pen_id)
        
        # --- محاسبات آماری نمودارها (سریع) ---
        active_sheeps = [s for s in selected_pen.sheep_list if s.status not in ['تلف شده', 'مرده', 'فروخته شده']]
        stats['total'] = len(active_sheeps)
        total_weight = sum(s.weight for s in active_sheeps if s.weight)
        stats['avg_weight'] = (total_weight / stats['total']) if stats['total'] > 0 else 0
        stats['capacity'] = selected_pen.capacity
        stats['fill_percentage'] = (stats['total'] / stats['capacity'] * 100) if stats['capacity'] > 0 else 0
        
        stats['genders'], stats['breeds'], stats['statuses'] = {}, {}, {}
        for s in active_sheeps:
            g = 'بره' if 'بره' in s.gender else s.gender
            stats['genders'][g] = stats['genders'].get(g, 0) + 1
            breed = s.breed or 'نامشخص'
            stats['breeds'][breed] = stats['breeds'].get(breed, 0) + 1
            stats['statuses'][s.status] = stats['statuses'].get(s.status, 0) + 1
            
        # دیتای سنسور (IoT)
        sensor = SensorData.query.filter_by(pen_id=selected_pen.id).order_by(SensorData.recorded_at.desc()).first()

        if sensor:
            # شاخص THI
            t = sensor.temperature
            rh = sensor.humidity
            thi = (0.8 * t) + ((rh / 100) * (t - 14.4)) + 46.4
            if thi < 72: thi_status = "نرمال و راحت"
            elif thi < 78: thi_status = "تنش حرارتی خفیف"
            elif thi < 82: thi_status = "تنش شدید (خطر)"
            else: thi_status = "بحران گرمایی!"
        else:
            thi = 0
            thi_status = "بدون داده"

        # --- رفع کندی: سیستم فیلتر بک اند و صفحه بندی ---
        query = Sheep.query.filter_by(pen_id=selected_pen.id)
        if search_q: query = query.filter(Sheep.ear_tag.ilike(f"%{search_q}%"))
        if gender_q != 'همه': query = query.filter(Sheep.gender == gender_q)
        if status_q != 'همه': query = query.filter(Sheep.status == status_q)
        if starred_q == '1': query = query.filter(Sheep.is_starred.is_(True))
        if min_w is not None: query = query.filter(Sheep.weight >= min_w)
        if max_w is not None: query = query.filter(Sheep.weight <= max_w)
        
        page = request.args.get('page', 1, type=int)
        sheeps_pagination = query.order_by(Sheep.id.desc()).paginate(page=page, per_page=50)
            
    return render_template('livestock/pens.html', 
                           pens=pens, selected_pen=selected_pen, 
                           stats=stats, sensor=sensor, thi=thi, thi_status=thi_status, 
                           sheeps=sheeps_pagination,
                           current_search=search_q, current_gender=gender_q, 
                           current_status=status_q, current_starred=starred_q,
                           current_min_w=min_w, current_max_w=max_w)

@livestock_bp.route('/api/pen/<int:pen_id>/sensor')
@login_required
def get_pen_sensor_api(pen_id):
    """API مخصوص به‌روزرسانی خودکار کارت‌های سنسور در پس‌زمینه"""
    from app.models import SensorData
    sensor = SensorData.query.filter_by(pen_id=pen_id).order_by(SensorData.recorded_at.desc()).first()
    if not sensor:
        return jsonify({"status": "no_data"}), 200
    
    t = sensor.temperature
    rh = sensor.humidity
    thi = (0.8 * t) + ((rh / 100) * (t - 14.4)) + 46.4
    
    if thi < 72: thi_status = "نرمال و راحت"
    elif thi < 78: thi_status = "تنش حرارتی خفیف"
    elif thi < 82: thi_status = "تنش شدید (خطر)"
    else: thi_status = "بحران گرمایی!"
    
    return jsonify({
        "status": "success",
        "temperature": t,
        "humidity": rh,
        "thi": round(thi, 1),
        "thi_status": thi_status
    })

@livestock_bp.route('/maintenance/cleanup_weights', methods=['POST'])
@login_required
def cleanup_weights():
    """حذف رکوردهای وزن‌کشی قدیمی‌تر از ۲ سال جهت بهینه‌سازی دیتابیس"""
    if current_user.role != 'مدیر':
        flash('فقط مدیر کل دسترسی به عملیات نگهداری و سبک‌سازی دیتابیس دارد.', 'danger')
        return redirect(url_for('dashboard.index'))

    cutoff_date = datetime.now(UTC).date() - timedelta(days=730)
    deleted_count = WeightRecord.query.filter(WeightRecord.record_date < cutoff_date).delete()
    db.session.commit()

    flash(f'عملیات سبک‌سازی با موفقیت انجام شد. تعداد {deleted_count} رکورد وزن‌کشی قدیمی (بیش از ۲ سال) از سیستم حذف گردید.', 'success')
    return redirect(url_for('dashboard.settings'))