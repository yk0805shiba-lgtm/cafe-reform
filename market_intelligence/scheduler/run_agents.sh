#!/bin/bash
# 手動実行用スクリプト（全店舗・全Agent）
# 使い方: bash scheduler/run_agents.sh [cafe_01|delivery_01|all] [event|competitor|all]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON=$(command -v python3)
CLI="${PROJECT_DIR}/cli.py"

STORE="${1:-all}"
AGENT="${2:-all}"

# .envが存在する場合は読み込む
if [ -f "${PROJECT_DIR}/../.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "${PROJECT_DIR}/../.env"
    set +a
fi

echo "[run_agents] 開始: store=${STORE} agent=${AGENT} $(date '+%Y-%m-%d %H:%M:%S')"

run_event() {
    local store_id=$1
    echo "[run_agents] 近隣イベントAgent: ${store_id}"
    cd "${PROJECT_DIR}" && ${PYTHON} ${CLI} event run --store "${store_id}" --days 90
}

run_competitor() {
    local store_id=$1
    echo "[run_agents] 競合モニタリングAgent: ${store_id}"
    cd "${PROJECT_DIR}" && ${PYTHON} ${CLI} competitor run --store "${store_id}"
}

run_report() {
    local store_id=$1
    echo "[run_agents] レポート生成: ${store_id}"
    cd "${PROJECT_DIR}" && ${PYTHON} ${CLI} report html --store "${store_id}"
}

stores=()
if [ "$STORE" = "all" ]; then
    stores=("cafe_01" "delivery_01")
else
    stores=("$STORE")
fi

for s in "${stores[@]}"; do
    if [ "$AGENT" = "event" ] || [ "$AGENT" = "all" ]; then
        run_event "$s"
    fi
    if [ "$AGENT" = "competitor" ] || [ "$AGENT" = "all" ]; then
        run_competitor "$s"
    fi
    run_report "$s"
done

echo "[run_agents] 完了: $(date '+%Y-%m-%d %H:%M:%S')"
