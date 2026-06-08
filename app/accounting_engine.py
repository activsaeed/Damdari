from decimal import Decimal
from app import db
from app.models import Account, JournalEntry, JournalEntryLine, InventoryItem, Equipment
from datetime import datetime, UTC
import time
import random

class AccountingEngine:
    @staticmethod
    def get_account(code):
        return Account.query.filter_by(code=code).first()

    @staticmethod
    def require_account(code):
        acc = AccountingEngine.get_account(code)
        if not acc:
            raise ValueError(f"حساب با کد {code} در سیستم تعریف نشده است. لطفاً ابتدا حساب‌های ضروری را ایجاد کنید.")
        return acc

    @staticmethod
    def get_vat_rate():
        from app.blueprints.dashboard import get_setting
        return Decimal(get_setting('vat_rate', '10')) / Decimal('100')

    @staticmethod
    def generate_entry_number():
        return f"SANAD-{time.time_ns()}-{random.randint(100000, 999999)}"

    @staticmethod
    def validate_amounts(debit, credit):
        if debit < 0 or credit < 0:
            raise ValueError(f"مقادیر بدهکار ({debit}) و بستانکار ({credit}) نمی‌توانند منفی باشند.")
        if debit > 0 and credit > 0:
            raise ValueError("هر ردیف سند حسابداری نمی‌تواند همزمان بدهکار و بستانکار داشته باشد.")
        if debit == 0 and credit == 0:
            raise ValueError("هر ردیف سند حسابداری باید حداقل یک طرف (بدهکار یا بستانکار) داشته باشد.")

    @staticmethod
    def add_line(journal_entry_id, account_id, debit, credit, description=None, contact_id=None):
        AccountingEngine.validate_amounts(debit, credit)
        db.session.add(JournalEntryLine(
            journal_entry_id=journal_entry_id, account_id=account_id,
            debit=Decimal(str(debit)), credit=Decimal(str(credit)),
            description=description, contact_id=contact_id
        ))

    @staticmethod
    def record_sale(transaction, contact_id=None, include_vat=True):
        """ثبت اتوماتیک سند فروش (درآمد)"""
        try:
            with db.session.begin_nested():
                cash_account = AccountingEngine.require_account('1010')
                receivable_account = AccountingEngine.require_account('1030')
                sales_account = AccountingEngine.require_account('4010')
                vat_payable = AccountingEngine.get_account('2030')

                amount = transaction.amount
                vat_amount = transaction.vat_amount or Decimal('0') if include_vat else Decimal('0')
                discount_amount = transaction.discount_amount or Decimal('0')
                total_amount = (amount - discount_amount) + vat_amount

                entry = JournalEntry(
                    entry_number=AccountingEngine.generate_entry_number(),
                    date=transaction.t_date,
                    description=f"بابت فاکتور فروش شماره {transaction.invoice_number or 'نامشخص'}",
                    transaction_id=transaction.id
                )
                db.session.add(entry)
                db.session.flush()

                effective_contact_id = contact_id or transaction.contact_id
                
                # تشخیص حساب بدهکار بر اساس نوع شخص و روش پرداخت
                if transaction.payment_method == 'نسیه' and effective_contact_id:
                    from app.models import Contact
                    contact = db.session.get(Contact, effective_contact_id)
                    if contact and contact.contact_type and 'تامین' in contact.contact_type:
                        debit_acc_id = cash_account.id  # تامین‌کننده -> نقدی
                    else:
                        debit_acc_id = receivable_account.id  # مشتری -> دریافتنی
                else:
                    debit_acc_id = cash_account.id
                
                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=debit_acc_id, contact_id=effective_contact_id, debit=total_amount, credit=0.0))
                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=sales_account.id, debit=0.0, credit=amount))

                if vat_amount > 0 and vat_payable:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=vat_payable.id, debit=0.0, credit=vat_amount))
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت فاکتور فروش: {str(e)}")

    @staticmethod
    def record_expense(transaction, contact_id=None, include_vat=True):
        """ثبت اتوماتیک سند خرید / هزینه"""
        try:
            with db.session.begin_nested():
                cash_account = AccountingEngine.require_account('1010')
                payable_account = AccountingEngine.require_account('2010')
                expense_account = AccountingEngine.require_account('5010')
                vat_receivable = AccountingEngine.get_account('1040')

                amount = transaction.amount
                vat_amount = transaction.vat_amount or Decimal('0') if include_vat else Decimal('0')
                discount_amount = transaction.discount_amount or Decimal('0')
                total_amount = (amount - discount_amount) + vat_amount

                entry = JournalEntry(
                    entry_number=AccountingEngine.generate_entry_number(),
                    date=transaction.t_date,
                    description=f"بابت فاکتور هزینه/خرید شماره {transaction.invoice_number or 'نامشخص'}",
                    transaction_id=transaction.id
                )
                db.session.add(entry)
                db.session.flush()

                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=expense_account.id, debit=amount, credit=0.0))

                if vat_amount > 0 and vat_receivable:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=vat_receivable.id, debit=vat_amount, credit=0.0))

                effective_contact_id = contact_id or transaction.contact_id
                
                # تشخیص حساب بستانکار بر اساس نوع شخص و روش پرداخت
                if transaction.payment_method == 'نسیه' and effective_contact_id:
                    from app.models import Contact
                    contact = db.session.get(Contact, effective_contact_id)
                    if contact and contact.contact_type and 'مشتری' in contact.contact_type:
                        credit_acc_id = cash_account.id  # مشتری -> نقدی
                    else:
                        credit_acc_id = payable_account.id  # تامین‌کننده -> پرداختنی
                else:
                    credit_acc_id = cash_account.id
                
                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=credit_acc_id, contact_id=effective_contact_id, debit=0.0, credit=total_amount))
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت فاکتور هزینه: {str(e)}")

    @staticmethod
    def record_cheque_issuance(cheque):
        """ثبت سند حسابداری هنگام صدور/دریافت چک (مرحله تعهدی)"""
        try:
            with db.session.begin_nested():
                description = f"ثبت تعهدی چک شماره {cheque.cheque_number} - {cheque.cheque_type} - بابت {cheque.reason}"
                entry = JournalEntry(
                    entry_number=AccountingEngine.generate_entry_number(),
                    date=cheque.issue_date or datetime.now(UTC).date(),
                    description=description
                )
                db.session.add(entry)
                db.session.flush()

                if cheque.cheque_type == 'دریافتی (مشتری)':
                    acc_notes_recv = AccountingEngine.get_account('1050')  # اسناد دریافتنی
                    acc_recv = AccountingEngine.get_account('1030')       # حساب‌های دریافتنی
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_notes_recv.id, debit=cheque.amount, credit=0.0, description=f"دریافت چک از {cheque.issuer_name or 'نامشخص'}"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_recv.id, debit=0.0, credit=cheque.amount, description=f"کاهش حساب دریافتنی - {cheque.issuer_name or 'نامشخص'}"))
                else:
                    acc_notes_pay = AccountingEngine.get_account('2020')  # اسناد پرداختنی
                    acc_pay = AccountingEngine.get_account('2010')        # حساب‌های پرداختنی
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_pay.id, debit=cheque.amount, credit=0.0, description=f"کاهش حساب پرداختنی - {cheque.registered_to or 'نامشخص'}"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_notes_pay.id, debit=0.0, credit=cheque.amount, description=f"صدور چک به {cheque.registered_to or 'نامشخص'}"))

                return entry
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت سند تعهدی چک: {str(e)}")

    @staticmethod
    def record_cheque_clearing(cheque):
        """ثبت سند حسابداری هنگام پاس شدن چک (انتقال از اسناد به بانک)"""
        try:
            with db.session.begin_nested():
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
                    acc_notes_recv = AccountingEngine.get_account('1050')  # اسناد دریافتنی
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=cheque.amount, credit=0.0, description=f"وصول چک دریافتی - {cheque.issuer_name or 'نامشخص'}"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_notes_recv.id, debit=0.0, credit=cheque.amount, description=f"کاهش اسناد دریافتنی - {cheque.issuer_name or 'نامشخص'}"))
                else:
                    acc_notes_pay = AccountingEngine.get_account('2020')  # اسناد پرداختنی
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_notes_pay.id, debit=cheque.amount, credit=0.0, description=f"تسویه اسناد پرداختنی - {cheque.registered_to or 'نامشخص'}"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=0.0, credit=cheque.amount, description=f"پرداخت نقدی چک به {cheque.registered_to or 'نامشخص'}"))
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت سند تسویه چک: {str(e)}")


    @staticmethod
    def record_livestock_valuation(total_fair_value):
        from sqlalchemy import func
        try:
            with db.session.begin_nested():
                acc_livestock = AccountingEngine.get_account('1200')
                acc_revenue = AccountingEngine.get_account('4010')
                acc_expense = AccountingEngine.get_account('5010')

                debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc_livestock.id).scalar() or 0.0
                credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc_livestock.id).scalar() or 0.0
                current_book_value = debits - credits

                adjustment = total_fair_value - current_book_value
                if abs(adjustment) < 1: return

                entry = JournalEntry(
                    entry_number=AccountingEngine.generate_entry_number(),
                    date=datetime.now(UTC).date(),
                    description=f"تعدیل ارزش منصفانه گله (استاندارد ۲۶) - ارزش جدید بازار: {total_fair_value:,.0f}"
                )
                db.session.add(entry)
                db.session.flush()

                if adjustment > 0:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_livestock.id, debit=adjustment, credit=0.0, description="افزایش ارزش منصفانه دارایی زیستی (رشد فیزیکی/قیمت)"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_revenue.id, debit=0.0, credit=adjustment, description="سود حاصل از تغییر ارزش منصفانه گله"))
                else:
                    loss_amount = abs(adjustment)
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=loss_amount, credit=0.0, description="زیان حاصل از تغییر ارزش منصفانه گله"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_livestock.id, debit=0.0, credit=loss_amount, description="کاهش ارزش منصفانه دارایی زیستی"))
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت ارزیابی گله: {str(e)}")

    @staticmethod
    def close_temporary_accounts():
        from sqlalchemy import func
        from app.models import Account, JournalEntryLine
        try:
            with db.session.begin_nested():
                acc_retained_earnings = AccountingEngine.get_account('3020') or AccountingEngine.get_account('3010')

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
                    if not acc.type: continue
                    debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc.id).scalar() or 0.0
                    credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc.id).scalar() or 0.0
                    
                    if acc.type.nature == 'بدهکار':
                        balance = debits - credits
                        if balance > 0:
                            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=0.0, credit=balance, description=f"بستن حساب {acc.name}"))
                            total_credit_adjustment += balance
                    else:
                        balance = credits - debits
                        if balance > 0:
                            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=balance, credit=0.0, description=f"بستن حساب {acc.name}"))
                            total_debit_adjustment += balance

                net_result = total_debit_adjustment - total_credit_adjustment
                
                if net_result > 0:
                    db.session.add(JournalEntryLine(
                        journal_entry_id=entry.id, account_id=acc_retained_earnings.id,
                        debit=0.0, credit=net_result,
                        description="انتقال سود خالص دوره مالی به حساب سود و زیان انباشته"
                    ))
                elif net_result < 0:
                    db.session.add(JournalEntryLine(
                        journal_entry_id=entry.id, account_id=acc_retained_earnings.id,
                        debit=abs(net_result), credit=0.0,
                        description="انتقال زیان خالص دوره مالی به حساب سود و زیان انباشته"
                    ))
                    
                return entry
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در بستن حساب‌های موقت: {str(e)}")

    @staticmethod
    def sync_inventory_ledger():
        from sqlalchemy import func
        try:
            with db.session.begin_nested():
                acc_inventory = AccountingEngine.get_account('1020')
                acc_expense = AccountingEngine.get_account('5010')

                all_items = InventoryItem.query.all()
                actual_warehouse_value = sum((item.quantity or 0) * (item.unit_price or 0) for item in all_items)

                debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc_inventory.id).scalar() or 0.0
                credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc_inventory.id).scalar() or 0.0
                book_value = debits - credits

                consumption_value = book_value - actual_warehouse_value

                if abs(consumption_value) < 1:
                    return None

                entry = JournalEntry(
                    entry_number=AccountingEngine.generate_entry_number(),
                    date=datetime.now(UTC).date(),
                    description=f"سند انبارگردانی و انتقال مانده به سال جدید - ارزش موجودی: {actual_warehouse_value:,.0f}"
                )
                db.session.add(entry)
                db.session.flush()

                if consumption_value > 0:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=consumption_value, credit=0.0, description="ثبت هزینه کالای مصرف شده در طول دوره"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_inventory.id, debit=0.0, credit=consumption_value, description="کاهش موجودی انبار بابت مصرف/انبارگردانی"))
                else:
                    added_value = abs(consumption_value)
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_inventory.id, debit=added_value, credit=0.0, description="افزایش موجودی دفتری بابت مازاد انبارگردانی"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=AccountingEngine.get_account('4010').id, debit=0.0, credit=added_value, description="درآمد حاصل از مازاد انبارگردانی"))

                return entry
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در همگام‌سازی انبار: {str(e)}")

    @staticmethod
    def record_depreciation(asset_name, amount):
        """ثبت هزینه استهلاک دارایی‌های ثابت"""
        from app.models import Equipment
        # یافتن دارایی برای کنترل سقف استهلاک
        asset = Equipment.query.filter_by(name=asset_name).first()

        try:
            with db.session.begin_nested():
                if asset:
                    current_bv = asset.book_value
                    # استهلاک باید تا رسیدن به ارزش اسقاط ادامه یابد
                    depreciable_base = current_bv - asset.scrap_value
                    if depreciable_base <= 0:
                        raise Exception(f"دارایی {asset_name} به ارزش اسقاط رسیده و کاملاً مستهلک شده است.")
                    
                    # جلوگیری از ثبت استهلاک مازاد بر مانده استهلاک‌پذیر
                    if amount > depreciable_base:
                        amount = depreciable_base

                description = f"ثبت استهلاک دوره‌ای - {asset_name}"
                entry = JournalEntry(
                    entry_number=AccountingEngine.generate_entry_number(),
                    date=datetime.now(UTC).date(),
                    description=description
                )
                db.session.add(entry)
                db.session.flush()

                acc_expense = AccountingEngine.get_account('5020') or AccountingEngine.get_account('5010')
                acc_accum_dep = AccountingEngine.get_account('1204')

                if not acc_accum_dep:
                    acc_accum_dep = AccountingEngine.get_account('1201')

                db.session.add(JournalEntryLine(
                    journal_entry_id=entry.id, account_id=acc_expense.id,
                    debit=amount, credit=0.0, description=f"هزینه استهلاک {asset_name}"
                ))

                db.session.add(JournalEntryLine(
                    journal_entry_id=entry.id, account_id=acc_accum_dep.id,
                    debit=0.0, credit=amount, description=f"ذخیره استهلاک انباشته {asset_name}"
                ))
                return entry
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت استهلاک: {str(e)}")

    @staticmethod
    def record_insurance_payment(amount, description, date):
        try:
            with db.session.begin_nested():
                entry = JournalEntry(
                    entry_number=AccountingEngine.generate_entry_number(),
                    date=date,
                    description=f"واریز حق بیمه سازمان: {description}"
                )
                db.session.add(entry)
                db.session.flush()

                acc_payable = AccountingEngine.get_account('2010')
                acc_bank = AccountingEngine.get_account('1010')

                db.session.add(JournalEntryLine(
                    journal_entry_id=entry.id, account_id=acc_payable.id,
                    debit=amount, credit=0.0,
                    description=f"بیمه پرداختنی سازمان - تسویه واریزی: {description}"
                ))

                db.session.add(JournalEntryLine(
                    journal_entry_id=entry.id, account_id=acc_bank.id,
                    debit=0.0, credit=amount,
                    description=f"برداشت از بانک بابت واریز بیمه - {description}"
                ))
                return entry
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت واریز بیمه: {str(e)}")

    @staticmethod
    def record_payroll(payslip):
        try:
            with db.session.begin_nested():
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

                insurance_employer = (payslip.base_salary or Decimal('0')) * Decimal('0.23')
                insurance_total = (payslip.base_salary or Decimal('0')) * Decimal('0.30')

                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=payslip.gross_pay, credit=0.0, description=f"هزینه حقوق و مزایای ناخالص - {payslip.worker.name}"))
                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_expense.id, debit=insurance_employer, credit=0.0, description=f"بیمه سهم کارفرما (23%) - {payslip.worker.name}"))
                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, debit=0.0, credit=payslip.net_pay, description=f"خالص حقوق پرداختنی - {payslip.worker.name}"))
                db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, debit=0.0, credit=insurance_total, description=f"بیمه پرداختنی سازمان (30%) - {payslip.worker.name}"))

                if (payslip.loan_deduction or 0) > 0:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_receivable.id, debit=0.0, credit=payslip.loan_deduction, description=f"وصول قسط وام - {payslip.worker.name}"))
                if (payslip.fines or 0) > 0:
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, debit=payslip.fines, credit=0.0, description=f"کسر جریمه - {payslip.worker.name}"))
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت سند حقوق: {str(e)}")

    @staticmethod
    def record_feed_consumption(total_cost):
        try:
            with db.session.begin_nested():
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
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت مصرف خوراک: {str(e)}")

    @staticmethod
    def record_contact_settlement(contact, amount, action_type, date):
        try:
            with db.session.begin_nested():
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
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_payable.id, contact_id=contact.id, debit=amount, credit=0.0, description=f"کاهش بدهی به {contact.name}"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=0.0, credit=amount, description=f"پرداخت نقدی به {contact.name}"))
                else:
                    acc_receivable = AccountingEngine.get_account('1030')
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_bank.id, debit=amount, credit=0.0, description=f"دریافت وجه از {contact.name}"))
                    db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc_receivable.id, contact_id=contact.id, debit=0.0, credit=amount, description=f"کاهش مطالبات از {contact.name}"))

                return entry
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت تسویه حساب: {str(e)}")

    @staticmethod
    def record_reversal_entry(old_entry, description=None):
        """ایجاد سند برگشتی (معکوس) برای یک سند حسابداری قبلی"""
        try:
            with db.session.begin_nested():
                rev_description = description or f"برگشت از سند {old_entry.entry_number} - {old_entry.description}"
                rev_entry = JournalEntry(
                    entry_number=AccountingEngine.generate_entry_number(),
                    date=datetime.now(UTC).date(),
                    description=rev_description,
                    transaction_id=old_entry.transaction_id,
                    reversed_entry_id=old_entry.id
                )
                db.session.add(rev_entry)
                db.session.flush()

                for line in old_entry.lines.all():
                    db.session.add(JournalEntryLine(
                        journal_entry_id=rev_entry.id,
                        account_id=line.account_id,
                        contact_id=line.contact_id,
                        debit=line.credit,
                        credit=line.debit,
                        description=f"برگشت: {line.description}"
                    ))

                old_entry.status = 'برگشتی'
                return rev_entry
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت سند برگشتی: {str(e)}")

    @staticmethod
    def record_opening_entry():
        from sqlalchemy import func, or_
        try:
            with db.session.begin_nested():
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
                    if not acc.type: continue
                    debits = db.session.query(func.sum(JournalEntryLine.debit)).filter_by(account_id=acc.id).scalar() or 0.0
                    credits = db.session.query(func.sum(JournalEntryLine.credit)).filter_by(account_id=acc.id).scalar() or 0.0
                    
                    if acc.type.nature == 'بدهکار':
                        balance = debits - credits
                        if balance > 0:
                            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=balance, credit=0.0, description=f"مانده اول دوره - {acc.name}"))
                        elif balance < 0:
                            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=0.0, credit=abs(balance), description=f"مانده اول دوره - {acc.name}"))
                    else:
                        balance = credits - debits
                        if balance > 0:
                            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=0.0, credit=balance, description=f"مانده اول دوره - {acc.name}"))
                        elif balance < 0:
                            db.session.add(JournalEntryLine(journal_entry_id=entry.id, account_id=acc.id, debit=abs(balance), credit=0.0, description=f"مانده اول دوره - {acc.name}"))
                
                return entry
        except Exception as e:
            db.session.rollback()
            raise Exception(f"خطا در ثبت سند افتتاحیه: {str(e)}")

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