import json
import tempfile
import unittest
from pathlib import Path

from harness.review_packet_validator import validate_review_packet


VALID_MARKDOWN = """# Review Packet: ABC-1

## Issue

## Pull Request

## Summary

## Changed files

## Tests run

## CI status

## Known risks

## Human review checklist
"""


VALID_JSON = {
    "issue": {"identifier": "ABC-1", "title": "Title", "url": "https://linear.app/ABC-1"},
    "pull_request": {"url": "https://github.com/org/repo/pull/1", "status": "open"},
    "summary": "Implemented the change.",
    "changed_files": ["src/app.py"],
    "tests": [{"command": "python -m unittest", "result": "passed", "notes": ""}],
    "ci": {"status": "passed", "url": "https://ci.example/build/1"},
    "artifacts": {"screenshots": [], "videos": [], "logs": [], "metrics": []},
    "risks": [],
    "follow_ups": [],
}


class ReviewPacketValidatorTests(unittest.TestCase):
    def test_valid_markdown_without_json_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review-packet.md"
            path.write_text(VALID_MARKDOWN, encoding="utf-8")

            self.assertEqual(validate_review_packet(path), [])

    def test_missing_markdown_sections_are_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review-packet.md"
            path.write_text("# Review Packet\n\n## Issue\n", encoding="utf-8")

            messages = validate_review_packet(path)

            self.assertTrue(messages)
            self.assertTrue(any("## Pull Request" in message.message for message in messages))

    def test_sibling_json_is_validated_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review-packet.md"
            path.write_text(VALID_MARKDOWN, encoding="utf-8")
            path.with_suffix(".json").write_text(json.dumps(VALID_JSON), encoding="utf-8")

            self.assertEqual(validate_review_packet(path), [])

    def test_json_missing_required_fields_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review-packet.json"
            path.write_text(json.dumps({"issue": {"identifier": "ABC-1"}}), encoding="utf-8")

            messages = validate_review_packet(path)

            self.assertTrue(messages)
            self.assertTrue(any("pull_request" in message.message for message in messages))
            self.assertTrue(any("issue.title" in message.message for message in messages))

    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review-packet.json"
            path.write_text("{", encoding="utf-8")

            messages = validate_review_packet(path)

            self.assertEqual(len(messages), 1)
            self.assertIn("review packet JSON is invalid", messages[0].message)


if __name__ == "__main__":
    unittest.main()
