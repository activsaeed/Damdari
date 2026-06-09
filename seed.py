import os, sys, random
from datetime import datetime, timedelta, UTC
from decimal import Decimal
from werkzeug.security import generate_password_hash
from app import create_app, db
from app.accounting_engine import AccountingEngine
from app.models import *

def get_or_create(model, filter_key, **kwargs):
    instance = db.session.query(model).filter_by(**{filter_key: kwargs.get(filter_key)}).first()
    if not instance:
        instance = model(**kwargs)
        db.session.add(instance)
        db.session.flush()
    return instance

IRR = lambda: random.randint(100000, 50000000)
NAME_PARTS = ['رضا', 'علي', 'محمد', 'حسين', 'مهدي', 'حسن', 'عباس', 'امير', 'سعيد', 'احمد',
              'زهرا', 'مريم', 'فاطمه', 'الناز', 'سارا', 'نگين', 'مينا', 'ليلا', 'نرگس', 'سميرا']
FAMILY_PARTS = ['احمدي', 'محمدي', 'حسيني', 'رضايي', 'مهدوي', 'حسن پور', 'عباسي', 'اميري',
                'سعيدي', 'کريمي', 'موسوي', 'يزداني', 'نوروزي', 'صادقي', 'جعفري', 'قاسمي',
                'مرادي', 'محمدزاده', 'اکبري', 'رستمي']
COMPANY_NAMES = ['دامداري', 'کشتارگاه', 'تعاوني', 'شرکت', 'کارخانه', 'واردات', 'توليدي']
COMPANY_SUFFIX = ['البرز', 'تهران', 'اصفهان', 'شيراز', 'تبريز', 'مشهد', 'کرج', 'قم', 'يزد', 'اهواز']

def random_contact_name():
    if random.random() > 0.4:
        return f'{random.choice(NAME_PARTS)} {random.choice(FAMILY_PARTS)}'
    return f'{random.choice(COMPANY_NAMES)} {random.choice(COMPANY_SUFFIX)}'

def seed_data():
    app = create_app()
    with app.app_context():
        print('='*60)
        print('  بذرپاشي سنگين - شروع عمليات')
        print('='*60)
        today = datetime.now(UTC).date()
        six_months_ago = today - timedelta(days=180)

        # --- 1. SYSTEM SETTINGS ---
        print('\n[1/25] تنظيمات سيستمي...')
        for s in [
            {'key': 'market_price', 'value': '285000', 'description': 'قيمت هر کيلو گوشت زنده'},
            {'key': 'vat_rate', 'value': '10', 'description': 'نرخ ماليات بر ارزش افزوده'},
            {'key': 'maturity_days', 'value': '240', 'description': 'سن بلوغ بره'},
            {'key': 'birth_weight', 'value': '3.8', 'description': 'ميانگين وزن تولد'},
            {'key': 'daily_feed_est', 'value': '16000', 'description': 'تخمين هزينه خوراک روزانه هر راس'},
            {'key': 'page_size', 'value': '50', 'description': 'تعداد رديف در هر صفحه'},
            {'key': 'farm_name', 'value': 'مجتمع دامپروري صنعتي نمونه', 'description': 'نام فارم'},
            {'key': 'currency_unit', 'value': 'تومان', 'description': 'واحد پول سيستم'}
        ]: get_or_create(SystemSetting, 'key', **s)
        db.session.commit()

        # --- 2. USERS ---
        print('[2/25] کاربرها...')
        for u in [
            {'username': 'admin', 'name': 'سعيد (مدير کل)', 'role': 'مدير',
             'password_hash': generate_password_hash('123456'), 'can_view_livestock': True,
             'can_view_finance': True, 'can_view_inventory': True, 'can_view_hr': True,
             'can_view_reports': True, 'can_view_settings': True},
            {'username': 'vet', 'name': 'دکتر حسيني', 'role': 'دامپزشک',
             'password_hash': generate_password_hash('123456'), 'can_view_livestock': True,
             'can_view_inventory': True, 'can_view_reports': True},
            {'username': 'acc', 'name': 'حسابدار', 'role': 'مدير',
             'password_hash': generate_password_hash('123456'), 'can_view_finance': True,
             'can_view_inventory': True, 'can_view_reports': True},
        ]: get_or_create(User, 'username', **u)
        db.session.commit()

        # --- 3. BASE DATA ---
        print('[3/25] اطلاعات پايه...')
        for n in ['افشاري', 'شال', 'رومانف', 'مغاني', 'قزل', 'بختياري', 'مهربان', 'بلوچي', 'کرماني', 'سنگسري']:
            get_or_create(BreedCategory, 'name', name=n)
        for i in range(1, 11):
            typ = 'پرواري' if i < 7 else 'داشتي'
            get_or_create(Pen, 'name', name=f'سالن {i}', capacity=150 if typ == 'پرواري' else 80, pen_type=typ)
        for s in [StatusCategory(name=n, type='عادي') for n in ['زنده و سالم', 'آبستن', 'شيرده']]:
            get_or_create(StatusCategory, 'name', name=s.name, type=s.type)
        for s in [StatusCategory(name=n, type='خطر') for n in ['بيمار', 'قرنطينه', 'تحت درمان', 'لاغر']]:
            get_or_create(StatusCategory, 'name', name=s.name, type=s.type)
        for s in [StatusCategory(name=n, type='پايان') for n in ['تلف شده', 'مرده', 'فروخته شده', 'کشتار']]:
            get_or_create(StatusCategory, 'name', name=s.name, type=s.type)
        for n in ['پرواربندي', 'داشتي (توليدمثل)', 'شيري', 'اصلاح نژاد']:
            get_or_create(PurposeCategory, 'name', name=n)
        for u in [{'name': 'کيلوگرم', 'description': 'وزن'}, {'name': 'عدد/ويال', 'description': 'دارو'},
                  {'name': 'سر', 'description': 'شمارش دام'}, {'name': 'ليتر', 'description': 'مايعات'},
                  {'name': 'متر', 'description': 'طول'}, {'name': 'کيلووات', 'description': 'برق'}]:
            get_or_create(Unit, 'name', **u)
        for n in ['واکسن', 'دارو/درمان', 'مکمل/ويتامين', 'ضد انگل', 'ضدعفوني']:
            get_or_create(MedicineCategory, 'name', name=n)
        for n in ['علوفه', 'خوراک', 'دارو', 'تجهيزات', 'بسته بندي', 'سوخت']:
            get_or_create(InventoryCategory, 'name', name=n)
        for n in ['قصاب/کشتارگاه', 'دامدار', 'واسطه', 'صادرات', 'مستقيم']:
            get_or_create(BuyerCategory, 'name', name=n)
        db.session.commit()

        # --- 4. ACCOUNTING CHART ---
        print('[4/25] کدينگ حسابداري...')
        t_asset = get_or_create(AccountType, 'name', name='دارايي', nature='بدهکار')
        t_liability = get_or_create(AccountType, 'name', name='بدهي', nature='بستانکار')
        t_equity = get_or_create(AccountType, 'name', name='حقوق صاحبان سهام', nature='بستانکار')
        t_revenue = get_or_create(AccountType, 'name', name='درآمد', nature='بستانکار')
        t_expense = get_or_create(AccountType, 'name', name='هزينه', nature='بدهکار')
        for a in [
            {'code': '1010', 'name': 'موجودي نقد و بانک', 'account_type_id': t_asset.id},
            {'code': '1020', 'name': 'موجودي کالا و انبار', 'account_type_id': t_asset.id},
            {'code': '1030', 'name': 'حساب هاي دريافتني', 'account_type_id': t_asset.id},
            {'code': '1040', 'name': 'اعتبار مالياتي (ماليات خريد)', 'account_type_id': t_asset.id},
            {'code': '1050', 'name': 'اسناد دريافتني', 'account_type_id': t_asset.id},
            {'code': '1060', 'name': 'سپرده بانکي', 'account_type_id': t_asset.id},
            {'code': '1200', 'name': 'دارايي هاي زيستي (گله)', 'account_type_id': t_asset.id},
            {'code': '1201', 'name': 'استهلاک انباشته گله', 'account_type_id': t_asset.id},
            {'code': '2010', 'name': 'حساب هاي پرداختني', 'account_type_id': t_liability.id},
            {'code': '2020', 'name': 'اسناد پرداختني', 'account_type_id': t_liability.id},
            {'code': '2030', 'name': 'ماليات پرداختني (ماليات فروش)', 'account_type_id': t_liability.id},
            {'code': '3010', 'name': 'مانده افتتاحيه (سرمايه)', 'account_type_id': t_equity.id},
            {'code': '3020', 'name': 'سود و زيان انباشته', 'account_type_id': t_equity.id},
            {'code': '4010', 'name': 'درآمد عملياتي', 'account_type_id': t_revenue.id},
            {'code': '4020', 'name': 'درآمد غيرعملياتي', 'account_type_id': t_revenue.id},
            {'code': '5010', 'name': 'هزينه هاي عملياتي', 'account_type_id': t_expense.id},
            {'code': '5020', 'name': 'هزينه استهلاک', 'account_type_id': t_expense.id},
            {'code': '5030', 'name': 'هزينه پرسنلي', 'account_type_id': t_expense.id},
        ]: get_or_create(Account, 'code', **a)
        db.session.commit()

        # --- 5. TRANSACTION CATEGORIES ---
        print('[5/25] دسته بندي مالي...')
        cats_data = [
            {'name': 'فروش دام', 't_type': 'درآمد', 'system_tag': 'SYS_LIVESTOCK_SALE'},
            {'name': 'خريد انبار (خودکار)', 't_type': 'هزينه', 'system_tag': 'SYS_INVENTORY'},
            {'name': 'حقوق و دستمزد', 't_type': 'هزينه', 'system_tag': 'SYS_PAYROLL'},
            {'name': 'استهلاک', 't_type': 'هزينه', 'system_tag': 'SYS_DEPRECIATION'},
            {'name': 'تسويه حساب اشخاص', 't_type': 'هزينه', 'system_tag': 'SYS_SETTLEMENT'},
            {'name': 'فروش نقدي', 't_type': 'درآمد', 'system_tag': None},
            {'name': 'فروش نسيه', 't_type': 'درآمد', 'system_tag': None},
            {'name': 'خريد نقدي', 't_type': 'هزينه', 'system_tag': None},
            {'name': 'خريد نسيه', 't_type': 'هزينه', 'system_tag': None},
        ]
        for fc in cats_data:
            if fc['system_tag']:
                get_or_create(TransactionCategory, 'system_tag', **fc)
            else:
                get_or_create(TransactionCategory, 'name', **fc)
        db.session.commit()

        # --- 6. FEED RATIONS ---
        print('[6/25] جيره هاي غذايي...')
        rations_data = [
            ('جيره استارتر بره', 12000), ('جيره پرواري سبک', 14500), ('جيره پرواري سنگين', 18500),
            ('جيره داشتي (ميش)', 9500), ('جيره شيري', 22000), ('جيره آبستني', 11000),
            ('جيره خشک (ميش خشک)', 7500), ('جيره قوچ هاي مولد', 13000), ('جيره کمکي رشد', 16000),
            ('جيره پيش پرواري', 10000), ('جيره پاياني', 14000), ('جيره مينرال', 8000),
            ('جيره ويتامينه', 9000), ('جيره کنسانتره پرواري', 17500), ('جيره کنسانتره شيري', 20000),
            ('جيره دانه ذرت', 11000), ('جيره دانه جو', 10500), ('جيره سبوس گندم', 7000),
            ('جيره پودر ماهي', 25000), ('جيره مکمل پروتئين', 23000), ('جيره يونجه', 8500),
            ('جيره کاه گندم', 5000), ('جيره سيلو ذرت', 6500), ('جيره تفاله چغندر', 6000),
            ('جيره پنبه دانه', 12000), ('جيره سويا', 28000), ('جيره کلزا', 15000),
            ('جيره گندم', 13500), ('جيره جو دو سر', 11500), ('جيره ارزن', 10000),
        ]
        for name, cost in rations_data:
            get_or_create(FeedRation, 'name', name=name, daily_cost=cost)
        db.session.commit()

        # --- 7. INVENTORY ITEMS ---
        print('[7/25] موجودي انبار...')
        cat_feed = InventoryCategory.query.filter_by(name='خوراک').first()
        cat_med = InventoryCategory.query.filter_by(name='دارو').first()
        cat_eq = InventoryCategory.query.filter_by(name='تجهيزات').first()
        cat_ff = InventoryCategory.query.filter_by(name='علوفه').first()
        unit_kg = Unit.query.filter_by(name='کيلوگرم').first()
        unit_vial = Unit.query.filter_by(name='عدد/ويال').first()
        inv_items_data = [
            ('جو محلي', cat_feed, unit_kg, 5000, 12500, 500),
            ('ذرت دامي', cat_feed, unit_kg, 3000, 11000, 300),
            ('يونجه خشک', cat_ff, unit_kg, 8000, 9500, 1000),
            ('کنسانتره پرواري', cat_feed, unit_kg, 2000, 17500, 400),
            ('سبوس گندم', cat_feed, unit_kg, 1500, 7000, 200),
            ('پودر ماهي', cat_feed, unit_kg, 500, 25000, 100),
            ('مکمل ويتامين', cat_med, unit_vial, 200, 45000, 50),
            ('واکسن تب برفکي', cat_med, unit_vial, 100, 85000, 20),
            ('واکسن شاربن', cat_med, unit_vial, 80, 72000, 15),
            ('داروي ضد انگل', cat_med, unit_vial, 150, 35000, 30),
            ('سيم خاردار', cat_eq, unit_kg, 300, 28000, 50),
            ('کتري (آبخوري)', cat_eq, unit_vial, 50, 120000, 10),
            ('دان خوري پلاستيکي', cat_eq, unit_vial, 80, 95000, 15),
            ('پوشال بستر', cat_ff, unit_kg, 2000, 3000, 500),
            ('کاه گندم', cat_ff, unit_kg, 10000, 5000, 2000),
            ('سيلو ذرت', cat_feed, unit_kg, 6000, 6500, 1000),
            ('تفاله چغندر', cat_feed, unit_kg, 3000, 6000, 500),
            ('پنبه دانه', cat_feed, unit_kg, 1000, 12000, 200),
            ('کنجاله سويا', cat_feed, unit_kg, 800, 28000, 150),
            ('نمک معدني', cat_feed, unit_kg, 500, 4000, 100),
        ]
        for name, cat, unit, qty, price, threshold in inv_items_data:
            cid = cat.id if cat else 1
            uid = unit.id if unit else 1
            get_or_create(InventoryItem, 'name', name=name, category_id=cid, unit_id=uid, quantity=qty, unit_price=price, min_threshold=threshold)
        db.session.commit()

        # --- 8. EQUIPMENT (60+) ---
        print('[8/25] تجهيزات و دارايي هاي ثابت...')
        eq_data = [
            ('فن تهويه سالن 1', 15000000, 10), ('فن تهويه سالن 2', 15000000, 10),
            ('فن تهويه سالن 3', 15000000, 10), ('فن تهويه سالن 4', 18000000, 10),
            ('فن تهويه سالن 5', 18000000, 10), ('فن تهويه سالن 6', 18000000, 10),
            ('آبخوري اتوماتيک', 8500000, 8), ('آبخوري سالن 2', 8500000, 8),
            ('آبخوري سالن 3', 8500000, 8), ('آبخوري سالن 4', 8500000, 8),
            ('دان خوري مکانيزه', 22000000, 12), ('دان خوري سالن 2', 22000000, 12),
            ('تراکتور', 850000000, 20), ('تريلر', 120000000, 15),
            ('تانکر آب', 45000000, 15), ('پمپ آب', 12000000, 8),
            ('موتور برق ديزلي', 350000000, 25), ('ژنراتور', 280000000, 20),
            ('سيستم روشنايي سالن', 18000000, 10), ('سيستم گرمايشي', 65000000, 15),
            ('سيستم سرمايشي', 75000000, 12), ('کاميون حمل', 950000000, 20),
            ('وانت بار', 450000000, 15), ('موتورسيکلت', 35000000, 8),
            ('باسکول ديجيتال', 28000000, 10), ('ترازوي دام', 12000000, 8),
            ('سيستم RFID', 45000000, 5), ('دوربين مداربسته', 32000000, 7),
            ('سرور و تجهيزات شبکه', 85000000, 5), ('کامپيوتر اداري', 25000000, 5),
            ('پرينتر', 8000000, 4), ('اسکنر', 6000000, 4),
            ('کولر گازي اداري', 15000000, 8), ('سيستم اعلام حريق', 28000000, 10),
            ('کپسول آتش نشاني', 3500000, 5), ('تابلو برق اصلي', 45000000, 20),
            ('سوله انبار علوفه', 450000000, 30), ('سوله انبار تجهيزات', 350000000, 30),
            ('حوضچه ضدعفوني', 18000000, 10), ('سمپاش پشتي', 4500000, 5),
            ('سمپاش موتوري', 15000000, 7), ('دستگاه شستشو', 8500000, 5),
            ('دريميل صنعتي', 6500000, 5), ('کابل برق', 12000000, 10),
            ('ترانس برق', 45000000, 25), ('ديگ بخار', 95000000, 20),
            ('ميکسر خوراک', 185000000, 15), ('آسياب', 120000000, 15),
            ('الک برقي', 28000000, 10), ('سردخانه', 250000000, 20),
            ('يخچال دارو', 18000000, 8), ('فريزر', 15000000, 8),
            ('ميز عمل', 12000000, 10), ('دستگاه سونوگرافي', 45000000, 8),
            ('لامپ حرارتي', 2500000, 3), ('قفس بره', 5500000, 5),
            ('باربند', 8000000, 7), ('چراغ قوه صنعتي', 1200000, 3),
            ('بيل مکانيکي', 650000000, 20), ('ليفتراک', 350000000, 15),
            ('چکش بادي', 8500000, 5),
        ]
        for name, price, life in eq_data:
            eq = Equipment.query.filter_by(name=name).first()
            if not eq:
                eq = Equipment(name=name, purchase_price=price, lifespan_years=life, scrap_value=price * Decimal('0.05'))
                db.session.add(eq)
        db.session.commit()
        print(f'   {Equipment.query.count()} تجهيزات')

        # --- 9. CONTACTS (600) ---
        print('[9/25] دفتر اشخاص...')
        existing_contacts = Contact.query.count()
        if existing_contacts < 600:
            types_pool = ['مشتري', 'تامين کننده', 'پرسنل', 'مشتري', 'تامين کننده']
            balance_range = lambda: random.randint(-50000000, 100000000)
            for i in range(existing_contacts + 1, 601):
                name = random_contact_name()
                if Contact.query.filter_by(name=name).first(): continue
                ctype = random.choice(types_pool)
                db.session.add(Contact(name=name, contact_type=ctype, balance=balance_range()))
                if i % 100 == 0: db.session.commit()
            db.session.commit()
        print(f'   {Contact.query.count()} مخاطب')

        # --- 10. WORKERS (30) ---
        print('[10/25] پرسنل...')
        worker_roles = [
            (random.choice(['چوپان', 'دامدار', 'کارگر', 'راننده', 'انباردار']), 8000000, 12000000),
            ('دامپزشک', 18000000, 25000000), ('حسابدار', 12000000, 18000000),
            ('مدير', 25000000, 35000000), ('تنخواه دار', 10000000, 15000000),
        ]
        for _ in range(30):
            role, base_min, base_max = random.choice(worker_roles)
            db.session.add(Worker(name=random_contact_name(), role=role,
                   phone=f'0912{random.randint(1000000, 9999999)}',
                   worker_code=f'WRK-{1000 + len(Worker.query.all()) + i}',
                   salary=random.randint(base_min, base_max),
                   status='فعال' if random.random() > 0.1 else 'غيرفعال'))
        db.session.commit()
        workers = Worker.query.all()
        print(f'   {len(workers)} پرسنل')

        # --- 11. SHEEP (500) ---
        print('[11/25] دام ها...')
        existing_sheep = Sheep.query.count()
        if existing_sheep < 500:
            breeds = [b.name for b in BreedCategory.query.all()]
            pens = Pen.query.all()
            rations = FeedRation.query.all()
            genders_pool = (['ميش'] * 30) + (['قوچ'] * 15) + (['بره ماده'] * 30) + (['بره نر'] * 25)
            purposes = ['پرواربندي', 'داشتي (توليدمثل)', 'شيري', 'اصلاح نژاد']
            for i in range(existing_sheep + 1, 501):
                gender = random.choice(genders_pool)
                age_days = random.randint(30, 2000)
                is_sick = random.random() < 0.08
                is_dead = random.random() < 0.03
                if is_dead: status, weight = random.choice(['تلف شده', 'مرده']), random.uniform(15, 70)
                elif is_sick: status, weight = random.choice(['بيمار', 'قرنطينه', 'تحت درمان', 'لاغر']), random.uniform(10, 60)
                else: status, weight = random.choice(['زنده و سالم', 'آبستن', 'شيرده']), random.uniform(20 + age_days * 0.03, 45 + age_days * 0.04)
                db.session.add(Sheep(ear_tag=f'DAM-{10000 + i}', breed=random.choice(breeds) if breeds else 'افشاري',
                      gender=gender, weight=round(weight, 1), status=status,
                      purpose=random.choice(purposes),
                      birth_date=today - timedelta(days=age_days),
                      pen_id=random.choice(pens).id if pens else None,
                      feed_ration_id=random.choice(rations).id if rations else None,
                      purchase_price=random.randint(3000000, 20000000)))
                if i % 100 == 0: db.session.commit()
            db.session.commit()
        sheep_all = Sheep.query.all()
        print(f'   {len(sheep_all)} راس دام')

        # --- 12. WEIGHT RECORDS ---
        print('[12/25] تاريخچه وزن...')
        if WeightRecord.query.count() < 500:
            count = 0
            for s in sheep_all:
                if s.status in ['تلف شده', 'مرده']: continue
                for w in range(random.randint(3, 8)):
                    rec_date = six_months_ago + timedelta(days=w * random.randint(15, 45))
                    if rec_date > today: continue
                    est = max(8, 20 + ((rec_date - s.birth_date).days if s.birth_date else 365) * 0.035)
                    db.session.add(WeightRecord(sheep_id=s.id, weight=round(random.uniform(est * 0.85, est * 1.15), 1),
                                 record_date=rec_date, bcs=round(random.uniform(2.5, 5.0), 1)))
                    count += 1
                    if count % 500 == 0: db.session.commit()
            db.session.commit()
        print(f'   {WeightRecord.query.count()} رکورد وزن')

        # --- 13. MEDICAL RECORDS ---
        print('[13/25] سوابق درماني...')
        if MedicalRecord.query.count() < 200:
            actions = ['واکسن', 'درمان', 'پروتکل', 'چکاپ', 'دارو']
            meds = ['تب برفکي', 'شاربن', 'آگالاکسي', 'پنوموني', 'انتروتوکسمي',
                    'ضد انگل خارجي', 'ضد انگل داخلي', 'مکمل ويتامين ADE', 'اکسی تتراسايکلين',
                    'پني سيلين', 'ضد التهاب', 'سرم قندي', 'بروسلوز', 'لمپي اسکين', 'طاعون']
            count = 0
            for s in sheep_all:
                if s.status in ['تلف شده', 'مرده']: continue
                for _ in range(random.randint(1, 4)):
                    rd = six_months_ago + timedelta(days=random.randint(0, 180))
                    if rd > today: continue
                    db.session.add(MedicalRecord(sheep_id=s.id, action_type=random.choice(actions),
                                  medicine_name=random.choice(meds), record_date=rd,
                                  operator=random.choice(['دکتر حسيني', 'سعيد', 'دامپزشک']),
                                  notes=random.choice(['دوز کامل', 'نيم دوز', 'تکرار پس از 14 روز', '']),
                                  next_date=rd + timedelta(days=random.randint(14, 60)) if random.random() > 0.5 else None))
                    count += 1
                    if count % 200 == 0: db.session.commit()
            db.session.commit()
        print(f'   {MedicalRecord.query.count()} رکورد درمان')

        # --- 14. BIRTH RECORDS ---
        print('[14/25] زايش ها...')
        if BirthRecord.query.count() < 30:
            ewes = [s for s in sheep_all if 'ميش' in s.gender]
            rams = [s for s in sheep_all if 'قوچ' in s.gender or 'بره نر' in s.gender]
            count = 0
            for mother in random.sample(ewes, min(120, len(ewes))):
                father = random.choice(rams) if rams else None
                bdate = six_months_ago + timedelta(days=random.randint(0, 160))
                db.session.add(BirthRecord(mother_id=mother.id, father_id=father.id if father else None,
                            birth_date=bdate, lambs_count=random.randint(1, 3),
                            status=random.choice(['موفق', 'موفق', 'موفق', 'سقط'])))
                count += 1
                if count % 50 == 0: db.session.commit()
            db.session.commit()
        print(f'   {BirthRecord.query.count()} زايش')

        # --- 15. LACTATION ---
        print('[15/25] شيردهي...')
        if LactationRecord.query.count() < 20:
            ewes = [s for s in sheep_all if 'ميش' in s.gender]
            count = 0
            for ewe in random.sample(ewes, min(100, len(ewes))):
                for _ in range(random.randint(1, 5)):
                    db.session.add(LactationRecord(sheep_id=ewe.id, record_date=six_months_ago + timedelta(days=random.randint(0, 180)),
                                    milk_yield=round(random.uniform(0.5, 3.5), 2)))
                    count += 1
            db.session.commit()

        # --- 16. FEEDING SCHEDULES ---
        print('[16/25] برنامه تغذيه...')
        db.session.commit()  # flush pending prev section
        all_rations = FeedRation.query.all()
        all_inv = InventoryItem.query.all()
        for i in range(30):
            ration = random.choice(all_rations) if all_rations else None
            inv_item = random.choice(all_inv) if all_inv else None
            if not ration or not inv_item: continue
            if not FeedingSchedule.query.filter_by(feed_ration_id=ration.id, inventory_item_id=inv_item.id).first():
                db.session.add(FeedingSchedule(feed_ration_id=ration.id,
                                inventory_item_id=inv_item.id,
                                amount_kg=random.uniform(50, 500),
                                time_of_day=random.choice(['06:00', '08:00', '12:00', '16:00', '18:00', '20:00'])))
        db.session.commit()

        # --- 17. TREATMENT TEMPLATES ---
        print('[17/25] پروتکل هاي درماني...')
        for t in [
            {'name': 'پروتکل واکسيناسيون پايه', 'medicines': 'تب برفکي,شاربن,آگالاکسي'},
            {'name': 'پروتکل درمان پنوموني', 'medicines': 'اکسي تتراسايکلين,ضد التهاب,سرم قندي'},
            {'name': 'پروتکل ضد انگل دوره اي', 'medicines': 'ضد انگل خارجي,ضد انگل داخلي'},
            {'name': 'پروتکل زايش', 'medicines': 'مکمل ويتامين ADE,سرم قندي,ضد التهاب'},
            {'name': 'پروتکل پشتيباني بره', 'medicines': 'مکمل ويتامين,سرم قندي'},
            {'name': 'پروتکل قرنطينه', 'medicines': 'تب برفکي,شاربن,ضد انگل خارجي'},
        ]: get_or_create(TreatmentTemplate, 'name', **t)
        db.session.commit()

        # --- 18. TRANSACTIONS (600) ---
        print('[18/25] فاکتورها...')
        tx_count = Transaction.query.count()
        if tx_count < 600:
            cats = TransactionCategory.query.all()
            contacts = Contact.query.all()
            methods = ['نقدي', 'نسيه', 'نقدي', 'نقدي', 'نسيه']
            for i in range(tx_count + 1, 601):
                is_income = random.random() > 0.4
                cat = random.choice(cats) if cats else None
                amount = random.randint(500000, 50000000)
                contact = random.choice(contacts) if contacts else None
                db.session.add(Transaction(t_type='درآمد' if is_income else 'هزينه',
                            category=cat.name if cat else ('فروش' if is_income else 'خريد'),
                            amount=amount, t_date=six_months_ago + timedelta(days=random.randint(0, 180)),
                            description=random.choice(['فروش دام', 'خريد نهاده', 'فروش نقدي', 'خريد نسيه',
                                                       'فروش نسيه', 'خريد تجهيزات', 'فروش شير']),
                            invoice_number=f'INV-{14000 + i}',
                            contact_id=contact.id if contact else None,
                            payment_method=random.choice(methods),
                            vat_amount=amount * Decimal('0.1'),
                            discount_amount=random.randint(0, amount // 20) if random.random() > 0.7 else 0))
                if i % 100 == 0: db.session.commit()
            db.session.commit()
        print(f'   {Transaction.query.count()} فاکتور')

        # --- 19. CHEQUES (600) ---
        print('[19/25] چک ها...')
        ch_count = Cheque.query.count()
        if ch_count < 600:
            contacts = Contact.query.all()
            statuses = ['در گردش', 'پاس شده', 'برگشتي', 'وصول شده', 'در گردش', 'در گردش', 'پاس شده']
            for i in range(ch_count + 1, 601):
                is_received = random.random() > 0.5
                contact = random.choice(contacts) if contacts else None
                amount = random.randint(1000000, 80000000)
                issue_date = six_months_ago + timedelta(days=random.randint(0, 160))
                db.session.add(Cheque(cheque_number=f'CHK-{30000 + i}',
                       cheque_type='دريافتي (مشتري)' if is_received else 'پرداختي (تامين کننده)',
                       amount=amount, issue_date=issue_date,
                       due_date=issue_date + timedelta(days=random.randint(15, 120)),
                       status=random.choice(statuses),
                       reason=random.choice(['بابت فروش دام', 'بابت خريد نهاده', 'تسويه حساب', 'پيش پرداخت', 'قسط']),
                       bank_name=random.choice(['ملي', 'ملت', 'صادرات', 'تجارت', 'رفاه', 'اقتصاد نوين']),
                       bank_branch=random.choice(['مرکزي', 'شاهين شهر', 'اصفهان', 'تهران', 'شيراز']),
                       issuer_name=contact.name if contact else random_contact_name(),
                       registered_to=contact.name if contact and not is_received else random_contact_name(),
                       contact_id=contact.id if contact else None))
                if i % 100 == 0: db.session.commit()
            db.session.commit()
        print(f'   {Cheque.query.count()} چک')

        # --- 20. PETTY CASH ---
        print('[20/25] تنخواه گردان...')
        db.session.commit()
        if PettyCash.query.count() < 50:
            for _ in range(50):
                w = random.choice(workers) if workers else None
                db.session.add(PettyCash(amount=random.randint(100000, 2000000),
                          description=random.choice(['خريد چاي و پذيرايي', 'کرايه حمل', 'تعميرات جزيي',
                                                     'سوخت', 'لوازم التحرير', 'خوراک روزانه']),
                          record_date=six_months_ago + timedelta(days=random.randint(0, 180)),
                          action_type='هزينه',
                          worker_id=w.id if w else None))
        db.session.commit()

        # --- 21. JOURNAL ENTRIES ---
        print('[21/25] اسناد حسابداري...')
        if JournalEntry.query.count() < 50:
            accs = {a.code: a.id for a in Account.query.all()}
            contacts = Contact.query.all()
            for i in range(300):
                entry_date = six_months_ago + timedelta(days=random.randint(0, 180))
                is_sale = random.random() > 0.5
                amount = Decimal(str(random.randint(100000, 50000000)))
                cid = random.choice(contacts).id if contacts and random.random() > 0.3 else None
                desc = random.choice(['فروش نقدي', 'خريد نهاده', 'فروش دام', 'هزينه درمان', 'حقوق پرسنل', 'خريد تجهيزات'])
                entry = JournalEntry(entry_number=AccountingEngine.generate_entry_number(),
                                     date=entry_date, description=desc, is_auto_generated=False)
                db.session.add(entry)
                db.session.flush()
                if is_sale:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=accs.get('1010') or accs.get('1030'),
                                                    contact_id=cid, debit=amount, credit=Decimal('0'), description=desc))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=accs.get('4010'),
                                                    debit=Decimal('0'), credit=amount, description=desc))
                else:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=accs.get('5010'),
                                                    debit=amount, credit=Decimal('0'), description=desc))
                    acc_id = accs.get('2010') or accs.get('1010')
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_id,
                                                    contact_id=cid, debit=Decimal('0'), credit=amount, description=desc))
                if i % 50 == 0: db.session.commit()
            db.session.commit()
        print(f'   {JournalEntry.query.count()} سند حسابداري')

        # --- 22. TASKS ---
        print('[22/25] وظايف...')
        if Task.query.count() < 10:
            users = User.query.all()
            for i in range(50):
                db.session.add(Task(description=random.choice(['تميزکاري سالن 1', 'واکسيناسيون دسته جمعي', 'تعمير آبخوري',
                                          'خريد نهاده', 'حسابرسي ماهانه', 'برگزاري جلسه', 'کنترل انبار',
                                          'بازديد دامپزشک', 'تعويض بستر', 'توزيع جيره', 'وزن کشي دوره اي',
                                          'چک کردن سنسورها']),
                     is_done=random.choice([True, False]),
                     task_date=six_months_ago + timedelta(days=random.randint(0, 180)),
                     worker_id=random.choice(users).id if users else None))
        db.session.commit()

        # --- 23. AUDIT LOGS (600) ---
        print('[23/25] لاگ امنيت...')
        if AuditLog.query.count() < 100:
            users = User.query.all()
            actions = ['ورود به سيستم', 'خروج از سيستم', 'ويرايش دام', 'ثبت وزن جديد',
                       'ثبت فاکتور فروش', 'ثبت فاکتور خريد', 'حذف کاربر', 'تغيير رمز عبور',
                       'صدور چک', 'وصول چک', 'ثبت سند حسابداري', 'بستن سال مالي',
                       'گزارش گيري', 'چاپ برچسب', 'ويرايش تنظيمات', 'بک آپ گيري']
            for _ in range(600):
                db.session.add(AuditLog(user_name=random.choice(users).name if users else 'سيستم',
                         action=random.choice(actions),
                         timestamp=six_months_ago + timedelta(seconds=random.randint(0, 180 * 86400)),
                         ip_address=f'{random.randint(10, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}'))
            db.session.commit()
        print(f'   {AuditLog.query.count()} لاگ')

        # --- 24. SENSOR DATA ---
        print('[24/25] داده هاي سنسور...')
        if SensorData.query.count() < 50:
            pens = Pen.query.all()
            for _ in range(500):
                pen = random.choice(pens) if pens else None
                if not pen: continue
                db.session.add(SensorData(pen_id=pen.id, temperature=round(random.uniform(15.0, 38.0), 1),
                           humidity=round(random.uniform(30.0, 85.0), 1),
                           recorded_at=six_months_ago + timedelta(hours=random.randint(0, 180 * 24))))
            db.session.commit()
        print(f'   {SensorData.query.count()} سنسور')

        # --- 25. PAYSLIPS ---
        print('[25/25] حقوق و دستمزد...')
        if Payslip.query.count() < 20:
            for w in workers:
                for month_name in ['فروردين', 'ارديبهشت', 'خرداد', 'تير']:
                    base = w.salary or 10000000
                    gross = base + random.randint(500000, 2000000)
                    db.session.add(Payslip(worker_id=w.id, month_name=month_name, base_salary=base,
                            overtime_pay=random.randint(0, 3000000),
                            housing_allowance=random.randint(300000, 1000000),
                            food_allowance=random.randint(500000, 1500000),
                            loan_deduction=random.choice([Decimal('0'), Decimal('0'), Decimal('500000'), Decimal('1000000')]),
                            net_pay=gross, gross_pay=gross,
                            is_paid=True, issue_date=six_months_ago + timedelta(days=30)))
        db.session.commit()
        print(f'   {Payslip.query.count()} فيش حقوقي')

        # --- WORKER LOANS ---
        db.session.commit()
        workers = Worker.query.all()
        if WorkerLoan.query.count() < 5:
            for w in workers[:10]:
                db.session.add(WorkerLoan(worker_id=w.id, amount=random.randint(5000000, 30000000),
                           issue_date=six_months_ago + timedelta(days=random.randint(0, 120)),
                           loan_type=random.choice(['مسکن', 'خودرو', 'درمان', 'سایر']),
                           installment_amount=random.randint(500000, 3000000),
                           description='وام', status='فعال'))
        db.session.commit()

        # --- DEPRECIATION ---
        print('   ثبت استهلاک تجهيزات...')
        dep_exp = Account.query.filter_by(code='5020').first() or Account.query.filter_by(code='5010').first()
        dep_acc = Account.query.filter_by(code='1201').first()
        if dep_exp and dep_acc:
            for eq in Equipment.query.all():
                if not eq.purchase_price or not eq.lifespan_years or eq.purchase_price <= 0: continue
                if JournalEntryLine.query.filter(JournalEntryLine.account_id == dep_exp.id,
                                                  JournalEntryLine.description.like(f'%{eq.name[:20]}%')).first(): continue
                annual = (eq.purchase_price - (eq.scrap_value or 0)) / eq.lifespan_years
                if annual <= 0: continue
                entry = JournalEntry(entry_number=AccountingEngine.generate_entry_number(),
                                     date=today - timedelta(days=random.randint(1, 30)),
                                     description=f'استهلاک {eq.name}', is_auto_generated=True)
                db.session.add(entry)
                db.session.flush()
                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=dep_exp.id,
                                                debit=annual, credit=Decimal('0'), description=f'استهلاک {eq.name}'))
                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=dep_acc.id,
                                                debit=Decimal('0'), credit=annual, description=f'استهلاک انباشته {eq.name}'))
            db.session.commit()

        print('\n' + '='*60)
        print('  بذرپاشي سنگين با موفقيت به پايان رسيد!')
        print('='*60)

if __name__ == '__main__':
    seed_data()
