"""ops-mcp: サーバ運用ツールを公開する read-only の MCP サーバ (Streamable HTTP)。

起動:  uv run python server.py     （設定は環境変数。README / config/server.env.example 参照）

全ツールは読み取り専用。ハンドラは意図的に `def`（`async def` ではない）にしている。
SDK が同期ハンドラを anyio.to_thread.run_sync のワーカースレッドで実行するので、
ブロッキング処理があってもイベントループは止まらない。`async def` の中で
subprocess.run() や psutil の blocking サンプリングを呼ぶと、その間ぜんぶのクライアントが止まる。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from ops import collectors as c
from ops.concurrency import TTL_FAST, TTL_LOG, TTL_NORMAL, cache

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

LogName = Literal["syslog", "auth", "kern", "dmesg"]
Priority = Literal["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]
assert set(LogName.__args__) == set(c.LOG_ALLOWLIST), "LogName と LOG_ALLOWLIST がずれている"  # type: ignore[attr-defined]

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

mcp = MCPServer(
    "ops-mcp",
    instructions=(
        "このホストの状態を調べる読み取り専用ツール群。CPU/メモリ/ディスク/プロセス/ポート/"
        "systemd サービス/ログを参照できる。変更や再起動はできない。"
        "「混雑しています」と返ったら少し待って再実行すること。"
    ),
    log_level=os.environ.get("MCP_LOG_LEVEL", "INFO"),  # type: ignore[arg-type]
)


# --- Tools ------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
def system_overview() -> dict[str, Any]:
    """ホスト名・OS・カーネル・起動時刻・uptime・CPU数・ロードアベレージを返す。"""
    return cache.call(("system_overview",), TTL_NORMAL, c.system_overview)


@mcp.tool(annotations=READ_ONLY)
def resource_usage(
    interval: Annotated[float, Field(ge=0.1, le=5.0, description="CPU をサンプリングする秒数")] = 1.0,
) -> dict[str, Any]:
    """CPU（全体とコア別）・メモリ・スワップの使用率を返す。interval 秒かけて CPU を計測する。"""
    return cache.call(("resource_usage", round(interval, 1)), TTL_FAST, lambda: c.resource_usage(interval))


@mcp.tool(annotations=READ_ONLY)
def disk_usage(path: Annotated[str, Field(description="容量を調べる絶対パス")] = "/") -> dict[str, Any]:
    """指定パスのディスク使用量と、全マウントポイントの一覧を返す。"""
    return cache.call(("disk_usage", path), TTL_NORMAL, lambda: c.disk_usage(path))


@mcp.tool(annotations=READ_ONLY)
def top_processes(
    sort_by: Literal["cpu", "memory"] = "cpu",
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
) -> list[dict[str, Any]]:
    """CPU またはメモリ使用量の多いプロセス上位を返す。cpu_percent は 1 コア = 100% で、100 を超えうる。"""
    # 全プロセスのスナップショットを1回だけ採り、並び替えと件数制限はここで行う。
    # 引数違いの並行呼び出しでも計測は1回に畳まれる。
    rows = cache.call(("top_processes",), TTL_FAST, c.process_snapshot)
    key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
    return sorted(rows, key=lambda r: r[key], reverse=True)[:limit]


@mcp.tool(annotations=READ_ONLY)
def listening_ports() -> list[dict[str, Any]]:
    """LISTEN 中の TCP ソケットを返す。他ユーザーのプロセスは pid / process が null になる。"""
    return cache.call(("listening_ports",), TTL_NORMAL, c.listening_ports)


@mcp.tool(annotations=READ_ONLY)
def service_status(name: Annotated[str, Field(description="systemd ユニット名。例: cron, ssh.service")]) -> dict[str, Any]:
    """systemd ユニットの状態（active/sub 状態、enabled、MainPID、起動時刻）を返す。"""
    c.validate_unit(name)  # 不正な入力はキャッシュに触れさせない
    return cache.call(("service_status", name), TTL_NORMAL, lambda: c.service_status(name))


@mcp.tool(annotations=READ_ONLY)
def tail_log(name: LogName, lines: Annotated[int, Field(ge=1, le=1000)] = 50) -> dict[str, Any]:
    """許可された /var/log のログ（syslog, auth, kern, dmesg）の末尾 lines 行を返す。"""
    return cache.call(("tail_log", name, lines), TTL_LOG, lambda: c.read_log_tail(name, lines))


@mcp.tool(annotations=READ_ONLY)
def journal_recent(
    unit: Annotated[str | None, Field(description="絞り込む systemd ユニット名（省略で全体）")] = None,
    priority: Annotated[Priority | None, Field(description="この重大度以上のみ。err なら emerg〜err")] = None,
    lines: Annotated[int, Field(ge=1, le=500)] = 50,
) -> dict[str, Any]:
    """systemd ジャーナルの直近エントリを返す。"""
    if unit is not None:
        c.validate_unit(unit)
    return cache.call(("journal_recent", unit, priority, lines), TTL_LOG, lambda: c.journal_recent(unit, priority, lines))


@mcp.tool(annotations=READ_ONLY)
def server_stats() -> dict[str, int]:
    """このサーバ自身の並行制御の統計。<tool>.computed=実測した回数 / .cache_hit=TTL で返した回数 /
    .coalesced=実行中の計測に相乗りした回数、command.launched=外部コマンドの起動回数、
    command.busy_rejected=混雑で断った回数。"""
    return cache.stats()


# --- Resources --------------------------------------------------------------


@mcp.resource("ops://host", mime_type="application/json")
def host_snapshot() -> str:
    """ホスト情報のスナップショット。"""
    return json.dumps(cache.call(("system_overview",), TTL_NORMAL, c.system_overview), ensure_ascii=False, indent=2)


@mcp.resource("ops://logs", mime_type="application/json")
def log_index() -> str:
    """閲覧できるログの一覧と、読み取り可否。"""
    return json.dumps(c.list_logs(), ensure_ascii=False, indent=2)


@mcp.resource("ops://logs/{name}")
def log_tail(name: str) -> str:
    """許可されたログの末尾100行。"""
    result = cache.call(("tail_log", name, 100), TTL_LOG, lambda: c.read_log_tail(name, 100))
    return "\n".join(result["lines"])


# --- Prompts ----------------------------------------------------------------


@mcp.prompt()
def health_check() -> str:
    """このホストの健康状態を総合的に点検する。"""
    return (
        "ops-mcp のツールでこのホストの健康状態を点検してください。"
        "system_overview / resource_usage / disk_usage / top_processes / listening_ports で状態を集め、"
        "journal_recent（priority=err）で直近のエラーを確認し、"
        "異常や気になる点があれば根拠の数値つきで指摘してください。問題がなければその旨を簡潔に。"
    )


@mcp.prompt()
def investigate_load() -> str:
    """負荷が高い原因を調べる。"""
    return (
        "このホストの負荷が高い原因を調べてください。"
        "system_overview のロードアベレージ、resource_usage の CPU/メモリ、top_processes（cpu と memory の両方）を確認し、"
        "怪しいプロセスがあれば service_status や journal_recent で背景を調べて、原因の仮説と根拠を示してください。"
    )


# --- 起動 -------------------------------------------------------------------


def build_transport_security(host: str) -> TransportSecuritySettings | None:
    """待受が localhost のときは None（SDK 既定の localhost allowlist に任せる）。

    localhost 以外で待つ場合は Host ヘッダの allowlist を明示する。これを忘れると
    全リクエストが 421 Misdirected Request になり、理由はサーバログにしか出ない。
    """
    if host in LOCAL_HOSTS:
        return None
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    for h in (x.strip() for x in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if x.strip()):
        bare = h[:-2] if h.endswith(":*") else h
        hosts += [bare, bare + ":*"]  # Host ヘッダはポート無し/有りの両方がありうる
    return TransportSecuritySettings(allowed_hosts=hosts)


def main() -> None:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8848"))
    security = build_transport_security(host)
    log = logging.getLogger("ops")
    if host not in LOCAL_HOSTS:
        log.warning("listening on %s (not localhost) with NO authentication; allowed hosts: %s", host, security.allowed_hosts if security else None)
    log.info("ops-mcp serving on http://%s:%d/mcp", host, port)
    mcp.run(transport="streamable-http", host=host, port=port, transport_security=security)


if __name__ == "__main__":
    main()
