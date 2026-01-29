# app/job_store.py
import sqlite3
import json
import time
from datetime import datetime
from typing import Optional, Any, Dict, List, Callable, TypeVar


T = TypeVar("T")


def _utc_now() -> str:
    # 1) datetime.utcnow() gets current UTC time (naive)
    # 2) isoformat() gives a standard readable string
    # 3) "Z" marks UTC for humans
    return datetime.utcnow().isoformat() + "Z"


class JobStore:
    """
    Industrial requirement: visibility + traceability.
    This class persists:
      - Job status (QUEUED/RUNNING/DONE/FAILED)
      - Results payload
      - Audit events per stage
      - Ticket Knowledge Pack metadata
    """

    def __init__(self, db_path: str):
        # db_path points to the sqlite file (e.g., jobs.db)
        self.db_path = db_path
        # Create tables on startup if missing
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        # Open sqlite connection; check_same_thread=False makes it safe for worker threads.
        # timeout controls how long sqlite waits on locks before raising.
        con = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        self._configure_connection(con)
        return con

    def _configure_connection(self, con: sqlite3.Connection) -> None:
        # WAL improves concurrent reader/writer behavior across processes.
        # busy_timeout reduces "database is locked" spikes under contention.
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=5000")

    def _is_locked_error(self, e: BaseException) -> bool:
        return isinstance(e, sqlite3.OperationalError) and (
            "database is locked" in str(e).lower() or "database is busy" in str(e).lower()
        )

    def _with_write_retry(self, op: Callable[[sqlite3.Connection], T]) -> T:
        # Retry short write transactions; sqlite allows only one writer at a time.
        # This avoids FastAPI webhook bursts causing 500s.
        delay = 0.05
        last_exc: Optional[BaseException] = None
        for _ in range(8):
            try:
                with self._conn() as con:
                    # Acquire the write lock early so failures happen here.
                    con.execute("BEGIN IMMEDIATE")
                    return op(con)
            except BaseException as e:
                if self._is_locked_error(e):
                    last_exc = e
                    time.sleep(delay)
                    delay = min(delay * 2.0, 1.0)
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def _init_db(self) -> None:
        # Ensure schema exists
        with self._conn() as con:
            # Table: job lifecycle
            con.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
              job_id TEXT PRIMARY KEY,
              issue_key TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              result_json TEXT,
              error TEXT
            )
            """)

            # Table: audit timeline (stage-by-stage)
            con.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              ts TEXT NOT NULL,
              stage TEXT NOT NULL,
              message TEXT NOT NULL,
              data_json TEXT
            )
            """)

            # Table: ticket knowledge pack metadata (search by Jira key even if RAG empty)
            con.execute("""
            CREATE TABLE IF NOT EXISTS ticket_packs (
              jira_key TEXT PRIMARY KEY,
              title TEXT,
              status TEXT,
              pack_path TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """)
            con.commit()

    # ----------------------
    # Jobs API
    # ----------------------

    def create_job(self, job_id: str, issue_key: str) -> None:
        now = _utc_now()
        def _op(con: sqlite3.Connection) -> None:
            con.execute(
                "INSERT INTO jobs(job_id, issue_key, status, created_at, updated_at) VALUES(?,?,?,?,?)",
                (job_id, issue_key, "QUEUED", now, now),
            )
            con.commit()

        self._with_write_retry(_op)

    def set_status(self, job_id: str, status: str, error: Optional[str] = None) -> None:
        now = _utc_now()
        def _op(con: sqlite3.Connection) -> None:
            con.execute(
                "UPDATE jobs SET status=?, updated_at=?, error=? WHERE job_id=?",
                (status, now, error, job_id),
            )
            con.commit()

        self._with_write_retry(_op)

    def set_result(self, job_id: str, result: Dict[str, Any]) -> None:
        now = _utc_now()
        def _op(con: sqlite3.Connection) -> None:
            con.execute(
                "UPDATE jobs SET result_json=?, updated_at=?, status=? WHERE job_id=?",
                (json.dumps(result), now, "DONE", job_id),
            )
            con.commit()

        self._with_write_retry(_op)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as con:
            row = con.execute(
                "SELECT job_id, issue_key, status, created_at, updated_at, result_json, error FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()

        if not row:
            return None

        return {
            "job_id": row[0],
            "issue_key": row[1],
            "status": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "result": json.loads(row[5]) if row[5] else None,
            "error": row[6],
        }

    # ----------------------
    # Audit API
    # ----------------------

    def audit(self, job_id: str, stage: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        # Insert one audit event line
        def _op(con: sqlite3.Connection) -> None:
            con.execute(
                "INSERT INTO audit_log(job_id, ts, stage, message, data_json) VALUES(?,?,?,?,?)",
                (job_id, _utc_now(), stage, message, json.dumps(data) if data else None),
            )
            con.commit()

        self._with_write_retry(_op)

    def get_audit(self, job_id: str) -> List[Dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT ts, stage, message, data_json FROM audit_log WHERE job_id=? ORDER BY id ASC",
                (job_id,),
            ).fetchall()

        out: List[Dict[str, Any]] = []
        for ts, stage, message, data_json in rows:
            out.append({
                "ts": ts,
                "stage": stage,
                "message": message,
                "data": json.loads(data_json) if data_json else None,
            })
        return out

    # ----------------------
    # Ticket Knowledge Packs metadata
    # ----------------------

    def upsert_ticket_pack(self, jira_key: str, title: str, status: str, pack_path: str) -> None:
        now = _utc_now()
        def _op(con: sqlite3.Connection) -> None:
            con.execute("""
            INSERT INTO ticket_packs(jira_key, title, status, pack_path, updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(jira_key)
            DO UPDATE SET title=excluded.title, status=excluded.status, pack_path=excluded.pack_path, updated_at=excluded.updated_at
            """, (jira_key, title, status, pack_path, now))
            con.commit()

        self._with_write_retry(_op)

    def get_ticket_pack(self, jira_key: str) -> Optional[Dict[str, Any]]:
        with self._conn() as con:
            row = con.execute(
                "SELECT jira_key, title, status, pack_path, updated_at FROM ticket_packs WHERE jira_key=?",
                (jira_key,),
            ).fetchone()

        if not row:
            return None

        return {
            "jira_key": row[0],
            "title": row[1],
            "status": row[2],
            "pack_path": row[3],
            "updated_at": row[4],
        }
