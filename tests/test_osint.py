from __future__ import annotations

import unittest
from unittest.mock import patch

from cogito.db import connect
from cogito.memory import ensure_db, list_memories
from cogito.osint import (
    browser_profile_dir,
    query_from_url,
    research_target,
    collect_browser_documents,
    research_target_with_browser_receipt,
    research_target_with_receipt,
)
from cogito.persona_knowledge import list_persona_knowledge
from cogito.personas import add_persona_for_model
from cogito.settings import set_embedding_model


class OsintTests(unittest.TestCase):
    def test_query_from_url_derives_person_name(self):
        query = query_from_url("https://www.linkedin.com/in/ruslan-klymenko-927a6b67/")

        self.assertIn("ruslan", query)
        self.assertIn("klymenko", query)

    def test_research_me_stores_public_memory(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")

        with patch("cogito.osint.collect_osint_documents", return_value=fake_collection()) as collect:
            created = research_target(conn, target="@me", source="Ruslan Klymenko")

        memories = list_memories(conn)
        self.assertEqual(len(created), 1)
        self.assertEqual(memories[0]["type"], "public_research")
        self.assertIn("software engineer in Zurich", memories[0]["text"])

    def test_research_persona_stores_persona_knowledge(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")
        add_persona_for_model(conn, name="architect", model="gpt-5.5", description="Architect.")

        with patch("cogito.osint.collect_osint_documents", return_value=fake_collection()) as collect:
            created = research_target(conn, target="@architect", source="architecture")

        knowledge = list_persona_knowledge(conn, persona_name="architect")
        self.assertEqual(len(created), 1)
        self.assertEqual(knowledge[0]["type"], "public_research")
        self.assertIn("software engineer in Zurich", knowledge[0]["text"])

    def test_research_receipt_reports_sources_and_saved_chunks(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")

        with patch("cogito.osint.collect_osint_documents", return_value=fake_collection()):
            receipt = research_target_with_receipt(conn, target="@me", source="Ruslan Klymenko")

        self.assertEqual(receipt["target"], "@me")
        self.assertEqual(receipt["query"], "Ruslan Klymenko")
        self.assertEqual(receipt["scanned_sources"][0]["url"], "https://example.com/ruslan")
        self.assertEqual(receipt["saved_chunks"][0]["store"], "user_memory")

    def test_browser_research_receipt_uses_browser_collection(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")

        with patch("cogito.osint.collect_browser_documents", return_value=fake_collection() | {"browser_profile": str(browser_profile_dir())}):
            receipt = research_target_with_browser_receipt(conn, target="@me", source="https://example.com/ruslan")

        self.assertIn("browser-profile", receipt["browser_profile"])
        self.assertEqual(receipt["saved_chunks"][0]["store"], "user_memory")

    def test_collect_browser_documents_runs_async_impl_in_thread(self):
        expected = fake_collection() | {"browser_profile": str(browser_profile_dir())}

        with patch("cogito.osint.collect_browser_documents_async", return_value=expected):
            result = collect_browser_documents("https://example.com/ruslan", limit=2, wait_seconds=0)

        self.assertEqual(result["browser_profile"], expected["browser_profile"])


def fake_collection():
    return {
        "query": "Ruslan Klymenko",
        "seed_urls": [],
        "discovered_urls": ["https://example.com/ruslan"],
        "scanned_sources": [{"url": "https://example.com/ruslan", "chars": 78, "preview": "Ruslan Klymenko"}],
        "failed_sources": [{"url": "https://example.com/private", "error": "forbidden"}],
        "documents": [
            {
                "url": "https://example.com/ruslan",
                "text": "Ruslan Klymenko is a software engineer in Zurich with AI agent interests.",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
