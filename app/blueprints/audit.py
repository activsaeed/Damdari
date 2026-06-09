from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from app.audit_engine import AuditEngine

audit_bp = Blueprint('audit', __name__, template_folder='../templates')


@audit_bp.route('/')
@login_required
def index():
    return render_template('audit/index.html')


@audit_bp.route('/run')
@login_required
def run_audit():
    engine = AuditEngine()
    check = request.args.get('check', 'all')

    checks = {
        'all': engine.run_full_audit,
        'double_entry': engine.verify_journal_entry_balance,
        'trial_balance': engine.verify_trial_balance,
        'balance_sheet': engine.verify_balance_sheet,
        'balance_sheet_equation': engine.verify_balance_sheet_equation,
        'income_statement': engine.verify_income_statement,
        'vat': engine.verify_vat_calculations,
        'discount': engine.verify_discount_handling,
        'contacts': engine.verify_contact_balances,
        'inventory': engine.verify_inventory_gl_match,
        'livestock': engine.verify_livestock_valuation,
        'depreciation': engine.verify_depreciation,
        'anomalies': engine.detect_anomalies,
    }

    if check in checks:
        result = checks[check]()
    else:
        return jsonify({'error': f'Unknown check: {check}'}), 400

    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response
