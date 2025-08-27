#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="/Users/catherinehsu/KDX"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/kd.out.log"
mkdir -p "$LOG_DIR"

# 指定 Python 腳本檔名（如果檔名不同，改這裡就好）
PY_SCRIPT="$PROJECT_DIR/kd_strategyB.py"

# 從這行開始，所有輸出導到 kd.out.log
exec >>"$LOG_FILE" 2>&1

echo "[$(date '+%F %T')] run_kd.sh starting (pid $$)"
cd "$PROJECT_DIR"

# 載入 .env（若存在）
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a; source "$PROJECT_DIR/.env"; set +a
  echo "env loaded (TZ=${TZ:-}, SUBS_FILE=${SUBS_FILE:-})"
else
  echo ".env not found (continue)"
fi

# 必要變數防呆（缺了會記錄到 log）
: "${LINE_CHANNEL_ACCESS_TOKEN:?missing LINE_CHANNEL_ACCESS_TOKEN}"
: "${LINE_CHANNEL_SECRET:?missing LINE_CHANNEL_SECRET}"

# 確認虛擬環境 Python
ls -l "$VENV_PY" || { echo "Python not found at $VENV_PY"; exit 1; }
"$VENV_PY" -V

# 檢查腳本是否存在
[ -f "$PY_SCRIPT" ] || { echo "Script not found: $PY_SCRIPT"; exit 78; }

echo "[$(date '+%F %T')] Running $(basename "$PY_SCRIPT") (DRY_RUN=${DRY_RUN:-0})"
START=$(date +%s)

# 改用變數呼叫
"$VENV_PY" "$PY_SCRIPT"

STATUS=$?
echo "[$(date '+%F %T')] Finished exit=$STATUS in $(( $(date +%s)-START ))s"
exit $STATUS
