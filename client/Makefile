# client/Makefile — MCP クライアント（Claude Code）側の操作窓口。`make help` で一覧。
# このディレクトリ一式を別端末にコピーすれば、そこからでも同じ手順で接続できる（要: claude, curl, make）。

.DEFAULT_GOAL := help
.PHONY: help config check add remove reset list show

help: ## ターゲット一覧
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-8s %s\n",$$1,$$2}'

config: ## config/endpoint.env を作る（接続先はここで編集）
	@[ -f config/endpoint.env ] && echo "config/endpoint.env は既にあります" || { cp config/endpoint.example.env config/endpoint.env; echo "created config/endpoint.env  <- MCP_SERVER_URL を確認・編集してください"; }

check: ## Claude 抜きの到達性チェック（TCP -> HTTP -> MCP tools/list）
	@scripts/check_reachable.sh

add: ## claude mcp add で登録
	@scripts/add_mcp.sh

remove: ## 登録を解除
	@scripts/remove_mcp.sh

reset: remove add ## 解除して再登録

list: ## 登録済み MCP サーバの一覧と疎通状態
	@claude mcp list

show: ## 登録内容の詳細
	@. scripts/_common.sh; claude mcp get "$$MCP_SERVER_NAME"
