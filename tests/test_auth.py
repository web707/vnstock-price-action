import time
import pytest
from fastapi.testclient import TestClient
from src.web.app import app
from src.web.auth import database, COOKIE
@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('QTA_AUTH_DB',str(tmp_path/'accounts.db'))
    monkeypatch.delenv('QTA_COOKIE_SECURE',raising=False)
    return TestClient(app)
def signup(c,name='alice'):
    d={'username':name,'password':'correct-password-123'}
    assert c.post('/api/auth/register',json=d).status_code==201
    r=c.post('/api/auth/login',json=d);assert r.status_code==200
    c.headers['X-CSRF-Token']=c.get('/api/auth/me').json()['csrf']
    return r
@pytest.mark.parametrize('path',['/api/summary','/api/signals/HPG','/api/history/HPG','/api/swings/HPG','/api/layer2/structure/HPG','/api/auth/me','/api/admin/users','/docs','/openapi.json'])
def test_private_routes(client,path): assert client.get(path).status_code==401
def test_home_and_login(client):
    assert client.get('/',follow_redirects=False).status_code==303
    assert 'Đăng nhập' in client.get('/login').text
def test_logout_revokes_cookie(client):
    r=signup(client);assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
    token=client.cookies.get(COOKIE)
    assert client.post('/api/auth/logout',json={}).status_code==200
    client.cookies.set(COOKIE,token)
    assert client.get('/api/auth/me').status_code==401
def test_hash_storage(client):
    signup(client)
    with database() as db:
        assert 'correct-password' not in db.execute('SELECT password FROM users').fetchone()[0]
        assert client.cookies.get(COOKIE)!=db.execute('SELECT token FROM sessions').fetchone()[0]
def test_generic_error(client):
    signup(client)
    for name in ['alice','unknown']:
        r=client.post('/api/auth/login',json={'username':name,'password':'wrong-password-123'})
        assert r.status_code==401
        assert r.json()['detail']=='Tên đăng nhập hoặc mật khẩu không đúng.'
def test_permissions(client):
    signup(client)
    assert client.get('/api/admin/users').status_code==403
    assert client.post('/api/fetch',json={'symbols':'HPG'}).status_code==403
    assert client.put('/api/admin/users/1/role',json={'role':'admin'}).status_code==403
def test_csrf_origin_content_type(client):
    signup(client);client.headers.pop('X-CSRF-Token')
    assert client.post('/api/auth/logout',json={}).status_code==403
    client.headers['X-CSRF-Token']=client.get('/api/auth/me').json()['csrf']
    assert client.post('/api/auth/logout',json={},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/auth/login',data={'username':'alice','password':'correct-password-123'}).status_code==415
def test_expiry(client):
    signup(client)
    with database() as db: db.execute('UPDATE sessions SET expires=?',(time.time()-1,))
    assert client.get('/api/auth/me').status_code==401
def test_preferences_isolated_persistent(client):
    signup(client);other=TestClient(app);signup(other,'bob')
    assert client.put('/api/account/preferences',json={'display_name':'Alice A','default_symbol':'FPT'}).status_code==200
    assert other.get('/api/auth/me').json()['display_name']=='bob'
    new=TestClient(app);new.post('/api/auth/login',json={'username':'alice','password':'correct-password-123'})
    assert new.get('/api/auth/me').json()['default_symbol']=='FPT'
def test_admin_and_revoke(client):
    signup(client);other=TestClient(app);signup(other,'bob')
    with database() as db: db.execute("UPDATE users SET role='admin' WHERE username='alice'")
    assert client.get('/api/admin/users').status_code==200
    assert client.put('/api/admin/users/2/role',json={'role':'admin'}).status_code==200
    assert other.get('/api/auth/me').status_code==401
    assert client.put('/api/admin/users/1/role',json={'role':'user'}).status_code==400
def test_throttle(client):
    for _ in range(10): assert client.post('/api/auth/login',json={'username':'unknown','password':'wrong-password-123'}).status_code==401
    assert client.post('/api/auth/login',json={'username':'unknown','password':'wrong-password-123'}).status_code==429
def test_duplicate_and_no_registration_admin(client):
    signup(client)
    assert client.get('/api/auth/me').json()['role']=='user'
    assert client.post('/api/auth/register',json={'username':'ALICE','password':'correct-password-123'}).status_code==409
def test_secure_cookie(client,monkeypatch):
    monkeypatch.setenv('QTA_COOKIE_SECURE','1')
    d={'username':'alice','password':'correct-password-123'}
    client.post('/api/auth/register',json=d)
    assert 'Secure' in client.post('/api/auth/login',json=d).headers['set-cookie']
def test_login_rotation_invalidates_old_session(client):
    signup(client)
    old=client.cookies.get(COOKIE)
    assert client.post('/api/auth/login',json={'username':'alice','password':'correct-password-123'}).status_code==200
    assert client.cookies.get(COOKIE)!=old
    replay=TestClient(app);replay.cookies.set(COOKIE,old)
    assert replay.get('/api/auth/me').status_code==401

def test_register_ignores_role_injection(client):
    d={'username':'mallory','password':'correct-password-123','role':'admin'}
    assert client.post('/api/auth/register',json=d).status_code==201
    assert client.post('/api/auth/login',json=d).status_code==200
    assert client.get('/api/auth/me').json()['role']=='user'

def test_forged_cookie_rejected(client):
    client.cookies.set(COOKIE,'forged-token')
    assert client.get('/api/auth/me').status_code==401
