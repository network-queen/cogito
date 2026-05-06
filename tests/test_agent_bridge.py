from __future__ import annotations

import unittest

from cogito.agent_bridge import build_agent_command, build_enriched_prompt, extract_final_answer


class AgentBridgeTests(unittest.TestCase):
    def test_build_enriched_prompt_contains_context_and_request(self):
        prompt = build_enriched_prompt("Lens: coding\n- User likes terse output.", "Fix tests")

        self.assertIn("Lens: coding", prompt)
        self.assertIn("Fix tests", prompt)
        self.assertIn("Respect access policy", prompt)
        self.assertIn("Do not claim that you saved", prompt)

    def test_yolo_flags_are_forwarded(self):
        codex = build_agent_command("codex", "do it", yolo=True, model="gpt-5.5")
        claude = build_agent_command("claude", "do it", yolo=True, model="sonnet")
        opencode = build_agent_command("opencode", "do it", yolo=True)

        self.assertIn("--dangerously-bypass-approvals-and-sandbox", codex)
        self.assertIn("gpt-5.5", codex)
        self.assertIn("--dangerously-skip-permissions", claude)
        self.assertIn("sonnet", claude)
        self.assertIn("--dangerously-skip-permissions", opencode)

    def test_extract_final_answer_removes_codex_wrapper(self):
        raw = """OpenAI Codex v0.128.0
--------
user
hidden prompt

codex
I am fine.
tokens used
7,062
"""

        self.assertEqual(extract_final_answer(raw), "I am fine.")


if __name__ == "__main__":
    unittest.main()
