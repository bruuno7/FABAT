"""SQLite migration and reliable writer regressions."""
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from motor.server import memoria_db
from motor.server.ledger import Ledger
from motor.server.memoria_db import Store


class SafetyPersistenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=Path.home())
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "safety.db"

    def test_legacy_events_schema_preserves_history_and_accepts_new_links(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                CREATE TABLE sessions(session_id TEXT PRIMARY KEY, started_at REAL, ended_at REAL,
                                      case_id TEXT, voice_mode TEXT, speed REAL, comms_mode TEXT);
                CREATE TABLE events(id INTEGER PRIMARY KEY, session_id TEXT, ts_unix REAL,
                                    event_type TEXT, action_id TEXT, payload_json TEXT);
                INSERT INTO sessions(session_id,started_at) VALUES ('legacy',1);
                INSERT INTO events VALUES (1,'legacy',1,'old','a-old','{}');
                CREATE TABLE cerebro_episodes (
                    id TEXT PRIMARY KEY, session_id TEXT, ts_unix REAL, tipo TEXT, zona TEXT,
                    franja TEXT, entrada_json TEXT, contexto_json TEXT, razonamiento TEXT,
                    decision_json TEXT, acciones_json TEXT, respuestas_json TEXT,
                    resultado_json TEXT, tiempos_json TEXT, texto_busqueda TEXT);
                INSERT INTO cerebro_episodes(id,session_id,ts_unix,razonamiento)
                VALUES ('old-reasoning','legacy',1,'Preservar este episodio');
                PRAGMA user_version=1;
            """)
        ledger = Ledger(self.path)
        self.addCleanup(ledger.close)
        self.assertTrue(ledger.enabled, ledger.warning)
        ledger.append_event("legacy", "new", incidente_id="i-new", accion_id="a-new")
        ledger.close()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT event_type FROM events ORDER BY id").fetchall(),
                             [("old",), ("new",)])
            self.assertEqual(db.execute("SELECT incidente_id,accion_id FROM events WHERE event_type='new'").fetchone(),
                             ("i-new", "a-new"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE session_id='legacy'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT razonamiento,agente FROM cerebro_episodes").fetchone(),
                             ("Preservar este episodio", None))

    def test_failed_migration_rolls_back_schema_and_keeps_history(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                CREATE TABLE sessions(session_id TEXT PRIMARY KEY, started_at REAL, ended_at REAL,
                                      case_id TEXT, voice_mode TEXT, speed REAL, comms_mode TEXT);
                INSERT INTO sessions(session_id,started_at) VALUES ('legacy',1);
                PRAGMA user_version=1;
            """)
        ensure = memoria_db._ensure_column

        def fail_later(db, table, column, sql_type):
            ensure(db, table, column, sql_type)
            if column == "agente":
                raise RuntimeError("injected migration failure")

        with patch.object(memoria_db, "_ensure_column", side_effect=fail_later):
            store = Store(self.path)
            self.assertFalse(store.enabled)
            store.release()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT session_id FROM sessions").fetchall(), [("legacy",)])
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                             [("sessions",)])

    def test_writer_connection_is_closed_at_shutdown(self):
        store = Store(self.path)
        connections = []
        store.write(lambda db: connections.append(db))
        store.release()
        self.assertFalse(store._thread.is_alive())
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
            self.assertFalse(connections[0].in_transaction)

    def test_snapshot_overflow_cannot_evict_sql_job(self):
        store = Store(self.path, queue_size=1)
        self.addCleanup(store.release)
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        results = []

        def hold(db):
            started.set()
            self.assertTrue(release.wait(3))

        blocker = threading.Thread(target=lambda: store.write(hold))
        blocker.start()
        self.assertTrue(started.wait(3))
        writer = threading.Thread(target=lambda: results.append(store.write(
            lambda db: db.execute("INSERT INTO sessions(session_id,started_at) VALUES ('reliable',1)").rowcount)))
        writer.start()
        with store._queue.not_empty:
            self.assertTrue(store._queue.not_empty.wait_for(lambda: len(store._queue.queue) > 0, timeout=3))
        for minute in range(100):
            store.offer({"session": {"id": "snapshots"}, "t": minute})
        release.set()
        blocker.join(5)
        writer.join(5)
        self.assertEqual(results, [1])
        self.assertGreater(store.dropped, 0)
        store.release()
        self.assertFalse(store._thread.is_alive())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE session_id='reliable'").fetchone()[0], 1)

    def test_failed_sql_job_rolls_back_partial_transaction(self):
        store = Store(self.path)
        self.addCleanup(store.release)

        def fail(db):
            db.execute("INSERT INTO sessions(session_id,started_at) VALUES ('partial',1)")
            raise ValueError("injected failure")

        self.assertIsNone(store.write(fail))
        store.release()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE session_id='partial'").fetchone()[0], 0)

    def test_ledger_double_close_does_not_close_other_owner(self):
        first, second = Ledger(self.path), Ledger(self.path)
        self.addCleanup(second.close)
        self.addCleanup(first.close)
        first.close()
        first.close()
        self.assertTrue(second.enabled)
        second.session_start("still-open")
        second.close()
        self.assertFalse(second._store._thread.is_alive())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE session_id='still-open'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
