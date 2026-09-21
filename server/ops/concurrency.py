"""並行リクエスト対策。

Claude Code は1ターン内で複数のツールを並列に呼ぶため、クライアントが1つでも
ハンドラは同時に走る。ここで扱うのは次の2種類の競合だけである。

  B. 重複作業  同じ計測が同時に N 本走る        -> Coalescer (TTL + single-flight)
  C. 資源競合  外部コマンドが無制限に走る        -> command_slot (セマフォ + 明示的な拒否)

全ツールが read-only なので、書き込み競合は存在しない。
ハンドラは SDK が anyio.to_thread.run_sync でワーカースレッドに載せるため、
ここのプリミティブは threading ベースで書く（asyncio ではない）。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from contextlib import contextmanager
from typing import Any, Callable, Generator, Hashable

from mcp.server.mcpserver.exceptions import ToolError

log = logging.getLogger("ops.concurrency")

# --- TTL -------------------------------------------------------------------
# 「時間方向」の重複排除。値は計測の性質に合わせる。
# MCP_CACHE_TTL_SCALE で一括スケールできる（0 でキャッシュ無効。single-flight は残る）。
_SCALE = float(os.environ.get("MCP_CACHE_TTL_SCALE", "1.0"))
TTL_FAST = 2.0 * _SCALE  # resource_usage / top_processes
TTL_NORMAL = 10.0 * _SCALE  # system_overview / disk_usage / listening_ports / service_status
TTL_LOG = 3.0 * _SCALE  # tail_log / journal_recent

# 先行実行の完了を待つ上限。これを超えたら待機側だけが諦める。
FLIGHT_WAIT_SECONDS = 30.0
# 外部コマンドのスロットを待つ上限と、同時実行数。
SLOT_WAIT_SECONDS = 3.0
MAX_CONCURRENT_COMMANDS = 4
# キャッシュエントリ数の上限（引数はクライアント由来なので無制限に増やさない）。
MAX_CACHE_ENTRIES = 256

BUSY_MESSAGE = "サーバが混雑しています。少し待って再実行してください。"


class _Flight:
    """1つの実行中の計測。後続の呼び出しはこれを待って結果を共有する。"""

    __slots__ = ("event", "value", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: Any = None
        self.error: ToolError | None = None


class Coalescer:
    """TTL キャッシュ + single-flight。

    TTL キャッシュだけでは、期限切れの瞬間に N 本が一斉に実測へ走る（cache stampede）。
    single-flight は「同じキーの実行中は先頭の1本だけが計算し、後続は待って結果を共有」する。
    前者は時間方向、後者は同時方向の重複排除で、役割が違うので両方置く。

    返り値は呼び出し間で共有される。呼び出し側は変更してはならない。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[Hashable, tuple[float, Any]] = {}
        self._inflight: dict[Hashable, _Flight] = {}
        self._stats: Counter[str] = Counter()

    def call(self, key: tuple, ttl: float, fn: Callable[[], Any]) -> Any:
        """key[0] はツール名（統計の集計単位）。fn は先頭の1本だけが実行する。"""
        tool = str(key[0])
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] > time.monotonic():
                self._stats[f"{tool}.cache_hit"] += 1
                return hit[1]
            flight = self._inflight.get(key)
            leader = flight is None
            if leader:
                flight = self._inflight[key] = _Flight()
                self._stats[f"{tool}.computed"] += 1
            else:
                self._stats[f"{tool}.coalesced"] += 1
        assert flight is not None

        if not leader:
            if not flight.event.wait(FLIGHT_WAIT_SECONDS):
                raise ToolError("先行する計測が完了しませんでした。少し待って再実行してください。")
            if flight.error is not None:
                raise ToolError(str(flight.error))
            return flight.value

        try:
            flight.value = fn()
            with self._lock:
                self._store(key, flight.value, ttl)
        except ToolError as e:
            flight.error = e  # 想定内の失敗。キャッシュしない
            raise
        except Exception:
            # 想定外。詳細はサーバログだけに残し、クライアントには一般化して返す。
            log.exception("unexpected error in %s", tool)
            flight.error = ToolError("内部エラーが発生しました。サーバログを確認してください。")
            raise flight.error from None
        finally:
            # キャッシュ格納 -> inflight 解除 の順。逆だと「どちらにも無い」隙間ができる。
            with self._lock:
                self._inflight.pop(key, None)
            flight.event.set()
        return flight.value

    def _store(self, key: Hashable, value: Any, ttl: float) -> None:
        now = time.monotonic()
        self._cache[key] = (now + ttl, value)
        if len(self._cache) > MAX_CACHE_ENTRIES:
            for k in [k for k, (exp, _) in self._cache.items() if exp <= now]:
                del self._cache[k]
            while len(self._cache) > MAX_CACHE_ENTRIES:
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest]

    def note(self, name: str) -> None:
        with self._lock:
            self._stats[name] += 1

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._stats.items()))

    def reset_stats(self) -> None:
        with self._lock:
            self._stats.clear()


cache = Coalescer()

_slots = threading.BoundedSemaphore(MAX_CONCURRENT_COMMANDS)


@contextmanager
def command_slot() -> Generator[None, None, None]:
    """外部コマンドの同時実行数を絞る。

    溢れたら無限に待たせず ToolError で返す。キューに積むとクライアントは
    タイムアウトするだけで原因が分からないが、エラーで返せばモデルが読んで自分で再試行できる。
    """
    if not _slots.acquire(timeout=SLOT_WAIT_SECONDS):
        cache.note("command.busy_rejected")
        raise ToolError(BUSY_MESSAGE)
    try:
        cache.note("command.launched")
        yield
    finally:
        _slots.release()
