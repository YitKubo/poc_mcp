# poc_mcp — トップレベルの操作窓口。実処理は server/ と client/ の Makefile に委譲する。
#   make server-<target>  ==  make -C server <target>
#   make client-<target>  ==  make -C client <target>
# uv が PATH に無い場合:  UV=/path/to/uv make ...

UV ?= uv
export UV

.DEFAULT_GOAL := help
.PHONY: help up down test

help: ## 使い方
	@echo "poc_mcp — MCP トライアル（サーバ運用ツール MCP / Streamable HTTP）"
	@echo
	@echo "  ショートカット"
	@echo "    make up            サーバの導入(uv sync)と起動"
	@echo "    make down          サーバ停止"
	@echo "    make test          サーバの smoke + load テスト（要: 起動済み）"
	@echo
	@echo "  サーバ側 (server/)   make server-<target>"
	@echo "    setup start stop restart status logs run smoke load test clean"
	@echo
	@echo "  クライアント側 (client/)   make client-<target>"
	@echo "    config check add remove reset list show"
	@echo
	@echo "  各ディレクトリの一覧:  make -C server help / make -C client help"
	@echo "  読む順: README.md -> docs/00-architecture.md -> server/README.md, client/README.md"

up: ## サーバの導入と起動
	@$(MAKE) --no-print-directory -C server setup start

down: ## サーバ停止
	@$(MAKE) --no-print-directory -C server stop

test: ## サーバの smoke + load テスト
	@$(MAKE) --no-print-directory -C server smoke load

server-%:
	@$(MAKE) --no-print-directory -C server $*

client-%:
	@$(MAKE) --no-print-directory -C client $*
