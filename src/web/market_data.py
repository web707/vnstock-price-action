"""Strict web data boundary. Never silently change source or timeframe."""
import re
import numpy as np
import pandas as pd
from fastapi import HTTPException
from src.data_quality import assess

TIMEZONE = 'Asia/Ho_Chi_Minh'
INTERVALS = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '60m': 60, '1h': 60, '1d': None}
COLUMNS = ['OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'VOLUME']


def fail(code, message, status=422):
    raise HTTPException(status_code=status, detail={'code': code, 'message': message})


def validate_request(symbol, timeframe, source):
    sym = symbol.strip().upper()
    if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^-]{0,19}', sym):
        fail('INVALID_SYMBOL', 'Mã chứng khoán không hợp lệ.')
    if timeframe not in INTERVALS or source not in ('api', 'db'):
        fail('INVALID_REQUEST', 'Khung nến hoặc nguồn dữ liệu không được hỗ trợ.')
    if source == 'db' and timeframe != '1d':
        fail('TIMEFRAME_SOURCE_MISMATCH', 'Database hiện chỉ lưu nến ngày; intraday phải dùng API.')
    return sym


def validate_frame(frame, timeframe):
    if frame is None or frame.empty:
        fail('NO_DATA', 'Không có dữ liệu cho yêu cầu này.', 404)
    df = frame.copy()
    if not {'TRADE_DATE', *COLUMNS}.issubset(df.columns):
        fail('INVALID_SCHEMA', 'Thiếu timestamp hoặc cột OHLCV.', 502)
    try:
        times = pd.to_datetime(df['TRADE_DATE'], errors='raise')
        if times.dt.tz is None:
            times = times.dt.tz_localize(TIMEZONE)
        else:
            times = times.dt.tz_convert(TIMEZONE)
        df['TRADE_DATE'] = times
        df[COLUMNS] = df[COLUMNS].apply(pd.to_numeric, errors='raise')
    except (ValueError, TypeError, AttributeError):
        fail('INVALID_DATA', 'Timestamp hoặc OHLCV không hợp lệ.', 502)
    if times.isna().any() or times.duplicated().any():
        fail('INVALID_TIMESTAMP', 'Timestamp thiếu hoặc trùng lặp.', 502)
    if not np.isfinite(df[COLUMNS].to_numpy(dtype=float)).all():
        fail('INVALID_OHLCV', 'OHLCV chứa NaN hoặc infinity.', 502)
    o, h, l, c, v = (df[col] for col in COLUMNS)
    if ((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0) | (v < 0) |
        (v % 1 != 0) | (h < df[['OPEN_PRICE','LOW_PRICE','CLOSE_PRICE']].max(axis=1)) |
        (l > df[['OPEN_PRICE','HIGH_PRICE','CLOSE_PRICE']].min(axis=1))).any():
        fail('INVALID_OHLCV', 'Giá/khối lượng hoặc quan hệ OHLC không hợp lệ.', 502)
    df = df.sort_values('TRADE_DATE').reset_index(drop=True)
    times = df['TRADE_DATE']
    if (times > pd.Timestamp.now(tz=TIMEZONE)).any():
        fail('FUTURE_TIMESTAMP', 'Dữ liệu chứa timestamp trong tương lai.', 502)
    step = INTERVALS[timeframe]
    if step is None:
        if times.dt.date.duplicated().any():
            fail('TIMEFRAME_MISMATCH', 'Nến ngày chứa nhiều bản ghi trong cùng ngày.', 502)
    else:
        deltas = times.diff().dt.total_seconds().div(60).dropna()
        # Require evidence of the requested cadence; allow session gaps/missing bars.
        if deltas.empty or not np.isclose(deltas, step).any() or (deltas < step).any():
            fail('TIMEFRAME_MISMATCH', f'Không xác minh được nến {timeframe} từ timestamp.', 502)
    return df


def exclude_forming_daily_bar(frame, timeframe, now=None):
    """Do not allow an unfinished daily candle into chart-derived signals."""
    if timeframe != '1d' or frame is None or frame.empty:
        return frame, 0
    local_now = now if now is not None else pd.Timestamp.now(tz=TIMEZONE)
    local_now = pd.Timestamp(local_now)
    if local_now.tzinfo is None:
        local_now = local_now.tz_localize(TIMEZONE)
    else:
        local_now = local_now.tz_convert(TIMEZONE)
    dates = pd.to_datetime(frame['TRADE_DATE'], errors='coerce')
    if dates.dt.tz is None:
        dates = dates.dt.tz_localize(TIMEZONE)
    else:
        dates = dates.dt.tz_convert(TIMEZONE)
    safe = dates.dt.date < local_now.date()
    return frame.loc[safe].copy(), int((~safe).sum())


def load_market_data(symbol, timeframe, source, get_repo, client_factory):
    sym = validate_request(symbol, timeframe, source)
    fetched_at = pd.Timestamp.now(tz='UTC').isoformat()
    if source == 'api':
        period = '7d' if timeframe == '1m' else ('max' if timeframe == '1d' else '60d')
        try:
            raw, err = client_factory(request_delay=0.1).fetch_intraday(sym, interval=timeframe, period=period)
        except Exception:
            fail('SOURCE_UNAVAILABLE', 'Không lấy được dữ liệu API. Không dùng dữ liệu thay thế.', 502)
        if err or raw is None or raw.empty:
            fail('SOURCE_UNAVAILABLE', 'API không trả dữ liệu hợp lệ. Không dùng dữ liệu thay thế.', 502)
        frame = raw.reset_index()
        date_col = next((c for c in ('Datetime', 'Date') if c in frame.columns), frame.columns[0])
        frame = frame.rename(columns={date_col: 'TRADE_DATE', 'Open': 'OPEN_PRICE', 'High': 'HIGH_PRICE',
                                     'Low': 'LOW_PRICE', 'Close': 'CLOSE_PRICE', 'Volume': 'VOLUME'})
    else:
        try:
            frame = get_repo().query_historical_prices(sym)
        except Exception:
            fail('SOURCE_UNAVAILABLE', 'Không đọc được database.', 503)
    # Refuse to feed today's in-progress daily candle into signals from any source.
    frame, excluded_forming = exclude_forming_daily_bar(frame, timeframe)
    if frame is None or frame.empty:
        fail('NO_CLOSED_DATA', 'Chưa có nến ngày đã đóng để phân tích.', 404)
    df = validate_frame(frame, timeframe)
    # A stored candle is not proof of up-to-date data. Count weekdays strictly
    # AFTER its session date and BEFORE today; holidays may reduce the count.
    local_now = pd.Timestamp.now(tz=TIMEZONE)
    latest_date = df['TRADE_DATE'].iloc[-1].date()
    elapsed_weekdays = int(np.busday_count(
        (latest_date + pd.Timedelta(days=1)).isoformat(),
        local_now.date().isoformat()
    )) if latest_date < local_now.date() else 0
    stale = timeframe == '1d' and elapsed_weekdays >= 2
    warnings = ['Cơ sở điều chỉnh giá chưa được xác minh; không coi nhãn VALID là chứng nhận giá đúng.', 'Nến ngày hiện tại được loại khỏi dữ liệu phân tích.' if timeframe == '1d' else 'Chưa xác minh trạng thái đóng của nến cuối.',
                'Timestamp không có timezone được hiểu là giờ Việt Nam.']
    if excluded_forming:
        warnings.insert(0, f'Đã loại {excluded_forming} nến ngày chưa đóng khỏi phân tích.')
    if stale:
        warnings.insert(0, f'Dữ liệu có thể đã cũ: ít nhất {elapsed_weekdays} ngày thường kể từ phiên cuối (chưa trừ ngày nghỉ lễ). Hãy đồng bộ và kiểm tra lại.')
    return df, {
        'symbol': sym, 'timeframe': timeframe, 'source': source,
        'provider': 'Yahoo Finance' if source == 'api' else 'database',
        'timezone': TIMEZONE, 'fetched_at': fetched_at,
        'data_as_of': df['TRADE_DATE'].iloc[-1].isoformat(),
        'freshness': 'potentially_stale' if stale else 'unverified',
        'weekdays_since_last_bar': elapsed_weekdays,
        'price_basis': 'unknown',
        'quality': assess(df, local_now.date().isoformat()),
        'realtime_verified': False,
        'last_bar_closed': True if timeframe == '1d' else None,
        'warnings': warnings,
    }
