import subprocess
import sys
import unittest
from pathlib import Path

from harness.agents_validator import validate_agents
from harness.docs_validator import validate_docs
from harness.review_packet_validator import validate_review_packet
from harness.workflow_validator import validate_workflow


ROOT = Path(__file__).resolve().parent.parent
ADOPTED_TINY_CLI = ROOT / "examples" / "adopted-tiny-cli"


class ExampleTests(unittest.TestCase):
    def test_adopted_tiny_cli_validates_as_target_repo(self):
        messages = []
        messages.extend(validate_docs(ADOPTED_TINY_CLI))
        messages.extend(validate_agents(ADOPTED_TINY_CLI))
        messages.extend(validate_workflow(ADOPTED_TINY_CLI))
        errors = [message.format(ADOPTED_TINY_CLI) for message in messages if message.level == "ERROR"]
        self.assertEqual(errors, [])

    def test_adopted_tiny_cli_tests_pass(self):
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=ADOPTED_TINY_CLI,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_adopted_tiny_cli_sample_review_packet_validates(self):
        packet = ADOPTED_TINY_CLI / "docs" / "exec-plans" / "completed" / "ABC-123" / "review-packet.md"
        self.assertEqual(validate_review_packet(packet), [])

    def test_adoption_guide_links_adopted_example(self):
        text = (ROOT / "docs" / "adoption-guide.md").read_text(encoding="utf-8")
        self.assertIn("examples/adopted-tiny-cli/", text)


if __name__ == "__main__":
    unittest.main()
