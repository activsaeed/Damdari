from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Equipment, Transaction
from app.accounting_engine import AccountingEngine
from datetime import datetime

assets_bp = Blueprint('assets', __name__)

@assets_bp.route('/')
@login_required
def index():
    if current_user.role != 'مدیر':
        flash('دسترسی محدود به مدیریت است.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    equipments = Equipment.query.order_by(Equipment.purchase_date.desc()).all()
    # دریافت فاکتورهای هزینه‌ای که می‌توانند مربوط به خرید دارایی باشند
    purchase_transactions = Transaction.query.filter_by(t_type='هزینه').order_by(Transaction.t_date.desc()).limit(100).all()
    
    return render_template('assets/index.html', equipments=equipments, purchase_transactions=purchase_transactions)

@assets_bp.route('/add', methods=['POST'])
@login_required
def add_asset():
    name = request.form.get('name')
    price = Decimal(request.form.get('purchase_price', '0').replace(',', ''))
    scrap = Decimal(request.form.get('scrap_value', '0').replace(',', ''))
    lifespan = int(request.form.get('lifespan_years', 10))
    purchase_date_str = request.form.get('purchase_date')
    transaction_id = request.form.get('transaction_id')
    
    try:
        p_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date() if purchase_date_str else datetime.utcnow().date()
        
        new_asset = Equipment(
            name=name,
            purchase_price=price,
            scrap_value=scrap,
            purchase_date=p_date,
            lifespan_years=lifespan,
            transaction_id=int(transaction_id) if transaction_id else None
        )
        db.session.add(new_asset)
        db.session.commit()
        flash('دارایی جدید با موفقیت ثبت شد.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در ثبت دارایی: {str(e)}', 'danger')
        
    return redirect(url_for('assets.index'))

@assets_bp.route('/depreciate/<int:id>', methods=['POST'])
@login_required
def depreciate_asset(id):
    asset = Equipment.query.get_or_404(id)
    # فرمول خط مستقیم: (بهای تمام شده - ارزش اسقاط) / عمر مفید
    annual_depreciation = (asset.purchase_price - asset.scrap_value) / asset.lifespan_years
    try:
        AccountingEngine.record_depreciation(asset.name, annual_depreciation)
        db.session.commit()
        flash(f'استهلاک سالانه برای {asset.name} ثبت شد.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در محاسبه استهلاک: {str(e)}', 'danger')
    return redirect(url_for('assets.index'))

@assets_bp.route('/edit/<int:id>', methods=['POST'])
@login_required
def edit_asset(id):
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('assets.index'))
    
    asset = Equipment.query.get_or_404(id)
    try:
        asset.name = request.form.get('name')
        asset.purchase_price = Decimal(request.form.get('purchase_price', '0').replace(',', ''))
        asset.scrap_value = Decimal(request.form.get('scrap_value', '0').replace(',', ''))
        asset.lifespan_years = int(request.form.get('lifespan_years', 10))
        
        transaction_id = request.form.get('transaction_id')
        asset.transaction_id = int(transaction_id) if transaction_id else None

        purchase_date_str = request.form.get('purchase_date')
        if purchase_date_str:
            asset.purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
        
        db.session.commit()
        flash('دارایی با موفقیت ویرایش شد.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در ویرایش دارایی: {str(e)}', 'danger')
    return redirect(url_for('assets.index'))

@assets_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_asset(id):
    if current_user.role != 'مدیر':
        flash('دسترسی محدود است.', 'danger')
        return redirect(url_for('assets.index'))
    
    asset = Equipment.query.get_or_404(id)
    try:
        db.session.delete(asset)
        db.session.commit()
        flash('دارایی از سیستم حذف شد.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در حذف دارایی: {str(e)}', 'danger')
    return redirect(url_for('assets.index'))