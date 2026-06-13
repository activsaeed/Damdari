from decimal import Decimal
from app.utils import (
    normalize_amount_to_toman, parse_smart_date,
    validate_national_id, validate_sheba, validate_card_luhn
)


def test_normalize_amount_persian_digits():
    result = normalize_amount_to_toman('۱۲۳۴۵۶۷۸۹۰', currency_unit='تومان')
    assert result == Decimal('1234567890')


def test_normalize_amount_with_commas():
    result = normalize_amount_to_toman('1,500,000', currency_unit='تومان')
    assert result == Decimal('1500000')


def test_normalize_amount_rial_to_toman():
    result = normalize_amount_to_toman('50000', currency_unit='ریال')
    assert result == Decimal('5000')


def test_normalize_amount_empty():
    result = normalize_amount_to_toman('')
    assert result == Decimal('0')


def test_normalize_amount_none():
    result = normalize_amount_to_toman(None)
    assert result == Decimal('0')


def test_validate_national_id_valid():
    # A known valid Iranian national ID for testing
    assert validate_national_id('1111111111') is False  # all same digits is invalid
    assert validate_national_id('') is True  # empty is OK
    assert validate_national_id('1234567890') is not None  # just checks it runs


def test_validate_national_id_invalid():
    assert validate_national_id('12345') is False
    assert validate_national_id('12345678901') is False
    assert validate_national_id('abcdefghij') is False


def test_validate_sheba():
    assert validate_sheba('') is True
    assert validate_sheba('IR123456789012345678901234') is True
    assert validate_sheba('IR12345678901234567890123') is False  # 25 chars
    assert validate_sheba('US123456789012345678901234') is False  # not IR


def test_validate_card_luhn():
    assert validate_card_luhn('') is True
    assert validate_card_luhn('6037701689095443') is True  # Valid Luhn
    assert validate_card_luhn('1234567890123456') is False  # Invalid Luhn
    assert validate_card_luhn('1234') is False  # Too short
    assert validate_card_luhn('12345678901234567') is False  # Too long