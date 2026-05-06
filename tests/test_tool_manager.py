from __future__ import annotations

import unittest

from cogito.tool_manager import infer_agent_for_model


class ToolManagerTests(unittest.TestCase):
    def test_infers_adapter_from_model_name(self):
        self.assertEqual(infer_agent_for_model("gpt-5.5"), "codex")
        self.assertEqual(infer_agent_for_model("sonnet"), "claude")
        self.assertEqual(infer_agent_for_model("opencode/gpt-5-nano"), "opencode")
        self.assertEqual(infer_agent_for_model("qwen3:0.6b"), "local")


if __name__ == "__main__":
    unittest.main()
