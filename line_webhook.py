import re, unicodedata, sys
from fastapi import FastAPI, Request, Header
from fastapi.responses import PlainTextResponse

from line_push import reply_text, verify_signature
from subscriptions import add_symbols, remove_symbols, list_symbols, clear_symbols

app = FastAPI(title="LINE KD Alert Webhook")

HELP_TEXT = (
    "💰 add <...>\n— add tickers (e.g., add 2330 00981A)\n"
    "💰 remove <...>\n— remove tickers (e.g., remove 2330 00981A)\n"
    "💰 list\n— show the following tickers\n"
    "💰 clear\n— remove all tickers\n"
    "💰 help\n— show this help\n"
)

_ALIASES = {
    # remove
    "rm": "remove", "del": "remove", "刪除": "remove", "移除": "remove", "取消": "remove", "退訂": "remove",
    # list
    "show": "list", "status": "list", "清單": "list", "列表": "list", "追蹤": "list", "查看": "list", "查詢": "list",
    "l": "list", "ls": "list",
    # clear
    "清空": "clear", "全部清除": "clear",
    # help
    "h": "help", "?": "help", "幫助": "help", "說明": "help"
}
_VALID_CMDS = {"add", "remove", "list", "clear", "help"}

def _normalize(s: str) -> str:
    # NFKC: turn full-width into half-width; trim; drop zero-width & NBSP
    s = unicodedata.normalize("NFKC", s or "").strip()
    s = s.replace("\u200b", "").replace("\u00A0", " ")
    return s

def _looks_like_symbols(tokens):
    if not tokens: return False
    pat = re.compile(r"^[A-Za-z0-9\.]{1,12}$")
    ok = False
    for t in tokens:
        if not t: continue
        if not pat.match(t): return False
        ok = True
    return ok

def _parse_cmd(s: str):
    s = _normalize(s)
    if not s:
        return "", []
    # allow leading slash /add 2330
    if s.startswith("/"):
        s = s[1:]
    # split by whitespace, ASCII comma, Chinese commas/、
    parts = re.split(r"[\s,，、]+", s)
    parts = [p for p in parts if p]
    if not parts:
        return "", []
    cmd = parts[0].lower()
    cmd = _ALIASES.get(cmd, cmd)
    args = parts[1:]
    if cmd not in _VALID_CMDS:
        # if first token is not a known command, but looks like symbols, treat as add
        cand = [cmd] + args
        if _looks_like_symbols(cand):
            return "add", cand
        return cmd, args
    return cmd, args

def _fmt_list(syms):
    if not syms:
        return "(none)"
    if len(syms) <= 12:
        bullets = "\n".join(f"• {s}" for s in syms)
        return f"{len(syms)} symbols: \n{bullets}"
    return f"{len(syms)} symbols: " + ", ".join(syms)

@app.get("/health")
def health():
    return PlainTextResponse("OK")

@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(default="")):
    raw = await request.body()
    if not verify_signature(raw, x_line_signature):
        return PlainTextResponse("signature NG", status_code=400)

    body = await request.json()
    events = body.get("events", [])
    for e in events:
        if e.get("type") != "message":
            continue
        msg = e.get("message", {})
        if msg.get("type") != "text":
            continue

        text = msg.get("text", "")
        # debug to terminal
        print(f"[WEBHOOK] text={text!r}", file=sys.stderr)

        reply_token = e.get("replyToken", "")
        src = e.get("source", {})
        rid = src.get("userId") or src.get("groupId") or src.get("roomId")
        if not rid or not reply_token:
            continue

        cmd, args = _parse_cmd(text)

        if cmd in ("help", ""):
            reply_text(reply_token, HELP_TEXT); continue

        if cmd == "add" and args:
            added, skipped = add_symbols(rid, args)
            syms = list_symbols(rid)
            lines = []
            if added:
                lines.append("Added: " + ", ".join(added))
            if skipped:
                lines.append("Skipped: " + ", ".join(skipped))
            lines.append("Now tracking:\n" + _fmt_list(syms))
            reply_text(reply_token, "\n".join(lines)); continue

        if cmd == "remove" and args:
            removed = remove_symbols(rid, args)
            syms = list_symbols(rid)
            if removed:
                reply_text(reply_token, "Removed: " + ", ".join(removed) + "\nNow tracking:\n" + _fmt_list(syms))
            else:
                reply_text(reply_token, "Nothing to remove.\nNow tracking:\n" + _fmt_list(syms))
            continue

        if cmd == "clear":
            n = clear_symbols(rid)
            reply_text(reply_token, f"Cleared {n} symbols.\nNow tracking:\n{_fmt_list(list_symbols(rid))}")
            continue

        if cmd == "list":
            syms = list_symbols(rid)
            reply_text(reply_token, "Your symbols:\n" + _fmt_list(syms))
            continue

        # default
        reply_text(reply_token, "Unknown command.\n" + HELP_TEXT)

    return PlainTextResponse("OK")