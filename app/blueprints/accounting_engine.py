from app import db
from app.models import JournalEntry, JournalEntryLine, Account, SystemSetting
from datetime import datetime, UTC
import time
import random

class AccountingEngine:
    """
    موتور حسابداری هوشمند برای تبدیل رویدادهای دامداری به اسناد استاندارد (طبق اصول حسابداری ایران)
    """

    @staticmethod
    def _get_vat_rate():
        # دریافت نرخ مالیات از تنظیمات سیستمی (پیش‌فرض 10 درصد)
        setting = SystemSetting.query.filter_by(key='vat_rate').first()
        try:
            return float(setting.value) / 100 if setting else 0.10
        except:
            return 0.10

    @staticmethod
    def _create_entry(description, ref_id=None):
        # ایجاد سربرگ سند حسابداری
        entry = JournalEntry(
            entry_number=f"ACC-{int(time.time())}-{random.randint(100, 999)}",
            description=description,
            date=datetime.now(UTC).date(),
            transaction_id=ref_id
        )
        db.session.add(entry)
        db.session.flush()
        return entry

    @staticmethod
    def record_sale(transaction, contact_id=None, include_vat=True):
        """
        ثبت سند فروش دام:
        بدهکار: موجودی نقد (1101) یا حساب‌های دریافتنی (1103)
        بستانکار: درآمد فروش (4101) - مبلغ خالص
        بستانکار: مالیات بر ارزش افزوده پرداختنی (2103) - در صورت شمول
        """
        vat_rate = AccountingEngine._get_vat_rate() if include_vat else 0
        net_amount = transaction.amount / (1 + vat_rate)
        vat_amount = transaction.amount - net_amount

        entry = AccountingEngine._create_entry(
            f"فروش سیستماتیک - فاکتور: {transaction.invoice_number or transaction.id} - {transaction.party_name}",
            ref_id=transaction.id
        )

        # 1. بدهکار: نقد و بانک یا حساب دریافتنی شخص
        acc_debtor_code = "1103" if contact_id else "1101"
        acc_debtor = Account.query.filter_by(code=acc_debtor_code).first()
        
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=acc_debtor.id,
            debit=transaction.amount,
            credit=0,
            description=f"دریافتنی بابت فروش به {transaction.party_name}"
        ))

        # 2. بستانکار: درآمد فروش (خالص)
        acc_revenue = Account.query.filter_by(code="4101").first()
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=acc_revenue.id,
            debit=0,
            credit=net_amount,
            description="درآمد حاصل از فروش دام"
        ))

        # 3. بستانکار: مالیات بر ارزش افزوده (اگر وجود داشت)
        if vat_amount > 0:
            acc_vat = Account.query.filter_by(code="2103").first()
            db.session.add(JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=acc_vat.id,
                debit=0,
                credit=vat_amount,
                description="مالیات بر ارزش افزوده فروش"
            ))

    @staticmethod
    def record_expense(transaction, contact_id=None, include_vat=True):
        """
        ثبت سند هزینه یا خرید انبار:
        بدهکار: هزینه عملیاتی (5101) یا موجودی انبار (1102)
        بدهکار: اعتبار مالیاتی / ارزش افزوده خرید (1104)
        بستانکار: موجودی نقد (1101) یا حساب‌های پرداختنی (2101)
        """
        vat_rate = AccountingEngine._get_vat_rate() if include_vat else 0
        net_amount = transaction.amount / (1 + vat_rate)
        vat_amount = transaction.amount - net_amount

        entry = AccountingEngine._create_entry(
            f"ثبت هزینه/خرید - {transaction.category} - {transaction.party_name}",
            ref_id=transaction.id
        )

        # 1. بدهکار: سرفصل هزینه یا انبار
        acc_exp_code = "1102" if "انبار" in transaction.category else "5101"
        acc_exp = Account.query.filter_by(code=acc_exp_code).first()
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_exp.id, debit=net_amount, credit=0))

        # 2. بدهکار: اعتبار مالیاتی (VAT خرید)
        if vat_amount > 0:
            acc_vat_in = Account.query.filter_by(code="1104").first()
            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_vat_in.id, debit=vat_amount, credit=0))

        # 3. بستانکار: نقد یا حساب پرداختنی
        acc_creditor_code = "2101" if contact_id else "1101"
        acc_creditor = Account.query.filter_by(code=acc_creditor_code).first()
        db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_creditor.id, debit=0, credit=transaction.amount))

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
        entry = AccountingEngine._create_entry(description)

        acc_expense = Account.query.filter_by(code="5101").first()
        acc_payable = Account.query.filter_by(code="2101").first()
        acc_receivable = Account.query.filter_by(code="1103").first()

        # محاسبات استاندارد بیمه در ایران بر اساس پایه حقوق
        insurance_employer = (payslip.base_salary or 0) * 0.23
        insurance_total = (payslip.base_salary or 0) * 0.30

        # 1. بدهکار: هزینه ناخالص حقوق (شامل پایه، حق مسکن، بن و ...)
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_expense.id,
            debit=payslip.gross_pay, credit=0,
            description=f"هزینه حقوق و مزایای ناخالص - {payslip.worker.name}"
        ))

        # 2. بدهکار: هزینه بیمه سهم کارفرما (23%)
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_expense.id,
            debit=insurance_employer, credit=0,
            description=f"هزینه بیمه سهم کارفرما (23%) - {payslip.worker.name}"
        ))

        # 3. بستانکار: خالص پرداختی (تعهد پرداخت به پرسنل)
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_payable.id,
            debit=0, credit=payslip.net_pay,
            description=f"خالص حقوق پرداختنی - {payslip.worker.name}"
        ))

        # 4. بستانکار: بیمه پرداختنی (مجموع سهم کارگر و کارفرما)
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_payable.id,
            debit=0, credit=insurance_total,
            description=f"بیمه پرداختنی سازمان (30%) - {payslip.worker.name}"
        ))

        # 5. بستانکار: کسر اقساط وام (کاهش دارایی دریافتنی از پرسنل)
        if (payslip.loan_deduction or 0) > 0:
            db.session.add(JournalEntryLine(
                journal_entry_id=entry.id, account_id=acc_receivable.id,
                debit=0, credit=payslip.loan_deduction,
                description=f"وصول قسط وام از حقوق - {payslip.worker.name}"
            ))

        # 6. بستانکار: جریمه‌ها (کاهش سرفصل هزینه)
        if (payslip.fines or 0) > 0:
            db.session.add(JournalEntryLine(
                journal_entry_id=entry.id, account_id=acc_expense.id,
                debit=0, credit=payslip.fines,
                description=f"کسر جریمه انضباطی - {payslip.worker.name}"
            ))

    @staticmethod
    def record_feed_consumption(total_cost):
        """
        ثبت سند مصرف خوراک (خروج از انبار به هزینه):
        بدهکار: هزینه های عملیاتی (5101)
        بستانکار: موجودی کالا و انبار (1102)
        """
        entry = AccountingEngine._create_entry(f"ثبت خودکار مصرف خوراک گله - مورخ {datetime.now(UTC).date()}")
        
        acc_inventory = AccountingEngine.get_account('1102')
        acc_expense = AccountingEngine.get_account('5101')

        # 1. بدهکار: شناسایی هزینه
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_expense.id,
            debit=total_cost, credit=0.0,
            description="هزینه خوراک مصرفی روزانه گله"
        ))

        # 2. بستانکار: کاهش دارایی انبار
        db.session.add(JournalEntryLine(
            journal_entry_id=entry.id, account_id=acc_inventory.id,
            debit=0.0, credit=total_cost,
            description="کاهش موجودی دفتری انبار بابت تغذیه"
        ))
        return entry

    @staticmethod
    def validate_balance(entry_id):
        # متدی برای چک کردن تراز بودن سند قبل از نهایی کردن
        lines = JournalEntryLine.query.filter_by(journal_entry_id=entry_id).all()
        return sum(l.debit for l in lines) == sum(l.credit for l in lines)