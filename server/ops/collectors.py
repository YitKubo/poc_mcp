"""OS から情報を集める層。

MCP の型には依存せず、失敗は ToolError で表す（メッセージはそのままモデルに見える）。
全て読み取り専用。外部コマンドは shell を経由せず、引数は配列の1要素として渡す。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

import psutil
from mcp.server.mcpserver.exceptions import ToolError

from .concurrency import command_slot

log = logging.getLogger("ops.collectors")

MIB = 1024 * 1024

# パス文字列を引数で受け取らないための許可リスト。キーだけがクライアントに見える。
LOG_ALLOWLIST: dict[str, str] = {
    "syslog": "/var/log/syslog",
    "auth": "/var/log/auth.log",
    "kern": "/var/log/kern.log",
    "dmesg": "/var/log/dmesg",
}
MAX_TAIL_BYTES = 1024 * 1024
MAX_LINE_CHARS = 2000

# 先頭は英数字のみ。`-` 始まりだと外部コマンドにオプションとして解釈されうる。
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@.:_\-]{0,127}$")
PRIORITIES = ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug")

_CMD_ENV = {**os.environ, "LC_ALL": "C", "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0"}

# ログ本文から除く制御文字。journal には色付きログの ANSI エスケープがそのまま入っており、
# LLM にはノイズにしかならない（改行と TAB は残す）。
_CTRL_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(s: str) -> str:
    return _CTRL_RE.sub("", s)


# --- 外部コマンド ----------------------------------------------------------


def run_command(args: list[str], timeout: float) -> str:
    """shell=False で実行し stdout を返す。失敗は一般化した ToolError にし、詳細はログにだけ残す。"""
    with command_slot():
        try:
            cp = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
                env=_CMD_ENV,
                check=False,
            )
        except subprocess.TimeoutExpired:
            log.warning("timeout after %ss: %s", timeout, args)
            raise ToolError(f"{args[0]} が {timeout:g} 秒でタイムアウトしました。") from None
        except FileNotFoundError:
            raise ToolError(f"{args[0]} が見つかりません。") from None
    if cp.returncode != 0:
        log.warning("command failed rc=%s: %s stderr=%s", cp.returncode, args, cp.stderr.strip()[:500])
        raise ToolError(f"{args[0]} が失敗しました (exit {cp.returncode})。")
    return cp.stdout


def validate_unit(name: str) -> str:
    if not UNIT_RE.fullmatch(name):
        raise ToolError("ユニット名が不正です。英数字で始まり、英数字と @ . : _ - のみ使えます（128文字まで）。")
    return name


# --- システム ---------------------------------------------------------------


def _is_wsl() -> bool:
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def system_overview() -> dict[str, Any]:
    boot = psutil.boot_time()
    try:
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME")
    except OSError:
        os_name = None
    load = os.getloadavg()
    return {
        "hostname": socket.gethostname(),
        "os": os_name or platform.platform(),
        "kernel": platform.release(),
        "is_wsl": _is_wsl(),
        "boot_time": datetime.fromtimestamp(boot, timezone.utc).isoformat(timespec="seconds"),
        "uptime_seconds": int(time.time() - boot),
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "load_average": {"1m": round(load[0], 2), "5m": round(load[1], 2), "15m": round(load[2], 2)},
    }


def resource_usage(interval: float) -> dict[str, Any]:
    # blocking モードの cpu_percent は t1/t2 をローカル変数で持つのでスレッドセーフ
    # （非 blocking は基準値をスレッドID単位で持つ）。interval 秒このスレッドを占有する。
    per_cpu = psutil.cpu_percent(interval=interval, percpu=True)
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "sampled_over_seconds": interval,
        "cpu": {
            "percent": round(sum(per_cpu) / len(per_cpu), 1),
            "per_cpu_percent": per_cpu,
        },
        "memory": {
            "total_mb": vm.total // MIB,
            "used_mb": vm.used // MIB,
            "available_mb": vm.available // MIB,
            "percent": vm.percent,
        },
        "swap": {
            "total_mb": sw.total // MIB,
            "used_mb": sw.used // MIB,
            "percent": sw.percent,
        },
    }


def disk_usage(path: str) -> dict[str, Any]:
    if "\x00" in path or not os.path.isabs(path):
        raise ToolError("path は絶対パスで指定してください。")
    real = os.path.realpath(path)
    try:
        u = psutil.disk_usage(real)
    except FileNotFoundError:
        raise ToolError(f"パスが存在しません: {path}") from None
    except PermissionError:
        raise ToolError(f"パスにアクセスする権限がありません: {path}") from None
    mounts = []
    for part in psutil.disk_partitions(all=False):
        try:
            mu = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue  # 到達できないマウントは省く
        mounts.append(
            {
                "mountpoint": part.mountpoint,
                "device": part.device,
                "fstype": part.fstype,
                "total_mb": mu.total // MIB,
                "used_mb": mu.used // MIB,
                "percent": mu.percent,
            }
        )
    return {
        "path": real,
        "total_mb": u.total // MIB,
        "used_mb": u.used // MIB,
        "free_mb": u.free // MIB,
        "percent": u.percent,
        "mounts": mounts,
    }


def _user_of(p: psutil.Process) -> str | None:
    try:
        return p.username()
    except Exception:  # noqa: BLE001  passwd に無い uid 等
        return None


def _exe_of(p: psutil.Process) -> str | None:
    """実行ファイルのパス。name() は comm なので、ランタイムによっては 'MainThread' のような
    スレッド名になり判別できない。cmdline は引数に秘密が入りうるので出さず、exe だけにする。
    他ユーザーのプロセスは非 root だと取れないので None に縮退する。"""
    try:
        return p.exe() or None
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
        return None


def process_snapshot(sample_seconds: float = 0.5) -> list[dict[str, Any]]:
    """全プロセスの CPU / メモリ。並び替えと件数制限は呼び出し側で行う。

    psutil.process_iter() は Process をモジュールグローバルにキャッシュして使い回す。
    Process.cpu_percent() の基準値はそのインスタンスに載るので、スレッド間で共有すると
    互いの基準値を壊す。呼び出しごとに新しい Process を作って基準値を独立させる。
    プロセスごとの cpu_percent は 1 コア = 100% で、マルチスレッドなら 100 を超えうる。
    """
    procs: list[psutil.Process] = []
    for pid in psutil.pids():
        try:
            p = psutil.Process(pid)
            p.cpu_percent(None)  # 基準値の採取（戻り値は捨てる）
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    time.sleep(sample_seconds)
    rows: list[dict[str, Any]] = []
    for p in procs:
        try:
            with p.oneshot():
                rows.append(
                    {
                        "pid": p.pid,
                        "name": p.name(),
                        "exe": _exe_of(p),
                        "user": _user_of(p),
                        "cpu_percent": p.cpu_percent(None),
                        "memory_percent": round(p.memory_percent(), 2),
                        "rss_mb": round(p.memory_info().rss / MIB, 1),
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return rows


def listening_ports() -> list[dict[str, Any]]:
    try:
        conns = psutil.net_connections(kind="tcp")
    except psutil.AccessDenied:
        raise ToolError("ソケット一覧を取得する権限がありません。") from None
    found: dict[tuple[str, int], dict[str, Any]] = {}
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        name = None
        if c.pid:
            try:
                name = psutil.Process(c.pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        # 他ユーザーのソケットは非 root だと pid が取れない。その場合は null に縮退する。
        found[(c.laddr.ip, c.laddr.port)] = {
            "address": c.laddr.ip,
            "port": c.laddr.port,
            "pid": c.pid,
            "process": name,
        }
    return sorted(found.values(), key=lambda r: (r["port"], r["address"]))


# --- systemd ----------------------------------------------------------------

_SHOW_PROPS = (
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "Description",
    "MainPID",
    "ActiveEnterTimestamp",
)


def service_status(name: str) -> dict[str, Any]:
    # `--` 以降は位置引数扱い。存在しないユニットでも exit 0 で LoadState=not-found を返す。
    out = run_command(
        ["systemctl", "show", "--no-pager", "--property=" + ",".join(_SHOW_PROPS), "--", name],
        timeout=5,
    )
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if props.get("LoadState") == "not-found":
        raise ToolError(f"ユニットが見つかりません: {name}")
    return {
        "unit": name,
        "description": props.get("Description"),
        "load_state": props.get("LoadState"),
        "active_state": props.get("ActiveState"),
        "sub_state": props.get("SubState"),
        "enabled": props.get("UnitFileState") or None,
        "main_pid": int(props.get("MainPID") or 0) or None,
        "active_since": props.get("ActiveEnterTimestamp") or None,
    }


def _journal_time(us: str | None) -> str | None:
    try:
        return datetime.fromtimestamp(int(us) / 1_000_000, timezone.utc).isoformat(timespec="seconds")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def journal_recent(unit: str | None, priority: str | None, lines: int) -> dict[str, Any]:
    args = ["journalctl", "--no-pager", "-o", "json", "-n", str(lines)]
    if unit is not None:
        args += ["-u", validate_unit(unit)]
    if priority is not None:
        if priority not in PRIORITIES:
            raise ToolError(f"priority は {', '.join(PRIORITIES)} のいずれかです。")
        args += ["-p", priority]  # 指定した重大度「以上」（err なら emerg〜err）
    out = run_command(args, timeout=15)
    entries = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        msg = e.get("MESSAGE")
        if isinstance(msg, list):  # 非 UTF-8 は int 配列で返ってくる
            msg = bytes(msg).decode("utf-8", errors="replace")
        prio = e.get("PRIORITY")
        entries.append(
            {
                "time": _journal_time(e.get("__REALTIME_TIMESTAMP")),
                "priority": PRIORITIES[int(prio)] if prio is not None and str(prio).isdigit() and int(prio) < 8 else None,
                "unit": e.get("_SYSTEMD_UNIT") or e.get("SYSLOG_IDENTIFIER"),
                "message": clean_text(msg or "")[:500],
            }
        )
    return {"count": len(entries), "entries": entries}


# --- ログファイル -----------------------------------------------------------


def list_logs() -> list[dict[str, Any]]:
    rows = []
    for name, path in LOG_ALLOWLIST.items():
        try:
            size = os.stat(path).st_size
        except OSError:
            size = None
        rows.append({"name": name, "path": path, "exists": size is not None, "readable": os.access(path, os.R_OK), "size_bytes": size})
    return rows


def read_log_tail(name: str, lines: int) -> dict[str, Any]:
    path = LOG_ALLOWLIST.get(name)
    if path is None:
        raise ToolError(f"許可されていないログです: {name}。使えるログ: {', '.join(LOG_ALLOWLIST)}")
    try:
        with open(path, "rb") as f:
            pos = f.seek(0, os.SEEK_END)
            data = b""
            while pos > 0 and data.count(b"\n") <= lines and len(data) < MAX_TAIL_BYTES:
                step = min(8192, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
    except FileNotFoundError:
        raise ToolError(f"ログファイルが存在しません: {name}") from None
    except PermissionError:
        raise ToolError(f"ログを読む権限がありません: {name}") from None
    tail = [clean_text(ln)[:MAX_LINE_CHARS] for ln in data.decode("utf-8", errors="replace").splitlines()[-lines:]]
    return {"log": name, "path": path, "lines_returned": len(tail), "lines": tail}
