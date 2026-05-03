import json
import unittest

from tiny_cli import report


class TinyCliTests(unittest.TestCase):
    def test_report_text(self):
        self.assertEqual(report(), "tiny-cli status: ok")

    def test_report_json(self):
        self.assertEqual(json.loads(report(json_output=True)), {"name": "tiny-cli", "status": "ok"})


if __name__ == "__main__":
    unittest.main()
