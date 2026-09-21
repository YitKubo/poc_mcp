# server/Makefile — ops-mcp サーバの操作窓口。`make help` で一覧。
# 依存管理と実行は uv。uv が PATH に無い場合は UV=/path/to/uv make ... で指定する。

UV ?= uv
export UV

# smoke / load が繋ぐ先。config/server.env の MCP_PORT に追従する（上書き: make smoke MCP_URL=...）。
MCP_URL ?= $(shell set -a; [ -f config/server.env ] && . ./config/server.env; echo "http://127.0.0.1:$${MCP_PORT:-8848}/mcp")

.DEFAULT_GOAL := help
.PHONY: help setup run start stop restart status logs smoke load test clean

help: ## ターゲット一覧
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-9s %s\n",$$1,$$2}'

setup: ## uv で .venv を作り依存を導入（config/server.env も用意）
	$(UV) sync
	@[ -f config/server.env ] || { cp config/server.env.example config/server.env; echo "created config/server.env"; }

run: ## フォアグラウンドで起動（Ctrl-C で停止）
	@scripts/serverctl.sh run

start: ## バックグラウンドで起動（PID: run/server.pid, ログ: run/server.log）
	@scripts/serverctl.sh start

stop: ## 停止
	@scripts/serverctl.sh stop

restart: stop start ## 再起動

status: ## 起動状態
	@scripts/serverctl.sh status

logs: ## サーバログを追う（Ctrl-C で抜ける）
	@tail -n 50 -f run/server.log

smoke: ## MCP プロトコル疎通テスト（要: サーバ起動済み）
	$(UV) run python scripts/smoke_test.py --url $(MCP_URL)

load: ## 並行リクエストの競合テスト（要: サーバ起動済み）
	$(UV) run python scripts/load_test.py --url $(MCP_URL)

test: smoke load ## smoke + load

clean: stop ## 停止して .venv と run/ を削除
	rm -rf .venv run
