# 02. 別マシンへ広げる場合の差分

既定は「同一ホスト内（`127.0.0.1`）」。別のマシンから繋ぐときに変わるのは次の3点だけ。

| | 変更 |
|---|---|
| サーバ | `MCP_HOST=0.0.0.0`（外から届く）と **`MCP_ALLOWED_HOSTS=<サーバのIP>`** |
| クライアント | `MCP_SERVER_URL=http://<サーバのIP>:8848/mcp` |
| 注意 | **認証が無い**。信頼できる LAN 内に限る |

## 手順

サーバ側（`server/config/server.env`）:

```
MCP_HOST=0.0.0.0
MCP_ALLOWED_HOSTS=172.23.142.25        # ← サーバの IP（クライアントが URL に書くホスト部と同じもの）
```

```bash
make restart   # run/server.log に「WARNING listening on 0.0.0.0 (not localhost) with NO authentication」が出る
```

クライアント側:

```bash
MCP_SERVER_URL=http://172.23.142.25:8848/mcp make check    # まず到達性
# endpoint.env の MCP_SERVER_URL を書き換えて  make reset
```

## 最大の落とし穴: `421 Misdirected Request`

SDK は既定で **DNS リバインド保護**（Host ヘッダの allowlist）を有効にしており、localhost 以外の Host は**全リクエストを拒否**する。
`MCP_HOST=0.0.0.0` にしただけで `MCP_ALLOWED_HOSTS` を設定しないと、TCP は繋がるのに MCP だけが全滅する。

### 再現と解消の実測記録

> **注**: 検証は同一ホスト上で、WSL の `eth0` の IP（`172.23.142.25`）宛に行った。**物理的に別のマシンからの接続は未検証**。
> ただし Host ヘッダは URL のホスト部そのものなので、allowlist の挙動は同じ。

**A. `MCP_HOST=0.0.0.0`・`MCP_ALLOWED_HOSTS` 未設定**

```
target: http://172.23.142.25:8860/mcp  (host=172.23.142.25 port=8860)
1. TCP  connect ...... OK
2. HTTP response ..... FAIL (421 Misdirected Request)
   -> サーバの Host ヘッダ allowlist に、この接続先が入っていません。サーバ側の MCP_ALLOWED_HOSTS に '172.23.142.25' を追加。
```

サーバのログ（**理由はここにしか出ない**。クライアントには汎用エラーしか届かない）:

```
WARNING  Invalid Host header: ...
INFO:    172.23.142.25:35954 - "POST /mcp HTTP/1.1" 421 Misdirected Request
```

**B. `MCP_ALLOWED_HOSTS=172.23.142.25` を設定**

```
2. HTTP response ..... OK (HTTP 200)
3. MCP tools/list .... OK
   tools: disk_usage,journal_recent,...
```

### allowlist の書き方

`MCP_ALLOWED_HOSTS` はカンマ区切り。各要素は自動で **ポート無し / ポート有り（`:*`）の両方**に展開される
（`172.23.142.25` → `172.23.142.25` と `172.23.142.25:*`）。`127.0.0.1` / `localhost` / `[::1]` は常に許可される。
ホスト名で繋ぐなら、URL に書くホスト名そのものを入れる（IP で繋ぐなら IP）。

## WSL2 の注意

- WSL2 の IP は**再起動で変わる**。変わったら `MCP_ALLOWED_HOSTS` とクライアントの URL を更新する（`hostname -I` で確認）
- WSL2 は既定で NAT。**別 PC や Windows ホストから WSL へ届かせるには追加のネットワーク設定（ポート転送・ファイアウォール）が要る**。本トライアルでは扱っておらず、未検証
- このため、Windows を挟まず Linux ↔ Linux に単純化した（[`../../docs/00-architecture.md` §9](../../docs/00-architecture.md)）

## 認証について

認証が無いので、`0.0.0.0` で待ち受けると**届く範囲の誰でも**読み取りツール（`auth` ログ等を含む）を呼べる。
公開するなら SDK の認可（https://py.sdk.modelcontextprotocol.io/run/authorization/ ）を先に導入すること。
