# file: subscriptions.py
import os, json, re
from typing import Dict, List, Set, Tuple

# Accept letters, digits, and dot for suffixes like .TW / .TWO
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9\.]{1,12}$")

# Taiwan ticker pattern: 1–6 digits + optional 1–2 letters (e.g., 00981A, 1101, 3707B)
_TW_NUM_LETTERS = re.compile(r"^\d{1,6}[A-Z]{0,2}$")

def ensure_tw_suffix(symbol: str) -> str:
    """Normalize symbol:
       - Uppercase
       - If it already has an exchange ('.TW' or '.TWO'), keep it
       - If it looks like a Taiwan ticker (digits + optional letters), append '.TW'
         (We default to TWSE; if a specific ticker is OTC you can input '.TWO' explicitly.)
    """
    s = symbol.strip().upper()
    if s.endswith(".TW") or s.endswith(".TWO"):
        return s
    if _TW_NUM_LETTERS.match(s):
        return s + ".TW"
    return s

def _normalize_map(d: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out = {}
    for rid, syms in (d or {}).items():
        uniq = sorted({ensure_tw_suffix(x) for x in syms if _SYMBOL_RE.match(ensure_tw_suffix(x))})
        out[rid] = uniq
    return out

class Backend:
    def load(self) -> Dict[str, List[str]]:
        raise NotImplementedError
    def save(self, data: Dict[str, List[str]]):
        raise NotImplementedError

class LocalJSONBackend(Backend):
    def __init__(self, path: str):
        self.path = path or "subscriptions.json"
    def load(self) -> Dict[str, List[str]]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict): return _normalize_map(data)
        except Exception:
            return {}
        return {}
    def save(self, data: Dict[str, List[str]]):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_normalize_map(data), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

class S3Backend(Backend):
    def __init__(self, bucket: str, key: str = "subscriptions.json"):
        import boto3
        self.s3 = boto3.client("s3")
        self.bucket = bucket
        self.key = key or "subscriptions.json"
    def load(self) -> Dict[str, List[str]]:
        import botocore
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=self.key)
            body = obj["Body"].read().decode("utf-8")
            data = json.loads(body)
            if isinstance(data, dict):
                return _normalize_map(data)
        except self.s3.exceptions.NoSuchKey:
            return {}
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return {}
            raise
        except Exception:
            return {}
        return {}
    def save(self, data: Dict[str, List[str]]):
        body = json.dumps(_normalize_map(data), ensure_ascii=False, indent=2).encode("utf-8")
        self.s3.put_object(Bucket=self.bucket, Key=self.key, Body=body, ContentType="application/json; charset=utf-8")

def _get_backend() -> 'Backend':
    backend = os.getenv("SUBS_BACKEND", "local").lower()
    if backend == "s3":
        bucket = os.getenv("SUBS_S3_BUCKET", "").strip()
        key = os.getenv("SUBS_S3_KEY", "subscriptions.json").strip()
        if not bucket:
            raise RuntimeError("SUBS_BACKEND=s3 requires SUBS_S3_BUCKET")
        return S3Backend(bucket, key)
    path = os.getenv("SUBS_FILE", "subscriptions.json")
    return LocalJSONBackend(path)

def list_symbols(recipient_id: str) -> List[str]:
    store = _get_backend()
    data = store.load()
    return sorted(set(data.get(recipient_id, [])))

def add_symbols(recipient_id: str, symbols: List[str]) -> Tuple[List[str], List[str]]:
    store = _get_backend()
    data = store.load()
    cur = set(data.get(recipient_id, []))
    added, skipped = [], []
    for raw in symbols:
        s = ensure_tw_suffix(raw)
        if not _SYMBOL_RE.match(s):
            skipped.append(raw); continue
        if s not in cur:
            cur.add(s); added.append(s)
    data[recipient_id] = sorted(cur)
    store.save(data)
    return added, skipped

def remove_symbols(recipient_id: str, symbols: List[str]) -> List[str]:
    store = _get_backend()
    data = store.load()
    cur = set(data.get(recipient_id, []))
    removed = []
    for raw in symbols:
        s = ensure_tw_suffix(raw)
        if s in cur:
            cur.remove(s); removed.append(s)
    data[recipient_id] = sorted(cur)
    store.save(data)
    return removed

def clear_symbols(recipient_id: str) -> int:
    store = _get_backend()
    data = store.load()
    n = len(set(data.get(recipient_id, [])))
    data[recipient_id] = []
    store.save(data)
    return n

def all_symbols_to_subscribers() -> Dict[str, Set[str]]:
    store = _get_backend()
    data = store.load()
    m: Dict[str, Set[str]] = {}
    for rid, syms in data.items():
        for s in syms:
            m.setdefault(s, set()).add(rid)
    return m