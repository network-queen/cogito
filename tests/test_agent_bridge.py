from __future__ import annotations

import unittest
from unittest.mock import patch

from cogito.agent_bridge import build_agent_command, build_enriched_prompt, extract_final_answer, run_agent_capture


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

    def test_local_agent_uses_ollama_without_external_command(self):
        with patch("cogito.agent_bridge.ollama_chat_generate", return_value="local answer") as generate:
            result = run_agent_capture("local", "hello", stream=False, model="qwen3:0.6b")

        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output"], "local answer")
        generate.assert_called_once_with("qwen3:0.6b", "hello")

    def test_local_agent_sends_output_to_callback(self):
        chunks = []
        with patch("cogito.agent_bridge.ollama_chat_generate", return_value="local answer"):
            result = run_agent_capture("local", "hello", stream=True, model="qwen3:0.6b", on_output=chunks.append)

        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(chunks, ["local answer\n"])


if __name__ == "__main__":
    unittest.main()
