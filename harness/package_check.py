"""Build and smoke-test the installable harness package."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import subprocess
import sys
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a wheel and smoke-test the installed harness command.")
    parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory(prefix="harness-package-check-") as directory:
        work = Path(directory)
        build_venv = work / "build-venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(build_venv)
        build_python = _venv_python(build_venv)
        wheel_dir = work / "wheels"
        wheel_dir.mkdir()
        try:
            _run([str(build_python), "-m", "pip", "wheel", str(root), "--no-deps", "--no-build-isolation", "-w", str(wheel_dir)])
        except RuntimeError as exc:
            if "bdist_wheel" not in str(exc):
                raise
            _build_wheel_with_stdlib(root, wheel_dir)

        wheels = sorted(wheel_dir.glob("harness_engineering_starter-*.whl"))
        if not wheels:
            raise RuntimeError(f"no wheel built in {wheel_dir}")

        venv_dir = work / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = _venv_python(venv_dir)
        harness = _venv_script(venv_dir, "harness")
        _run([str(python), "-m", "pip", "install", str(wheels[-1])])

        target = work / "target"
        dry_run = work / "dry-run-target"
        _run([str(harness), "--help"])
        _run([str(harness), "init", "--target", str(dry_run), "--profile", "toy-example", "--dry-run"])
        _run([str(harness), "init", "--target", str(target), "--profile", "toy-example"])
        _run([str(harness), "validate", "--target", str(target)])
    return 0


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        output = completed.stdout.strip()
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{output}")


def _build_wheel_with_stdlib(root: Path, wheel_dir: Path) -> Path:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    name = project["name"].replace("-", "_")
    version = project["version"]
    dist_info = f"{name}-{version}.dist-info"
    wheel_name = f"{name}-{version}-py3-none-any.whl"
    wheel_path = wheel_dir / wheel_name
    records: list[tuple[str, str, str]] = []

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((root / "harness").rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            _write_wheel_file(archive, records, path.relative_to(root).as_posix(), path.read_bytes())

        metadata = "\n".join(
            [
                "Metadata-Version: 2.1",
                f"Name: {project['name']}",
                f"Version: {version}",
                f"Summary: {project.get('description', '')}",
                f"Requires-Python: {project.get('requires-python', '')}",
                "",
            ]
        )
        wheel = "\n".join(
            [
                "Wheel-Version: 1.0",
                "Generator: harness.package_check",
                "Root-Is-Purelib: true",
                "Tag: py3-none-any",
                "",
            ]
        )
        entry_points = "[console_scripts]\nharness = harness.cli:main\n"
        _write_wheel_file(archive, records, f"{dist_info}/METADATA", metadata.encode("utf-8"))
        _write_wheel_file(archive, records, f"{dist_info}/WHEEL", wheel.encode("utf-8"))
        _write_wheel_file(archive, records, f"{dist_info}/entry_points.txt", entry_points.encode("utf-8"))

        record_path = f"{dist_info}/RECORD"
        record_lines = []
        for row in records:
            record_lines.append(row)
        record_lines.append((record_path, "", ""))
        record_buffer = _csv_records(record_lines).encode("utf-8")
        archive.writestr(record_path, record_buffer)
    return wheel_path


def _write_wheel_file(archive: zipfile.ZipFile, records: list[tuple[str, str, str]], name: str, data: bytes) -> None:
    archive.writestr(name, data)
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
    records.append((name, f"sha256={digest}", str(len(data))))


def _csv_records(records: list[tuple[str, str, str]]) -> str:
    from io import StringIO

    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(records)
    return buffer.getvalue()


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_script(venv_dir: Path, name: str) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


if __name__ == "__main__":
    raise SystemExit(main())
