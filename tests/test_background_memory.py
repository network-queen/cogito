from __future__ import annotations

import time
import unittest
from tempfile import TemporaryDirectory

from cogito.db import connect
from cogito.memory import ensure_db, list_memories
from cogito.sessions import ask_session, create_session, process_pending_memory_jobs
from cogito.settings import set_memory_model


class BackgroundMemoryTests(unittest.TestCase):
    def test_background_memory_extraction_uses_separate_connection(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        session = create_session(conn, title="Memory background")

        result = ask_session(
            conn,
            session_id=session["id"],
            user_prompt="I prefer concise engineering answers",
            execute=False,
            memory_mode="background",
        )

        self.assertEqual(result["stored_memories"], [])
        self.assertEqual(list_memories(conn), [])

    def test_background_memory_extraction_stores_for_file_db(self):
        with TemporaryDirectory() as tmp:
            db_path = f"{tmp}/cogito.db"
            conn = connect(db_path)
            ensure_db(conn)
            set_memory_model(conn, "heuristic")
            session = create_session(conn, title="Memory background")

            ask_session(
                conn,
                session_id=session["id"],
                user_prompt="I prefer concise engineering answers",
                execute=False,
                memory_mode="background",
            )

            deadline = time.time() + 2
            memories = []
            while time.time() < deadline:
                memories = list_memories(conn)
                if memories:
                    break
                time.sleep(0.05)

            self.assertTrue(any("prefer concise" in memory["text"] for memory in memories))

    def test_pending_memory_job_can_resume_later(self):
        with TemporaryDirectory() as tmp:
            db_path = f"{tmp}/cogito.db"
            conn = connect(db_path)
            ensure_db(conn)
            set_memory_model(conn, "heuristic")
            session = create_session(conn, title="Memory background")

            ask_session(
                conn,
                session_id=session["id"],
                user_prompt="I prefer durable memory jobs",
                execute=False,
                memory_mode="background",
            )
            conn.execute("UPDATE memory_jobs SET state = 'pending'")
            conn.commit()

            process_pending_memory_jobs(conn)

            memories = list_memories(conn)
            self.assertTrue(any("durable memory jobs" in memory["text"] for memory in memories))


if __name__ == "__main__":
    unittest.main()
