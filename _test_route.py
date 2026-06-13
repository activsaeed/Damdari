import sys, os
sys.path.insert(0, r'C:\Users\saeed 2025-10-20\Desktop\Dam2')

from app import create_app
app = create_app()

with app.test_request_context('/livestock/breeding?year=1404&month=1'):
    from flask_login import login_user
    from app.models import User
    user = User.query.filter_by(role='admin').first()
    if user:
        login_user(user)
        print(f"Logged in as {user.username}")
        from flask import url_for
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
            resp = c.get('/livestock/breeding?year=1404&month=1')
            print(f"Status: {resp.status_code}")
            print(f"Response length: {len(resp.data) if resp.data else 0}")
            if resp.status_code != 200:
                print(f"Response: {resp.data[:500]}")
            else:
                print("SUCCESS - 200 OK")
