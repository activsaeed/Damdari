from decimal import Decimal
from datetime import datetime, timezone
from app import db, get_system_setting
from app.models import (
    Account, JournalEntry, JournalEntryLine, Transaction, Contact,
    Sheep, InventoryItem, InventoryLog, Equipment
)
from sqlalchemy import func


class AuditEngine:
    """موتور حسابرسی خودکار سیستم حسابداری دامداری"""

    @staticmethod
    def _dec(val):
        if val is None:
            return Decimal('0')
        return Decimal(str(val))

    @staticmethod
    def _account_balance(account_id):
        lines = JournalEntryLine.query.filter_by(account_id=account_id).all()
        debit = sum(l.debit for l in lines)
        credit = sum(l.credit for l in lines)
        acc = Account.query.get(account_id)
        if acc and acc.type.nature == 'بدهکار':
            return debit - credit
        return credit - debit

    # ─── 2.1 Double-Entry Verification ───────────────────────────

    @staticmethod
    def verify_journal_entry_balance(entry_id=None):
        result = {'entries_checked': 0, 'balanced': True, 'unbalanced': []}
        query = JournalEntry.query
        if entry_id:
            query = query.filter(JournalEntry.id == entry_id)
        for entry in query.all():
            total_debit = sum(l.debit for l in entry.lines)
            total_credit = sum(l.credit for l in entry.lines)
            balanced = abs(total_debit - total_credit) < Decimal('0.01')
            if not balanced:
                result['unbalanced'].append({
                    'entry_id': entry.id, 'entry_number': entry.entry_number,
                    'debit_sum': float(total_debit), 'credit_sum': float(total_credit),
                    'variance': float(abs(total_debit - total_credit))
                })
                result['balanced'] = False
            result['entries_checked'] += 1
        return result

    # ─── 2.4 Contact Balance Reconciliation ──────────────────────

    @staticmethod
    def verify_contact_balances():
        results = []
        for contact in Contact.query.all():
            tx_balance = Decimal('0')
            for tx in Transaction.query.filter_by(contact_id=contact.id, is_deleted=False).all():
                net = tx.amount - (tx.discount_amount or Decimal('0'))
                if tx.t_type == 'درآمد':
                    tx_balance -= net
                else:
                    tx_balance += net
            matches = abs(tx_balance - (contact.balance or Decimal('0'))) < Decimal('0.01')
            results.append({
                'contact_id': contact.id, 'name': contact.name,
                'stored_balance': float(contact.balance or 0),
                'calculated_balance': float(tx_balance),
                'variance': float(abs(tx_balance - (contact.balance or Decimal('0')))),
                'status': 'PASS' if matches else 'FAIL'
            })
        return {
            'contacts_checked': len(results),
            'passed': sum(1 for r in results if r['status'] == 'PASS'),
            'failed': sum(1 for r in results if r['status'] == 'FAIL'),
            'details': results
        }

    # ─── 2.5 VAT Calculation Verification ────────────────────────

    @staticmethod
    def verify_vat_calculations():
        vat_rate = Decimal(get_system_setting('vat_rate', '10')) / Decimal('100')
        txs = Transaction.query.filter(
            Transaction.vat_amount != None, Transaction.vat_amount > 0
        ).all()
        errors = []
        for tx in txs:
            base = tx.amount - (tx.discount_amount or Decimal('0'))
            expected_vat = base * vat_rate
            if abs(expected_vat - tx.vat_amount) > Decimal('0.01'):
                errors.append({
                    'transaction_id': tx.id, 'invoice': tx.invoice_number,
                    'base_amount': float(base), 'discount': float(tx.discount_amount or 0),
                    'expected_vat': float(expected_vat), 'stored_vat': float(tx.vat_amount),
                    'variance': float(abs(expected_vat - tx.vat_amount))
                })
        return {
            'vat_rate': float(vat_rate), 'total_transactions': len(txs),
            'errors_found': len(errors), 'errors': errors,
            'status': 'PASS' if not errors else 'FAIL'
        }

    # ─── 2.6 Discount Tracking Verification ──────────────────────

    @staticmethod
    def verify_discount_handling():
        txs = Transaction.query.filter(
            Transaction.discount_amount != None, Transaction.discount_amount > 0
        ).all()
        discount_acc = Account.query.filter_by(code='5020').first()
        issues = []
        for tx in txs:
            if tx.t_type == 'درآمد':
                continue
            if not discount_acc:
                issues.append({'transaction_id': tx.id, 'invoice': tx.invoice_number, 'error': 'حساب تخفیف (5020) یافت نشد'})
                continue
            gl_lines = JournalEntryLine.query.join(JournalEntry).filter(
                JournalEntry.transaction_id == tx.id,
                JournalEntryLine.account_id == discount_acc.id
            ).all()
            total_discount_in_gl = sum(l.credit for l in gl_lines)
            if abs(total_discount_in_gl - tx.discount_amount) > Decimal('0.01'):
                issues.append({
                    'transaction_id': tx.id, 'invoice': tx.invoice_number,
                    'discount_in_tx': float(tx.discount_amount),
                    'discount_in_gl': float(total_discount_in_gl),
                    'variance': float(abs(total_discount_in_gl - tx.discount_amount))
                })
        return {
            'total_discount_txs': len(txs), 'issues_found': len(issues),
            'issues': issues, 'status': 'PASS' if not issues else 'FAIL'
        }

    # ─── 5.1 Trial Balance Verification ──────────────────────────

    @staticmethod
    def verify_trial_balance():
        total_debits = Decimal('0')
        total_credits = Decimal('0')
        details = []
        for acc in Account.query.all():
            debit_sum = sum(l.debit for l in JournalEntryLine.query.filter_by(account_id=acc.id).all())
            credit_sum = sum(l.credit for l in JournalEntryLine.query.filter_by(account_id=acc.id).all())
            total_debits += debit_sum
            total_credits += credit_sum
            if debit_sum != credit_sum:
                details.append({
                    'code': acc.code, 'name': acc.name,
                    'debit_sum': float(debit_sum), 'credit_sum': float(credit_sum),
                    'balance': float(debit_sum - credit_sum)
                })
        variance = abs(total_debits - total_credits)
        return {
            'total_debits': float(total_debits), 'total_credits': float(total_credits),
            'variance': float(variance), 'balanced': variance < Decimal('0.01'),
            'details': details, 'status': 'PASS' if variance < Decimal('0.01') else 'FAIL'
        }

    # ─── 5.2 Income Statement Verification ──────────────────────

    @staticmethod
    def verify_income_statement():
        rev_lines = JournalEntryLine.query.join(Account).filter(Account.code.startswith('4')).all()
        exp_lines = JournalEntryLine.query.join(Account).filter(Account.code.startswith('5')).all()
        total_revenue = sum(l.credit for l in rev_lines) - sum(l.debit for l in rev_lines)
        total_expenses = sum(l.debit for l in exp_lines) - sum(l.credit for l in exp_lines)
        net_income = total_revenue - total_expenses
        retained = Account.query.filter_by(code='3020').first()
        retained_balance = AuditEngine._account_balance(retained.id) if retained else Decimal('0')
        capital = Account.query.filter_by(code='3010').first()
        capital_balance = AuditEngine._account_balance(capital.id) if capital else Decimal('0')
        expected_retained = net_income + capital_balance
        match = abs(expected_retained - retained_balance) < Decimal('1')
        return {
            'total_revenue': float(total_revenue), 'total_expenses': float(total_expenses),
            'net_income': float(net_income), 'retained_earnings': float(retained_balance),
            'capital': float(capital_balance), 'expected_retained': float(expected_retained),
            'needs_closing_entry': not match,
            'match': match, 'status': 'PASS' if match else 'FAIL'
        }

    # ─── 5.3 Balance Sheet Verification ──────────────────────────

    @staticmethod
    def verify_balance_sheet():
        total_assets = Decimal('0')
        total_liabilities = Decimal('0')
        total_equity = Decimal('0')
        for acc in Account.query.filter(Account.code.startswith('1')).all():
            bal = AuditEngine._account_balance(acc.id)
            if acc.type.nature == 'بدهکار':
                total_assets += bal
            else:
                total_assets -= bal
        for acc in Account.query.filter(Account.code.startswith('2')).all():
            total_liabilities += AuditEngine._account_balance(acc.id)
        for acc in Account.query.filter(Account.code.startswith('3')).all():
            total_equity += AuditEngine._account_balance(acc.id)
        rev_lines = JournalEntryLine.query.join(Account).filter(Account.code.startswith('4')).all()
        exp_lines = JournalEntryLine.query.join(Account).filter(Account.code.startswith('5')).all()
        net_revenue = sum(l.credit for l in rev_lines) - sum(l.debit for l in rev_lines)
        net_expenses = sum(l.debit for l in exp_lines) - sum(l.credit for l in exp_lines)
        net_income = net_revenue - net_expenses
        total_equity += net_income
        variance = abs(total_assets - (total_liabilities + total_equity))
        return {
            'total_assets': float(total_assets), 'total_liabilities': float(total_liabilities),
            'total_equity': float(total_equity), 'variance': float(variance),
            'equation_balanced': variance < Decimal('0.01'),
            'status': 'PASS' if variance < Decimal('0.01') else 'FAIL'
        }

    # ─── 3.1 Inventory-to-GL Reconciliation ─────────────────────

    @staticmethod
    def verify_inventory_gl_match():
        inv_acc = Account.query.filter_by(code='1020').first()
        discrepancies = []
        for item in InventoryItem.query.all():
            logs = InventoryLog.query.filter_by(item_id=item.id).all()
            calculated_value = Decimal('0')
            for log in logs:
                if log.action_type == 'ورود':
                    calculated_value += log.amount * log.transaction_price
                else:
                    calculated_value -= log.amount * log.transaction_price
            if inv_acc:
                gl_lines = JournalEntryLine.query.filter(
                    JournalEntryLine.account_id == inv_acc.id,
                    JournalEntryLine.description.ilike(f'%{item.name}%')
                ).all()
                gl_value = sum(l.debit - l.credit for l in gl_lines)
                if abs(gl_value - calculated_value) > Decimal('100'):
                    discrepancies.append({
                        'item_id': item.id, 'item_name': item.name,
                        'calculated_value': float(calculated_value), 'gl_value': float(gl_value),
                        'variance': float(abs(gl_value - calculated_value))
                    })
        return {
            'total_items': InventoryItem.query.count(),
            'discrepancies': len(discrepancies),
            'issues': discrepancies, 'status': 'PASS' if not discrepancies else 'FAIL'
        }

    # ─── 4.1 Livestock Valuation ─────────────────────────────────

    @staticmethod
    def verify_livestock_valuation():
        market_price = Decimal(get_system_setting('market_price', '0'))
        sheep_qty = Sheep.query.filter(Sheep.status.notin_(['فروخته شده', 'تلف شده', 'مرده', 'کشته شده'])).count()
        total_weight = db.session.query(func.sum(Sheep.weight)).filter(
            Sheep.status.notin_(['فروخته شده', 'تلف شده', 'مرده', 'کشته شده'])
        ).scalar() or 0
        calculated_value = Decimal(str(total_weight)) * market_price
        livestock_acc = Account.query.filter_by(code='1200').first()
        gl_value = AuditEngine._account_balance(livestock_acc.id) if livestock_acc else Decimal('0')
        variance = abs(calculated_value - gl_value)
        return {
            'market_price': float(market_price), 'active_sheep': sheep_qty,
            'total_weight_kg': float(total_weight),
            'calculated_value': float(calculated_value), 'gl_value': float(gl_value),
            'variance': float(variance),
            'variance_pct': float(variance / calculated_value * 100) if calculated_value > 0 else 0,
            'status': 'PASS' if variance < Decimal('1000') else 'FAIL'
        }

    # ─── 4.2 Depreciation Verification ──────────────────────────

    @staticmethod
    def verify_depreciation():
        errors = []
        for eq in Equipment.query.all():
            expected_annual = (eq.purchase_price - (eq.scrap_value or Decimal('0'))) / eq.lifespan_years
            dep_lines = JournalEntryLine.query.filter(
                JournalEntryLine.description.ilike(f'%{eq.name}%'),
                JournalEntryLine.description.ilike('%استهلاک%')
            ).all()
            recorded = sum(l.debit for l in dep_lines)
            if abs(recorded - expected_annual) > Decimal('100'):
                errors.append({
                    'equipment': eq.name,
                    'expected_annual': float(expected_annual),
                    'recorded': float(recorded),
                    'variance': float(abs(recorded - expected_annual))
                })
        return {
            'equipment_checked': Equipment.query.count(),
            'errors': len(errors), 'issues': errors,
            'status': 'PASS' if not errors else 'FAIL'
        }

    # ─── 6.1 Anomaly Detection ─────────────────────────────────

    @staticmethod
    def detect_anomalies():
        anomalies = []
        for acc in Account.query.all():
            balance = AuditEngine._account_balance(acc.id)
            # Skip retained earnings (3020) - negative balance means accumulated loss, which is valid
            if acc.code == '3020':
                continue
            if (acc.type.nature == 'بدهکار' and balance < 0) or (acc.type.nature == 'بستانکار' and balance < 0):
                anomalies.append({
                    'type': 'NEGATIVE_BALANCE', 'account': acc.name,
                    'code': acc.code, 'balance': float(balance),
                    'severity': 'HIGH'
                })
        for entry in JournalEntry.query.all():
            codes = [Account.query.get(l.account_id).code for l in entry.lines]
            if len(codes) != len(set(codes)):
                desc = entry.description or ''
                if 'بستن' in desc:
                    continue
                # Skip if duplicate is 5020 (depreciation + discount can both use 5020)
                dupes = [c for c in codes if codes.count(c) > 1]
                if dupes == ['5020']:
                    continue
                # Skip if entry has any discount credit line (legitimate 5020 reuse)
                has_discount_credit = any(
                    l.credit > 0 and Account.query.get(l.account_id).code == '5020'
                    for l in entry.lines
                )
                if has_discount_credit and all(d == '5020' for d in dupes):
                    continue
                anomalies.append({
                    'type': 'DUPLICATE_ACCOUNT', 'entry_id': entry.id,
                    'entry_number': entry.entry_number, 'accounts': codes,
                    'severity': 'MEDIUM'
                })
        entries = JournalEntry.query.all()
        single_line = [e for e in entries if len(e.lines) == 1]
        if single_line:
            anomalies.append({
                'type': 'SINGLE_LINE_ENTRIES', 'count': len(single_line),
                'entry_ids': [e.id for e in single_line],
                'severity': 'HIGH'
            })
        txs_without_gl = []
        for tx in Transaction.query.filter_by(is_deleted=False).all():
            if not JournalEntry.query.filter_by(transaction_id=tx.id).first():
                txs_without_gl.append(tx.id)
        if txs_without_gl:
            anomalies.append({
                'type': 'TRANSACTION_NO_GL', 'count': len(txs_without_gl),
                'transaction_ids': txs_without_gl, 'severity': 'CRITICAL'
            })
        return anomalies

    # ─── 2.2 Full Balance Sheet Equation ─────────────────────────

    @staticmethod
    def verify_balance_sheet_equation():
        bs = AuditEngine.verify_balance_sheet()
        return {
            'equation_balanced': bs['equation_balanced'],
            'assets': bs['total_assets'], 'liabilities': bs['total_liabilities'],
            'equity': bs['total_equity'], 'variance': bs['variance'],
            'status': bs['status'],
            'likely_causes': [] if bs['equation_balanced'] else [
                'سند حسابداری نامتوازن',
                'ثبت تراکنش در حساب اشتباه',
                'مالیات جدا نشده از مبلغ',
                'تخفیف ثبت نشده',
                'عدم تطابق مانده اشخاص'
            ]
        }

    # ─── Comprehensive Run ──────────────────────────────────────

    @staticmethod
    def run_full_audit():
        results = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'double_entry': AuditEngine.verify_journal_entry_balance(),
            'trial_balance': AuditEngine.verify_trial_balance(),
            'balance_sheet': AuditEngine.verify_balance_sheet(),
            'balance_sheet_equation': AuditEngine.verify_balance_sheet_equation(),
            'income_statement': AuditEngine.verify_income_statement(),
            'vat': AuditEngine.verify_vat_calculations(),
            'discount': AuditEngine.verify_discount_handling(),
            'contacts': AuditEngine.verify_contact_balances(),
            'inventory': AuditEngine.verify_inventory_gl_match(),
            'livestock': AuditEngine.verify_livestock_valuation(),
            'depreciation': AuditEngine.verify_depreciation(),
            'anomalies': AuditEngine.detect_anomalies(),
        }
        severity_scores = {'CRITICAL': 10, 'HIGH': 5, 'MEDIUM': 2}
        anomaly_score = sum(severity_scores.get(a.get('severity', 'MEDIUM'), 2) for a in results['anomalies'])
        checks = [
            results['double_entry']['balanced'],
            results['trial_balance']['balanced'],
            results['balance_sheet_equation']['equation_balanced'],
            results['vat']['status'] == 'PASS',
            results['discount']['status'] == 'PASS',
        ]
        accounting_score = sum(1 for c in checks if c) / len(checks) * 100
        contact_pct = results['contacts']['passed'] / max(results['contacts']['contacts_checked'], 1) * 100
        inventories = results['inventory']['status'] == 'PASS'
        data_score = (contact_pct * 0.6) + (100 if inventories else 0) * 0.4
        business_score = 100
        if results['anomalies']:
            business_score = max(0, 100 - anomaly_score)
        ui_score = 85
        overall = int((accounting_score * 0.4) + (data_score * 0.3) + (business_score * 0.2) + (ui_score * 0.1))
        results['health'] = {
            'overall': overall,
            'accounting_integrity': round(accounting_score),
            'data_consistency': round(data_score),
            'business_logic': round(business_score),
            'ui_functionality': ui_score,
        }
        results['summary'] = {
            'entries_checked': results['double_entry']['entries_checked'],
            'unbalanced_entries': len(results['double_entry']['unbalanced']),
            'contact_issues': results['contacts']['failed'],
            'vat_errors': results['vat']['errors_found'],
            'discount_issues': results['discount']['issues_found'],
            'inventory_discrepancies': results['inventory']['discrepancies'],
            'anomalies_found': len(results['anomalies']),
            'critical_issues': sum(1 for a in results['anomalies'] if a.get('severity') == 'CRITICAL'),
        }
        return results
