"""Local account store; opaque server-side sessions, no shared default credentials."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from src.config import settings

router = APIRouter()
COOKIE = 'qta_session'
TTL = 8 * 3600

@contextmanager
def database():
    path = Path(os.getenv('QTA_AUTH_DB', str(settings.state_dir / 'qta_accounts.db')))
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', display_name TEXT NOT NULL,
          default_symbol TEXT NOT NULL DEFAULT 'HPG');
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, reset REAL NOT NULL);
        ''')
        yield db

def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + key

def verify(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)

DUMMY = password_hash('dummy-password-not-a-login')

class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=10, max_length=128)

class Preferences(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)
    default_symbol: str = Field(pattern=r'^[A-Z0-9]{1,10}$')

class RoleUpdate(BaseModel):
    role: Literal['user', 'admin']

def username(value):
    value = value.strip().lower()
    if not re.fullmatch(r'[a-z0-9_.-]{3,32}', value):
        raise HTTPException(422, 'Tên đăng nhập: 3–32 ký tự a-z, 0-9, _, dấu chấm hoặc gạch ngang.')
    return value

def throttle(request, name):
    # Persist limits across processes/restarts; never trust client-supplied X-Forwarded-For.
    now = time.time()
    ip = request.client.host if request.client else 'unknown'
    keys = [(digest('ip:'+ip), 40), (digest('account:'+name), 10)]
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM attempts WHERE reset <= ?', (now,))
        for key, limit in keys:
            row = db.execute('SELECT count FROM attempts WHERE key=?', (key,)).fetchone()
            if row and row['count'] >= limit:
                raise HTTPException(429, 'Quá nhiều lần thử. Vui lòng thử lại sau 15 phút.')
        for key, _ in keys:
            db.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key,now+900))

def session_user(request):
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        return None
    with database() as db:
        row = db.execute('''SELECT u.id,u.username,u.role,u.display_name,u.default_symbol,s.csrf
          FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?''',
          (digest(token),time.time())).fetchone()
    return dict(row) if row else None

async def guard(request, call_next):
    path = request.url.path
    public = path in ('/login','/api/auth/login','/api/auth/register')
    user = session_user(request)
    request.state.user = user
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        expected = os.getenv('QTA_PUBLIC_ORIGIN', str(request.base_url).rstrip('/'))
        if origin and origin.rstrip('/') != expected.rstrip('/'):
            return JSONResponse({'detail':'Origin không hợp lệ.'}, status_code=403)
        if path.startswith('/api/'):
            if not request.headers.get('content-type','').startswith('application/json'):
                return JSONResponse({'detail':'Yêu cầu JSON.'},status_code=415)
            if not public and user and not hmac.compare_digest(request.headers.get('x-csrf-token',''), user['csrf']):
                return JSONResponse({'detail':'CSRF token không hợp lệ.'},status_code=403)
    if not public and user is None:
        if path == '/':
            return RedirectResponse('/login',status_code=303)
        return JSONResponse({'detail':'Vui lòng đăng nhập.'},status_code=401)
    if user and (path.startswith('/api/admin/') or path == '/api/fetch') and user['role'] != 'admin':
        return JSONResponse({'detail':'Chỉ quản trị viên được phép thao tác.'},status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response

@router.post('/api/auth/register',status_code=201)
def register(data: Credentials, request: Request):
    name = username(data.username)
    throttle(request,name)
    hashed = password_hash(data.password)
    try:
        with database() as db:
            db.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(name,hashed,name))
    except sqlite3.IntegrityError:
        raise HTTPException(409,'Tên đăng nhập đã được sử dụng.')
    return {'message':'Đã tạo tài khoản. Vui lòng đăng nhập.'}

@router.post('/api/auth/login')
def login(data: Credentials, request: Request, response: Response):
    name = username(data.username)
    throttle(request,name)
    with database() as db:
        user = db.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
    if not verify(data.password,user['password'] if user else DUMMY) or not user:
        raise HTTPException(401,'Tên đăng nhập hoặc mật khẩu không đúng.')
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with database() as db:
        db.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),))
        old = request.cookies.get(COOKIE)
        if old: db.execute('DELETE FROM sessions WHERE token=?',(digest(old),))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(token),user['id'],csrf,time.time()+TTL))
    response.set_cookie(COOKIE,token,max_age=TTL,httponly=True,samesite='strict',
                        secure=os.getenv('QTA_COOKIE_SECURE','0') == '1',path='/')
    return {'message':'Đăng nhập thành công.'}

@router.get('/api/auth/me')
def me(request: Request):
    return request.state.user

@router.post('/api/auth/logout')
def logout(request: Request,response: Response):
    with database() as db:
        db.execute('DELETE FROM sessions WHERE token=?',(digest(request.cookies.get(COOKIE,'')),))
    response.delete_cookie(COOKIE,path='/')
    return {'message':'Đã đăng xuất.'}

@router.put('/api/account/preferences')
def preferences(data: Preferences,request: Request):
    with database() as db:
        db.execute('UPDATE users SET display_name=?,default_symbol=? WHERE id=?',
                   (data.display_name.strip(),data.default_symbol,request.state.user['id']))
    return data.model_dump()

@router.get('/api/admin/users')
def users():
    with database() as db:
        return [dict(r) for r in db.execute('SELECT id,username,role,display_name FROM users ORDER BY id')]

@router.put('/api/admin/users/{user_id}/role')
def role(user_id: int,data: RoleUpdate,request: Request):
    if user_id == request.state.user['id']:
        raise HTTPException(400,'Không tự đổi quyền của chính mình.')
    with database() as db:
        result=db.execute('UPDATE users SET role=? WHERE id=?',(data.role,user_id))
        if result.rowcount == 0: raise HTTPException(404,'Không tìm thấy tài khoản.')
        db.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
    return {'message':'Đã cập nhật quyền và thu hồi phiên đăng nhập của tài khoản.'}

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Cấp quyền admin cho tài khoản đã đăng ký, chỉ chạy tại máy chủ.')
    parser.add_argument('--promote',required=True)
    args=parser.parse_args()
    with database() as db:
        r=db.execute("UPDATE users SET role='admin' WHERE username=?",(username(args.promote),))
        if r.rowcount != 1: raise SystemExit('Không tìm thấy tài khoản. Hãy đăng ký trước.')
    print('Đã cấp quyền admin. Đăng nhập lại để dùng giao diện quản trị.')
