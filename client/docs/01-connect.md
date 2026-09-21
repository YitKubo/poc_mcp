# 01. 別ターミナルから接続する

## 前提

- サーバが起動している（`make server-status` / サーバ側で `make status` → `running`）
- `claude`（Claude Code）、`curl`、`make` が使える

## 手順

```bash
cd client
make config        # 1. config/endpoint.env を作る。MCP_SERVER_URL を確認（同一ホストなら既定のまま）
make check         # 2. Claude 抜きの到達性チェック
make add           # 3. Claude Code に登録
claude             # 4. ★ 新しいセッションを起動（登録は起動済みのセッションには反映されない）
                   #    /mcp で ops-mcp が connected と表示されることを確認
```

### 2. `make check` の期待出力（実測）

```
target: http://127.0.0.1:8848/mcp  (host=127.0.0.1 port=8848)
1. TCP  connect ...... OK
2. HTTP response ..... OK (HTTP 200)
3. MCP tools/list .... OK
   tools: disk_usage,journal_recent,listening_ports,resource_usage,server_stats,service_status,system_overview,tail_log,top_processes
=> サーバに届いており、MCP として応答しています。次は make add で Claude に登録できます。
```

3段階で「どこで詰まっているか」が一意に決まる（失敗時の対処は [`03-troubleshooting.md`](03-troubleshooting.md)）。

### 3. `make add` の期待出力（実測）

```
+ claude mcp add --transport http --scope local ops-mcp http://127.0.0.1:8848/mcp
Added HTTP MCP server ops-mcp with URL: http://127.0.0.1:8848/mcp to local config
File modified: /home/kubo/.claude.json [project: /home/kubo/poc_mcp/client]

ops-mcp:
  Scope: Local config (private to you in this project)
  Status: ✔ Connected
  Type: http
  URL: http://127.0.0.1:8848/mcp
```

`make list`（= `claude mcp list`）は実際に接続して状態を確認する。他の MCP サーバと並んで `ops-mcp: http://127.0.0.1:8848/mcp (HTTP) - ✔ Connected` と出る。

## Claude に使わせる

Claude Code 上のツール名は `mcp__ops-mcp__<ツール名>`（例: `mcp__ops-mcp__resource_usage`）。話しかけ方の例:

- 「メモリ使用状況と、CPU使用率の高いプロセス上位3つを調べて」
- 「cron サービスは動いている？」
- 「直近のエラーレベルのジャーナルを見て、気になるものがあれば教えて」
- 「ディスクの空きは足りている？」

### 実測: ヘッドレスで実際にツールを呼ばせた結果

```bash
cd client && claude -p "ops-mcp のツールを使って、このホストのメモリ使用状況と、CPU使用率の高いプロセス上位3つを調べて、日本語で3行以内で報告して。" \
  --allowedTools "mcp__ops-mcp__resource_usage,mcp__ops-mcp__top_processes"
```

- Claude は `resource_usage` と `top_processes` を呼び、実データから回答した（メモリ 24,033MB 中 8,254MB 使用 34.3%、CPU 全体 4.7%、上位プロセス3件）
- この実行では**ツールは逐次**に呼ばれた。最初に `ToolSearch`（MCP ツールの定義を引く）が挟まる
- `--allowedTools` は、対話セッションで毎回出る**ツール実行の許可確認**を事前に許可するもの。全ツール read-only なので許可しやすい

### プロンプトとリソース

サーバは prompts（`health_check` / `investigate_load`）と resources（`ops://host` 等）も公開している。
Claude Code の対話 UI からの呼び出し方（プロンプトは `/mcp__ops-mcp__health_check` の形のスラッシュコマンド、リソースは `@` 参照、という認識）は、
**この環境の対話 UI では未確認**。サーバ側の実装は `make smoke` で検証済み（`prompts/get`・`resources/read` は通る）。

## scope（登録の有効範囲）

`MCP_SCOPE`（`config/endpoint.env`）で選ぶ。既定は `local`。

| scope | 有効になる範囲 | 保存先 | 用途 |
|---|---|---|---|
| `local`（既定） | **登録時のディレクトリ（プロジェクト）で `claude` を起動したときだけ**。自分専用 | `~/.claude.json` | 試すだけ |
| `user` | どのディレクトリで起動しても。自分専用 | `~/.claude.json` | 普段使い |
| `project` | リポジトリの `.mcp.json`。チームで共有 | `.mcp.json` | 共有（初回に承認を求められることがある） |

> **local scope の落とし穴**: 実測で `[project: /home/kubo/poc_mcp/client]` に紐づいた。
> 別のディレクトリで `claude` を起動すると `ops-mcp` は見えない。どこからでも使いたいなら `MCP_SCOPE=user make add`。

## `.mcp.json` 方式（project scope を手で書く場合）

`config/mcp.json.template` をプロジェクトのルートに `.mcp.json` として置く:

```json
{
  "mcpServers": {
    "ops-mcp": {
      "type": "http",
      "url": "http://127.0.0.1:8848/mcp"
    }
  }
}
```

**`"type": "http"` が必須**。`url` だけだと stdio サーバとして解釈される（JSON にコメントは書けないのでここで注意）。`streamable-http` も `http` の別名として使える。

## 解除・再登録

```bash
make remove     # 登録解除（scope は自動判別）
make reset      # 解除して再登録（endpoint.env を変えたあとに）
```

`make add` は登録済みなら何もせず `既に登録済みです` と現状を表示する（冪等）。

## make を使わない場合の生コマンド

```bash
claude mcp add --transport http --scope local ops-mcp http://127.0.0.1:8848/mcp
claude mcp get ops-mcp
claude mcp list
claude mcp remove ops-mcp
```

## 別端末に持っていく

1. `client/` ディレクトリごとコピーする（要: `claude`・`curl`・`make`。Python は不要）
2. `make config` → `config/endpoint.env` の `MCP_SERVER_URL` をサーバのアドレスにする
3. 以降は同じ（`make check` → `make add`）。サーバ側の準備は [`02-remote-host.md`](02-remote-host.md)
