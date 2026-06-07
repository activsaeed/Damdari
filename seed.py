import os
import random
from datetime import datetime, timedelta, UTC
from werkzeug.security import generate_password_hash
from app import create_app, db
from app.accounting_engine import AccountingEngine
from app.models import (User, Sheep, WeightRecord, MedicalRecord, BirthRecord, 
                        FeedRation, Pen, Medicine, BreedCategory, PurposeCategory, 
                        StatusCategory, Transaction, TransactionCategory, 
                        InventoryItem, InventoryLog, Worker, Cheque, TreatmentTemplate,
                        Contact, AccountType, Account, PettyCash, Task, Unit,
                        MedicineCategory, BuyerCategory, InventoryCategory,
                        SystemSetting, Payslip, WorkerLoan, FeedingSchedule)

def get_or_create(model, filter_key, **kwargs):
    """جلوگیری از ایجاد رکوردهای تکراری بر اساس یک کلید مشخص"""
    instance = db.session.query(model).filter_by(**{filter_key: kwargs.get(filter_key)}).first()
    if not instance:
        instance = model(**kwargs)
        db.session.add(instance)
        db.session.flush()
    return instance

def seed_data():
    app = create_app()
    with app.app_context():
        print("🚀 شروع عملیات بذرپاشی هوشمند...")

        today = datetime.now(UTC).date()

        print("⚙️ مرحله 1.5: تنظیمات سیستمی...")
        sys_settings = [
            {'key': 'market_price', 'value': '285000', 'description': 'قیمت هر کیلو گوشت زنده'},
            {'key': 'vat_rate', 'value': '10', 'description': 'نرخ مالیات بر ارزش افزوده'},
            {'key': 'maturity_days', 'value': '240', 'description': 'سن بلوغ بره'},
            {'key': 'birth_weight', 'value': '3.8', 'description': 'میانگین وزن تولد'},
            {'key': 'daily_feed_est', 'value': '16000', 'description': 'تخمین هزینه خوراک روزانه هر راس'},
            {'key': 'page_size', 'value': '50', 'description': 'تعداد ردیف در هر صفحه'},
            {'key': 'farm_name', 'value': 'مجتمع دامپروری صنعتی نمونه', 'description': 'نام فارم'},
            {'key': 'currency_unit', 'value': 'تومان', 'description': 'واحد پول سیستم'}
        ]
        for s in sys_settings:
            get_or_create(SystemSetting, 'key', **s)

        print("👥 مرحله 2: ساخت کاربران...")
        users = [
            {'username': 'admin', 'name': 'سعید (مدیر کل)', 'role': 'مدیر', 
             'password_hash': generate_password_hash('123456'), 'can_view_livestock': True, 
             'can_view_finance': True, 'can_view_inventory': True, 'can_view_hr': True, 
             'can_view_reports': True, 'can_view_settings': True},
            {'username': 'vet', 'name': 'دکتر حسینی', 'role': 'دامپزشک', 
             'password_hash': generate_password_hash('123456'), 'can_view_livestock': True, 
             'can_view_inventory': True, 'can_view_reports': True},
        ]
        for u in users:
            get_or_create(User, 'username', **u)
        db.session.commit()
        
        print("🏗️ مرحله 3: تنظیمات پایه...")
        breed_names = ['افشاری', 'شال', 'رومانف', 'مغانی', 'قزل', 'بختیاری']
        for n in breed_names:
            get_or_create(BreedCategory, 'name', name=n)
        
        for i in range(1, 6):
            get_or_create(Pen, 'name', name=f"سالن {i}", capacity=100, pen_type="پرواری" if i<4 else "داشتی")
        
        get_or_create(FeedRation, 'name', name="جیره استارتر", daily_cost=12000)
        get_or_create(FeedRation, 'name', name="جیره پرواری سنگین", daily_cost=18500)
        
        status_list = [StatusCategory(name=n, type='عادی') for n in ['زنده و سالم', 'آبستن']]
        status_list += [StatusCategory(name=n, type='خطر') for n in ['بیمار', 'قرنطینه']]
        for s in status_list:
            get_or_create(StatusCategory, 'name', name=s.name, type=s.type)
        
        for n in ['پرواربندی', 'داشتی (تولیدمثل)']:
            get_or_create(PurposeCategory, 'name', name=n)

        print("📑 مرحله 3.5: ساخت دفتر اشخاص...")
        contacts = [
            {'name': "تعاونی خوراک البرز", 'contact_type': "تامین‌کننده", 'balance': -25000000},
            {'name': "کشتارگاه صنعتی ری", 'contact_type': "مشتری", 'balance': 45000000},
        ]
        for c in contacts:
            get_or_create(Contact, 'name', **c)
        db.session.commit()

        print("📏 مرحله 3.6: واحدهای اندازه‌گیری...")
        units = [
            {'name': "کیلوگرم", 'description': "وزن"},
            {'name': "عدد/ویال", 'description': "دارو"},
            {'name': "سر", 'description': "شمارش دام"}
        ]
        for u in units:
            get_or_create(Unit, 'name', **u)
        db.session.commit()

        print("💊 مرحله 3.8: دسته‌بندی‌ها...")
        for n in ["واکسن", "دارو/درمان", "مکمل/ویتامین"]:
            get_or_create(MedicineCategory, 'name', name=n)
        
        inv_cats = []
        for n in ["علوفه", "خوراک", "دارو", "تجهیزات"]:
            inv_cats.append(get_or_create(InventoryCategory, 'name', name=n))
            
        for n in ["قصاب/کشتارگاه", "دامدار", "واسطه"]:
            get_or_create(BuyerCategory, 'name', name=n)
        db.session.commit()

        print("📦 مرحله 3.11: بذرپاشی انبار اولیه...")
        unit_kg = Unit.query.filter_by(name="کیلوگرم").first()
        cat_feed = InventoryCategory.query.filter_by(name="خوراک").first()
        if unit_kg and cat_feed:
            inventory_seeds = [
                {'name': 'جو محلی', 'category_id': cat_feed.id, 'unit_id': unit_kg.id, 'quantity': 1500, 'unit_price': 12500, 'min_threshold': 500},
                {'name': 'ذرت دامی', 'category_id': cat_feed.id, 'unit_id': unit_kg.id, 'quantity': 800, 'unit_price': 11000, 'min_threshold': 300},
                {'name': 'یونجه خشک', 'category_id': cat_feed.id, 'unit_id': unit_kg.id, 'quantity': 2000, 'unit_price': 9500, 'min_threshold': 1000},
            ]
            for item in inventory_seeds:
                get_or_create(InventoryItem, 'name', **item)
        db.session.commit()

        print("🧪 مرحله 3.9: تعریف داروهای پایه...")
        mc_vax = MedicineCategory.query.filter_by(name="واکسن").first()
        if mc_vax:
            get_or_create(Medicine, 'name', name="واکسن تب برفکی", medicine_category_id=mc_vax.id)

        print("💰 مرحله 3.10: ساخت دسته‌بندی‌های مالی با تگ سیستمی...")
        fin_cats = [
            {'name': "فروش دام", 't_type': "درآمد", 'system_tag': "SYS_LIVESTOCK_SALE"},
            {'name': "خرید انبار (خودکار)", 't_type': "هزینه", 'system_tag': "SYS_INVENTORY"},
            {'name': "حقوق و دستمزد", 't_type': "هزینه", 'system_tag': "SYS_PAYROLL"},
            {'name': "استهلاک", 't_type': "هزینه", 'system_tag': "SYS_DEPRECIATION"},
            {'name': "تسویه حساب اشخاص", 't_type': "هزینه", 'system_tag': "SYS_SETTLEMENT"}
        ]
        for fc in fin_cats:
            get_or_create(TransactionCategory, 'system_tag', **fc)

        print("📊 مرحله 3.7: تولید کدینگ استاندارد حسابداری ایران...")
        # ساخت ماهیت حساب ها
        t_asset = get_or_create(AccountType, 'name', name="دارایی", nature="بدهکار")
        t_liability = get_or_create(AccountType, 'name', name="بدهی", nature="بستانکار")
        t_equity = get_or_create(AccountType, 'name', name="حقوق صاحبان سهام", nature="بستانکار")
        t_revenue = get_or_create(AccountType, 'name', name="درآمد", nature="بستانکار")
        t_expense = get_or_create(AccountType, 'name', name="هزینه", nature="بدهکار")
        db.session.commit()

        # ساخت حساب های کل استاندارد
        accounts = [
            {'code': "1010", 'name': "موجودی نقد و بانک", 'account_type_id': t_asset.id},
            {'code': "1020", 'name': "موجودی کالا و انبار", 'account_type_id': t_asset.id},
            {'code': "1030", 'name': "حساب‌های دریافتنی", 'account_type_id': t_asset.id},
            {'code': "1040", 'name': "اعتبار مالیاتی (مالیات خرید)", 'account_type_id': t_asset.id},
            {'code': "1200", 'name': "دارایی‌های زیستی (گله)", 'account_type_id': t_asset.id},
            {'code': "2010", 'name': "حساب‌های پرداختنی", 'account_type_id': t_liability.id},
            {'code': "2030", 'name': "مالیات پرداختنی (مالیات فروش)", 'account_type_id': t_liability.id},
            {'code': "4010", 'name': "درآمد عملیاتی", 'account_type_id': t_revenue.id},
            {'code': "5010", 'name': "هزینه‌های عملیاتی", 'account_type_id': t_expense.id}
        ]
        for acc in accounts:
            get_or_create(Account, 'code', **acc)
        db.session.commit()

        if Sheep.query.count() == 0:
            print("🐑 مرحله 7: تولید دام نمونه...")
            breeds = BreedCategory.query.all()
            pens = Pen.query.all()
            rations = FeedRation.query.all()
            
            for i in range(1, 21): # ایجاد ۲۰ راس دام نمونه
                breed = random.choice(breeds).name if breeds else 'افشاری'
                gender = random.choice(['میش', 'قوچ', 'بره ماده', 'بره نر'])
                status = 'آبستن' if gender == 'میش' and random.random() > 0.7 else 'زنده و سالم'
                
                new_sheep = Sheep(
                    ear_tag=f"TAG-{1000 + i}",
                    breed=breed,
                    gender=gender,
                    weight=random.uniform(30, 80),
                    status=status,
                    purpose='پرواربندی' if 'بره' in gender else 'داشتی (تولیدمثل)',
                    birth_date=today - timedelta(days=random.randint(100, 1000)),
                    pen_id=random.choice(pens).id if pens else None,
                    feed_ration_id=random.choice(rations).id if rations else None,
                    purchase_price=random.randint(5000000, 15000000)
                )
                db.session.add(new_sheep)
            db.session.commit()

        print("✨ بذرپاشی هوشمند با موفقیت به پایان رسید. تمام بخش‌های سیستم دارای دیتای نمونه هستند.")
        db.session.commit()

if __name__ == '__main__':
    seed_data()