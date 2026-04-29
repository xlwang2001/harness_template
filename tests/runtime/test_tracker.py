import unittest

from harness.runtime.tracker import normalize_linear_issue


class TrackerTests(unittest.TestCase):
    def test_normalizes_linear_issue(self):
        issue = normalize_linear_issue(
            {
                "id": "id1",
                "identifier": "ABC-1",
                "title": "Title",
                "priority": "2",
                "state": {"name": "Todo"},
                "labels": {"nodes": [{"name": "Backend"}]},
                "inverseRelations": {
                    "nodes": [
                        {"type": "blocks", "issue": {"id": "id0", "identifier": "ABC-0", "state": {"name": "Done"}}},
                        {"type": "relates", "issue": {"id": "id9", "identifier": "ABC-9"}},
                    ]
                },
            }
        )
        self.assertEqual(issue.priority, 2)
        self.assertEqual(issue.labels, ("backend",))
        self.assertEqual(issue.blocked_by[0].identifier, "ABC-0")
