# poc_mcp — MCP トライアル

MCP（Model Context Protocol）を実地で理解するためのトライアル。
このホスト（WSL2 / Ubuntu）で **MCP サーバを1つ立て**、**別ターミナルの Claude Code から HTTP で接続**する。

- **題材**: サーバ運用ツール（CPU・メモリ・ディスク・プロセス・ポート・systemd・ログ）。**全て読み取り専用**
- **構成**: サーバ（`server/`）とクライアント（`client/`）を**ディレクトリごと分離**。それぞれ設定・スクリプト・ドキュメントで自己完結
- **トランスポート**: Streamable HTTP（`http://127.0.0.1:8848/mcp`）
- **道具**: 依存管理と実行は **uv**、操作の入口は **make**

```
   ターミナル B                         ターミナル A
┌──────────────────┐  HTTP POST /mcp  ┌────────────────────────┐
│ Claude Code      │ ───────────────▶ │ ops-mcp (server.py)    │ ─▶ psutil / systemctl /
│  = MCP クライアント│ ◀─────────────── │ uvicorn 127.0.0.1:8848 │    journalctl / /var/log
└──────────────────┘                  └────────────────────────┘
   client/                               server/
```

詳細な図（配置・シーケンス・サーバ内部・stdio との対比）は [`docs/00-architecture.md`](docs/00-architecture.md)。

## クイックスタート

**前提**: `uv`・`make`・`claude`・`curl`（uv の導入は [`server/docs/01-setup.md`](server/docs/01-setup.md)。uv が PATH に無ければ `UV=/path/to/uv make …`）

```bash
# --- ターミナル A: サーバ ---
make up                 # uv で依存を導入し、バックグラウンド起動
make server-smoke       # MCP プロトコル疎通テスト（24項目）
make server-load        # 並行リクエストの競合テスト（22項目）

# --- ターミナル B: クライアント ---
make client-config      # client/config/endpoint.env を作る
make client-check       # Claude 抜きの到達性チェック（TCP → HTTP → MCP tools/list）
make client-add         # claude mcp add で登録
cd client && claude     # ★ 新しいセッションを起動 → /mcp で ops-mcp が connected
                        #   「メモリ使用状況と CPU の重いプロセスを調べて」と話しかける

# --- 後片付け ---
make client-remove      # Claude の登録を解除
make down               # サーバ停止
```

`make help`（トップ）/ `make -C server help` / `make -C client help` でターゲット一覧。

## ディレクトリ

```
poc_mcp/
├── Makefile, README.md
├── docs/                    共通: 全体アーキテクチャ（図）、MCP 学習メモ
├── server/                  サーバ側（何を公開し、どう動かすか）
│   ├── server.py  ops/      MCPServer 定義 / collectors（OS から集める）・concurrency（並行制御）
│   ├── config/  scripts/  docs/  Makefile  pyproject.toml  uv.lock
└── client/                  クライアント側（どこに繋ぎ、どう登録するか）※Python 不要
    └── config/  scripts/  docs/  Makefile
```

## ドキュメント

| 読む順 | | |
|---|---|---|
| 1 | [`docs/00-architecture.md`](docs/00-architecture.md) | **全体仕様の図**・公開インターフェース・信頼境界・設計判断 |
| 2 | [`server/README.md`](server/README.md) | サーバの起動・ファイル構成 → `server/docs/01〜04` |
| 3 | [`client/README.md`](client/README.md) | 接続手順・scope → `client/docs/01〜03` |
| 4 | [`docs/90-mcp-notes.md`](docs/90-mcp-notes.md) | このトライアルで分かったこと（**予想が外れた点**を含む） |

サーバ側: [セットアップ](server/docs/01-setup.md) / [ツール仕様](server/docs/02-tools-spec.md) / [運用](server/docs/03-operations.md) / [**並行リクエストの競合と対処**](server/docs/04-concurrency.md)
クライアント側: [接続手順](client/docs/01-connect.md) / [別マシンへ広げる](client/docs/02-remote-host.md) / [トラブルシューティング](client/docs/03-troubleshooting.md)

## 検証状況（この環境で実際に確認したこと）

| 項目 | 結果 |
|---|---|
| `make server-smoke`（正常系9ツール・入力検証の異常系8件・resources/prompts） | **24/24 通過**。異常系は「意図した層・意図した理由」で弾かれていることをメッセージで確認 |
| `make server-load`（20並列・40並列） | **22/22 通過**。`journalctl` の起動は20リクエスト中**1回**、遅い呼び出し 3.0s 中も軽い呼び出しは **0.03s** |
| テストの判別力 | 重複排除を無効化した改変サーバで **S1・S2・S3 が FAIL**（`journalctl` 起動 1→20 回）。弱いアサーション1件を発見して修正 |
| `make client-check` | 正常系と、失敗系（ポート違い→TCP FAIL / パス違い→404 / 偽 Host→421）の診断を確認 |
| **421 の再現と解消** | `MCP_HOST=0.0.0.0` で allowlist 未設定 → 421（理由はサーバログのみ）→ `MCP_ALLOWED_HOSTS` で 200 |
| **Claude Code からの接続** | `claude mcp list` で `ops-mcp ✔ Connected`。`claude -p` で実際に `resource_usage` / `top_processes` を呼び、実データで回答 |
| `serverctl.sh` の安全動作 | 重複起動・ポート占有・起動失敗・**古い PID ファイルで無関係なプロセスを kill しない**、を確認 |

### 未検証・既知の限界

- **Claude Code の対話 UI**での `/mcp` 表示、prompts（スラッシュコマンド）・resources（`@` 参照）の呼び出し（サーバ側の `prompts/get`・`resources/read` は検証済み）
- **物理的に別のマシン**・Windows ホストからの接続（同一ホスト内で WSL の IP 宛には検証。WSL2 は NAT のため別途ネットワーク設定が要る）
- Claude が複数ツールを**並列**に呼ぶ場面（実測した1回は逐次。並列でも同じ対策が効く設計）
- `docs/00-architecture.md` の Mermaid 図の描画（構文は標準的なものだが、この環境では描画確認していない）
- 認証・レート制限・複数ワーカー（→ [`server/docs/04-concurrency.md`](server/docs/04-concurrency.md) の既知の限界）

## 注意

- **認証なし**。既定の待受は `127.0.0.1`（同一ホストのみ）。`0.0.0.0` で外に開くと、届く範囲の誰でも読み取りツールを呼べる。
- 全ツール read-only だが、**`auth` ログなど機微な情報を返しうる**。ログ本文は外部入力を含み、プロンプトインジェクションの経路になりうる（[`docs/00-architecture.md` §8](docs/00-architecture.md)）。
