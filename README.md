# poc_mcp — MCP トライアル

MCP（Model Context Protocol）を実地で理解するためのトライアル。
このホスト（WSL2 / Ubuntu）で **MCP サーバを1つ立て**、**別ターミナルの Claude Code から HTTP で接続**する。

- **題材**: サーバ運用ツール（CPU・メモリ・ディスク・プロセス・ポート・systemd・ログ）。**全て読み取り専用**
- **トランスポート**: Streamable HTTP（`http://127.0.0.1:8848/mcp`）
- **道具**: 依存管理と実行は **uv**、操作の入口は **make**

## サーバ側とクライアント側は完全に分かれている

**ルートに Makefile は無い。操作は必ず `server/` か `client/` のディレクトリに入って行う。**
入ったディレクトリで、どちら側の操作かが決まる（`make help` の先頭にも `[SERVER 側]` / `[CLIENT 側]` と表示される）。

| | **サーバ側** `server/` | **クライアント側** `client/` |
|---|---|---|
| 役割 | 何を公開し、どう動かすか | どこに繋ぎ、どう Claude に登録するか |
| 動かす端末 | ターミナル A | ターミナル B |
| 操作 | `cd server && make …` | `cd client && make …` |
| 要るもの | `uv`・`make`・Python ≥ 3.10 | `claude`・`curl`・`make`（**Python 不要**） |
| 中身 | `server.py` `ops/` `config/` `scripts/` `docs/` `Makefile` | `config/` `scripts/` `docs/` `Makefile` |
| 互いへの依存 | **なし**（`client/` を参照しない） | **なし**（`server/` を参照しない） |

両側にまたがる資料だけが共有の `docs/` にある（全体図・別マシンへ広げる手順・MCP 学習メモ）。

```
   ターミナル B（クライアント側）           ターミナル A（サーバ側）
   cd client                               cd server
┌──────────────────┐  HTTP POST /mcp  ┌────────────────────────┐
│ Claude Code      │ ───────────────▶ │ ops-mcp (server.py)    │ ─▶ psutil / systemctl /
│  = MCP クライアント│ ◀─────────────── │ uvicorn 127.0.0.1:8848 │    journalctl / /var/log
└──────────────────┘                  └────────────────────────┘
```

詳細な図（配置・シーケンス・サーバ内部・stdio との対比）は [`docs/00-architecture.md`](docs/00-architecture.md)。

## クイックスタート

**前提**: `uv`（[導入手順](server/docs/01-setup.md)。PATH に無ければ `UV=/path/to/uv make …`）・`make`・`claude`・`curl`

### ① ターミナル A — サーバ側（`server/`）

```bash
cd server
make up          # uv で依存を導入し、バックグラウンド起動（= make setup + make start）
make smoke       # MCP プロトコル疎通テスト（24項目）
make load        # 並行リクエストの競合テスト（22項目）
```

### ② ターミナル B — クライアント側（`client/`）

```bash
cd client
make config      # config/endpoint.env を作る（接続先を確認）
make check       # Claude 抜きの到達性チェック（TCP → HTTP → MCP tools/list）
make add         # claude mcp add で登録
claude           # ★ 新しいセッションを起動 → /mcp で ops-mcp が connected
                 #   「メモリ使用状況と CPU の重いプロセスを調べて」と話しかける
```

### ③ 後片付け（端末ごとに実行）

```bash
# ターミナル B（client/）: Claude の登録を解除
make remove
# ターミナル A（server/）: サーバ停止
make down
```

## ディレクトリ

```
poc_mcp/
├── README.md                 このファイル（Makefile は置かない）
├── docs/                     共有: 00-architecture.md（全体図）/ 10-remote-host.md / 90-mcp-notes.md
├── server/                   【サーバ側】自己完結
│   ├── Makefile  README.md  pyproject.toml  uv.lock
│   ├── server.py  ops/       MCPServer 定義 / collectors・concurrency
│   ├── config/  scripts/  docs/
└── client/                   【クライアント側】自己完結（Python 不要）
    ├── Makefile  README.md
    └── config/  scripts/  docs/
```

## ドキュメント

| 側 | 読む順 | |
|---|---|---|
| 共有 | [`docs/00-architecture.md`](docs/00-architecture.md) | **全体仕様の図**・公開インターフェース・信頼境界・設計判断 |
| サーバ | [`server/README.md`](server/README.md) | 起動・ファイル構成 → [セットアップ](server/docs/01-setup.md) / [ツール仕様](server/docs/02-tools-spec.md) / [運用](server/docs/03-operations.md) / [**並行リクエストの競合と対処**](server/docs/04-concurrency.md) / [トラブルシューティング](server/docs/05-troubleshooting.md) |
| クライアント | [`client/README.md`](client/README.md) | 接続手順・scope → [接続手順](client/docs/01-connect.md) / [トラブルシューティング](client/docs/02-troubleshooting.md) |
| 共有 | [`docs/10-remote-host.md`](docs/10-remote-host.md) | 別マシンへ広げる（**【サーバ側】と【クライアント側】の両方の手順**、`421` の再現と対処） |
| 共有 | [`docs/90-mcp-notes.md`](docs/90-mcp-notes.md) | このトライアルで分かったこと（**予想が外れた点**を含む） |

## 検証状況（この環境で実際に確認したこと）

| 項目 | 結果 |
|---|---|
| サーバ側 `make smoke`（正常系9ツール・入力検証の異常系8件・resources/prompts） | **24/24 通過**。異常系は「意図した層・意図した理由」で弾かれていることをメッセージで確認 |
| サーバ側 `make load`（20並列・40並列） | **22/22 通過**。`journalctl` の起動は20リクエスト中**1回**、遅い呼び出し 3.0s 中も軽い呼び出しは **0.03s** |
| テストの判別力 | 重複排除を無効化した改変サーバで **S1・S2・S3 が FAIL**（`journalctl` 起動 1→20 回）。弱いアサーション1件を発見して修正 |
| クライアント側 `make check` | 正常系と、失敗系（ポート違い→TCP FAIL / パス違い→404 / 偽 Host→421）の診断を確認 |
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
