"""MCP プロトコル疎通テスト（Claude 不要）。実際に HTTP でサーバへ繋いで確認する。

  uv run python scripts/smoke_test.py [--url http://127.0.0.1:8848/mcp]

確認すること:
  1. 接続できる / 9 ツールが read_only_hint 付きで公開されている
  2. 各ツールが実データを返す（structured_content つき）
  3. 不正な入力が拒否される（コマンド・パス注入の遮断）
  4. resources / prompts が読める
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from mcp import Client

EXPECTED_TOOLS = {
    "system_overview", "resource_usage", "disk_usage", "top_processes", "listening_ports",
    "service_status", "tail_log", "journal_recent", "server_stats",
}

passed = failed = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global passed, failed
    passed, failed = passed + ok, failed + (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))


def text_of(result: Any) -> str:
    return " ".join(getattr(b, "text", "") for b in result.content)


async def call(client: Client, name: str, args: dict[str, Any] | None = None) -> tuple[Any, str | None]:
    """(結果, エラー文言)。プロトコル例外とツールエラーの両方を「エラー文言」に寄せる。"""
    try:
        result = await client.call_tool(name, args or {})
    except Exception as e:  # noqa: BLE001  入力検証エラーは例外で届くことがある
        return None, f"{type(e).__name__}: {e}"
    return result, (text_of(result) if result.is_error else None)


async def run(url: str) -> None:
    async with Client(url) as client:
        print(f"connected: {url}")
        print(f"  server_info={client.server_info.name!r} protocol={client.protocol_version}")

        print("tools/list")
        tools = (await client.list_tools()).tools
        names = {t.name for t in tools}
        check(names == EXPECTED_TOOLS, f"{len(tools)} tools", f"diff={sorted(names ^ EXPECTED_TOOLS)}" if names != EXPECTED_TOOLS else "")
        check(all(t.annotations and t.annotations.read_only_hint for t in tools), "all tools have read_only_hint=true")

        print("tools/call (正常系)")
        cases: list[tuple[str, dict[str, Any], Any]] = [
            ("system_overview", {}, lambda r: r["hostname"] and r["uptime_seconds"] > 0),
            ("resource_usage", {"interval": 0.3}, lambda r: 0 <= r["cpu"]["percent"] <= 100 and r["memory"]["total_mb"] > 0),
            ("disk_usage", {"path": "/"}, lambda r: r["total_mb"] > 0 and isinstance(r["mounts"], list)),
            ("top_processes", {"sort_by": "memory", "limit": 5}, lambda r: 1 <= len(r["result"]) <= 5),
            ("listening_ports", {}, lambda r: isinstance(r["result"], list)),
            ("service_status", {"name": "cron"}, lambda r: r["load_state"] == "loaded"),
            ("tail_log", {"name": "syslog", "lines": 5}, lambda r: r["lines_returned"] <= 5),
            ("journal_recent", {"lines": 5}, lambda r: 0 < r["count"] <= 5),
            ("server_stats", {}, lambda r: "command.launched" in r),
        ]
        for name, args, ok in cases:
            result, err = await call(client, name, args)
            data = result.structured_content if result is not None else None
            try:
                good = err is None and data is not None and bool(ok(data))
            except (KeyError, TypeError) as e:
                good, err = False, f"unexpected shape: {e!r}"
            check(good, f"{name}({args})", err or "")

        result, err = await call(client, "journal_recent", {"lines": 500})
        msgs = [e["message"] for e in (result.structured_content["entries"] if result is not None else [])]
        check(err is None and bool(msgs) and not any("\x1b" in m for m in msgs), "journal_recent の本文に ANSI エスケープが残っていない", f"{len(msgs)} 件を検査")

        print("tools/call (異常系: 入力検証)")
        rejects = [
            ("service_status", {"name": "--help"}, "先頭が - のユニット名（オプション注入）"),
            ("service_status", {"name": "cron; id"}, "シェルメタ文字"),
            ("service_status", {"name": "no-such-unit-xyz"}, "存在しないユニット"),
            ("journal_recent", {"unit": "-p"}, "journalctl のオプション注入"),
            ("tail_log", {"name": "../etc/shadow"}, "パストラバーサル（許可リスト外）"),
            ("tail_log", {"name": "syslog", "lines": 100000}, "範囲外の lines"),
            ("resource_usage", {"interval": 999}, "範囲外の interval"),
            ("disk_usage", {"path": "relative/path"}, "相対パス"),
        ]
        for name, args, why in rejects:
            _, err = await call(client, name, args)
            check(err is not None, f"{name}({args}) は拒否される", why if err is not None else f"{why} なのに通ってしまった")

        print("resources / prompts")
        res = await client.read_resource("ops://host")
        check("hostname" in res.contents[0].text, "resources/read ops://host")
        res = await client.read_resource("ops://logs")
        check("syslog" in res.contents[0].text, "resources/read ops://logs")
        res = await client.read_resource("ops://logs/syslog")
        check(bool(res.contents[0].text), "resources/read ops://logs/syslog (テンプレート)")
        prompt = await client.get_prompt("health_check")
        check(len(prompt.messages) == 1, "prompts/get health_check")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8848/mcp"))
    args = ap.parse_args()
    try:
        asyncio.run(run(args.url))
    except Exception as e:  # noqa: BLE001
        print(f"\nCONNECT/RUN ERROR: {type(e).__name__}: {e}")
        print("  -> サーバは起動していますか? (make start / make status)")
        return 2
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
