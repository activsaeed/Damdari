from app import create_app

app = create_app()

if __name__ == '__main__':
    # با اضافه کردن use_reloader=False، مشکل قطع شدن سایت هنگام آپلود عکس برای همیشه حل می‌شود!
    app.run(debug=True, use_reloader=False, port=5000)