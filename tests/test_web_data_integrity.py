"""API regressions: deterministic fixtures, no Yahoo/Oracle access."""
import importlib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

web = importlib.import_module('src.web.app')


def frame(freq='15min', periods=40):
    idx = pd.date_range('2025-01-02 09:00', periods=periods, freq=freq, tz='Asia/Ho_Chi_Minh', name='Datetime')
    return pd.DataFrame({'Open': 100., 'High': 102., 'Low': 99., 'Close': 101., 'Volume': 1000}, index=idx)


def db_frame():
    return frame('1D').reset_index().rename(columns={'Datetime':'TRADE_DATE','Open':'OPEN_PRICE',
        'High':'HIGH_PRICE','Low':'LOW_PRICE','Close':'CLOSE_PRICE','Volume':'VOLUME'})


@pytest.fixture
def client(monkeypatch, signed_client):
    class API:
        def __init__(self, **kwargs): pass
        def fetch_intraday(self, *args, **kwargs): return frame(), None
    monkeypatch.setattr(web, 'YFinanceClient', API)
    class Repo:
        def query_historical_prices(self, *args): return db_frame()
    monkeypatch.setattr(web, 'get_repo', lambda: Repo())
    return signed_client


PATHS = ['/api/history/HPG', '/api/swings/HPG', '/api/layer2/structure/HPG']


@pytest.mark.parametrize('path', PATHS)
def test_api_failure_never_falls_back(client, monkeypatch, path):
    monkeypatch.setattr(web.YFinanceClient, 'fetch_intraday', lambda *a, **kw: (None, 'NO_DATA'))
    monkeypatch.setattr(web, 'get_repo', lambda: pytest.fail('DB fallback forbidden'))
    r = client.get(path)
    assert r.status_code == 502
    assert r.json()['detail']['code'] == 'SOURCE_UNAVAILABLE'


@pytest.mark.parametrize('path', PATHS)
def test_daily_api_cannot_masquerade_as_15m(client, monkeypatch, path):
    monkeypatch.setattr(web.YFinanceClient, 'fetch_intraday', lambda *a, **kw: (frame('1D'), None))
    r = client.get(path)
    assert r.status_code == 502
    assert r.json()['detail']['code'] == 'TIMEFRAME_MISMATCH'


@pytest.mark.parametrize('path', PATHS)
def test_explicit_intraday_db_rejected(client, path):
    assert client.get(path+'?source=db&timeframe=15m').status_code == 422


@pytest.mark.parametrize('query', ['timeframe=oops','source=oops','limit=0','limit=-2','limit=10001'])
def test_invalid_requests(client, query):
    assert client.get('/api/history/HPG?'+query).status_code == 422


def test_correct_source_timezone_order_and_limit(client, monkeypatch):
    raw = frame().iloc[::-1].copy()
    raw.index = raw.index.tz_convert('UTC')
    monkeypatch.setattr(web.YFinanceClient, 'fetch_intraday', lambda *a, **kw: (raw, None))
    r = client.get('/api/history/HPG?limit=2')
    assert r.status_code == 200
    d = r.json()
    assert d['count'] == 2 and d['bars'][0]['time'] < d['bars'][1]['time']
    assert d['bars'][-1]['time'] == '2025-01-02 18:45'
    assert d['metadata']['source'] == 'api'
    assert d['metadata']['data_as_of'].endswith('+07:00')
    assert d['metadata']['realtime_verified'] is False


@pytest.mark.parametrize('kind', ['nan','inf','negative_volume','bad_high','duplicate','missing','one_bar','future'])
def test_bad_data_rejected(client, monkeypatch, kind):
    raw = frame()
    if kind == 'nan': raw.iloc[0,0] = np.nan
    if kind == 'inf': raw.iloc[0,0] = np.inf
    if kind == 'negative_volume': raw.iloc[0,4] = -1
    if kind == 'bad_high': raw.iloc[0,1] = 90
    if kind == 'duplicate': raw = pd.concat([raw, raw.iloc[:1]])
    if kind == 'missing': raw = raw.drop(columns='Volume')
    if kind == 'one_bar': raw = raw.iloc[:1]
    if kind == 'future': raw.index = raw.index + pd.DateOffset(years=100)
    monkeypatch.setattr(web.YFinanceClient, 'fetch_intraday', lambda *a, **kw: (raw, None))
    assert client.get('/api/history/HPG').status_code == 502


def test_daily_db_and_signals_metadata(client):
    history = client.get('/api/history/HPG?source=db&timeframe=1d')
    signals = client.get('/api/signals/HPG')
    assert history.status_code == signals.status_code == 200
    for r in (history, signals):
        assert r.json()['metadata']['timeframe'] == '1d'
        assert r.json()['metadata']['source'] == 'db'


@pytest.mark.parametrize('path', PATHS)
def test_valid_intraday_routes(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    assert r.json()['metadata']['timeframe'] == '15m'


def test_session_gap_allowed(client, monkeypatch):
    raw = frame(periods=4)
    later = raw.copy()
    later.index += pd.Timedelta(days=3)
    monkeypatch.setattr(web.YFinanceClient, 'fetch_intraday', lambda *a, **kw: (pd.concat([raw,later]), None))
    assert client.get('/api/history/HPG').status_code == 200


def test_empty_db_is_not_success(client, monkeypatch):
    class Repo:
        def query_historical_prices(self, *args): return pd.DataFrame()
    monkeypatch.setattr(web, 'get_repo', lambda: Repo())
    assert client.get('/api/history/HPG?source=db&timeframe=1d').status_code == 404
    assert client.get('/api/signals/HPG').status_code == 404


def test_db_error_is_structured(client, monkeypatch):
    def unavailable(): raise RuntimeError('private credentials must not be exposed')
    monkeypatch.setattr(web, 'get_repo', unavailable)
    r = client.get('/api/history/HPG?source=db&timeframe=1d')
    assert r.status_code == 503
    assert 'private credentials' not in r.text


def test_fetch_reports_failures_honestly(client, monkeypatch):
    from src.data_reporter import DataReporter
    reporter = DataReporter('test-batch')
    reporter.record_symbol_result('HPG', 'HPG.VN', 'HOSE', 'FAILED', 0, 0, 0)
    class Repo:
        def get_symbols_summary(self): return []
    monkeypatch.setattr(web, 'get_repo', lambda: Repo())
    monkeypatch.setattr(web.HistoricalImporter, 'import_symbols', lambda *a, **kw: reporter)
    r = client.post('/api/fetch', json={'symbols': 'HPG'})
    assert r.status_code == 200, r.text
    assert r.json()['fetched_count'] == 0
    assert r.json()['status'] == 'incomplete'
    assert r.json()['summary']['failed_symbols'] == 1


def test_daily_layer2_cutoff_with_timezone(client):
    r = client.get('/api/layer2/structure/HPG?source=db&timeframe=1d&date=2025-01-10')
    assert r.status_code == 200, r.text
    assert r.json()['metadata']['requested_cutoff'] == '2025-01-10'
