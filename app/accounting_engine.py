from app import db
from app.models import Account, JournalEntry, JournalEntryLine, InventoryItem
from datetime import datetime, UTC
import time
import random

class AccountingEngine:
    @staticmethod
    def get_account(code):
        return Account.query.filter_by(code=code).first()

    @staticmethod
    def get_vat_rate():
        from app.blueprints.dashboard import get_setting
        return float(get_setting('vat_rate', 10)) / 100

    @staticmethod
    def generate_entry_number():
        return f"SANAD-{time.time_ns()}-{random.randint(100000, 999999)}"

    @staticmethod
    def record_sale(transaction, contact_id=None, include_vat=True):
        """ثبت اتوماتیک سند فروش (درآمد)"""
        # حساب های درگیر: صندوق/بانک/مشتریان (بدهکار) | فروش (بستانکار) | مالیات بر ارزش افزوده پرداختنی (بستانکار)
        cash_account = AccountingEngine.get_account('1010') # موجودی نقد و بانک
        receivable_account = AccountingEngine.get_account('1030') # حسابهای دریافتنی
        sales_account = AccountingEngine.get_account('4010') # درآمد فروش
        vat_payable = AccountingEngine.get_account('2030') # مالیات پرداختنی


        amount = transaction.amount
        vat_amount = amount * AccountingEngine.get_vat_rate() if include_vat else 0
        total_amount = amount + vat_amount

        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=transaction.t_date,
            description=f"بابت فاکتور فروش شماره {transaction.invoice_number or 'نامشخص'}",
            transaction_id=transaction.id
        )
        db.session.add(entry)
        db.session.flush()

        # اگر شخص مشخص بود، نسیه (حساب دریافتنی) بدهکار میشود، وگرنه نقد (صندوق)
        debit_acc_id = receivable_account.id if contact_id else cash_account.id
        
        # 1. طرف بدهکار (ورود پول یا ایجاد طلب)
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=debit_acc_id, contact_id=contact_id, debit=total_amount, credit=0.0))
        
        # 2. طرف بستانکار (درآمد فروش)
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=sales_account.id, debit=0.0, credit=amount))
        
        # 3. طرف بستانکار (ارزش افزوده)
        if vat_amount > 0:
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=vat_payable.id, debit=0.0, credit=vat_amount))

    @staticmethod
    def record_expense(transaction, contact_id=None, include_vat=True):
        """ثبت اتوماتیک سند خرید / هزینه"""
        # حساب های درگیر: هزینه/موجودی کالا (بدهکار) | مالیات خرید (بدهکار) | صندوق/تامین کنندگان (بستانکار)
        cash_account = AccountingEngine.get_account('1010')
        payable_account = AccountingEngine.get_account('2010') # حسابهای پرداختنی
        expense_account = AccountingEngine.get_account('5010') # هزینه های عملیاتی
        vat_receivable = AccountingEngine.get_account('1040') # پیش پرداخت مالیات


        amount = transaction.amount
        vat_amount = amount * AccountingEngine.get_vat_rate() if include_vat else 0
        total_amount = amount + vat_amount

        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=transaction.t_date,
            description=f"بابت فاکتور هزینه/خرید شماره {transaction.invoice_number or 'نامشخص'}",
            transaction_id=transaction.id
        )
        db.session.add(entry)
        db.session.flush()

        # 1. طرف بدهکار (شناسایی هزینه)
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=expense_account.id, debit=amount, credit=0.0))
        
        # 2. طرف بدهکار (اعتبار ارزش افزوده خرید)
        if vat_amount > 0:
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=vat_receivable.id, debit=vat_amount, credit=0.0))

        # 3. طرف بستانکار (خروج پول یا ایجاد بدهی)
        credit_acc_id = payable_account.id if contact_id else cash_account.id
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=credit_acc_id, contact_id=contact_id, debit=0.0, credit=total_amount))

    @staticmethod
    def record_cheque_clearing(cheque):
        """
        ثبت سند تسویه نهایی چک (Clearing):
        برای چک دریافتی: بدهکار: بانک (1101) | بستانکار: اسناد دریافتنی (1103)
        برای چک پرداختی: بدهکار: اسناد پرداختنی (2101) | بستانکار: بانک (1101)
        """
        description = f"تسویه نهایی چک شماره {cheque.cheque_number} - بابت {cheque.reason}"
        
        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=datetime.now(UTC).date(),
            description=description
        )
        db.session.add(entry)
        db.session.flush()

        acc_bank = AccountingEngine.get_account('1010')

        if cheque.cheque_type == 'دریافتی (مشتری)':
            acc_receivable = AccountingEngine.get_account('1030')
            # بدهکار: بانک (ورود وجه به حساب)
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=cheque.amount, credit=0.0))
            # بستانکار: اسناد دریافتنی (کاهش مطالبات)
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_receivable.id, debit=0.0, credit=cheque.amount))
        else:
            acc_payable = AccountingEngine.get_account('2010')
            # بدهکار: اسناد پرداختنی (کاهش بدهی ما)
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, debit=cheque.amount, credit=0.0))
            # بستانکار: بانک (خروج وجه از حساب)
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=0.0, credit=cheque.amount))


    @staticmethod
    def record_livestock_valuation(total_fair_value):
        """
        ارزیابی ارزش منصفانه گله (استاندارد ۲۶ حسابداری ایران):
        تعدیل مانده حساب دارایی‌های زیستی (1202) بر اساس ارزش منصفانه فعلی بازار.
        سود یا زیان حاصل از این ارزیابی در صورت سود و زیان دوره منعکس می‌شود.
        """
        from sqlalchemy import func
        
        acc_livestock = AccountingEngine.get_account('1200')
        acc_revenue = AccountingEngine.get_account('4010') # درآمد ارزیابی
        acc_expense = AccountingEngine.get_account('5010') # هزینه/زیان ارزیابی


        # محاسبه مانده دفتری فعلی حساب ۱۲۰۲ (دارایی‌های زیستی) از تراکنش‌های قبلی
        debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc_livestock.id).scalar() or 0.0
        credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc_livestock.id).scalar() or 0.0
        current_book_value = debits - credits

        adjustment = total_fair_value - current_book_value
        if abs(adjustment) < 1: return # تفاوت معنی‌داری وجود ندارد

        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=datetime.now(UTC).date(),
            description=f"تعدیل ارزش منصفانه گله (استاندارد ۲۶) - ارزش جدید بازار: {total_fair_value:,.0f}"
        )
        db.session.add(entry)
        db.session.flush()

        if adjustment > 0:
            # افزایش ارزش (بدهکار: دارایی زیستی | بستانکار: سود ارزیابی)
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_livestock.id, debit=adjustment, credit=0.0, description="افزایش ارزش منصفانه دارایی زیستی (رشد فیزیکی/قیمت)"))
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_revenue.id, debit=0.0, credit=adjustment, description="سود حاصل از تغییر ارزش منصفانه گله"))
        else:
            # کاهش ارزش (بدهکار: زیان ارزیابی | بستانکار: دارایی زیستی)
            loss_amount = abs(adjustment)
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=loss_amount, credit=0.0, description="زیان حاصل از تغییر ارزش منصفانه گله"))
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_livestock.id, debit=0.0, credit=loss_amount, description="کاهش ارزش منصفانه دارایی زیستی"))

    @staticmethod
    def close_temporary_accounts():
        """
        بستن حساب‌های موقت (درآمد و هزینه) پایان سال مالی:
        1. شناسایی مانده حساب‌های کد 4 (درآمد) و کد 5 (هزینه)
        2. صفر کردن مانده‌ها و انتقال به حساب سود و زیان انباشته (3102)
        """
        from sqlalchemy import func
        from app.models import Account, JournalEntryLine

        # حساب مقصد: سود و زیان انباشته (Equity)
        # نکته: اگر این کد در سیستم شما نیست، باید در seed.py اضافه شود
        acc_retained_earnings = AccountingEngine.get_account('3020') or AccountingEngine.get_account('3010')

        # دریافت تمام حساب‌های درآمد و هزینه
        temp_accounts = Account.query.filter(
            (Account.code.startswith('4')) | (Account.code.startswith('5'))
        ).all()


        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=datetime.now(UTC).date(),
            description="بستن حساب‌های موقت و انتقال سود/زیان به سال مالی جدید"
        )
        db.session.add(entry)
        db.session.flush()

        total_debit_adjustment = 0
        total_credit_adjustment = 0

        for acc in temp_accounts:
            debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc.id).scalar() or 0.0
            credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc.id).scalar() or 0.0
            
            # محاسبه مانده بر اساس ماهیت
            if acc.type.nature == 'بدهکار':
                balance = debits - credits
                if balance > 0: # هزینه مانده بدهکار دارد، پس بستانکار می‌شود تا صفر شود
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=0.0, credit=balance, description=f"بستن حساب {acc.name}"))
                    total_credit_adjustment += balance
            else:
                balance = credits - debits
                if balance > 0: # درآمد مانده بستانکار دارد، پس بدهکار می‌شود تا صفر شود
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=balance, credit=0.0, description=f"بستن حساب {acc.name}"))
                    total_debit_adjustment += balance

        # محاسبه سود یا زیان خالص برای بالانس کردن سند
        net_result = total_debit_adjustment - total_credit_adjustment
        
        if net_result > 0: # سود خالص -> بستانکار کردن حساب حقوق صاحبان سهام
            db.session.add(JournalEntryLine(
                journal_entry_id=entry.id, account_id=acc_retained_earnings.id,
                debit=0.0, credit=net_result,
                description="انتقال سود خالص دوره مالی به حساب سود و زیان انباشته"
            ))
        elif net_result < 0: # زیان خالص -> بدهکار کردن حساب حقوق صاحبان سهام
            db.session.add(JournalEntryLine(
                journal_entry_id=entry.id, account_id=acc_retained_earnings.id,
                debit=abs(net_result), credit=0.0,
                description="انتقال زیان خالص دوره مالی به حساب سود و زیان انباشته"
            ))
            
        return entry

        @staticmethod
    def sync_inventory_ledger():
        """
        همگام‌سازی مانده دفتر کل با ارزش واقعی انبار (انبارگردانی پایان سال):
        1. محاسبه ارزش ریالی تمام کالاهای موجود در جدول InventoryItem
        2. محاسبه مانده فعلی حساب 1020 در دفتر کل
        3. صدور سند تعدیل (هزینه مصرف) برای رساندن مانده دفتر به ارزش واقعی کالاها
        """
        from sqlalchemy import func
        
        acc_inventory = AccountingEngine.get_account('1020')
        acc_expense = AccountingEngine.get_account('5010')


        # 1. ارزش واقعی انبار از جدول کالاها
        all_items = InventoryItem.query.all()
        actual_warehouse_value = sum((item.quantity or 0) * (item.unit_price or 0) for item in all_items)

        # 2. مانده دفتری حساب 1102
        debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc_inventory.id).scalar() or 0.0
        credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc_inventory.id).scalar() or 0.0
        book_value = debits - credits

        # 3. محاسبه مبلغ مصرف شده (تفاوت دفتر و انبار واقعی)
        consumption_value = book_value - actual_warehouse_value

        if abs(consumption_value) < 1:
            return None # انبار تراز است

        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=datetime.now(UTC).date(),
            description=f"سند انبارگردانی و انتقال مانده به سال جدید - ارزش موجودی: {actual_warehouse_value:,.0f}"
        )
        db.session.add(entry)
        db.session.flush()

        if consumption_value > 0:
            # موجودی دفتر بیشتر است -> ثبت هزینه مصرف کالا (بدهکار هزینه | بستانکار انبار)
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=consumption_value, credit=0.0, description="ثبت هزینه کالای مصرف شده در طول دوره"))
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_inventory.id, debit=0.0, credit=consumption_value, description="کاهش موجودی انبار بابت مصرف/انبارگردانی"))
        else:
            # موجودی واقعی بیشتر است (اضافه انبار) -> بدهکار انبار | بستانکار درآمد/تعدیل
            added_value = abs(consumption_value)
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_inventory.id, debit=added_value, credit=0.0, description="افزایش موجودی دفتری بابت مازاد انبارگردانی"))
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=AccountingEngine.get_account('4010').id, debit=0.0, credit=added_value, description="درآمد حاصل از مازاد انبارگردانی"))


        return entry

    @staticmethod
    def record_depreciation(asset_name, amount):
        """
        ثبت هزینه استهلاک دارایی‌های ثابت (تجهیزات، ساختمان و ...):
        بدهکار: هزینه استهلاک (5101 یا 5102)
        بستانکار: استهلاک انباشته (1204) - به عنوان کاهنده دارایی
        """
        description = f"ثبت استهلاک دوره‌ای - {asset_name}"
        entry = AccountingEngine._create_entry(description)

                # سرفصل هزینه استهلاک (در صورت نبود کد 5020 از کد هزینه عمومی استفاده می‌شود)
        acc_expense = AccountingEngine.get_account('5020') or AccountingEngine.get_account('5010')
        # سرفصل استهلاک انباشته (کد استاندارد 1204)
        acc_accum_dep = AccountingEngine.get_account('1204')


        if not acc_accum_dep:
            # اگر کد 1204 در دیتابیس نبود، پیغامی برای مدیر صادر شود یا از دارایی مستقیم کسر شود
            acc_accum_dep = AccountingEngine.get_account('1201') # حساب اثاثه و تجهیزات

        # 1. بدهکار: شناسایی هزینه دوره
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_expense.id, 
            debit=amount, credit=0.0, description=f"هزینه استهلاک {asset_name}"
        ))

        # 2. بستانکار: افزایش استهلاک انباشته (کاهش ارزش دفتری دارایی)
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_accum_dep.id, 
            debit=0.0, credit=amount, description=f"ذخیره استهلاک انباشته {asset_name}"
        ))
        
        return entry

        @staticmethod
    def record_insurance_payment(amount, description, date):
        """
        ثبت سند واریز حق بیمه به سازمان:
        بدهکار: حساب‌ها و اسناد پرداختنی (2010)
        بستانکار: موجودی نقد و بانک (1010)
        """
        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=date,
            description=f"واریز حق بیمه سازمان: {description}"
        )
        db.session.add(entry)
        db.session.flush()

        acc_payable = AccountingEngine.get_account('2010')
        acc_bank = AccountingEngine.get_account('1010')


        # 1. بدهکار: کاهش بدهی (توضیح باید شامل 'بیمه پرداختنی سازمان' باشد تا در محاسبات داشبورد لحاظ شود)
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_payable.id,
            debit=amount, credit=0.0,
            description=f"بیمه پرداختنی سازمان - تسویه واریزی: {description}"
        ))

        # 2. بستانکار: خروج وجه از بانک
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_bank.id,
            debit=0.0, credit=amount,
            description=f"برداشت از بانک بابت واریز بیمه - {description}"
        ))
        return entry

    @staticmethod
    def record_payroll(payslip):
        """
        ثبت سند هزینه حقوق و بیمه (Payroll):
        بدهکار: هزینه حقوق و مزایا (5101) -> مبلغ ناخالص (Gross Pay)
        بدهکار: هزینه بیمه سهم کارفرما (5101) -> 23% حقوق پایه
        بستانکار: حقوق پرداختنی (2101) -> مبلغ خالص (Net Pay)
        بستانکار: بیمه پرداختنی سازمان (2101) -> 30% پایه (7% سهم کارگر + 23% سهم کارفرما)
        بستانکار: حساب‌های دریافتنی - مساعده/وام (1103) -> اقساط کسر شده
        """
        description = f"سند حقوق و دستمزد {payslip.month_name} - پرسنل: {payslip.worker.name}"
        
        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=datetime.now(UTC).date(),
            description=description
        )
        db.session.add(entry)
        db.session.flush()

        acc_expense = AccountingEngine.get_account('5010')
        acc_payable = AccountingEngine.get_account('2010')
        acc_receivable = AccountingEngine.get_account('1030')


        # محاسبات استاندارد بیمه در ایران
        insurance_employer = (payslip.base_salary or 0) * 0.23
        insurance_total = (payslip.base_salary or 0) * 0.30

        # 1. بدهکار: هزینه ناخالص حقوق
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=payslip.gross_pay, credit=0.0, description=f"هزینه حقوق و مزایای ناخالص - {payslip.worker.name}"))
        # 2. بدهکار: هزینه بیمه سهم کارفرما
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=insurance_employer, credit=0.0, description=f"بیمه سهم کارفرما (23%) - {payslip.worker.name}"))
        # 3. بستانکار: خالص حقوق پرداختنی
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, debit=0.0, credit=payslip.net_pay, description=f"خالص حقوق پرداختنی - {payslip.worker.name}"))
        # 4. بستانکار: بیمه پرداختنی سازمان
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, debit=0.0, credit=insurance_total, description=f"بیمه پرداختنی سازمان (30%) - {payslip.worker.name}"))

        if (payslip.loan_deduction or 0) > 0:
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_receivable.id, debit=0.0, credit=payslip.loan_deduction, description=f"وصول قسط وام - {payslip.worker.name}"))
        if (payslip.fines or 0) > 0:
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=0.0, credit=payslip.fines, description=f"کسر جریمه - {payslip.worker.name}"))

        @staticmethod
    def record_feed_consumption(total_cost):
        """ثبت سند مصرف خوراک (خروج از انبار به سرفصل هزینه)"""
        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=datetime.now(UTC).date(),
            description=f"ثبت خودکار مصرف خوراک گله - مورخ {datetime.now(UTC).date()}"
        )
        db.session.add(entry)
        db.session.flush()
        
        acc_inventory = AccountingEngine.get_account('1020')
        acc_expense = AccountingEngine.get_account('5010')


        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=total_cost, credit=0.0, description="هزینه خوراک مصرفی روزانه گله"))
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_inventory.id, debit=0.0, credit=total_cost, description="کاهش موجودی دفتری انبار بابت تغذیه"))

    @staticmethod
    def record_contact_settlement(contact, amount, action_type, date):
        """
        ثبت سند تسویه حساب اشخاص (بدون درگیری حساب هزینه/درآمد جهت جلوگیری از ثبت مضاعف):
        اگر پرداخت به شخص: بدهکار: حساب پرداختنی (2101) | بستانکار: نقد و بانک (1101)
        اگر دریافت از شخص: بدهکار: نقد و بانک (1101) | بستانکار: حساب دریافتنی (1103)
        """
        description = f"تسویه حساب با {contact.name} - {action_type}"
        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=date,
            description=description
        )
        db.session.add(entry)
        db.session.flush()

        acc_bank = AccountingEngine.get_account('1010')
        
        if "پرداخت" in action_type:
            acc_payable = AccountingEngine.get_account('2010')
            # بدهکار: کاهش بدهی ما به شخص
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, contact_id=contact.id, debit=amount, credit=0.0, description=f"کاهش بدهی به {contact.name}"))
            # بستانکار: خروج پول از بانک
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=0.0, credit=amount, description=f"پرداخت نقدی به {contact.name}"))
        else:
            acc_receivable = AccountingEngine.get_account('1030')
            # بدهکار: ورود پول به بانک
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=amount, credit=0.0, description=f"دریافت وجه از {contact.name}"))
            # بستانکار: کاهش طلب ما از شخص
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_receivable.id, contact_id=contact.id, debit=0.0, credit=amount, description=f"کاهش مطالبات از {contact.name}"))


        return entry

    @staticmethod
    def record_opening_entry():
        """
        صدور سند افتتاحیه: انتقال مانده حساب‌های دائمی (کدهای 1، 2، 3) به دوره مالی جدید.
        """
        from sqlalchemy import func, or_
        
        # دریافت حساب‌های دائمی (دارایی، بدهی، سرمایه)
        permanent_accounts = Account.query.filter(
            or_(Account.code.startswith('1'), Account.code.startswith('2'), Account.code.startswith('3'))
        ).all()

        entry = JournalEntry(
            entry_number=AccountingEngine.generate_entry_number(),
            date=datetime.now(UTC).date(),
            description="سند افتتاحیه - انتقال مانده حساب‌های دائمی از دوره قبل"
        )
        db.session.add(entry)
        db.session.flush()

        for acc in permanent_accounts:
            debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc.id).scalar() or 0.0
            credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc.id).scalar() or 0.0
            
            # محاسبه مانده بر اساس ماهیت حساب
            if acc.type.nature == 'بدهکار':
                balance = debits - credits
                if balance > 0:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=balance, credit=0.0, description=f"مانده اول دوره - {acc.name}"))
                elif balance < 0:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=0.0, credit=abs(balance), description=f"مانده اول دوره - {acc.name}"))
            else: # بستانکار
                balance = credits - debits
                if balance > 0:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=0.0, credit=balance, description=f"مانده اول دوره - {acc.name}"))
                elif balance < 0:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=abs(balance), credit=0.0, description=f"مانده اول دوره - {acc.name}"))
        
        return entry

    @staticmethod
    def get_financial_report():
        """محاسبه خلاصه وضعیت سود و زیان و مالیات از دفتر کل"""
        from app.models import Account, JournalEntryLine
        from sqlalchemy import func
        
                # محاسبات ساده مالیاتی بر اساس کدهای کل
        vat_p_acc = Account.query.filter_by(code='2030').first() # مالیات پرداختنی
        vat_r_acc = Account.query.filter_by(code='1040').first() # اعتبار مالیاتی

        
        vat_p = 0
        if vat_p_acc:
            vat_p = (db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=vat_p_acc.id).scalar() or 0) - \
                    (db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=vat_p_acc.id).scalar() or 0)
                    
        vat_r = 0
        if vat_r_acc:
            vat_r = (db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=vat_r_acc.id).scalar() or 0) - \
                    (db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=vat_r_acc.id).scalar() or 0)

        return {'vat_payable': vat_p, 'vat_receivable': vat_r, 'net_tax': vat_p - vat_r}