import unittest
from pathlib import Path


FORBIDDEN = tuple(
    "".join(parts)
    for parts in (
        ("vendor/symphony", "/elixir"),
        ("sync", "-symphony"),
        ("does not reimplement", " Symphony"),
        ("vendors Symphony", " as an upstream runtime"),
    )
)

ALLOWED = {
    Path("docs/decisions/0001-reuse-symphony-as-submodule.md"),
}


class StaleDesignTests(unittest.TestCase):
    def test_no_operational_docs_point_to_old_runtime_design(self):
        root = Path(__file__).resolve().parent.parent
        offenders = []
        for path in root.rglob("*"):
            if not path.is_file() or path.parts[-2:-1] == (".git",):
                continue
            relative = path.relative_to(root)
            if relative in ALLOWED or relative.parts[:2] == ("vendor", "symphony"):
                continue
            if relative == Path("tests/test_stale_design.py"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for forbidden in FORBIDDEN:
                if forbidden in text:
                    offenders.append(f"{relative}: {forbidden}")
        self.assertEqual(offenders, [])
