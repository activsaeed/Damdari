from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app import db
from app.models import InventoryItem, InventoryLog, Transaction, Unit, InventoryCategory
from datetime import datetime, timedelta, UTC

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/')
@login_required
def index():
    # مرتب‌سازی بر اساس شناسه (نزولی) برای نمایش جدیدترین‌ها در ابتدا
    items = InventoryItem.query.order_by(InventoryItem.id.desc()).all()
    units = Unit.query.all()
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    
    low_stock_count = sum(1 for item in items if (item.quantity or 0) <= (item.min_threshold or 0))
    # اصلاح فیلتر خوراک بر اساس نام دسته‌بندی جدید
    total_feed = sum((item.quantity or 0) for item in items if item.category and item.category.name in ['خوراک', 'علوفه'] and item.unit and item.unit.name in ['کیلوگرم', 'تن'])
    total_value = sum(((item.quantity or 0) * (item.unit_price or 0)) for item in items)
    
    # ---> فاز 3: سیستم هشدار تاریخ انقضای دارو <---
    today = datetime.now(UTC).date()
    warning_date = today + timedelta(days=30) # هشدار برای 30 روز آینده
    expiring_items = [i for i in items if i.expiry_date and i.expiry_date <= warning_date and i.quantity > 0]
    
    return render_template('inventory/index.html', 
                           items=items, categories=categories, units=units,
                           low_stock_count=low_stock_count, total_feed=total_feed, total_value=total_value,
                           expiring_items=expiring_items, today=today)

@inventory_bp.route('/add_item', methods=['POST'])
@login_required
def add_item():
    name = request.form.get('name', '').strip()
    cat_name = request.form.get('category', 'عمومی').strip()
    unit_id = request.form.get('unit_id')

    if not name or not cat_name or not unit_id:
        flash('خطا: نام، دسته‌بندی و واحد اندازه‌گیری الزامی هستند.', 'danger')
        return redirect(url_for('inventory.index'))

    # منطق هوشمند: اگر دسته‌بندی تایپ شده وجود ندارد، ساخته شود
    target_cat = InventoryCategory.query.filter_by(name=cat_name).first()
    if not target_cat:
        target_cat = InventoryCategory(name=cat_name)
        db.session.add(target_cat)
        db.session.flush()

    exp_date_str = request.form.get('expiry_date')
    exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date() if exp_date_str else None

    new_item = InventoryItem(
        name=name, 
        category_id=target_cat.id, 
        unit_id=int(unit_id), 
        min_threshold=float(request.form.get('min_threshold')) if request.form.get('min_threshold') else 0.0,
        description=request.form.get('description'), 
        unit_price=0.0,
        expiry_date=exp_date # ذخیره تاریخ انقضا
    )
    db.session.add(new_item)
    db.session.commit()
    flash('کالای جدید به انبار اضافه شد.', 'success')
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/edit_item/<int:id>', methods=['POST'])
@login_required
def edit_item(id):
    item = InventoryItem.query.get_or_404(id)
    unit_id = request.form.get('unit_id')
    cat_name = request.form.get('category', '').strip()

    # به‌روزرسانی دسته‌بندی
    category = InventoryCategory.query.filter_by(name=cat_name).first()
    if not category:
        category = InventoryCategory(name=cat_name)
        db.session.add(category)
        db.session.flush()

    item.name = request.form.get('name').strip()
    item.category_id = category.id
    if unit_id: item.unit_id = int(unit_id)
    item.min_threshold = float(request.form.get('min_threshold') or 0)
    item.description = request.form.get('description')
    
    exp_date_str = request.form.get('expiry_date')
    item.expiry_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date() if exp_date_str else None
    
    db.session.commit()
    flash('مشخصات کالا با موفقیت ویرایش شد.', 'info')
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/delete_item/<int:id>', methods=['POST'])
@login_required
def delete_item(id):
    item = InventoryItem.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/transaction', methods=['POST'])
@login_required
def transaction():
    item_id = request.form.get('item_id')
    action_type = request.form.get('action_type')
    amount = float(request.form.get('amount') or 0)
    notes = request.form.get('notes')
    today = datetime.now(UTC).date()
    
    item = InventoryItem.query.get_or_404(item_id)
    
    if action_type == 'ورود':
        total_price_str = request.form.get('total_price')
        if total_price_str and float(total_price_str) > 0:
            total_price = float(total_price_str)
            # فرمول حسابداری میانگین موزون: (ارزش فعلی انبار + مبلغ خرید جدید) / کل تعداد جدید
            current_value = item.quantity * item.unit_price
            item.quantity += amount
            item.unit_price = (current_value + total_price) / item.quantity
            
            # ثبت اتوماتیک در دفتر کل حسابداری! # ۲. رفع ضعف موتور حسابداری (حذف String Matching)
            db.session.add(Transaction(t_type='هزینه', category='خرید انبار (خودکار)', amount=total_price, t_date=today, is_archived=False, description=f"خرید {amount} {item.unit.name if item.unit else ''} {item.name}"))
            flash('موجودی شارژ شد و مبلغ در دفتر کل مالی ثبت گردید.', 'success')
        else:
            item.quantity += amount
            flash('موجودی بدون ثبت هزینه شارژ شد.', 'warning')
            
        transaction_price = item.unit_price
        
    elif action_type == 'خروج':
        item.quantity -= amount
        transaction_price = item.unit_price # قفل کردن قیمت در لحظه مصرف (ضد تورم)
        flash('مصرف روزانه ثبت شد.', 'info')
        
    db.session.add(InventoryLog(item_id=item_id, action_type=action_type, amount=amount, transaction_price=transaction_price, notes=notes))
    db.session.commit()
    return redirect(url_for('inventory.index'))


# ==========================================
# سیستم ماشین‌حساب جیره‌نویس هوشمند
# ==========================================
@inventory_bp.route('/smart_ration', endpoint='smart_ration')
def smart_ration():
    # استخراج تمام خوراک های موجود در انبار به همراه قیمتشان
    feed_items = InventoryItem.query.join(InventoryCategory).filter(InventoryCategory.name == 'خوراک').all()
    return render_template('inventory/smart_ration.html', feed_items=feed_items)

@inventory_bp.route('/kardex/<int:id>')
def kardex(id):
    """گزارش ریز گردش انبار (کاردکس کالا) با محاسبات مانده لحظه‌ای"""
    item = InventoryItem.query.get_or_404(id)
    logs = InventoryLog.query.filter_by(item_id=id).order_by(InventoryLog.date.asc()).all()
    
    kardex_data = []
    running_qty = 0
    
    for log in logs:
        if log.action_type == 'ورود':
            running_qty += log.amount
        else:
            running_qty -= log.amount
            
        kardex_data.append({
            'log': log,
            'balance': running_qty
        })
    return render_template('inventory/kardex.html', item=item, kardex=kardex_data[::-1])