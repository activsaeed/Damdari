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

def seed_data():
    app = create_app()
    with app.app_context():
        print("🚀 شروع عملیات بذرپاشی هوشمند و جامع...")
        
        print("🧹 مرحله 1: پاکسازی و نوسازی دیتابیس...")
        db.drop_all()
        db.create_all()

        today = datetime.now(UTC).date()
        six_months_ago = today - timedelta(days=180)

        print("⚙️ مرحله 1.5: تنظیمات سیستمی...")
        settings = [
            SystemSetting(key='market_price', value='285000', description='قیمت هر کیلو گوشت زنده'),
            SystemSetting(key='vat_rate', value='10', description='نرخ مالیات بر ارزش افزوده'),
            SystemSetting(key='maturity_days', value='240', description='سن بلوغ بره'),
            SystemSetting(key='birth_weight', value='3.8', description='میانگین وزن تولد'),
            SystemSetting(key='daily_feed_est', value='16000', description='تخمین هزینه خوراک روزانه هر راس'),
            SystemSetting(key='page_size', value='50', description='تعداد ردیف در هر صفحه'),
            SystemSetting(key='farm_name', value='مجتمع دامپروری صنعتی نمونه', description='نام فارم')
        ]
        db.session.add_all(settings)

        print("👥 مرحله 2: ساخت کاربران...")
        admin = User(username='admin', name='سعید (مدیر کل)', role='مدیر', 
                     password_hash=generate_password_hash('123456'),
                     can_view_livestock=True, can_view_finance=True, can_view_inventory=True, 
                     can_view_hr=True, can_view_reports=True, can_view_settings=True)
        
        vet = User(username='vet', name='دکتر حسینی (دامپزشک)', role='دامپزشک', 
                   password_hash=generate_password_hash('123456'),
                   can_view_livestock=True, can_view_inventory=True, can_view_reports=True)
        
        worker_user = User(username='ahmad', name='احمد (کارگر)', role='کارگر', 
                           password_hash=generate_password_hash('123456'),
                           can_view_livestock=True)
        db.session.add_all([admin, vet, worker_user])
        db.session.commit()
        
        print("🏗️ مرحله 3: تنظیمات پایه...")
        breed_names = ['افشاری', 'شال', 'رومانف', 'مغانی', 'قزل', 'بختیاری']
        breed_objs = [BreedCategory(name=n) for n in breed_names]
        db.session.add_all(breed_objs)
        db.session.flush()
        
        pens = [Pen(name=f"سالن {i}", capacity=100, pen_type="پرواری" if i<4 else "داشتی") for i in range(1, 6)]
        db.session.add_all(pens)
        
        rations = [FeedRation(name="جیره استارتر", daily_cost=12000), FeedRation(name="جیره پرواری سنگین", daily_cost=18500)]
        db.session.add_all(rations)
        
        status_list = [StatusCategory(name=n, type='عادی') for n in ['زنده و سالم', 'آبستن']]
        status_list += [StatusCategory(name=n, type='خطر') for n in ['بیمار', 'قرنطینه']]
        db.session.add_all(status_list)
        
        purposes = [PurposeCategory(name=n) for n in ['پرواربندی', 'داشتی (تولیدمثل)']]
        db.session.add_all(purposes)

        print("📑 مرحله 3.5: ساخت دفتر اشخاص...")
        contacts = [
            Contact(name="تعاونی خوراک البرز", contact_type="تامین‌کننده", balance=-25000000),
            Contact(name="کشتارگاه صنعتی ری", contact_type="مشتری", balance=45000000),
            Contact(name="پخش دارو دامی رازی", contact_type="تامین‌کننده", balance=-5000000),
            Contact(name="فروشگاه محصولات لبنی", contact_type="مشتری", balance=8000000)
        ]
        db.session.add_all(contacts)
        db.session.commit()

        print("💊 مرحله 3.8: ساخت دسته‌بندی‌های دارویی و خریداران...")
        mc_vax = MedicineCategory(name="واکسن")
        mc_med = MedicineCategory(name="دارو/درمان")
        mc_sup = MedicineCategory(name="مکمل/ویتامین")
        ic_fodder = InventoryCategory(name="علوفه")
        ic_feed = InventoryCategory(name="خوراک")
        ic_med = InventoryCategory(name="دارو")
        db.session.add_all([mc_vax, mc_med, mc_sup, ic_fodder, ic_feed, ic_med])

        bc_1 = BuyerCategory(name="قصاب/کشتارگاه")
        bc_2 = BuyerCategory(name="دامدار (پرورش)")
        bc_3 = BuyerCategory(name="واسطه/دلال")
        bc_4 = BuyerCategory(name="مصرف‌کننده شخصی")
        db.session.add_all([bc_1, bc_2, bc_3, bc_4])
        db.session.commit()

        print("🧪 مرحله 3.9: تعریف داروهای پایه...")
        vax_fmd = Medicine(name="واکسن تب برفکی", medicine_category_id=mc_vax.id)
        vax_pox = Medicine(name="واکسن آبله", medicine_category_id=mc_vax.id)
        med_pen = Medicine(name="پنیسیلین", medicine_category_id=mc_med.id)
        med_ivo = Medicine(name="آیورمکتین", medicine_category_id=mc_med.id)
        db.session.add_all([vax_fmd, vax_pox, med_pen, med_ivo])
        db.session.commit()

        db.session.add(TreatmentTemplate(name="پروتکل عفونت تنفسی", medicines="پنیسیلین، ویتامین C", description="تزریق عضلانی ۳ مرحله"))
        db.session.add_all([
            FeedingSchedule(feed_ration_id=rations[0].id, time_of_day='صبح', feed_type='جو روسی', amount_kg=0.5),
            FeedingSchedule(feed_ration_id=rations[1].id, time_of_day='ظهر', feed_type='کنسانتره پرواری', amount_kg=1.2)
        ])
        db.session.commit()

        print("📏 مرحله 3.6: ساخت واحدهای اندازه‌گیری...")
        u_kg = Unit(name="کیلوگرم", description="وزن")
        u_vial = Unit(name="عدد/ویال", description="دارو")
        u_head = Unit(name="سر", description="شمارش دام")
        db.session.add_all([u_kg, u_vial, u_head])
        db.session.commit()

        print("📊 مرحله 3.7: تولید کدینگ استاندارد حسابداری ایران...")
        # ساخت ماهیت حساب ها
        t_asset = AccountType(name="دارایی", nature="بدهکار")
        t_liability = AccountType(name="بدهی", nature="بستانکار")
        t_equity = AccountType(name="حقوق صاحبان سهام", nature="بستانکار")
        t_revenue = AccountType(name="درآمد", nature="بستانکار")
        t_expense = AccountType(name="هزینه", nature="بدهکار")
        db.session.add_all([t_asset, t_liability, t_equity, t_revenue, t_expense])
        db.session.commit()

                # ساخت حساب های کل استاندارد حسابداری ایران (۴ رقمی)
        accounts = [
            Account(code="1010", name="موجودی نقد و بانک", account_type_id=t_asset.id),
            Account(code="1020", name="موجودی کالا و انبار", account_type_id=t_asset.id),
            Account(code="1030", name="حساب‌ها و اسناد دریافتنی (مشتریان)", account_type_id=t_asset.id),
            Account(code="1040", name="پیش‌پرداخت‌ها و اعتبار مالیاتی", account_type_id=t_asset.id),
            Account(code="1200", name="دارایی‌های زیستی (گله)", account_type_id=t_asset.id),
            Account(code="2010", name="حساب‌ها و اسناد پرداختنی (تامین‌کنندگان)", account_type_id=t_liability.id),
            Account(code="2030", name="مالیات بر ارزش افزوده پرداختنی", account_type_id=t_liability.id),
            Account(code="3010", name="سرمایه اولیه/ثبتی", account_type_id=t_equity.id),
            Account(code="3020", name="سود و زیان انباشته", account_type_id=t_equity.id),
            Account(code="4010", name="درآمد عملیاتی (فروش)", account_type_id=t_revenue.id),
            Account(code="5010", name="هزینه‌های عملیاتی و توزیع", account_type_id=t_expense.id)
        ]

        db.session.bulk_save_objects(accounts)
        db.session.commit()

        print("💰 مرحله 4: تولید 300 فاکتور و 300 چک...")
        all_contacts = Contact.query.all()
        income_cats = ['فروش دام', 'فروش شیر', 'فروش پشم', 'فروش کود']
        expense_cats = ['خرید علوفه', 'خرید دارو', 'هزینه تعمیرات', 'حقوق و دستمزد']
        
        for i in range(300):
            t_type = random.choice(['هزینه', 'درآمد'])
            contact = random.choice(all_contacts) if random.random() > 0.5 else None
            tx = Transaction(
                t_type=t_type, amount=random.randint(500000, 100000000),
                category=random.choice(expense_cats if t_type=='هزینه' else income_cats),
                t_date=today - timedelta(days=random.randint(0, 365)),
                party_name=contact.name if contact else f"شخص متفرقه {i}",
                contact_id=contact.id if contact else None,
                is_archived=random.random() > 0.95,
                description=f"توضیحات فاکتور {i}"
            )
            db.session.add(tx)
            db.session.flush() # دریافت ID برای ثبت سند

            # ثبت خودکار در دفاتر حسابداری از طریق موتور حسابداری
            try:
                if t_type == 'درآمد':
                    AccountingEngine.record_sale(tx, contact_id=tx.contact_id, include_vat=True)
                else:
                    AccountingEngine.record_expense(tx, contact_id=tx.contact_id, include_vat=True)
            except Exception as e:
                db.session.rollback()

        for i in range(300):
            contact = random.choice(all_contacts) if random.random() > 0.7 else None
            db.session.add(Cheque(
                cheque_type=random.choice(['دریافتی (مشتری)', 'پرداختی (خودم)']),
                cheque_number=f"CHQ-{random.randint(100000, 999999)}",
                amount=random.randint(5000000, 200000000),
                due_date=today + timedelta(days=random.randint(-30, 200)),
                status=random.choices(['در جریان', 'پاس شده', 'برگشت خورده'], weights=[60, 35, 5])[0],
                bank_name=random.choice(['ملی', 'ملت', 'تجارت', 'کشاورزی'])
            ))
        db.session.commit()

        print("🌾 مرحله 5: شارژ انبار...")
        items = [
            InventoryItem(name="جو روسی", category_id=ic_feed.id, quantity=5000, min_threshold=1000, unit_id=u_kg.id, unit_price=13500),
            InventoryItem(name="یونجه دشت مغان", category_id=ic_fodder.id, quantity=800, min_threshold=2000, unit_id=u_kg.id, unit_price=19000), # هشدار کمبود
            InventoryItem(name="کنسانتره پرواری", category_id=ic_feed.id, quantity=12000, min_threshold=2000, unit_id=u_kg.id, unit_price=22000),
            InventoryItem(name="پنیسیلین", category_id=ic_med.id, quantity=50, min_threshold=10, unit_id=u_vial.id, unit_price=75000),
            InventoryItem(name="واکسن تب برفکی", category_id=ic_med.id, quantity=200, min_threshold=50, unit_id=u_vial.id, unit_price=120000, expiry_date=today + timedelta(days=15)) # هشدار انقضا
        ]
        db.session.add_all(items)
        db.session.commit()

        print("👷 مرحله 6: تولید لیست پرسنل و وظایف...")
        workers = [
            Worker(worker_code="PR-1001", name="احمد محمدی", role="کارگر ارشد", salary=15000000, housing_allowance=9000000, food_allowance=14000000, status="فعال", assigned_pen_id=pens[0].id),
            Worker(worker_code="PR-1002", name="رضا اسدی", role="کارگر", salary=12000000, status="فعال", assigned_pen_id=pens[1].id)
        ]
        db.session.add_all(workers)
        db.session.flush()

        # ثبت فیش حقوقی برای تست گزارش بیمه
        for w in workers:
            for m in ["تیر", "مرداد", "شهریور"]:
                p = Payslip(worker_id=w.id, month_name=f"{m} 1403", base_salary=w.salary, gross_pay=w.salary+23000000, net_pay=w.salary+20000000, is_paid=True)
                db.session.add(p)
                db.session.flush()
                AccountingEngine.record_payroll(p)
            
            db.session.add(Task(worker_id=w.id, description="تغذیه نوبت عصر سالن 1", task_date=today, is_done=False))
            db.session.add(PettyCash(worker_id=w.id, amount=500000, action_type='شارژ تنخواه', description='هزینه بنزین تراکتور'))
            db.session.add(WorkerLoan(worker_id=w.id, loan_type='مساعده', amount=2000000, status='در حال پرداخت', installment_amount=500000))

        db.session.commit()

        print("🐑 مرحله 7: بذرپاشی 300 رأس دام با چرخه حیات کامل...")
        all_pens = Pen.query.all()
        all_rations = FeedRation.query.all()
        genders = ['میش', 'قوچ', 'بره نر', 'بره ماده']
        
        for i in range(300):
            gender = random.choices(genders, weights=[40, 10, 25, 25])[0]
            birth_days_ago = random.randint(10, 1500)
            status = random.choices(['زنده و سالم', 'آبستن', 'بیمار', 'فروخته شده', 'تلف شده'], weights=[70, 15, 5, 5, 5])[0]
            
            s = Sheep(
                ear_tag=f"ID-{i+1000}",
                breed=random.choice(breed_names),
                gender=gender,
                status=status,
                birth_date=today - timedelta(days=birth_days_ago),
                weight=random.uniform(15.0, 95.0),
                pen_id=random.choice(all_pens).id,
                feed_ration_id=random.choice(all_rations).id,
                purpose=random.choice(['پرواربندی', 'داشتی (تولیدمثل)']),
                purchase_price=random.randint(5000000, 12000000)
            )
            if status == 'فروخته شده':
                s.sale_date = today - timedelta(days=random.randint(1, 60))
                s.sale_price = s.purchase_price + random.randint(3000000, 8000000)
            if status == 'تلف شده':
                s.death_reason = random.choice(['نفخ شدید', 'عفونت ریه', 'اسهال خونی'])

            db.session.add(s)
            db.session.flush()

            # بذرپاشی تاریخچه وزن (برای نمودار رشد)
            for w_idx in range(5):
                db.session.add(WeightRecord(
                    sheep_id=s.id, weight=s.weight - (w_idx * 5),
                    record_date=today - timedelta(days=(w_idx+1) * 30)
                ))
            
            # بذرپاشی سوابق پزشکی
            if random.random() > 0.5:
                db.session.add(MedicalRecord(
                    sheep_id=s.id, action_type=random.choice(['واکسن', 'درمان']),
                    medicine_name=random.choice(['تب برفکی', 'پنیسیلین']),
                    record_date=today - timedelta(days=random.randint(5, 100)),
                    withdrawal_end_date=today + timedelta(days=random.randint(-10, 10))
                ))
            
            # بذرپاشی زایش برای میش ها
            if gender == 'میش' and birth_days_ago > 400:
                db.session.add(BirthRecord(
                    mother_id=s.id, lambs_count=random.choice([1, 2]),
                    birth_date=today - timedelta(days=random.randint(150, 300)),
                    status='موفق'
                ))

        db.session.commit()
        
        print("📉 مرحله نهایی: ایجاد تراکنش‌های انبار برای نمودارها...")
        items = InventoryItem.query.all()
        for item in items:
            for d in range(1, 6):
                db.session.add(InventoryLog(
                    item_id=item.id, action_type='ورود', 
                    amount=random.randint(100, 1000), 
                    transaction_price=item.unit_price,
                    date=today - timedelta(days=d*30)
                )
                )
        db.session.commit()

        print("✨ بذرپاشی هوشمند با موفقیت به پایان رسید. تمام بخش‌های سیستم دارای دیتای نمونه هستند.")

if __name__ == '__main__':
    seed_data()