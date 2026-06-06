# Dam2 - سامانه مدیریت دامداری

یک پروژه Flask برای مدیریت دام، مالی، انبار، منابع انسانی و گزارش‌دهی.

## پیش‌نیازها

- Python 3.11 یا بالاتر
- بسته‌های مورد نیاز در `requirements.txt`

## نصب

از پوشه پروژه:

```powershell
python -m pip install -r requirements.txt
```

## اجرا

### روش ساده (بدون فعال کردن محیط مجازی)

اگر قصد داری از همان Python که در CMD نصب شده استفاده کنی، کافی است:

```powershell
cd C:\Users\saeed 2025-10-20\Desktop\Dam2
python run.py
```

### روش پیشنهادی (محیط مجازی)

```powershell
cd C:\Users\saeed 2025-10-20\Desktop\Dam2
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python run.py
```

## پیکربندی

یک فایل `.env` ایجاد کن یا از `.env.example` کپی بگیر:

```powershell
copy .env.example .env
```

سپس مقادیر زیر را در `.env` تنظیم کن:

- `SECRET_KEY`
- `DATABASE_URI`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `ADMIN_NAME`

## نکات

- اگر `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID` را تنظیم نکنی، سرویس بکاپ تلگرام غیرفعال می‌ماند.
- برای اجرای پروژه لازم نیست حتماً از محیط مجازی استفاده کنی، ولی در صورت استفاده، وابستگی‌ها ایزوله‌تر می‌مانند.

## رفع خطاهای رایج

- `ModuleNotFoundError: No module named 'dotenv'`
  - برای CMD: `python -m pip install python-dotenv`

- اگر بسته‌ای نصب نشده باشد:
  - `python -m pip install -r requirements.txt`
"# Damdari" 
