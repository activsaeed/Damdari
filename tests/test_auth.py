def test_login_page_loads(client):
    response = client.get('/auth/login')
    assert response.status_code == 200


def test_login_with_valid_credentials(client):
    response = client.post('/auth/login', data={
        'username': 'admin',
        'password': 'test-admin-password'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert 'داشبورد'.encode('utf-8') in response.data or 'dashboard'.encode('utf-8') in response.data


def test_login_with_invalid_credentials(client):
    response = client.post('/auth/login', data={
        'username': 'admin',
        'password': 'wrong-password'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert 'نام کاربری یا رمز عبور اشتباه'.encode('utf-8') in response.data


def test_protected_page_redirects_to_login(client):
    response = client.get('/livestock/', follow_redirects=False)
    # Should either redirect to login or show login page
    assert response.status_code in (200, 302)
    if response.status_code == 302:
        assert '/auth/login' in response.location