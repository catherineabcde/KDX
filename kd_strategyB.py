
# file: kd_strategyB.py
"""
Strategy B (MultiIndex-safe):
- Fixes yfinance MultiIndex where level-0 is OHLC and level-last is ticker (e.g., ('Close','2330.TW')).
- Strips trailing ticker suffixes like "Close 2330.Tw" to standard "Close".
- Falls back to Adj Close when Close missing.
- Daily K/D cross with weekly filter (K>D, K>=50, weekly Close>weekly MA).
"""

import os, json, math, re
from datetime import datetime, timezone
from typing import Dict, Set, Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ---- Optional integrations ----
try:
    from line_push import push_text
except Exception:
    def push_text(to_id: str, text: str):
        print(f"[WARN] line_push not available; would push to {to_id}:\n{text}")

try:
    from subscriptions import all_symbols_to_subscribers
except Exception:
    def all_symbols_to_subscribers() -> Dict[str, Set[str]]:
        return {}

try:
    from config_loader import load_config
except Exception:
    def load_config() -> dict:
        return {}

try:
    from institutions import get_institutions, fmt_line
except Exception:
    def get_institutions(sym: str, day: datetime):
        return None
    def fmt_line(row) -> str:
        return ""

# ---- Tunables ----
K_PERIOD = int(os.getenv("K_PERIOD", "9"))
ALPHA = float(os.getenv("ALPHA", "0.3333333333"))
DAILY_MA = int(os.getenv("DAILY_MA", "20"))
WEEKLY_MA = int(os.getenv("WEEKLY_MA", "20"))
STATE_FILE = os.getenv("STATE_FILE", "kd_b_state.json")
TZ_NAME = os.getenv("TZ", "Asia/Taipei")
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
DEBUG = os.getenv("DEBUG", "0") == "1"


def tz_now(tz_name: str = TZ_NAME):
    return datetime.now(tz=timezone.utc).astimezone(pd.Timestamp.now(tz=tz_name).tz)


def to_tz(ts, tz_name: str = TZ_NAME) -> str:
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(tz_name).strftime("%Y-%m-%d %H:%M")
    return str(ts)


# ---- State ----
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# ---- Column normalization ----
def _clean_name(x) -> str:
    s = str(x)
    s = s.replace('*', '').replace('#','').strip()
    s = re.sub(r'\s+', ' ', s)
    return s

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer level-0 if it contains OHLC; otherwise try last level; else flatten join."""
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = [_clean_name(c) for c in df.columns.get_level_values(0)]
        lvlL = [_clean_name(c) for c in df.columns.get_level_values(-1)]
        lvl0_title = [c.title() for c in lvl0]
        lvlL_title = [c.title() for c in lvlL]
        if {'Open','High','Low','Close'}.issubset(set(lvl0_title)):
            df = df.copy(); df.columns = lvl0_title; return df
        if {'Open','High','Low','Close'}.issubset(set(lvlL_title)):
            df = df.copy(); df.columns = lvlL_title; return df
        flat = [' '.join(_clean_name(p) for p in tup if str(p) != '') for tup in df.columns.to_flat_index()]
        df = df.copy(); df.columns = flat
    return df

def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    df = _flatten_columns(df)
    # First pass: trim + title case
    df = df.rename(columns=lambda s: _clean_name(s).title())

    # Second pass: strip trailing ticker suffixes like "Close 2330.Tw"
    new_cols = []
    for c in df.columns:
        cc = _clean_name(c)
        m = re.match(r'(?i)^(open|high|low|adj close|close)\b', cc)
        if m:
            new_cols.append(m.group(1).title())
        else:
            new_cols.append(cc.title())
    df = df.copy()
    df.columns = new_cols

    # If Close missing but Adj Close present -> use Adj Close as Close
    if 'Close' not in df.columns and 'Adj Close' in df.columns:
        df = df.rename(columns={'Adj Close': 'Close'})

    if DEBUG:
        print(f"[DEBUG] normalized columns => {list(df.columns)}")
    return df


# ---- Fetch ----
def fetch_ohlc(symbol: str, interval: str) -> pd.DataFrame:
    kw = dict(auto_adjust=False, progress=False, group_by='column')
    if interval == "1d":
        df = yf.download(symbol, period="2y", interval="1d", **kw)
    elif interval == "1wk":
        df = yf.download(symbol, period="10y", interval="1wk", **kw)
    else:
        raise ValueError("interval must be '1d' or '1wk'")
    if df is None or df.empty:
        raise RuntimeError(f"no data for {symbol} {interval}")
    df = df[~df.index.duplicated(keep="last")]
    df = _normalize_ohlc(df)
    if DEBUG:
        print(f"[DEBUG] {symbol} {interval} columns: {list(df.columns)}")

    return df


def last_completed_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    local_now = tz_now(TZ_NAME)
    last_idx = df.index[-1]
    try:
        last_date = (last_idx.tz_convert(TZ_NAME).date() if last_idx.tzinfo else last_idx.date())
    except Exception:
        last_date = pd.Timestamp(last_idx).date()
    if last_date == local_now.date() and (local_now.hour < 13 or (local_now.hour == 13 and local_now.minute < 35)):
        return df.iloc[:-1]
    return df


def weekly_completed_row(df_w: pd.DataFrame) -> Optional[pd.Series]:
    if len(df_w) < 2:
        return None
    return df_w.iloc[-2]


# ---- Indicators ----
def compute_kd_recursive(df: pd.DataFrame, n: int = K_PERIOD, alpha: float = ALPHA) -> pd.DataFrame:
    req = {"High", "Low", "Close"}
    if not req.issubset(df.columns):
        if DEBUG:
            print(f"[DEBUG] columns present: {list(df.columns)}")
        missing = req - set(df.columns)
        raise ValueError(f"missing OHLC columns: {missing}")
    high = df["High"]; low = df["Low"]; close = df["Close"]
    lowest_n = low.rolling(window=n, min_periods=n).min()
    highest_n = high.rolling(window=n, min_periods=n).max()
    denom = (highest_n - lowest_n).replace(0, np.nan)
    rsv = 100 * (close - lowest_n) / denom
    K = rsv.ewm(alpha=alpha, adjust=False).mean()
    D = K.ewm(alpha=alpha, adjust=False).mean()
    out = df.copy()
    out["K"] = K; out["D"] = D
    return out


def ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def crossed_up(k_prev, d_prev, k, d) -> bool:
    return k_prev <= d_prev and k > d


def crossed_down(k_prev, d_prev, k, d) -> bool:
    return k_prev >= d_prev and k < d


# ---- Push wrapper ----
def send_to(recipients: Set[str], text: str):
    if not recipients:
        return
    if DRY_RUN:
        print("[DRY_RUN] to", ",".join(sorted(recipients)), ":\n" + text)
        return
    for rid in recipients:
        try:
            push_text(rid, text)
        except Exception as e:
            print(f"[ERROR] push to {rid}: {e}")


# ---- Core per-symbol ----
def process_symbol(sym: str, recipients: Set[str], state: dict, cfg: dict):
    print(f"[INFO] Processing {sym} ...")
    df_d = last_completed_daily(fetch_ohlc(sym, "1d"))
    df_w = fetch_ohlc(sym, "1wk")

    need_d = max(DAILY_MA + 2, K_PERIOD + 2)
    need_w = max(WEEKLY_MA + 2, K_PERIOD + 2)
    if len(df_d) < need_d or len(df_w) < need_w:
        print(f"[SKIP] {sym}: not enough data (d={len(df_d)} need≥{need_d}, w={len(df_w)} need≥{need_w})")
        return

    d_kd = compute_kd_recursive(df_d).dropna(subset=["K","D"])
    if len(d_kd) < 2:
        print(f"[SKIP] {sym}: not enough daily KD values")
        return

    w_kd = compute_kd_recursive(df_w).dropna(subset=["K","D"])
    if len(w_kd) < 2:
        print(f"[SKIP] {sym}: not enough weekly KD values")
        return

    # Daily last two
    d_prev, d_last = d_kd.iloc[-2], d_kd.iloc[-1]
    k_prev, dprev_prev = float(d_prev["K"]), float(d_prev["D"])
    k_last, d_last_d = float(d_last["K"]), float(d_last["D"])
    d_close = float(d_last["Close"])
    d_ma20 = float(ma(d_kd["Close"], DAILY_MA).iloc[-1])
    d_ts = d_last.name

    # Weekly completed
    w_row = weekly_completed_row(w_kd)
    if w_row is None or math.isnan(w_row["K"]) or math.isnan(w_row["D"]):
        print(f"[SKIP] {sym}: weekly completed row NA")
        return
    w_idx = w_row.name
    w_k = float(w_row["K"]); w_d = float(w_row["D"]); w_close = float(w_row["Close"])
    w_ma20_series = ma(w_kd["Close"], WEEKLY_MA)
    w_ma20 = float(w_ma20_series.loc[w_idx]) if w_idx in w_ma20_series.index else float("nan")

    weekly_ok = (w_k > w_d) and (w_k >= 50.0) and (not math.isnan(w_ma20) and w_close > w_ma20)
    entry_cross = crossed_up(k_prev, dprev_prev, k_last, d_last_d)
    exit_cross = crossed_down(k_prev, dprev_prev, k_last, d_last_d)
    daily_trend_ok = d_close > d_ma20

    inst_line = ""
    if cfg.get("features", {}).get("institutions", {}).get("enabled", False):
        try:
            row = get_institutions(sym, day=pd.Timestamp(d_ts).to_pydatetime())
            if row and cfg["features"]["institutions"].get("include_in_push", True):
                inst_line = "\n" + fmt_line(row)
        except Exception as e:
            print(f"[WARN] institutions fetch failed for {sym}: {e}")

    sym_state = state.get(sym, {"position": "flat", "alerts": {}})
    alerts = sym_state.get("alerts", {})

    def alerted(key: str) -> bool:
        return alerts.get(key, False)

    def mark_alert(key: str):
        alerts[key] = True
        sym_state["alerts"] = alerts
        state[sym] = sym_state
        save_state(state)

    # Entry
    if sym_state.get("position") == "flat" and weekly_ok and entry_cross and daily_trend_ok:
        msg = (f"[B Entry] {sym}\n"
               f"日線黃金交叉 + MA{DAILY_MA} 之上，週濾網 OK\n"
               f"日收盤 {d_close:.2f}  K={k_last:.2f} D={d_last_d:.2f}\n"
               f"週(完成) K={w_k:.2f} D={w_d:.2f}  Close={w_close:.2f} > MA{WEEKLY_MA}={w_ma20:.2f}\n"
               f"時間（日K收盤）：{to_tz(d_ts, TZ_NAME)}{inst_line}")
        send_to(recipients, msg)
        sym_state["position"] = "long"
        sym_state["last_entry"] = str(d_ts)
        state[sym] = sym_state
        save_state(state)
        print(f"[ENTRY] {sym} long @ {to_tz(d_ts)}")
        return

    # Reduce on daily cross down (once per date)
    date_key = pd.Timestamp(d_ts).tz_localize("UTC").tz_convert(TZ_NAME).strftime("%Y-%m-%d")
    ex_key = f"daily_exit@{date_key}"
    if sym_state.get("position") == "long" and exit_cross and not alerted(ex_key):
        msg = (f"[B Reduce] {sym}\n"
               f"日線死亡交叉（部分減碼建議）\n"
               f"日收盤 {d_close:.2f}  K={k_last:.2f} D={d_last_d:.2f}\n"
               f"時間（日K收盤）：{to_tz(d_ts, TZ_NAME)}{inst_line}")
        send_to(recipients, msg)
        mark_alert(ex_key)
        print(f"[REDUCE] {sym} daily cross-down @ {to_tz(d_ts)}")

    # Exit when weekly filter turns off (once per completed week)
    w_week_str = pd.Timestamp(w_idx).tz_localize("UTC").tz_convert(TZ_NAME).strftime("%Y-%m-%d")
    full_key = f"weekly_off@{w_week_str}"
    weekly_off = not weekly_ok
    if sym_state.get("position") == "long" and weekly_off and not alerted(full_key):
        msg = (f"[B Exit] {sym}\n"
               f"週濾網失效（K≤D 或 K<50 或 Close≤週MA{WEEKLY_MA}）→ 全部出清建議\n"
               f"週(完成) K={w_k:.2f} D={w_d:.2f}  Close={w_close:.2f}  MA{WEEKLY_MA}={w_ma20:.2f}\n"
               f"週期時間（完成週）：{to_tz(w_idx, TZ_NAME)}{inst_line}")
        send_to(recipients, msg)
        sym_state["position"] = "flat"
        state[sym] = sym_state
        save_state(state)
        print(f"[EXIT] {sym} weekly filter off @ {to_tz(w_idx)}")

    # 若沒有任何動作，印出狀態摘要（便於確認條件）
    print(
        f"[NOOP] {sym}: K={k_last:.1f} D={d_last_d:.1f} "
        f"daily_ma20_ok={daily_trend_ok} weekly_ok={weekly_ok} "
        f"cross_up={entry_cross} cross_down={exit_cross}"
    )


def main():
    print(f"[START] KD Strategy B  TZ={TZ_NAME}  DRY_RUN={int(DRY_RUN)}  K_PERIOD={K_PERIOD}  ALPHA={ALPHA}")
    cfg = load_config()
    subs = all_symbols_to_subscribers()
    if not subs:
        print("[INFO] No subscriptions yet. Use chat: 'add 2330'")
        return
    symbols = sorted(subs.keys())
    state = load_state()
    print(f"[INFO] symbols={symbols}")
    for sym in symbols:
        try:
            process_symbol(sym, subs[sym], state, cfg)
        except Exception as e:
            print(f"[ERROR] {sym}: {e}")
    print("[DONE]")


if __name__ == "__main__":
    main()
