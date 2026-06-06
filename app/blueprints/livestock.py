from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify
from werkzeug.utils import secure_filename
from app import db
from sqlalchemy import func, case
from app.models import Sheep, WeightRecord, MedicalRecord, MedicalPhoto, BirthRecord, FeedRation, Pen, TreatmentTemplate, Medicine, BreedCategory, PurposeCategory, StatusCategory, Transaction, TransactionCategory
from datetime import datetime, timedelta, UTC # استفاده از UTC برای دقت بیشتر
from app.accounting_engine import AccountingEngine
import qrcode
import os
import csv
import io
import time
import random
from flask_login import current_user, login_required
from app.blueprints.dashboard import get_setting

livestock_bp = Blueprint('livestock', __name__)

def log_audit(action):
    try:
        user = current_user.name if current_user.is_authenticated else "سیستم/ناشناس"
        ip = request.remote_addr
        from app.models import AuditLog
        db.session.add(AuditLog(user_name=user, action=action, ip_address=ip))
        db.session.commit()
    except:
        pass

@livestock_bp.route('/')
def index():
    today = datetime.now(UTC).date()
    maturity_days = int(get_setting('maturity_days', 240))
    maturity_date = today - timedelta(days=maturity_days)
    lambs_to_update = Sheep.query.filter(Sheep.gender.like('%بره%'), Sheep.birth_date <= maturity_date).all()
    if lambs_to_update:
        for lamb in lambs_to_update:
            lamb.gender = 'میش' if 'ماده' in lamb.gender else 'قوچ'
        db.session.commit()
    
    rations = FeedRation.query.all()
    pens = Pen.query.all()
    breeds = BreedCategory.query.all()
    statuses = StatusCategory.query.all()
    
    from sqlalchemy import func
    total_sheep = Sheep.query.filter(Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).count()
    sick_count = Sheep.query.filter_by(status='بیمار').count()
    pregnant_count = Sheep.query.filter_by(status='آبستن').count()
    total_live_weight = db.session.query(func.sum(Sheep.weight)).filter(Sheep.status.notin_(['تلف شده', 'مرده', 'فروخته شده'])).scalar() or 0.0

    query = Sheep.query
    search_q = request.args.get('search', '').strip()
    gender_q = request.args.get('gender', 'همه')
    breed_q = request.args.get('breed', 'همه')
    status_q = request.args.get('status', 'فعال')
    min_w = request.args.get('min_weight', type=float)
    max_w = request.args.get('max_weight', type=float)
    starred_q = request.args.get('starred') # دریافت فیلتر ستاره دار

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
def export_sheep():
    query = Sheep.query
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
    
    # تکنیک جادویی تولید اکسل استایل دار و راست چین
    html_content = '<html dir="rtl"><head><meta charset="utf-8"><style>table {border-collapse: collapse; width: 100%;} th, td {border: 1px solid black; padding: 8px; text-align: center;} th {background-color: #f2f2f2; font-weight: bold;}</style></head><body>'
    html_content += '<table><thead><tr><th>پلاک</th><th>نژاد</th><th>جنسیت</th><th>وزن (kg)</th><th>وضعیت</th><th>هدف</th><th>جیره</th><th>بهاربند</th></tr></thead><tbody>'
    for s in sheeps:
        html_content += f"<tr><td>{s.ear_tag}</td><td>{s.breed or '-'}</td><td>{s.gender}</td><td>{s.weight}</td><td>{s.status}</td><td>{s.purpose or '-'}</td><td>{s.ration.name if s.ration else 'ندارد'}</td><td>{s.pen.name if s.pen else 'نامشخص'}</td></tr>"
    html_content += '</tbody></table></body></html>'
    
    response = Response(html_content, mimetype='application/vnd.ms-excel')
    response.headers['Content-Disposition'] = 'attachment; filename=livestock_filtered_export.xls'
    return response

@livestock_bp.route('/print')
def print_sheep():
    query = Sheep.query
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
def quick_weight():
    sheep = Sheep.query.filter_by(ear_tag=request.form.get('ear_tag').strip()).first()
    if sheep:
        new_weight = float(request.form.get('weight'))
        sheep.weight = new_weight
        db.session.add(WeightRecord(sheep_id=sheep.id, weight=new_weight, notes="ثبت سریع"))
        db.session.commit()
    return redirect(url_for('livestock.index'))

@livestock_bp.route('/bulk_action', methods=['POST'])
def bulk_action():
    sheep_ids = request.form.getlist('sheep_ids')
    action_type = request.form.get('bulk_action_type')
    if sheep_ids:
        if action_type == 'change_status':
            new_status = request.form.get('new_status')
            Sheep.query.filter(Sheep.id.in_(sheep_ids)).update({Sheep.status: new_status}, synchronize_session=False)
            db.session.commit()
            
            # اگر وضعیت جدید "فروخته شده" است، باید فاکتور خودکار ایجاد شود
            if new_status == 'فروخته شده':
                bulk_sale_price = request.form.get('bulk_sale_price', '0').replace(',', '').strip()
                bulk_sale_date = request.form.get('bulk_sale_date')
                
                try:
                    sale_price = float(bulk_sale_price) if bulk_sale_price else 0.0
                except ValueError:
                    sale_price = 0.0
                
                try:
                    sale_date = datetime.strptime(bulk_sale_date, '%Y-%m-%d').date() if bulk_sale_date else datetime.now(UTC).date()
                except (ValueError, TypeError):
                    sale_date = datetime.now(UTC).date()
                
                # دریافت تمام دام‌های انتخاب شده برای ایجاد فاکتورهای منفرد
                selected_sheeps = Sheep.query.filter(Sheep.id.in_(sheep_ids)).all()
                transaction_count = 0
                
                for sheep in selected_sheeps:
                    sheep.sale_price = sale_price
                    sheep.sale_date = sale_date
                    
                    if sale_price > 0:
                        # بررسی اینکه فاکتور قبلی وجود دارد یا نه
                        existing_tx = Transaction.query.filter(
                            Transaction.description.ilike(f"%پلاک: {sheep.ear_tag}%"),
                            Transaction.category == 'فروش دام'
                        ).first()
                        
                        if not existing_tx:
                            from app.models import BuyerCategory
                            buyer_name = 'فروش گروهی'
                            if sheep.buyer_category_id:
                                bc = db.session.get(BuyerCategory, sheep.buyer_category_id)
                                if bc: buyer_name = bc.name
                            
                            new_tx = Transaction(
                                t_type='درآمد',
                                category='فروش دام',
                                amount=sale_price,
                                t_date=sale_date,
                                is_archived=False,
                                party_name=buyer_name,
                                description=f"فروش سیستمی - پلاک: {sheep.ear_tag} - خریدار: {sheep.buyer_category.name if sheep.buyer_category else 'نامشخص'}"
                            )
                            db.session.add(new_tx)
                            db.session.flush()
                            
                            try:
                                AccountingEngine.record_sale(new_tx, include_vat=True)
                                db.session.commit()
                            except Exception as e:
                                print(f"خطا در ثبت حسابداری: {e}")
                                db.session.rollback()
                            
                            transaction_count += 1
                
                db.session.commit()
                
                if transaction_count > 0:
                    flash(f'✅ {transaction_count} فاکتور درآمد با موفقیت ایجاد و در دفتر کل ثبت شد.', 'success')
                else:
                    flash('⚠️ وضعیت دام‌ها به "فروخته شده" تغییر یافت ولی فاکتوری جدید ایجاد نشد (احتمالاً قبلاً ثبت شده بودند یا قیمت وارد نشده بود).', 'warning')
                
                log_audit(f"ثبت فروش گروهی برای {len(selected_sheeps)} رأس دام")
        
        elif action_type == 'change_ration':
            Sheep.query.filter(Sheep.id.in_(sheep_ids)).update({Sheep.feed_ration_id: request.form.get('new_ration_id')}, synchronize_session=False)
            db.session.commit()
        
        elif action_type == 'change_pen':
            Sheep.query.filter(Sheep.id.in_(sheep_ids)).update({Sheep.pen_id: request.form.get('new_pen_id')}, synchronize_session=False)
            db.session.commit()
    
    return redirect(url_for('livestock.index'))

@livestock_bp.route('/add', methods=['GET', 'POST'])
def add_sheep():
    if request.method == 'POST':
        ear_tag = request.form.get('ear_tag').strip()
        
        # ---> رفع باگ: بازگشت به صفحه ثبت و نمایش هشدار پلاک تکراری <---
        if Sheep.query.filter_by(ear_tag=ear_tag).first():
            flash(f'خطا! پلاک {ear_tag} قبلاً در سیستم ثبت شده است.', 'danger')
            return redirect(url_for('livestock.add_sheep'))
            
        weight = float(request.form.get('weight')) if request.form.get('weight') else 0.0
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
            birth_date=datetime.strptime(b_date_str, '%Y-%m-%d').date() if b_date_str else None,
            qr_code_path=qr_path, purchase_price=float(purchase_price) if purchase_price else 0.0
        )
        db.session.add(new_sheep)
        db.session.commit()
        if weight > 0: db.session.add(WeightRecord(sheep_id=new_sheep.id, weight=weight, notes="وزن اولیه"))
        db.session.commit()
        flash('دام جدید با موفقیت ثبت شد.', 'success')
        return redirect(url_for('livestock.index'))
    return render_template('livestock/add.html', rations=FeedRation.query.all(), pens=Pen.query.all(), breeds=BreedCategory.query.all(), purposes=PurposeCategory.query.all(), statuses=StatusCategory.query.all())

@livestock_bp.route('/profile/<int:id>')
def profile(id):
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
    
    days_alive = max((datetime.now(UTC).date() - (sheep.birth_date or sheep.entry_date.date())).days, 1)
    daily_feed_cost = sheep.ration.daily_cost if sheep.ration else 0
    estimated_feed_cost = days_alive * daily_feed_cost

    # ---> فاز 3: هوش مصنوعی نقطه سربه سر (Marginal Profit) و FCR <---
    fcr_cost = 0
    b_weight = float(get_setting('birth_weight', 3.5))
    weight_gained = (sheep.weight or 0) - b_weight
    if weight_gained > 0:
        fcr_cost = estimated_feed_cost / weight_gained # هزینه به ازای هر کیلوگرم رشد
        
    smart_alerts = []
    
    # الگوریتم سیگنال فروش
    market_price_per_kg = float(get_setting('market_price', 250000))
    daily_value_gain = (adg / 1000) * market_price_per_kg if adg > 0 else 0
    
    if sheep.purpose == 'پرواربندی' and sheep.status not in ['تلف شده', 'فروخته شده', 'مرده']:
        if daily_feed_cost > 0:
            if daily_value_gain < daily_feed_cost and adg > 0:
                smart_alerts.append(f"🔴 سیگنال فروش فوری: هزینه روزانه خوراک این دام ({daily_feed_cost:,.0f} ت) از ارزش رشد روزانه آن ({daily_value_gain:,.0f} ت) بیشتر شده است! نگهداری این دام ضررده است.")
            elif daily_value_gain < (daily_feed_cost * 1.2) and adg > 0:
                smart_alerts.append(f"🟠 هشدار سربه سر: رشد دام در حال توقف است. به زودی هزینه خوراک از سود رشد بیشتر خواهد شد.")

    if adg < 0: smart_alerts.append(f"🔴 هشدار بحرانی: کاهش وزن روزانه {abs(adg):.0f} گرم!")

    # هشدار هم خونی
    today = datetime.now(UTC).date()
    mother = Sheep.query.get(sheep.mother_id) if sheep.mother_id else None
    father = Sheep.query.get(sheep.father_id) if sheep.father_id else None
    if mother and father:
        if (mother.father_id and father.father_id and mother.father_id == father.father_id) or (mother.mother_id and father.mother_id and mother.mother_id == father.mother_id):
            smart_alerts.append("⚠️ هشدار ژنتیکی (هم‌خونی): پدر و مادر این دام نسبت فامیلی نزدیک دارند!")

    import jdatetime
    for med in medical_history:
        if med.withdrawal_end_date and med.withdrawal_end_date > today: 
            smart_alerts.append(f"پرهیز دارویی تا {jdatetime.date.fromgregorian(date=med.withdrawal_end_date).strftime('%Y/%m/%d')} ({med.medicine_name}).")
        if med.next_date and today <= med.next_date <= today + timedelta(days=5): 
            smart_alerts.append(f"نوبت بعدی {med.medicine_name}: {jdatetime.date.fromgregorian(date=med.next_date).strftime('%Y/%m/%d')}.")

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
                           birth_stats=birth_stats, offsprings=offsprings, fcr_cost=fcr_cost, # fcr اضافه شد
                           estimated_feed_cost=estimated_feed_cost, smart_alerts=smart_alerts, age_in_months=age_in_months,
                           days_to_target=days_to_target, next_heat_date=next_heat_date,
                           rams=Sheep.query.filter_by(gender='قوچ').all(), rations=FeedRation.query.all(),
                           pens=Pen.query.all(), medicines=Medicine.query.all(), breeds=BreedCategory.query.all(), 
                           purposes=PurposeCategory.query.all(), statuses=StatusCategory.query.all(),
                           buyer_categories=BuyerCategory.query.all(),
                           mother=mother, father=father, today_str=today.strftime('%Y-%m-%d'))

@livestock_bp.route('/edit/<int:id>', methods=['POST'])
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
    sheep.target_weight = float(t_weight) if t_weight else None
    
    heat_str = request.form.get('last_heat_date')
    sheep.last_heat_date = datetime.strptime(heat_str, '%Y-%m-%d').date() if heat_str else None

    # منطق ثبت خودکار فاکتور فروش در دفتر کل
    if sheep.status == 'فروخته شده':
        # جلوگیری از خطا در صورت خالی بودن یا فرمت ناصحیح مبالغ و تاریخ
        raw_price = request.form.get('sale_price', '0').replace(',', '').strip()
        try:
            sheep.sale_price = float(raw_price) if raw_price else 0.0
        except ValueError:
            sheep.sale_price = 0.0

        s_date_str = request.form.get('sale_date')
        try:
            sheep.sale_date = datetime.strptime(s_date_str, '%Y-%m-%d').date() if s_date_str else datetime.now(UTC).date()
        except ValueError:
            sheep.sale_date = datetime.now(UTC).date()

        # انتساب خریدار و فلاش کردن جهت دسترسی به روابط در گام بعد
        buyer_cat_id = request.form.get('buyer_category_id')
        sheep.buyer_category_id = int(buyer_cat_id) if (buyer_cat_id and buyer_cat_id.isdigit()) else None
        db.session.flush()
        
        if sheep.sale_price > 0:
            # تهیه نام خریدار برای درج در ستون طرف حساب دفتر کل
            from app.models import BuyerCategory
            buyer_name = 'فروش نقدی'
            if sheep.buyer_category_id:
                bc = db.session.get(BuyerCategory, sheep.buyer_category_id)
                if bc: buyer_name = bc.name

            existing_tx = Transaction.query.filter(
                Transaction.description.ilike(f"%پلاک: {sheep.ear_tag}%"),
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
                
                try:
                    AccountingEngine.record_sale(new_tx, include_vat=True)
                except:
                    pass
                flash(f'✅ فروش دام (پلاک {sheep.ear_tag}) با موفقیت ثبت شد و فاکتور درآمد در لیست فاکتورها قرار گرفت.', 'success')
            else:
                existing_tx.amount = sheep.sale_price
                existing_tx.t_date = sheep.sale_date
                existing_tx.party_name = buyer_name
                db.session.add(existing_tx)
                flash(f'ℹ️ فاکتور فروش پلاک {sheep.ear_tag} در دفتر کل بروزرسانی شد.', 'info')
        else:
            flash('⚠️ وضعیت دام به "فروخته شده" تغییر یافت، اما به دلیل عدم ورود مبلغ فروش، فاکتوری صادر نشد.', 'warning')

        # ثبت آخرین وزن زمان فروش اگر وارد شده باشد
        s_weight = request.form.get('sale_weight')
        if s_weight:
            sheep.weight = float(s_weight)
            db.session.add(WeightRecord(sheep_id=sheep.id, weight=float(s_weight), notes="وزن زمان فروش"))
    else:
        sheep.sale_price = 0.0
        sheep.sale_date = None
     
    log_audit(f"ویرایش اطلاعات پروفایل دام پلاک {sheep.ear_tag}") 
    db.session.commit()
    return redirect(url_for('livestock.profile', id=id))

@livestock_bp.route('/add_weight/<int:id>', methods=['POST'])
def add_weight(id):
    sheep = Sheep.query.get_or_404(id)
    new_weight = float(request.form.get('weight'))
    date_str = request.form.get('record_date')
    r_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now(UTC).date()
    
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
def add_medical(id):
    r_date = datetime.strptime(request.form.get('record_date'), '%Y-%m-%d').date() if request.form.get('record_date') else datetime.now(UTC).date()
    n_date = datetime.strptime(request.form.get('next_date'), '%Y-%m-%d').date() if request.form.get('next_date') else None
    w_date = datetime.strptime(request.form.get('withdrawal_end_date'), '%Y-%m-%d').date() if request.form.get('withdrawal_end_date') else None
    r_date = datetime.strptime(request.form.get('record_date'), '%Y-%m-%d').date() if request.form.get('record_date') else datetime.now(UTC).date()
    n_date = datetime.strptime(request.form.get('next_date'), '%Y-%m-%d').date() if request.form.get('next_date') else None
    w_date = datetime.strptime(request.form.get('withdrawal_end_date'), '%Y-%m-%d').date() if request.form.get('withdrawal_end_date') else None
    
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
def add_birth(id):
    r_date = datetime.strptime(request.form.get('record_date'), '%Y-%m-%d').date() if request.form.get('record_date') else datetime.utcnow().date()
    father_id = request.form.get('father_id')
    lambs_count = int(request.form.get('lambs_count', 1))
    status = request.form.get('status', 'موفق')
    
    db.session.add(BirthRecord(mother_id=id, father_id=father_id or None, lambs_count=lambs_count, status=status, notes=request.form.get('notes'), birth_date=r_date))
    db.session.commit()
    
    if status == 'موفق':
        mother = Sheep.query.get(id)
        b_weight = float(get_setting('birth_weight', 3.5))
        for i in range(lambs_count):
            tag = f"LMB-{mother.ear_tag}-{random.randint(100, 9999)}"
            db.session.add(Sheep(ear_tag=tag, breed=mother.breed, gender="نامشخص", weight=b_weight, status="زنده و سالم", purpose="پرواربندی", birth_date=r_date, mother_id=mother.id, father_id=father_id or None))
        db.session.commit()
    return redirect(url_for('livestock.profile', id=id))

@livestock_bp.route('/delete/<int:id>')
def delete_sheep(id):
    sheep = Sheep.query.get_or_404(id)
    db.session.delete(sheep)
    db.session.commit()
    return redirect(url_for('livestock.index'))

@livestock_bp.route('/vet_queue')
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
def apply_protocol(id):
    template = TreatmentTemplate.query.get_or_404(request.form.get('template_id'))
    today = datetime.utcnow().date()
    for med in template.medicines.split(','):
        db.session.add(MedicalRecord(sheep_id=id, action_type="پروتکل", medicine_name=med.strip(), record_date=today, operator="سیستم", notes=f"پروتکل: {template.name}"))
    sheep = Sheep.query.get(id)
    if sheep.status == 'بیمار': sheep.status = 'تحت درمان'
    db.session.commit()
    flash(f"پروتکل روی دام اعمال شد.", "success")
    return redirect(request.referrer)

@livestock_bp.route('/medical')
def medical_overview():
    today = datetime.now(UTC).date()
    sick_sheep = Sheep.query.filter_by(status='بیمار').all()
    upcoming_meds = MedicalRecord.query.filter(MedicalRecord.next_date != None, MedicalRecord.next_date <= today + timedelta(days=7)).order_by(MedicalRecord.next_date.asc()).all()
    return render_template('livestock/medical.html', sick_sheep=sick_sheep, upcoming_meds=upcoming_meds, today=today)

@livestock_bp.route('/mark_healthy/<int:id>')
def mark_healthy(id):
    sheep = Sheep.query.get_or_404(id)
    sheep.status = 'زنده و سالم'
    db.session.commit()
    flash(f"دام {sheep.ear_tag} ترخیص شد.", "success")
    return redirect(request.referrer)

@livestock_bp.route('/mark_med_done/<int:med_id>')
def mark_med_done(med_id):
    old_med = MedicalRecord.query.get_or_404(med_id)
    db.session.add(MedicalRecord(sheep_id=old_med.sheep_id, action_type=old_med.action_type, medicine_name=old_med.medicine_name, record_date=datetime.now(UTC).date(), operator="سیستم", notes="تکرار نوبت قبلی انجام شد."))
    old_med.next_date = None
    db.session.commit()
    flash(f"داروی {old_med.medicine_name} ثبت شد و از صف حذف گردید.", "success")
    return redirect(request.referrer)

@livestock_bp.route('/mark_newborn_checked/<int:id>')
def mark_newborn_checked(id):
    db.session.add(MedicalRecord(sheep_id=id, action_type="ویزیت", medicine_name="چکاپ سلامت نوزاد", record_date=datetime.now(UTC).date(), operator="سیستم", notes="ویزیت اولیه ثبت شد."))
    db.session.commit()
    flash("چکاپ نوزاد ثبت شد و از صف حذف گردید.", "success")
    return redirect(request.referrer)

@livestock_bp.route('/toggle_star/<int:id>')
def toggle_star(id):
    sheep = Sheep.query.get_or_404(id)
    sheep.is_starred = not sheep.is_starred
    db.session.commit()
    return jsonify({'success': True, 'is_starred': sheep.is_starred})

@livestock_bp.route('/passport/<ear_tag>')
def public_passport(ear_tag):
    sheep = Sheep.query.filter_by(ear_tag=ear_tag).first_or_404()
    from app.models import SystemSetting
    settings = {s.key: s.value for s in SystemSetting.query.all()}
    
    # محاسبه سن
    age = "نامشخص"
    if sheep.birth_date:
        age_days = (datetime.now(UTC).date() - sheep.birth_date).days
        age = f"{age_days // 30} ماه"
        
    return render_template('livestock/passport.html', sheep=sheep, age=age, settings=settings)


from flask import jsonify
# ==========================================
# سیستم هوش مصنوعی پیشنهاد جفت‌گیری (Genetics)
# ==========================================
@livestock_bp.route('/genetics')
def genetics():
    # 1. بهینه‌سازی کوئری قوچ‌ها (محاسبه تجمعی در سطح دیتابیس)
    offspring_sub = db.session.query(
        Sheep.father_id, 
        func.count(Sheep.id).label('offspring_count')
    ).filter(Sheep.father_id.isnot(None)).group_by(Sheep.father_id).subquery()

    birth_sub = db.session.query(
        BirthRecord.father_id,
        func.sum(case((BirthRecord.lambs_count == 2, 1), else_=0)).label('twins'),
        func.sum(case((BirthRecord.lambs_count >= 3, 1), else_=0)).label('triplets')
    ).filter(BirthRecord.father_id.isnot(None)).group_by(BirthRecord.father_id).subquery()

    top_rams_data = db.session.query(
        Sheep,
        offspring_sub.c.offspring_count,
        birth_sub.c.twins,
        birth_sub.c.triplets
    ).join(offspring_sub, Sheep.id == offspring_sub.c.father_id)\
     .outerjoin(birth_sub, Sheep.id == birth_sub.c.father_id)\
     .filter(Sheep.gender == 'قوچ', Sheep.status == 'زنده و سالم').all()

    top_rams = []
    for r, o_count, twins, triplets in top_rams_data:
        twins_val = int(twins or 0)
        triplets_val = int(triplets or 0)
        score = (twins_val * 2) + (triplets_val * 3) + o_count
        top_rams.append({'ram': r, 'offsprings': o_count, 'twins': twins_val, 'score': score})
        
    top_rams.sort(key=lambda x: x['score'], reverse=True)

    # 2. بهینه‌سازی کوئری میش‌ها (استفاده از Join و Limit در SQL)
    top_ewes_data = db.session.query(
        Sheep,
        func.count(BirthRecord.id).label('successful_births')
    ).join(BirthRecord, Sheep.id == BirthRecord.mother_id)\
     .filter(Sheep.gender == 'میش', Sheep.status == 'زنده و سالم', BirthRecord.status == 'موفق')\
     .group_by(Sheep.id)\
     .order_by(func.count(BirthRecord.id).desc())\
     .limit(5).all()

    top_ewes = [{'ewe': e, 'successful_births': count} for e, count in top_ewes_data]

    return render_template('livestock/genetics.html', top_rams=top_rams[:5], top_ewes=top_ewes)



# ==========================================
# مانیتورینگ هوشمند و اینترنت اشیا (IoT) بهاربندها
# ==========================================
@livestock_bp.route('/pens')
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