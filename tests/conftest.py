import pytest
from fastapi.testclient import TestClient
from src.web.app import app
from src.web.auth import database
@pytest.fixture
def signed_client(tmp_path,monkeypatch):
    monkeypatch.setenv('QTA_AUTH_DB',str(tmp_path/'auth.db'))
    c=TestClient(app);d={'username':'tester','password':'test-password-123'}
    assert c.post('/api/auth/register',json=d).status_code==201
    with database() as db: db.execute("UPDATE users SET role='admin'")
    assert c.post('/api/auth/login',json=d).status_code==200
    c.headers['X-CSRF-Token']=c.get('/api/auth/me').json()['csrf']
    return c
