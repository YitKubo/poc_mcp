# MCP 学習メモ — このトライアルで分かったこと

## 1. 3つの機能は「誰が決めるか」で分かれる

| | 決めるのは | 例（`ops-mcp`） | 使い方 |
|---|---|---|---|
| **Tools** | **モデル** | `resource_usage`, `service_status` … | モデルが必要に応じて呼ぶ関数 |
| **Resources** | **アプリ**（ホスト） | `ops://host`, `ops://logs/{name}` | アプリが読み込んで文脈としてモデルに渡す（URI で指定） |
| **Prompts** | **ユーザー** | `health_check`, `investigate_load` | ユーザーが選ぶテンプレート（スラッシュコマンド等） |

同じ「ログを見る」でも、`tail_log`（モデルが呼ぶ）と `ops://logs/syslog`（アプリが読む）と使い分けられる。
関数名・docstring・型ヒントが、そのままツール名・説明・入力スキーマになる（スキーマを手で書かない）。

## 2. トランスポート: stdio と Streamable HTTP

| | stdio | Streamable HTTP |
|---|---|---|
| 起動 | ホストがサーバを子プロセスで起動 | **サーバを先に起動しておく** |
| 登録 | `claude mcp add NAME -- <起動コマンド>` | `claude mcp add --transport http NAME <URL>` |
| 用途 | ローカル専用 | デプロイ・複数クライアント・別マシン |

SSE は Streamable HTTP に置き換えられた旧方式で、新規には使わない。
図とともに [`00-architecture.md` §2](00-architecture.md)。

## 3. MCP Python SDK v2 で変わっていた点（記憶で書くと壊れる）

| v1 の記憶 | v2（検証: mcp 2.2.0） |
|---|---|
| `from mcp.server.fastmcp import FastMCP` | `from mcp.server import MCPServer` |
| `FastMCP(..., host=..., port=...)` | **トランスポート引数は `mcp.run(...)` に渡す**（コンストラクタに渡すと `TypeError`） |
| `ToolError` | `from mcp.server.mcpserver.exceptions import ToolError` |
| `ToolAnnotations` | `from mcp.types import ToolAnnotations` |
| クライアント | `from mcp import Client` → `Client("http://…/mcp")`（URL = Streamable HTTP） |
| `pip install mcp` | 現在は **2.x が入る**。v1 に留めるなら `mcp>=1.28,<2` |

- 戻り値: `dict` は `structured_content` にそのまま、**`list` は `{"result": [...]}` に包まれる**
- 同期 `def` のツールは SDK がスレッドで実行する（`async def` は I/O を `await` する場合だけ）
- `MCPServer(resource_security=...)` の既定で、リソース URI のパストラバーサル・絶対パス・NUL は拒否される

## 4. プロトコル（2026-07-28）

- **セッションレス**: 1リクエスト=1 POST で完結。`initialize` も `Mcp-Session-Id` も不要
- 必須: `MCP-Protocol-Version` / `Mcp-Method`（本文の `method` と一致）ヘッダ、`params._meta` の `protocolVersion` と `clientCapabilities`
- 素の `curl` で `tools/list` が叩ける（[`00-architecture.md` §4](00-architecture.md)）。**MCP over HTTP は JSON-RPC を POST しているだけ**
- 旧プロトコルのクライアント向けに、サーバはセッション付きの経路も持つ（`stateless_http` 等はそちら専用）

## 5. 予想が外れた・実測で分かったこと

「机上の想定」と「実測」がずれた箇所。トライアルで最も学びが大きかった部分。

| 想定 | 実測 |
|---|---|
| `psutil.cpu_percent()` はグローバル状態で、並行サンプリングで値が壊れる（→ Lock が要る） | **壊れない**。基準値はスレッドごと・blocking はローカル変数（32スレッドで 9.9〜13.6%）。本当の共有状態は `process_iter()` の `Process` キャッシュ側 |
| Claude は1ターンで複数ツールを**並列**に呼ぶ | 実測した1回では**逐次**（`ToolSearch` を挟む）。並列は「あることがある」 |
| `uv run` は exec して PID が実サーバになる | **exec しない**。uv が親で python が子。`stop` は uv への SIGTERM が子へ転送されて両方止まる |
| journal の本文はそのままテキスト | 色付きログの **ANSI エスケープ**が混ざっていた（→ 除去） |
| `top_processes` の `name` でプロセスが分かる | ランタイムのスレッド名 `MainThread` が並び判別不能（→ `exe` を追加。`cmdline` は秘密が入りうるので出さない） |
| `--all` のユニット一覧は実在ユニットだけ | 「参照されているが未インストール」も含む → テストの想定外エラー判定が誤り（テスト側のバグ） |
| 環境変数で設定を一時上書きできる | `server.env` を `source` する実装だと**ファイルが勝つ**（→ 環境変数優先に修正） |
| 異常系テストは「エラーが返れば PASS」で十分 | 別の理由で偶然失敗していても通る → 実際のメッセージを見て「意図した層・意図した理由」で弾かれているか確認した |
| テストが通れば保護は効いている | **保護を外した改変版で FAIL するか**を確認して初めて判別力が分かる。弱いアサーション（S3）が1つ見つかった |

## 6. 覚えておく用語・落とし穴

- **DNS リバインド保護 / Host allowlist**: 既定で localhost 以外の Host を拒否。外へ開くと全リクエストが `421 Misdirected Request`（→ [`10-remote-host.md`](10-remote-host.md)）
- **single-flight**: 同じ計測が実行中なら、後続は待って結果を共有する。TTL キャッシュは「時間方向」、single-flight は「同時方向」の重複排除
- **バックプレッシャの明示**: 溢れた要求は無限に待たせず、モデルが読めるエラーで断る
- **`local` scope**: 登録時のディレクトリに紐づく。別ディレクトリで `claude` を起動すると見えない
- **deferred tools**: MCP ツールの定義は最初から全部渡されず、`ToolSearch` で引かれることがある
- ログ本文は外部入力＝**プロンプトインジェクションの経路**になりうる

## 7. 次に読むもの

- 認証を付ける: https://py.sdk.modelcontextprotocol.io/run/authorization/
- デプロイ・複数ワーカー・リバースプロキシ: https://py.sdk.modelcontextprotocol.io/run/deploy/
- 旧プロトコルのクライアントを扱う: https://py.sdk.modelcontextprotocol.io/run/legacy-clients/
- SDK のトラブルシューティング: https://py.sdk.modelcontextprotocol.io/troubleshooting/
- MCP 仕様: https://modelcontextprotocol.io/specification/2026-07-28
