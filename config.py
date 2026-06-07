import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', '9b7f8e2d3c4b5a6f7e8d9c0b1a2f3e4d') # کلید ثابت و قوی
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URI', 'sqlite:///' + str(BASE_DIR / 'app' / 'damdari.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
    BACKUP_HOUR = int(os.getenv('BACKUP_HOUR', '0'))
    BACKUP_MINUTE = int(os.getenv('BACKUP_MINUTE', '0'))

    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '123456')
    ADMIN_NAME = os.getenv('ADMIN_NAME', 'مدیر سیستم')

    # تنظیمات سیستمی
    VAT_RATE = float(os.getenv('VAT_RATE', '10'))
    CURRENCY_UNIT = os.getenv('CURRENCY_UNIT', 'تومان')
