import json
import time
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List, Callable, TypeVar

import psycopg2
import psycopg2.pool
import psycopg2.extras
from psycopg2 import sql, errors


T = TypeVar("T")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStorePostgres:
    """
    Industrial requirement: visibility + traceability.
    PostgreSQL-backed implementation.
    """

    def __init__(self, dsn: str, minconn: int = 1, maxconn: int = 10):
        """
        dsn example:
        postgresql://user:password@localhost:5432/jobs_db
        """
        self.pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            dsn=dsn,
        )
        self._init_db()

    # ----------------------
    # Connection helpers
    # ----------------------

    def _conn(self):
        return self.pool.getconn()

    def _putconn(self, conn):
        self.pool.putconn(conn)

    def _is_retryable_error(self, e: BaseException) -> bool:
        return isinstance(e, (
            errors.SerializationFailure,
            errors.DeadlockDetected,
        ))

    def _with_write_retry(self, op: Callable) -> T:
        delay = 0.05
        last_exc: Optional[BaseException] = None

        for _ in range(6):
            conn = self._conn()
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    result = op(cur)
                conn.commit()
                return result
            except BaseException as e:
                conn.rollback()
                if self._is_retryable_error(e):
                    last_exc = e
                    time.sleep(delay)
                    delay = min(delay * 2, 1.0)
                    continue
                raise
            finally:
                self._putconn(conn)

        assert last_exc is not None
        raise last_exc

    # ----------------------
    # Schema
    # ----------------------

    def _init_db(self) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    issue_key TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('QUEUED','RUNNING','DONE','FAILED')),
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    result_json JSONB,
                    error TEXT
                );
                """)

                cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    ts TIMESTAMPTZ NOT NULL,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data_json JSONB
                );
                """)

                cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_packs (
                    jira_key TEXT PRIMARY KEY,
                    title TEXT,
                    status TEXT,
                    pack_path TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                """)

                # Indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_issue_key ON jobs(issue_key);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_job_id ON audit_log(job_id);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_packs_updated ON ticket_packs(updated_at);")

            conn.commit()
        finally:
            self._putconn(conn)

    # ----------------------
    # Jobs API
    # ----------------------

    def create_job(self, job_id: str, issue_key: str) -> None:
        now = _utc_now()

        def _op(cur):
            cur.execute("""
            INSERT INTO jobs(job_id, issue_key, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """, (job_id, issue_key, "QUEUED", now, now))

        self._with_write_retry(_op)

    def set_status(self, job_id: str, status: str, error: Optional[str] = None) -> None:
        now = _utc_now()

        def _op(cur):
            cur.execute("""
            UPDATE jobs
            SET status=%s, updated_at=%s, error=%s
            WHERE job_id=%s
            """, (status, now, error, job_id))

        self._with_write_retry(_op)

    def set_result(self, job_id: str, result: Dict[str, Any]) -> None:
        now = _utc_now()

        def _op(cur):
            cur.execute("""
            UPDATE jobs
            SET result_json=%s, updated_at=%s, status='DONE'
            WHERE job_id=%s
            """, (psycopg2.extras.Json(result), now, job_id))

        self._with_write_retry(_op)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                SELECT job_id, issue_key, status, created_at, updated_at, result_json, error
                FROM jobs WHERE job_id=%s
                """, (job_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            self._putconn(conn)

    # ----------------------
    # Audit API
    # ----------------------

    def audit(
        self,
        job_id: str,
        stage: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = _utc_now()

        def _op(cur):
            cur.execute("""
            INSERT INTO audit_log(job_id, ts, stage, message, data_json)
            VALUES (%s, %s, %s, %s, %s)
            """, (
                job_id,
                now,
                stage,
                message,
                psycopg2.extras.Json(data) if data else None,
            ))

        self._with_write_retry(_op)

    def get_audit(self, job_id: str) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                SELECT ts, stage, message, data_json
                FROM audit_log
                WHERE job_id=%s
                ORDER BY id ASC
                """, (job_id,))
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._putconn(conn)

    # ----------------------
    # Ticket Knowledge Packs
    # ----------------------

    def upsert_ticket_pack(
        self,
        jira_key: str,
        title: str,
        status: str,
        pack_path: str,
    ) -> None:
        now = _utc_now()

        def _op(cur):
            cur.execute("""
            INSERT INTO ticket_packs(jira_key, title, status, pack_path, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (jira_key)
            DO UPDATE SET
                title=EXCLUDED.title,
                status=EXCLUDED.status,
                pack_path=EXCLUDED.pack_path,
                updated_at=EXCLUDED.updated_at
            """, (jira_key, title, status, pack_path, now))

        self._with_write_retry(_op)

    def get_ticket_pack(self, jira_key: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                SELECT jira_key, title, status, pack_path, updated_at
                FROM ticket_packs WHERE jira_key=%s
                """, (jira_key,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            self._putconn(conn)
