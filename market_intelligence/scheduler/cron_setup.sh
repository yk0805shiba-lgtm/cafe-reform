#!/bin/bash
# Local Market Intelligence - cron設定スクリプト
# 使い方: bash scheduler/cron_setup.sh
# 設定後に確認: crontab -l

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON=$(command -v python3)
CLI="${PROJECT_DIR}/cli.py"
LOG_DIR="${PROJECT_DIR}/logs"

mkdir -p "$LOG_DIR"

# 設定ファイルから環境変数を読み込む（存在する場合）
ENV_FILE="${PROJECT_DIR}/../.env"
if [ -f "$ENV_FILE" ]; then
    ENV_LOAD="set -a; source $ENV_FILE; set +a &&"
else
    ENV_LOAD=""
fi

# 現在のcrontabを取得
EXISTING=$(crontab -l 2>/dev/null || echo "")

# 既存のLocal Market Intelligence設定を削除
CLEANED=$(echo "$EXISTING" | grep -v "local-market-intelligence")

CAFE_REFORM_DIR="$(dirname "$PROJECT_DIR")"

# 新しいcron設定（PYTHONPATH に cafe-reform を追加してモジュール解決）
NEW_CRON="${CLEANED}
# local-market-intelligence: 近隣イベントAgent (毎日6時 JST)
0 6 * * * cd ${CAFE_REFORM_DIR} && PYTHONPATH=${CAFE_REFORM_DIR} ${PYTHON} ${CLI} event run --store cafe_01 >> ${LOG_DIR}/event_agent_cafe.log 2>&1 # local-market-intelligence
0 6 * * * cd ${CAFE_REFORM_DIR} && PYTHONPATH=${CAFE_REFORM_DIR} ${PYTHON} ${CLI} event run --store delivery_01 >> ${LOG_DIR}/event_agent_delivery.log 2>&1 # local-market-intelligence

# local-market-intelligence: 競合モニタリングAgent (毎日8時 JST)
0 8 * * * cd ${CAFE_REFORM_DIR} && PYTHONPATH=${CAFE_REFORM_DIR} ${PYTHON} ${CLI} competitor run --store cafe_01 >> ${LOG_DIR}/competitor_cafe.log 2>&1 # local-market-intelligence
0 8 * * * cd ${CAFE_REFORM_DIR} && PYTHONPATH=${CAFE_REFORM_DIR} ${PYTHON} ${CLI} competitor run --store delivery_01 >> ${LOG_DIR}/competitor_delivery.log 2>&1 # local-market-intelligence

# local-market-intelligence: レポート生成 (毎日9時)
0 9 * * * cd ${CAFE_REFORM_DIR} && PYTHONPATH=${CAFE_REFORM_DIR} ${PYTHON} ${CLI} report html --store cafe_01 >> ${LOG_DIR}/report.log 2>&1 # local-market-intelligence
0 9 * * * cd ${CAFE_REFORM_DIR} && PYTHONPATH=${CAFE_REFORM_DIR} ${PYTHON} ${CLI} report html --store delivery_01 >> ${LOG_DIR}/report.log 2>&1 # local-market-intelligence
"

echo "$NEW_CRON" | crontab -
echo "[cron_setup] cron設定完了。確認: crontab -l"
echo "[cron_setup] ログ出力先: $LOG_DIR"
echo ""
echo "注意: cron環境では PATH が限られる場合があります。"
echo "必要に応じて run_agents.sh の PYTHONPATH 設定を確認してください。"
