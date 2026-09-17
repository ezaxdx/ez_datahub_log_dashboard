"""
db_logger.py — SQLite 기반 알림 실행 이력 로거

DB 파일: checkpoints/notifier.db

테이블:
  notifier_runs   : 매 실행 결과 (구간·상태·메시지)
  notifier_alerts : 감지된 위험 인원 상세 (run_id FK)
"""

import sqlite3
import os

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "checkpoints", "notifier.db"
)


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """테이블이 없으면 생성"""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notifier_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT NOT NULL,
                session_type    TEXT,
                interval_start  TEXT,
                interval_end    TEXT,
                status          TEXT,
                message         TEXT,
                detected_count  INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS notifier_alerts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       INTEGER NOT NULL REFERENCES notifier_runs(id),
                timestamp    TEXT NOT NULL,
                user_no      TEXT,
                name         TEXT,
                dept         TEXT,
                rank         TEXT,
                detail       TEXT,
                total_count  INTEGER DEFAULT 0
            );
        """)


def log_run(
    timestamp,
    session_type,
    interval_start,
    interval_end,
    status,
    message,
    detected_count=0,
):
    """실행 결과 1행을 저장하고 run_id를 반환"""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO notifier_runs
               (timestamp, session_type, interval_start, interval_end,
                status, message, detected_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp,
                session_type,
                interval_start,
                interval_end,
                status,
                message,
                detected_count,
            ),
        )
        return cur.lastrowid


def log_alerts(run_id, users, timestamp):
    """
    감지된 위험 인원 목록을 저장
    users: list of dict with keys: user_no, name, dept, rank, detail, total_count
    """
    if not users:
        return
    init_db()
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO notifier_alerts
               (run_id, timestamp, user_no, name, dept, rank, detail, total_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    timestamp,
                    str(u.get("user_no", "")),
                    u.get("name", ""),
                    u.get("dept", ""),
                    u.get("rank", ""),
                    u.get("detail", ""),
                    int(u.get("total_count", 0)),
                )
                for u in users
            ],
        )
