from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from app.config import DB_PATH

# 默认 FULL：单笔提交落盘后才算成功。测试环境可用 PODRIFT_DB_SYNC=OFF 跳过 fsync。
_SYNC = (os.environ.get("PODRIFT_DB_SYNC") or "FULL").upper()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if _SYNC in ("OFF", "NORMAL", "FULL", "EXTRA"):
        conn.execute(f"PRAGMA synchronous = {_SYNC}")
    return conn


@contextmanager
def db(write: bool = False):
    """单笔事务边界。

    写路径用 BEGIN IMMEDIATE 先占写锁：运行态改写与启停单推进要么同笔提交，
    要么整笔回滚；并发双写按写锁排队，后来者在锁内读到已提交的运行态。
    读路径保持自动提交，不持锁。
    """
    conn = connect()
    conn.isolation_level = None  # 事务由本上下文显式开关
    started = False
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
            started = True
        yield conn
        if started:
            conn.execute("COMMIT")
            started = False
    except BaseException:
        if started:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in have:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS images (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          tag TEXT NOT NULL,
          pull_state TEXT NOT NULL,
          layers_done INTEGER NOT NULL DEFAULT 0,
          layers_total INTEGER NOT NULL DEFAULT 4,
          ready_at TEXT
        );
        CREATE TABLE IF NOT EXISTS pods (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          image_id INTEGER,
          run_state TEXT NOT NULL,
          run_state_rev INTEGER NOT NULL DEFAULT 0,
          run_state_at TEXT,
          quota_held INTEGER NOT NULL DEFAULT 0,
          sidecar TEXT,
          cpu_quota REAL NOT NULL DEFAULT 1.0,
          mem_quota_mb INTEGER NOT NULL DEFAULT 512,
          FOREIGN KEY(image_id) REFERENCES images(id)
        );
        CREATE TABLE IF NOT EXISTS start_orders (
          id INTEGER PRIMARY KEY,
          pod_id INTEGER NOT NULL,
          action TEXT NOT NULL,
          target_image_id INTEGER,
          status TEXT NOT NULL,
          note TEXT,
          prev_state TEXT,
          result_state TEXT,
          state_rev INTEGER,
          created_at TEXT NOT NULL,
          FOREIGN KEY(pod_id) REFERENCES pods(id)
        );
        CREATE TABLE IF NOT EXISTS probes (
          id INTEGER PRIMARY KEY,
          pod_id INTEGER NOT NULL UNIQUE,
          color TEXT NOT NULL,
          fail_streak INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT,
          FOREIGN KEY(pod_id) REFERENCES pods(id)
        );
        CREATE TABLE IF NOT EXISTS quotas (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          cpu_used REAL NOT NULL,
          cpu_limit REAL NOT NULL,
          mem_used_mb INTEGER NOT NULL,
          mem_limit_mb INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS restart_policy (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          mode TEXT NOT NULL,
          backoff_sec INTEGER NOT NULL DEFAULT 5
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY,
          kind TEXT NOT NULL,
          ref TEXT,
          detail TEXT NOT NULL,
          at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )
    # 兼容旧库：真源列需要版本号，启停单需要记录推进前后的运行态以便对读/审计。
    _ensure_column(conn, "pods", "run_state_rev", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "pods", "run_state_at", "TEXT")
    _ensure_column(conn, "pods", "quota_held", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "start_orders", "prev_state", "TEXT")
    _ensure_column(conn, "start_orders", "result_state", "TEXT")
    _ensure_column(conn, "start_orders", "state_rev", "INTEGER")
