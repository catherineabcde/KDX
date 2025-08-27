# file: institutions.py
import os, json, time, requests
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
_TZ = timezone(timedelta(hours=8))
def _yyyymmdd(dt: datetime) -> str:
  return dt.astimezone(_TZ).strftime("%Y%m%d")
def _date_iso(dt: datetime) -> str:
  return dt.astimezone(_TZ).strftime("%Y-%m-%d")
def _cache_path(day: datetime) -> str:
  d = day.astimezone(_TZ).strftime("%Y%m%d")
  os.makedirs("cache", exist_ok=True)
  return os.path.join("cache", f"twse_T86_{d}.json")
def _load_cache(day: datetime):
  p = _cache_path(day)
  if os.path.exists(p):
    try:
      with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return None
  return None
def _save_cache(day: datetime, data):
  p = _cache_path(day)
  with open(p, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
def _fetch_twse_t86(day: datetime):
  url = "https://www.twse.com.tw/rwd/zh/fund/T86"
  params = {"date": _yyyymmdd(day), "selectType": "All", "response": "json"}
  r = requests.get(url, params=params, timeout=20); r.raise_for_status()
  return r.json()
def _parse_rows_to_map(payload) -> Dict[str, Dict[str, Any]]:
  headers = payload.get("fields") or payload.get("title") or []
  rows = payload.get("data") or []
  idx = {h: i for i, h in enumerate(headers)}
  col_id = idx.get("證券代號", 0)
  col_f = idx.get("外陸資買賣超股數(不含外資自營商)", None)
  col_t = idx.get("投信買賣超股數", None)
  col_d = idx.get("自營商買賣超股數", None)
  col_sum = idx.get("三大法人買賣超股數", None)
  out = {}
  for r in rows:
    code = r[col_id].strip()
    def _to_int(x):
      try:
        return int(str(x).replace(",","").replace("--","0"))
      except Exception:
        return 0
    foreign = _to_int(r[col_f]) if col_f is not None else 0
    trust = _to_int(r[col_t]) if col_t is not None else 0
    dealer = _to_int(r[col_d]) if col_d is not None else 0
    total = _to_int(r[col_sum]) if col_sum is not None else (foreign + trust + dealer)
    out[code] = {"foreign": foreign, "trust": trust, "dealer": dealer, "total": total}
  return out
def get_institutions(symbol: str, day: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
  if day is None:
    day = datetime.now(tz=_TZ)
  code = symbol.split(".")[0]
  payload = _load_cache(day)
  if payload is None:
    try:
      payload = _fetch_twse_t86(day)
      if (payload or {}).get("stat") != "OK":
        return None
      _save_cache(day, payload)
    except Exception:
      return None
  m = _parse_rows_to_map(payload)
  row = m.get(code)
  if not row:
    return None
  row["symbol"] = f"{code}.TW" if ".TW" not in symbol and ".TWO" not in symbol else symbol
  row["date"] = _date_iso(day)
  return row
def fmt_line(row: Dict[str, Any]) -> str:
  def f(n): return f"{n:+,}"
  return f"外資 {f(row['foreign'])}、投信 {f(row['trust'])}、自營 {f(row['dealer'])}、合計 {f(row['total'])} 股"