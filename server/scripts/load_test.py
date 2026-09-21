"""並行リクエストの競合テスト（Claude 不要）。

  make load      (= uv run python scripts/load_test.py --url ...)

HTTP 越し（サーバは別プロセス。効果はサーバ自身の server_stats の差分で数える）:
  S1 coalescing      同一リクエスト N 並列        -> 計測は1回に畳まれ、値も壊れない
  S2 command dedupe  同一 journal_recent N 並列   -> 外部コマンドの起動は1回
  S3 arg variants    引数違いの top_processes     -> スナップショットは1回
  S4 fan-out         別々のユニット名 N 並列      -> 全部が成功か「混雑」で終わり、ハングしない
  S5 non-blocking    遅いツールの実行中でも軽いツールが待たされない（スレッド実行が効いている）
プロセス内（プリミティブ単体。実サーバでは再現しづらい経路を決定的に検証）:
  S6 backpressure    同時実行上限を超えたら待たせず「混雑」で断る
  S7 error path      先行実行の失敗は待機側に伝わり、キャッシュされない。想定外の例外は漏らさない
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import subprocess
import sys
import threading
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # ops を import するため

from mcp import Client  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from ops import concurrency as cc  # noqa: E402
from ops.collectors import UNIT_RE  # noqa: E402

passed = failed = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global passed, failed
    passed, failed = passed + bool(ok), failed + (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))


async def timed(c: Client, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        r = await c.call_tool(name, args or {})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": f"{type(e).__name__}: {e}", "data": None, "t": time.monotonic() - t0}
    err = " ".join(getattr(b, "text", "") for b in r.content) if r.is_error else None
    return {"ok": not r.is_error, "err": err, "data": r.structured_content, "t": time.monotonic() - t0}


async def server_stats(c: Client) -> dict[str, int]:
    return (await c.call_tool("server_stats")).structured_content


def delta(before: dict[str, int], after: dict[str, int], prefix: str) -> dict[str, int]:
    out = {k: after.get(k, 0) - before.get(k, 0) for k in after if k.startswith(prefix)}
    return {k[len(prefix):]: v for k, v in out.items() if v}


# --- HTTP 越し --------------------------------------------------------------


async def http_scenarios(url: str, n: int) -> None:
    async with AsyncExitStack() as stack:
        ctl = await stack.enter_async_context(Client(url))
        # 複数ターミナルからの同時接続を模して、リクエストごとに別のクライアントを使う
        clients = [await stack.enter_async_context(Client(url)) for _ in range(n)]
        print(f"connected {n} clients + 1 control client")

        print(f"S1 coalescing: resource_usage x{n} (同一引数)")
        interval = random.choice([0.6, 0.7, 0.8, 0.9, 1.1, 1.2, 1.3, 1.4])
        before = await server_stats(ctl)
        t0 = time.monotonic()
        rs = await asyncio.gather(*[timed(c, "resource_usage", {"interval": interval}) for c in clients])
        elapsed = time.monotonic() - t0
        d = delta(before, await server_stats(ctl), "resource_usage.")
        pct = [r["data"]["cpu"]["percent"] for r in rs if r["ok"]]
        check(len(pct) == n, f"{n}/{n} 成功", "; ".join({r["err"] for r in rs if not r["ok"]}))
        check(bool(pct) and all(0 <= p <= 100 for p in pct), "全応答の CPU% が 0..100", f"min={min(pct, default=None)} max={max(pct, default=None)}")
        check(d.get("computed", 0) <= 1 and sum(d.values()) == n, "計測は高々1回で残りは相乗り/キャッシュ", str(d))
        check(elapsed < interval * 3, f"所要 {elapsed:.2f}s ≒ 計測1回分 ({interval}s)。{n}回分 ({n * interval:.0f}s) ではない")

        print(f"S2 command dedupe: journal_recent x{n} (同一引数)")
        lines = random.randint(51, 499)  # 未使用のキーなのでキャッシュは必ず冷えている
        before = await server_stats(ctl)
        rs = await asyncio.gather(*[timed(c, "journal_recent", {"lines": lines}) for c in clients])
        after = await server_stats(ctl)
        launched = after.get("command.launched", 0) - before.get("command.launched", 0)
        d = delta(before, after, "journal_recent.")
        check(all(r["ok"] for r in rs), f"{n}/{n} 成功", "; ".join({r["err"] for r in rs if not r["ok"]}))
        check(launched == 1, f"journalctl の起動は {launched} 回（{n} リクエスト中）", str(d))
        check(len({json.dumps(r["data"], sort_keys=True) for r in rs}) == 1, "全員が同一の結果を受け取った")

        print(f"S3 arg variants: top_processes x{n} (sort_by/limit 違い)")
        variants = [("cpu", 5), ("memory", 10), ("cpu", 50), ("memory", 1)]
        before = await server_stats(ctl)
        rs = await asyncio.gather(*[timed(c, "top_processes", {"sort_by": v[0], "limit": v[1]}) for c, v in zip(clients, variants * n)])
        d = delta(before, await server_stats(ctl), "top_processes.")
        check(all(r["ok"] for r in rs), f"{n}/{n} 成功", "; ".join({r["err"] for r in rs if not r["ok"]}))
        check(d.get("computed", 0) <= 1 and sum(d.values()) == n, "引数が違ってもスナップショットは高々1回で、残りは相乗り/キャッシュ", str(d))
        good = True
        for r, (sort_by, limit) in zip(rs, variants * n):
            rows = r["data"]["result"] if r["ok"] else []
            key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
            good &= 0 < len(rows) <= limit and all(a[key] >= b[key] for a, b in zip(rows, rows[1:]))
        check(good, "各応答が要求どおりの並びと件数（共有スナップショットから正しく切り出せている）")

        print(f"S4 fan-out: service_status x{n} (別々のユニット名)")
        out = subprocess.run(["systemctl", "list-units", "--type=service", "--no-legend", "--plain"], capture_output=True, text=True).stdout
        units = list(dict.fromkeys(ln.split()[0] for ln in out.splitlines() if ln.split() and UNIT_RE.fullmatch(ln.split()[0])))[:n]
        before = await server_stats(ctl)
        rs = await asyncio.gather(*[timed(c, "service_status", {"name": u}) for c, u in zip(clients, units)])
        after = await server_stats(ctl)
        busy = sum(1 for r in rs if not r["ok"] and cc.BUSY_MESSAGE in (r["err"] or ""))
        ok = sum(r["ok"] for r in rs)
        other = [r["err"] for r in rs if not r["ok"] and cc.BUSY_MESSAGE not in (r["err"] or "") and "見つかりません" not in (r["err"] or "")]
        launched = after.get("command.launched", 0) - before.get("command.launched", 0)
        rejected = after.get("command.busy_rejected", 0) - before.get("command.busy_rejected", 0)
        hits = delta(before, after, "service_status.").get("cache_hit", 0)
        check(len(units) == len(rs) and not other, f"{len(rs)} 件が成功か「混雑」で完了（成功 {ok} / 混雑 {busy}）。ハングも想定外エラーも無し", "; ".join(map(str, other[:2])))
        # 別キーは畳まれない。各リクエストは「TTL ヒット」「コマンド起動」「混雑で拒否」のどれか1つに必ず分類される。
        check(launched + rejected + hits == len(units), f"会計が合う: 起動 {launched} + 拒否 {rejected} + キャッシュ {hits} = {len(units)} 件")
        healthy = await timed(ctl, "system_overview")
        check(healthy["ok"], "負荷後もサーバは健全に応答する")

        print("S5 non-blocking: 遅いツールの実行中に軽いツールを呼ぶ")
        slow = asyncio.create_task(timed(clients[0], "resource_usage", {"interval": 3.0}))
        await asyncio.sleep(0.3)  # 遅い方が worker スレッドを掴んだ状態にする
        paths = ["/", "/tmp", "/var", "/usr", "/home", "/etc", "/opt"]
        lights = await asyncio.gather(*[timed(c, "disk_usage", {"path": p}) for c, p in zip(clients[1:], paths)])
        still_running = not slow.done()
        slow_r = await slow
        worst = max(r["t"] for r in lights)
        check(all(r["ok"] for r in lights), "軽いツールは全て成功", "; ".join({r["err"] for r in lights if not r["ok"]}))
        check(still_running, "軽い呼び出しが返った時点で、遅い呼び出し (3s) はまだ実行中")
        check(worst < 1.0, f"軽い呼び出しの最悪レイテンシ {worst:.2f}s < 1.0s（同期ハンドラのスレッド実行が効いている）", f"slow={slow_r['t']:.2f}s")


# --- プロセス内（プリミティブ単体） -----------------------------------------


def unit_scenarios() -> None:
    print("S6 backpressure: command_slot (プロセス内)")
    old, cc.SLOT_WAIT_SECONDS = cc.SLOT_WAIT_SECONDS, 0.3
    try:
        extra, results, lock = 6, [], threading.Lock()

        def worker() -> None:
            try:
                with cc.command_slot():
                    time.sleep(1.0)
                    r = "ok"
            except ToolError as e:
                r = "busy" if str(e) == cc.BUSY_MESSAGE else f"other:{e}"
            with lock:
                results.append(r)

        ts = [threading.Thread(target=worker) for _ in range(cc.MAX_CONCURRENT_COMMANDS + extra)]
        t0 = time.monotonic()
        [t.start() for t in ts]
        [t.join() for t in ts]
        check(results.count("ok") == cc.MAX_CONCURRENT_COMMANDS, f"同時に通るのは上限の {cc.MAX_CONCURRENT_COMMANDS} 本だけ", str(results.count("ok")))
        check(results.count("busy") == extra, f"溢れた {extra} 本は待たされ続けず『混雑』で断られる", f"{results.count('busy')}本, 全体 {time.monotonic() - t0:.2f}s")
    finally:
        cc.SLOT_WAIT_SECONDS = old

    print("S7 error path: Coalescer (プロセス内)")
    co, calls, outs, lock = cc.Coalescer(), [], [], threading.Lock()

    def boom() -> None:
        calls.append(1)
        time.sleep(0.3)
        raise ToolError("boom")

    def waiter() -> None:
        try:
            co.call(("t",), 10.0, boom)
            r = "value"
        except ToolError as e:
            r = str(e)
        with lock:
            outs.append(r)

    ts = [threading.Thread(target=waiter) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check(len(calls) == 1 and outs.count("boom") == 10, "10 並列で実行は1回。失敗は待機側 9 本にも伝わる", f"calls={len(calls)} outs={set(outs)}")
    calls.clear()
    check(co.call(("t",), 10.0, lambda: (calls.append(1), 42)[1]) == 42 and len(calls) == 1, "失敗はキャッシュされず、次の呼び出しは再計算される")

    def bug() -> None:
        raise KeyError("secret-internal-detail")

    class Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    cap, lg = Capture(), logging.getLogger("ops.concurrency")
    lg.addHandler(cap)
    lg.propagate = False  # 意図的な例外のトレースバックを出力に混ぜない
    try:
        try:
            co.call(("t2",), 10.0, bug)
            leaked = True
        except ToolError as e:
            leaked = "secret" in str(e)
    finally:
        lg.removeHandler(cap)
        lg.propagate = True
    check(not leaked, "想定外の例外の詳細はクライアントに漏れない")
    check(any(r.exc_info and "secret-internal-detail" in str(r.exc_info[1]) for r in cap.records), "詳細はサーバログにだけ残る")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8848/mcp"))
    ap.add_argument("-n", type=int, default=20, help="並列数 (既定 20)")
    args = ap.parse_args()
    try:
        asyncio.run(http_scenarios(args.url, args.n))
    except Exception as e:  # noqa: BLE001
        print(f"\nCONNECT/RUN ERROR: {type(e).__name__}: {e}")
        print("  -> サーバは起動していますか? (make start / make status)")
        return 2
    unit_scenarios()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
