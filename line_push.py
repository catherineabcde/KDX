# file: line_push.py
# Helpers for LINE Messaging API (push + reply) with DRY_RUN support.
import os, json, hmac, hashlib, base64, time, requests

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
DRY_RUN = os.getenv("DRY_RUN") == "1"

API_PUSH = "https://api.line.me/v2/bot/message/push"
API_REPLY = "https://api.line.me/v2/bot/message/reply"

_session = requests.Session()

def _headers():
    return {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

def _post(url: str, payload: dict, retries: int = 2, backoff: float = 2.0):
    data = json.dumps(payload, ensure_ascii=False)
    for i in range(retries + 1):
        r = _session.post(url, headers=_headers(), data=data, timeout=15)
        if r.status_code == 200:
            return
        # 簡單重試：429/5xx
        if r.status_code in (429, 500, 502, 503, 504) and i < retries:
            time.sleep(backoff * (i + 1))
            continue
        raise RuntimeError(f"LINE API failed: {r.status_code} {r.text}")

def push_text(to_id: str, text: str):
    """Push a plain text message to a LINE userId or groupId."""
    if DRY_RUN or not CHANNEL_ACCESS_TOKEN:
        print(f"[DRY_RUN] would push to {to_id}:\n{text}")
        return
    payload = {"to": to_id, "messages": [{"type": "text", "text": text}]}
    _post(API_PUSH, payload)

def reply_text(reply_token: str, text: str):
    """Reply to a message using the replyToken from webhook events."""
    if DRY_RUN or not CHANNEL_ACCESS_TOKEN:
        print(f"[DRY_RUN] would reply:\n{text}")
        return
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    _post(API_REPLY, payload)

# 可選：讓你在 help/list 用 Flex 卡片加粗/上色/對齊
def reply_flex(reply_token: str, alt_text: str, contents: dict):
    if DRY_RUN or not CHANNEL_ACCESS_TOKEN:
        print("[DRY_RUN] would reply flex:", json.dumps(contents, ensure_ascii=False, indent=2))
        return
    payload = {"replyToken": reply_token, "messages": [{
        "type": "flex", "altText": alt_text, "contents": contents
    }]}
    _post(API_REPLY, payload)

def verify_signature(raw_body: bytes, x_line_signature: str) -> bool:
    """Optional signature check (recommended in production)."""
    if not CHANNEL_SECRET:
        return True
    mac = hmac.new(CHANNEL_SECRET.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    return hmac.compare_digest(expected, x_line_signature or "")
