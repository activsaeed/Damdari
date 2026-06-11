from app import db
from datetime import datetime
from decimal import Decimal
from flask_login import UserMixin
from sqlalchemy import Numeric

# این کلاس User را جایگزین کلاس قبلی کنید
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='کارگر') # مدیر، دامپزشک، حسابدار، کارگر
    
    # فیلدهای جدید برای دسترسی داینامیک (تیک زدن در تنظیمات)
    can_view_livestock = db.Column(db.Boolean, default=False)
    can_view_finance = db.Column(db.Boolean, default=False)
    can_view_inventory = db.Column(db.Boolean, default=False)
    can_view_hr = db.Column(db.Boolean, default=False)
    can_view_reports = db.Column(db.Boolean, default=False)
    can_view_settings = db.Column(db.Boolean, default=False)

class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    medicine_category_id = db.Column(db.Integer, db.ForeignKey('medicine_category.id'), nullable=True)
    category = db.relationship('MedicineCategory', backref='medicines')

class FeedRation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    daily_cost = db.Column(Numeric(18, 2), default=0.0)
    description = db.Column(db.String(255), nullable=True)
    schedules = db.relationship('FeedingSchedule', backref='ration', lazy=True, cascade="all, delete-orphan")

class FeedingSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    feed_ration_id = db.Column(db.Integer, db.ForeignKey('feed_ration.id'), nullable=False)
    time_of_day = db.Column(db.String(50), nullable=False)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False, index=True)
    amount_kg = db.Column(Numeric(18, 2), nullable=False)
    item = db.relationship('InventoryItem', backref='usage_in_schedules')

class Pen(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    capacity = db.Column(db.Integer, default=50)
    pen_type = db.Column(db.String(50), nullable=False)
    sheep_list = db.relationship('Sheep', backref='pen', lazy=True)

class BreedCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class PurposeCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class StatusCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    type = db.Column(db.String(50), default='عادی')

class TreatmentTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    medicines = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)

class Sheep(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ear_tag = db.Column(db.String(50), unique=True, nullable=False)
    breed = db.Column(db.String(50), nullable=True)
    gender = db.Column(db.String(20), nullable=False)
    birth_date = db.Column(db.Date, nullable=True)
    entry_date = db.Column(db.DateTime, default=datetime.utcnow)
    weight = db.Column(Numeric(18, 2), nullable=True)
    purchase_price = db.Column(Numeric(18, 2), default=0.0) 
    last_heat_date = db.Column(db.Date, nullable=True) 
    target_weight = db.Column(Numeric(18, 2), nullable=True) 
    sale_price = db.Column(Numeric(18, 2), default=0.0) 
    sale_date = db.Column(db.Date, nullable=True)
    buyer_category_id = db.Column(db.Integer, db.ForeignKey('buyer_category.id'), nullable=True)
    buyer_category = db.relationship('BuyerCategory', backref='sold_sheeps')
    status = db.Column(db.String(50), default='زنده و سالم')
    purpose = db.Column(db.String(50), nullable=True)
    qr_code_path = db.Column(db.String(200), nullable=True)
    death_reason = db.Column(db.String(200), nullable=True)
     # ---> این فیلد را اضافه کنید <---
    is_starred = db.Column(db.Boolean, default=False) 
    mother_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='SET NULL'), nullable=True, index=True)
    father_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='SET NULL'), nullable=True, index=True)
    feed_ration_id = db.Column(db.Integer, db.ForeignKey('feed_ration.id', ondelete='SET NULL'), nullable=True, index=True)
    pen_id = db.Column(db.Integer, db.ForeignKey('pen.id', ondelete='SET NULL'), nullable=True, index=True)
    is_deleted = db.Column(db.Boolean, default=False)
    
    ration = db.relationship('FeedRation', backref='sheep_list')
    weight_records = db.relationship('WeightRecord', backref='sheep', lazy=True, cascade="all, delete-orphan")
    medical_records = db.relationship('MedicalRecord', backref='sheep', lazy=True, cascade="all, delete-orphan")
    birth_records = db.relationship('BirthRecord', foreign_keys='BirthRecord.mother_id', backref='mother', lazy=True, cascade="all, delete-orphan")
    lactation_records = db.relationship('LactationRecord', backref='sheep', lazy=True, cascade="all, delete-orphan")

class LactationRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sheep_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='CASCADE'), nullable=False, index=True)
    record_date = db.Column(db.Date, default=datetime.utcnow)
    milk_yield = db.Column(Numeric(18, 2), nullable=False)
    notes = db.Column(db.String(200), nullable=True)

class BirthRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mother_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='CASCADE'), nullable=False, index=True)
    father_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='SET NULL'), nullable=True, index=True)
    birth_date = db.Column(db.Date, default=datetime.utcnow)
    lambs_count = db.Column(db.Integer, default=1)
    status = db.Column(db.String(50), default='موفق')
    notes = db.Column(db.String(200), nullable=True)

class WeightRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sheep_id = db.Column(db.Integer, db.ForeignKey('sheep.id'), nullable=False)
    weight = db.Column(Numeric(18, 2), nullable=False)
    record_date = db.Column(db.Date, default=datetime.utcnow)
    bcs = db.Column(Numeric(4, 2), nullable=True)
    notes = db.Column(db.String(200), nullable=True)

class MedicalRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sheep_id = db.Column(db.Integer, db.ForeignKey('sheep.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    medicine_name = db.Column(db.String(100), nullable=False)
    drug_id = db.Column(db.Integer, db.ForeignKey('drug_inventory.id', ondelete='SET NULL'), nullable=True)
    record_date = db.Column(db.Date, default=datetime.utcnow)
    next_date = db.Column(db.Date, nullable=True)
    withdrawal_end_date = db.Column(db.Date, nullable=True)
    operator = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.String(200), nullable=True)
    photos = db.relationship('MedicalPhoto', backref='medical_record', lazy=True, cascade="all, delete-orphan")
    drug = db.relationship('DrugInventory', backref='medical_records', lazy=True)

class MedicalPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    medical_record_id = db.Column(db.Integer, db.ForeignKey('medical_record.id'), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)


# ==========================================
# هسته حسابداری دوطرفه (Double-Entry Accounting)
# ==========================================

class AccountType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False) # دارایی، بدهی، سرمایه، درآمد، هزینه
    nature = db.Column(db.String(20), nullable=False) # ماهیت: بدهکار یا بستانکار

class Account(db.Model):
    """کدینگ حسابداری (دفتر کل و معین)"""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False) # مثلا: 1101 (موجودی نقد)
    name = db.Column(db.String(100), nullable=False)
    account_type_id = db.Column(db.Integer, db.ForeignKey('account_type.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True) # برای حساب های زیرمجموعه
    
    type = db.relationship('AccountType', backref='accounts')
    children = db.relationship('Account', backref=db.backref('parent', remote_side=[id]))

class JournalEntry(db.Model):
    """سند حسابداری (Sanad)"""
    id = db.Column(db.Integer, primary_key=True)
    entry_number = db.Column(db.String(50), unique=True, nullable=False) # شماره سند
    date = db.Column(db.Date, default=datetime.utcnow)
    description = db.Column(db.String(255), nullable=False) # شرح سند
    is_auto_generated = db.Column(db.Boolean, default=True) # آیا سیستم خودش ساخته؟
    status = db.Column(db.String(20), default='تایید شده') # موقت، تایید شده، برگشتی
    
    # ارتباط با فاکتور یا چک (برای پیگیری)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=True)
    reversed_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=True) # سند برگشتی
    
    lines = db.relationship('JournalEntryLine', backref='journal_entry', lazy=True, cascade="all, delete-orphan")
    reversal = db.relationship('JournalEntry', backref=db.backref('reversed_by', remote_side=[id]), lazy=True)

class JournalEntryLine(db.Model):
    """آرتیکل‌های سند (بدهکار/بستانکار)"""
    id = db.Column(db.Integer, primary_key=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=True) # حساب تفصیلی اشخاص
    
    debit = db.Column(Numeric(18, 2), default=Decimal('0'))  # بدهکار
    credit = db.Column(Numeric(18, 2), default=Decimal('0')) # بستانکار
    description = db.Column(db.String(255), nullable=True)


class TransactionCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    t_type = db.Column(db.String(20), nullable=False)
    # ---> فیلد جدید: تگ سیستمی غیرقابل تغییر برای بک‌اند <---
    system_tag = db.Column(db.String(50), nullable=True, unique=True)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    t_type = db.Column(db.String(20), nullable=False) 
    category = db.Column(db.String(50), nullable=False) 
    amount = db.Column(Numeric(18, 2), nullable=False) 
    discount_amount = db.Column(Numeric(18, 2), default=0.0) # مبلغ تخفیف
    vat_amount = db.Column(Numeric(18, 2), default=0.0) # مبلغ مالیات دقیق
    t_date = db.Column(db.Date, default=datetime.utcnow) 
    due_date = db.Column(db.Date, nullable=True) # تاریخ سررسید برای نسیه
    description = db.Column(db.String(255), nullable=True)
    invoice_number = db.Column(db.String(100), nullable=True)
    
    # ---> فیلدهای جدید فاکتور <---
    party_name = db.Column(db.String(150), nullable=True) # نام شرکت/شخص/فروشگاه
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=True)
    payment_method = db.Column(db.String(50), default='نقدی') # نقدی یا نسیه
    cost_center = db.Column(db.String(100), nullable=True) # مرکز هزینه (پرواری، داشتی و...)
    is_starred = db.Column(db.Boolean, default=False) # ستاره دار بودن فاکتور
    is_deleted = db.Column(db.Boolean, default=False) # ابطال منطقی فاکتور (Soft Delete)
    is_archived = db.Column(db.Boolean, default=False) # وضعیت بایگانی
    moadian_status = db.Column(db.String(20), default='منتظر ارسال') # وضعیت سامانه مودیان
    moadian_sent_at = db.Column(db.DateTime, nullable=True) # تاریخ ارسال به مودیان
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=True) # کالای مرتبط در انبار
    inventory_quantity = db.Column(Numeric(18, 2), nullable=True) # مقدار کالا در این فاکتور
    
    documents = db.relationship('TransactionDocument', backref='transaction', lazy=True, cascade="all, delete-orphan")

class TransactionDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    task_date = db.Column(db.Date, default=datetime.utcnow)
    is_done = db.Column(db.Boolean, default=False)
    livestock_id = db.Column(db.Integer, db.ForeignKey('sheep.id'), nullable=True)

# ---> آپدیت سیستم انبار برای قیمت گذاری داینامیک خوراک <---
class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=True)
    category = db.relationship('InventoryCategory', backref='items')
    quantity = db.Column(Numeric(18, 2), default=0.0)
    unit_id = db.Column(db.Integer, db.ForeignKey('unit.id'), nullable=False)
    unit = db.relationship('Unit', backref='inventory_items')
    min_threshold = db.Column(Numeric(18, 2), default=10.0)
    
    # فیلد جدید: محاسبه میانگین قیمت تمام شده کالا (Moving Average)
    unit_price = db.Column(Numeric(18, 2), default=0.0) 
    expiry_date = db.Column(db.Date, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    logs = db.relationship('InventoryLog', backref='item', lazy=True, cascade="all, delete-orphan")

class InventoryLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    action_type = db.Column(db.String(20), nullable=False)
    amount = db.Column(Numeric(18, 2), nullable=False)
    
    # فیلد جدید برای لاگ: قیمت در زمان ورود/خروج
    transaction_price = db.Column(Numeric(18, 2), default=0.0)
    
    date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(200), nullable=True)

# ---> جدول جدید: مدیریت چک و اسناد دریافتنی/پرداختنی <---

class Cheque(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cheque_type = db.Column(db.String(50), nullable=False) 
    cheque_number = db.Column(db.String(50), nullable=False) 
    amount = db.Column(Numeric(18, 2), nullable=False) 
    issue_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=False) 
    bank_name = db.Column(db.String(100), nullable=True) 
    bank_branch = db.Column(db.String(100), nullable=True) 
    issuer_name = db.Column(db.String(100), nullable=True) 
    issuer_national_id = db.Column(db.String(20), nullable=True) 
    registered_to = db.Column(db.String(100), nullable=True) 
    registrar_national_id = db.Column(db.String(20), nullable=True) 
    reason = db.Column(db.String(200), nullable=True) 
    notes = db.Column(db.String(255), nullable=True) 
    image_path = db.Column(db.String(255), nullable=True) 
    status = db.Column(db.String(50), default='در جریان')
    
    # ---> فیلد جدید چک <---
    is_starred = db.Column(db.Boolean, default=False) # ستاره دار بودن چک
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)
    cheque_book_id = db.Column(db.Integer, db.ForeignKey('cheque_book.id'), nullable=True)


class ChequeBook(db.Model):
    """مدیریت دسته چک"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # نام دسته چک
    bank_name = db.Column(db.String(100), nullable=False)  # نام بانک
    start_number = db.Column(db.String(50), nullable=False)  # اولین شماره
    end_number = db.Column(db.String(50), nullable=False)  # آخرین شماره
    received_date = db.Column(db.Date, default=datetime.utcnow)  # تاریخ دریافت
    status = db.Column(db.String(20), default='فعال')  # فعال / مصرف شده / باطل
    notes = db.Column(db.String(255), nullable=True)
    cheques = db.relationship('Cheque', backref='cheque_book', lazy=True)

    @property
    def total_count(self):
        return int(self.end_number) - int(self.start_number) + 1 if self.end_number.isdigit() and self.start_number.isdigit() else 0

    @property
    def used_count(self):
        return len([c for c in self.cheques if not c.is_deleted])

    @property
    def remaining_count(self):
        return self.total_count - self.used_count

# ==========================================
# سیستم پیشرفته منابع انسانی (HR) و پرسنل بر اساس قانون کار
# ==========================================
class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_code = db.Column(db.String(50), unique=True, nullable=False) 
    name = db.Column(db.String(100), nullable=False)
    national_id = db.Column(db.String(20), nullable=True) 
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(50), default='کارگر ساده') 
    start_date = db.Column(db.Date, default=datetime.utcnow) 
    
    # اطلاعات تکمیلی و هویتی
    education = db.Column(db.String(100), nullable=True) # مدرک تحصیلی
    address = db.Column(db.String(255), nullable=True) # آدرس
    bank_account = db.Column(db.String(50), nullable=True) # شماره کارت/شبا
    
    # حقوق و مزایای ثابت ماهانه (قانون کار)
    salary = db.Column(Numeric(18, 2), default=0.0) # پایه حقوق
    housing_allowance = db.Column(Numeric(18, 2), default=0.0) # حق مسکن
    food_allowance = db.Column(Numeric(18, 2), default=0.0) # حق بن و خواربار
    family_allowance = db.Column(Numeric(18, 2), default=0.0) # حق عائله‌مندی (اولاد)
    
    insurance_status = db.Column(db.String(50), default='بدون بیمه')
    status = db.Column(db.String(50), default='فعال') 
    assigned_pen_id = db.Column(db.Integer, db.ForeignKey('pen.id'), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False) 
    
    tasks = db.relationship('Task', backref='worker', lazy=True, cascade="all, delete-orphan")
    events = db.relationship('WorkerEvent', backref='worker', lazy=True, cascade="all, delete-orphan") 
    loans = db.relationship('WorkerLoan', backref='worker', lazy=True, cascade="all, delete-orphan") 
    petty_cash_records = db.relationship('PettyCash', backref='worker', lazy=True, cascade="all, delete-orphan")
    documents = db.relationship('WorkerDocument', backref='worker', lazy=True, cascade="all, delete-orphan") # گالری مدارک پرسنلی

# خط خدمت پرسنل (تایم لاین)
class WorkerEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    event_type = db.Column(db.String(50), nullable=False) 
    event_date = db.Column(db.Date, default=datetime.utcnow)
    description = db.Column(db.String(255), nullable=True)

# وام و مساعده
class WorkerLoan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    loan_type = db.Column(db.String(50), nullable=False) 
    amount = db.Column(Numeric(18, 2), nullable=False)
    issue_date = db.Column(db.Date, default=datetime.utcnow)
    installment_amount = db.Column(Numeric(18, 2), nullable=True) 
    status = db.Column(db.String(50), default='در حال پرداخت') 
    document_image = db.Column(db.String(255), nullable=True) 
    description = db.Column(db.String(255), nullable=True)

class WorkerContract(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    contract_type = db.Column(db.String(50), nullable=False)  # دائم, موقت, فصلی, پروژه‌ای
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    monthly_salary = db.Column(Numeric(18, 2), default=0.0)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    worker = db.relationship('Worker', backref=db.backref('contracts', lazy=True, cascade='all, delete-orphan'))

class PettyCash(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    amount = db.Column(Numeric(18, 2), nullable=False) 
    action_type = db.Column(db.String(20), nullable=False) 
    record_date = db.Column(db.Date, default=datetime.utcnow)
    description = db.Column(db.String(255), nullable=True)

    # ==========================================
# جداول سیستم هوشمند (IoT، حسابرسی و استهلاک)
# ==========================================

# 1. جدول مچ‌گیری و حسابرسی (Audit Trail)
class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100), nullable=False) # چه کسی؟
    action = db.Column(db.String(255), nullable=False) # چه کاری کرد؟ (مثلا: ویرایش وزن پلاک 1024)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow) # چه زمانی؟
    ip_address = db.Column(db.String(50), nullable=True)

# 2. جدول تجهیزات برای استهلاک
class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    purchase_price = db.Column(Numeric(18, 2), nullable=False)
    purchase_date = db.Column(db.Date, default=datetime.utcnow)
    lifespan_years = db.Column(db.Integer, nullable=False) # عمر مفید (سال)
    scrap_value = db.Column(Numeric(18, 2), default=0.0) # ارزش اسقاط
    
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=True)
    transaction = db.relationship('Transaction', backref='linked_assets')

    @property
    def book_value(self):
        """محاسبه ارزش دفتری: بهای تمام شده منهای استهلاک انباشته"""
        from app.models import JournalEntryLine
        from decimal import Decimal
        # جستجوی تمام آرتیکل‌های بستانکار در دفتر کل که شامل نام این دارایی در شرح استهلاک هستند
        raw = db.session.query(db.func.sum(JournalEntryLine.credit)).filter(
            JournalEntryLine.description.ilike(f"%ذخیره استهلاک انباشته {self.name}%")
        ).scalar()
        accumulated = Decimal(str(raw)) if raw is not None else Decimal('0')
        return (self.purchase_price or Decimal('0')) - accumulated

# 3. جدول اینترنت اشیا (سنسورهای دما و رطوبت بهاربندها)
class SensorData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pen_id = db.Column(db.Integer, db.ForeignKey('pen.id'), nullable=False)
    temperature = db.Column(Numeric(5, 2), nullable=False)
    humidity = db.Column(Numeric(5, 2), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)


    # ==========================================
# سیستم دفتر کل اشخاص (نسیه، طلب، بدهی)
# ==========================================
class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False) # نام شخص، قصابی یا کارخانه
    phone = db.Column(db.String(20), nullable=True)
    contact_type = db.Column(db.String(50), default='عمومی') # مشتری، تامین‌کننده خوراک
    
    # فیلدهای جدید (کد اقتصادی و بانکی)
    economic_code = db.Column(db.String(50), nullable=True)
    bank_card = db.Column(db.String(30), nullable=True)

    # فرمول تراز: اگر مثبت باشد یعنی ما از او طلبکاریم، اگر منفی باشد یعنی ما به او بدهکاریم
    balance = db.Column(Numeric(18, 2), default=0.0) 
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    transactions = db.relationship('Transaction', backref='contact', lazy=True)
    cheques = db.relationship('Cheque', backref='contact', lazy=True)
    documents = db.relationship('ContactDocument', backref='contact', lazy=True, cascade="all, delete-orphan")

# ==========================================
# سیستم حقوق و دستمزد اتوماتیک (فیش حقوقی)
# ==========================================
# ارتقای جدول فیش حقوقی برای ثبت متغیرهای متغیر ماهانه
class Payslip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    month_name = db.Column(db.String(50), nullable=False) 
    issue_date = db.Column(db.Date, default=datetime.utcnow)
    
    # دریافتی ها
    base_salary = db.Column(Numeric(18, 2), default=0.0) 
    housing_allowance = db.Column(Numeric(18, 2), default=0.0) 
    food_allowance = db.Column(Numeric(18, 2), default=0.0) 
    family_allowance = db.Column(Numeric(18, 2), default=0.0) 
    
    overtime_pay = db.Column(Numeric(18, 2), default=0.0) # مبلغ اضافه کاری
    night_shift_pay = db.Column(Numeric(18, 2), default=0.0) # مبلغ شیفت شب
    transportation_pay = db.Column(Numeric(18, 2), default=0.0) # ایاب ذهاب
    mission_pay = db.Column(Numeric(18, 2), default=0.0) # حق ماموریت
    kpi_bonus = db.Column(Numeric(18, 2), default=0.0) # پاداش
    eydi_sanavat = db.Column(Numeric(18, 2), default=0.0) # عیدی و سنوات
    
    # کسورات
    loan_deduction = db.Column(Numeric(18, 2), default=0.0) 
    fines = db.Column(Numeric(18, 2), default=0.0) 
    insurance = db.Column(Numeric(18, 2), default=0.0) # بیمه سهم کارگر (7% مجموع دریافتی ناخالص)
    tax = db.Column(Numeric(18, 2), default=0.0) # مالیات
    
    gross_pay = db.Column(Numeric(18, 2), default=0.0) # ناخالص دریافتی
    net_pay = db.Column(Numeric(18, 2), default=0.0) # خالص پرداختی
    is_paid = db.Column(db.Boolean, default=False) 
    
    worker = db.relationship('Worker', backref='payslips')


# جدول جدید برای گالری مدارک پرسنل (کارت ملی، سفته، مدرک، قرارداد)
class WorkerDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    doc_title = db.Column(db.String(100), nullable=False) # عنوان مدرک (مثلا: کپی کارت ملی)
    file_path = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.Date, default=datetime.utcnow)

class ContactDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False)
    doc_title = db.Column(db.String(100), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.Date, default=datetime.utcnow)

class SystemSetting(db.Model):
    """ذخیره تنظیمات و متغیرهای کلیدی سیستم"""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)

class Unit(db.Model):
    """جدول برای مدیریت واحدهای اندازه گیری (کیلوگرم، سر، ویال و...)"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

class MedicineCategory(db.Model):
    """دسته‌بندی داروها (آنتی‌بیوتیک، واکسن، مکمل و...)"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class InventoryCategory(db.Model):
    """دسته‌بندی اقلام انبار (خوراک، دارو، تجهیزات و...)"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class BuyerCategory(db.Model):
    """انواع خریداران (قصاب، دلال، دامدار، شخصی)"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class TelegramBot(db.Model):
    """ذخیره چندین ربات تلگرام برای ارسال بک‌آپ"""
    id = db.Column(db.Integer, primary_key=True)
    bot_name = db.Column(db.String(100), nullable=False)
    bot_token = db.Column(db.String(255), nullable=False)
    chat_id = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)


class Budget(db.Model):
    """بودجه سالانه/ماهانه برای هر حساب"""
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)  # سال شمسی
    month = db.Column(db.Integer, nullable=True)  # ماه (برای بودجه ماهانه)، None=سالانه
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    amount = db.Column(Numeric(18, 2), nullable=False)  # سقف بودجه
    notes = db.Column(db.String(255), nullable=True)
    account = db.relationship('Account', backref='budgets')

    @property
    def spent(self):
        """میزان مصرف شده از بودجه بر اساس تراکنش‌های همان حساب"""
        from app import db
        from sqlalchemy import func
        from app.models import JournalEntryLine
        total = db.session.query(func.sum(JournalEntryLine.debit)).filter(
            JournalEntryLine.account_id == self.account_id
        ).scalar() or 0
        return float(total)


class Instalment(db.Model):
    """قسط بندی - قرارداد اقساط با مشتری"""
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False)
    total_amount = db.Column(Numeric(18, 2), nullable=False)
    paid_amount = db.Column(Numeric(18, 2), default=0.0)
    instalment_count = db.Column(db.Integer, nullable=False)  # تعداد کل اقساط
    amount_per_instalment = db.Column(Numeric(18, 2), nullable=False)  # مبلغ هر قسط
    start_date = db.Column(db.Date, nullable=False)
    interval_days = db.Column(db.Integer, default=30)  # فاصله بین اقساط (روز)
    description = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='فعال')  # فعال / تسویه شده / مشکل دار
    contact = db.relationship('Contact', backref='instalments')

    @property
    def remaining(self):
        return float(self.total_amount - self.paid_amount)

    @property
    def due_instalments(self):
        """تعداد اقساط سررسید شده پرداخت نشده"""
        from datetime import date
        today = date.today()
        passed = (today - self.start_date).days // self.interval_days
        paid = int(float(self.paid_amount) / float(self.amount_per_instalment)) if self.amount_per_instalment else 0
        return max(0, passed - paid)


class DailyAttendance(db.Model):
    """ثبت روزانه حضور و غیاب کارگران — اضافه‌کاری، شیفت شب، مرخصی"""
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='حاضر')  # حاضر / غایب / مرخصی / ماموریت
    overtime_hours = db.Column(db.Float, default=0.0)  # ساعت اضافه‌کاری
    night_shift_hours = db.Column(db.Float, default=0.0)  # ساعت شب‌کاری
    fine_amount = db.Column(Numeric(18, 2), default=0.0)  # جریمه نقدی
    notes = db.Column(db.String(255), nullable=True)
    payslip_id = db.Column(db.Integer, db.ForeignKey('payslip.id'), nullable=True)  # ارجاع به فیش حقوقی صادر شده
    worker = db.relationship('Worker', backref='attendances')


class LivestockCost(db.Model):
    """هزینه‌های ثبت شده برای محاسبه بهای تمام شده هر دام"""
    id = db.Column(db.Integer, primary_key=True)
    sheep_id = db.Column(db.Integer, db.ForeignKey('sheep.id'), nullable=False)
    cost_type = db.Column(db.String(50), nullable=False)  # خوراک / دارو / سایر
    amount = db.Column(Numeric(18, 2), nullable=False)
    record_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    sheep = db.relationship('Sheep', backref='costs')

# ==========================================
# تولیدمثل، سونوگرافی و اصلاح نژاد
# ==========================================

class MatingRecord(db.Model):
    """ثبت جفت‌اندازی و تلقیح"""
    id = db.Column(db.Integer, primary_key=True)
    sheep_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='CASCADE'), nullable=False, index=True)
    male_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='SET NULL'), nullable=True, index=True)
    mating_date = db.Column(db.Date, nullable=False)
    mating_type = db.Column(db.String(50), default='طبیعی')  # طبیعی, تلقیح مصنوعی, لاپاراسکوپی
    semen_id = db.Column(db.Integer, db.ForeignKey('semen_inventory.id', ondelete='SET NULL'), nullable=True)
    result = db.Column(db.String(50), default='منتظر نتیجه')  # منتظر نتیجه, آبستن, خالی, سقط
    result_date = db.Column(db.Date, nullable=True)
    confirmed_by = db.Column(db.String(50), nullable=True)  # سونوگرافی, لمس, مشاهده
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sheep = db.relationship('Sheep', foreign_keys=[sheep_id], backref='matings_as_female')
    male = db.relationship('Sheep', foreign_keys=[male_id], backref='matings_as_male')

class UltrasoundRecord(db.Model):
    """ثبت نتایج سونوگرافی"""
    id = db.Column(db.Integer, primary_key=True)
    sheep_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='CASCADE'), nullable=False, index=True)
    exam_date = db.Column(db.Date, nullable=False)
    exam_type = db.Column(db.String(50), default='روتین')  # روتین, تشخیصی, تأیید آبستنی, فولیکولی
    result = db.Column(db.String(50), nullable=False)  # آبستن, خالی, سقط, نامشخص, تخمک‌گذاری
    fetus_count = db.Column(db.Integer, nullable=True)
    gestational_days = db.Column(db.Integer, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sheep = db.relationship('Sheep', backref='ultrasounds')
    images = db.relationship('UltrasoundImage', backref='record', lazy=True, cascade='all, delete-orphan')

class UltrasoundImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ultrasound_id = db.Column(db.Integer, db.ForeignKey('ultrasound_record.id', ondelete='CASCADE'), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)

class SemenInventory(db.Model):
    """مدیریت اسپرم/سیمن برای تلقیح مصنوعی"""
    id = db.Column(db.Integer, primary_key=True)
    ram_name = db.Column(db.String(100), nullable=False)
    ram_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='SET NULL'), nullable=True)
    breed = db.Column(db.String(50), nullable=True)
    collection_date = db.Column(db.Date, nullable=True)
    quantity_doses = db.Column(db.Integer, default=0)
    price_per_dose = db.Column(Numeric(18, 2), default=0.0)
    storage_location = db.Column(db.String(100), nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(255), nullable=True)

# ==========================================
# قرنطینه و اپیدمیولوژی
# ==========================================

class QuarantineRecord(db.Model):
    """مدیریت قرنطینه دام‌های جدید یا بیمار"""
    id = db.Column(db.Integer, primary_key=True)
    sheep_id = db.Column(db.Integer, db.ForeignKey('sheep.id', ondelete='CASCADE'), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    reason = db.Column(db.String(100), nullable=False)  # دام جدید, بیماری, بازگشت از نمایشگاه
    expected_end_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    sheep = db.relationship('Sheep', backref='quarantines')

# ==========================================
# انبار دارو
# ==========================================

class DrugInventory(db.Model):
    """موجودی داروهای دامپزشکی"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), default='عمومی')  # آنتی‌بیوتیک, واکسن, مکمل, ضدانگل, ضدالتهاب, سایر
    stock_quantity = db.Column(Numeric(18, 2), default=0.0)
    unit = db.Column(db.String(20), default='عدد')  # عدد, سی‌سی, میلی‌لیتر, گرم, دوز
    price_per_unit = db.Column(Numeric(18, 2), default=0.0)
    supplier = db.Column(db.String(100), nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)
    min_stock_alert = db.Column(Numeric(18, 2), default=0.0)
    notes = db.Column(db.String(255), nullable=True)