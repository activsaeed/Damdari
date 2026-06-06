import os

base_dir = r"C:\Users\saeed 2025-10-20\Desktop\Dam2"

folders = [
    "app",
    "app/blueprints",
    "app/static",
    "app/static/css",
    "app/static/js",
    "app/static/img",
    "app/templates",
    "app/templates/dashboard",
    "app/templates/livestock",
    "app/templates/finance",
    "app/templates/hr",
    "uploads"
]

files = [
    ("run.py", ""),
    ("requirements.txt", "flask\nflask-sqlalchemy\nflask-migrate\n"),
    ("app/__init__.py", ""),
    ("app/models.py", ""),
    ("app/blueprints/__init__.py", ""),
    ("app/blueprints/dashboard.py", ""),
    ("app/blueprints/livestock.py", ""),
    ("app/static/css/style.css", ""),
    ("app/static/js/main.js", ""),
    ("app/templates/base.html", ""),
    ("app/templates/dashboard/index.html", "")
]

# ساخت پوشه‌ها
for folder in folders:
    os.makedirs(os.path.join(base_dir, folder), exist_ok=True)

# ساخت فایل‌ها
for file_name, content in files:
    file_path = os.path.join(base_dir, file_name)
    if not os.path.exists(file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

print("✅ ساختار پوشه ها و فایل های اولیه با موفقیت در پوشه Dam2 ساخته شد!")