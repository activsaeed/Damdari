import jdatetime
from decimal import Decimal
from datetime import datetime
from app.extensions import db

PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹'
ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'
ENGLISH_DIGITS = '0123456789'
DIGIT_TRANSLATION = str.maketrans(PERSIAN_DIGITS + ARABIC_DIGITS, ENGLISH_DIGITS + ENGLISH_DIGITS)

def get_system_setting(key, default):
    from app.models import SystemSetting
    s = SystemSetting.query.filter_by(key=key).first()
    return s.value if s else default


def set_system_setting(key, value):
    from app.models import SystemSetting
    s = SystemSetting.query.filter_by(key=key).first()
    if not s:
        s = SystemSetting(key=key, value=str(value))
        db.session.add(s)
    else:
        s.value = str(value)
    db.session.commit()


# Cache for currency unit
_currency_unit = None

def _get_currency_unit():
    global _currency_unit
    if _currency_unit is not None:
        return _currency_unit
    try:
        _currency_unit = get_system_setting('currency_unit', 'تومان')
    except Exception:
        _currency_unit = 'تومان'
    return _currency_unit


def normalize_amount_to_toman(amount_str, currency_unit=None):
    if not amount_str:
        return Decimal('0')
    try:
        clean_str = str(amount_str).translate(DIGIT_TRANSLATION).replace(',', '').strip()
        amount = Decimal(clean_str)
        unit = currency_unit or _get_currency_unit()
        if unit == 'ریال':
            return amount / Decimal('10')
        return amount
    except Exception:
        return Decimal('0')


def parse_smart_date(date_str, default_val=None):
    if not date_str or str(date_str).strip() in ['', 'None']:
        return default_val

    date_str = str(date_str).translate(DIGIT_TRANSLATION).replace('/', '-').strip()
    try:
        if date_str.startswith(('13', '14')):
            p = date_str.split('-')
            return jdatetime.date(int(p[0]), int(p[1]), int(p[2])).togregorian()
        return datetime.strptime(date_str[:10], '%Y-%m-%d').date()
    except Exception:
        return default_val


def validate_national_id(nid):
    if not nid:
        return True
    nid = str(nid).translate(DIGIT_TRANSLATION).replace(' ', '').strip()
    if not nid.isdigit() or len(nid) != 10:
        return False
    if nid in [str(i) * 10 for i in range(10)]:
        return False
    s = sum(int(nid[i]) * (10 - i) for i in range(9))
    r = s % 11
    c = int(nid[9])
    return (r < 2 and c == r) or (r >= 2 and c == 11 - r)


def validate_sheba(sheba):
    if not sheba:
        return True
    sheba = str(sheba).replace(' ', '').strip().upper()
    if not sheba.startswith('IR') or len(sheba) != 26:
        return False
    return sheba[2:].isdigit()


def validate_card_luhn(card):
    if not card:
        return True
    card = str(card).replace(' ', '').strip()
    if not card.isdigit() or len(card) != 16:
        return False
    digits = [int(d) for d in card]
    for i in range(0, 16, 2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    return sum(digits) % 10 == 0


def permission_required(permission_name):
    """دکوراتور چک کردن دسترسی‌های داینامیک بر اساس فیلدهای مدل User"""
    from functools import wraps
    from flask_login import current_user
    from flask import flash, redirect, url_for

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                from flask import redirect, url_for
                return redirect(url_for('auth.login'))
            if not getattr(current_user, permission_name, False) and current_user.role != 'مدیر':
                flash('شما دسترسی لازم برای مشاهده این بخش را ندارید.', 'danger')
                from flask import redirect, url_for
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def clear_utils_cache():
    """Clear cached values (useful when SystemSetting changes currency unit)"""
    global _currency_unit
    _currency_unit = None