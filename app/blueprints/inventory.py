from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app import db
from app.models import InventoryItem, InventoryLog, Transaction, Unit, InventoryCategory, AuditLog
from datetime import datetime, timedelta, UTC
from app.blueprints.finance import permission_required, parse_smart_date

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/')
@login_required
@permission_required('can_view_inventory')
def index():
    search_q = request.args.get('search', '').strip()
    cat_q = request.args.get('category_id', type=int)
    query = InventoryItem.query
    if search_q:
        query = query.filter(InventoryItem.name.ilike(f"%{search_q}%"))
    if cat_q:
        query = query.filter(InventoryItem.category_id == cat_q)
    items = query.order_by(InventoryItem.id.desc()).all()
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
                           expiring_items=expiring_items, today=today,
                           current_search=search_q, current_cat=cat_q)

@inventory_bp.route('/add_item', methods=['POST'])
@login_required
@permission_required('can_view_inventory')
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
    exp_date = parse_smart_date(exp_date_str)

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
    log = AuditLog(user_name=current_user.name, action=f"ثبت کالای جدید: {new_item.name}", timestamp=datetime.now(UTC))
    db.session.add(log)
    db.session.commit()
    flash('کالای جدید به انبار اضافه شد.', 'success')
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/edit_item/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_inventory')
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
    item.expiry_date = parse_smart_date(exp_date_str)
    
    db.session.commit()
    log = AuditLog(user_name=current_user.name, action=f"ویرایش کالا: {item.name}", timestamp=datetime.now(UTC))
    db.session.add(log)
    db.session.commit()
    flash('مشخصات کالا با موفقیت ویرایش شد.', 'info')
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/delete_item/<int:id>', methods=['POST'])
@login_required
@permission_required('can_view_inventory')
def delete_item(id):
    item = InventoryItem.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/transaction', methods=['POST'])
@login_required
@permission_required('can_view_inventory')
def transaction():
    item_id = request.form.get('item_id')
    action_type = request.form.get('action_type')
    amount = Decimal(request.form.get('amount') or '0')
    notes = request.form.get('notes')
    today = datetime.now(UTC).date()

    # Concurrency Protection: قفل کردن ردیف کالا در دیتابیس تا پایان محاسبات
    item = db.session.query(InventoryItem).filter_by(id=item_id).with_for_update().first()
    if not item:
        flash('کالا یافت نشد.', 'danger')
        return redirect(url_for('inventory.index'))
    
    if action_type == 'ورود':
        total_price_str = request.form.get('total_price')
        if total_price_str and Decimal(total_price_str) > 0:
            total_price = Decimal(total_price_str)
            
            # تراکنش اتمیک برای شارژ انبار و ثبت سند مالی بصورت همزمان
            with db.session.begin_nested():
                current_qty = item.quantity if item.quantity else Decimal('0')
                current_price = item.unit_price if item.unit_price else Decimal('0')
                current_value = current_qty * current_price
                
                # فرمول دقیق میانگین موزون با جلوگیری از ریسک تقسیم بر صفر
                new_total_qty = current_qty + amount
                if new_total_qty > 0:
                    item.unit_price = (current_value + total_price) / new_total_qty
                item.quantity = new_total_qty

                # ثبت خودکار هزینه در دفتر کل
                new_tx = Transaction(t_type='هزینه', category='خرید انبار (خودکار)', amount=total_price, t_date=today, is_archived=False, inventory_item_id=item.id, inventory_quantity=amount, description=f"خرید {amount} {item.unit.name if item.unit else ''} {item.name}")
                db.session.add(new_tx)
                db.session.flush()
                AccountingEngine.record_expense(new_tx)

            flash('موجودی شارژ شد و سند مالی با متد میانگین موزون ثبت گردید.', 'success')
        else:
            item.quantity += amount
            flash('موجودی بدون ثبت هزینه شارژ شد.', 'warning')
            
        transaction_price = item.unit_price
        
    elif action_type == 'خروج':
        if item.quantity >= amount:
            item.quantity -= amount
            transaction_price = item.unit_price
            # صدور سند هزینه در لحظه مصرف (ضد فاجعه حسابداری)
            from app.accounting_engine import AccountingEngine
            total_cost = amount * (transaction_price or 0)
            if total_cost > 0:
                AccountingEngine.record_feed_consumption(total_cost)
            flash('مصرف ثبت و هزینه آن در دفاتر لحاظ شد.', 'info')
        else:
            flash('خطا: موجودی انبار کافی نیست!', 'danger')
            return redirect(url_for('inventory.index'))
        
    db.session.add(InventoryLog(item_id=item_id, action_type=action_type, amount=amount, transaction_price=transaction_price, notes=notes))
    db.session.commit()
    log = AuditLog(user_name=current_user.name, action=f"انبار: {action_type} {amount} {item.unit.name if item.unit else ''} {item.name}", timestamp=datetime.now(UTC))
    db.session.add(log)
    db.session.commit()
    return redirect(url_for('inventory.index'))


# ==========================================
# سیستم ماشین‌حساب جیره‌نویس هوشمند
# ==========================================
@inventory_bp.route('/smart_ration', endpoint='smart_ration')
@login_required
@permission_required('can_view_inventory')
def smart_ration():
    feed_items = InventoryItem.query.join(InventoryCategory).filter(InventoryCategory.name == 'خوراک').all()
    return render_template('inventory/smart_ration.html', feed_items=feed_items)

@inventory_bp.route('/kardex/<int:id>')
@login_required
@permission_required('can_view_inventory')
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