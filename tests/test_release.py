"""Keep local development files out of source releases."""

from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.check_release import check_source_archive, scan_text
from tools.source_archive import source_files


class SourceReleaseTests(unittest.TestCase):
    def test_file_selection_excludes_nested_local_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contents = (
                "README.md",
                "README.zh-CN.md",
                "THIRD_PARTY_NOTICES.md",
                "THIRD_PARTY_NOTICES.zh-CN.md",
                "start.bat",
                "启动轻压.bat",
                "CHANGELOG.md",
                "CONTRIBUTING.md",
                "AGENTS.md",
                "docs/usage.md",
                "docs/CHANGELOG.md",
                "docs/contributing.md",
                "docs/Agents.md",
                "docs/.codex/config.toml",
                "tests/data/settings.json",
                "tests/.env.local",
                "tests/__pycache__/cached.py",
                "tools/private.key",
                "compressor/main.py",
            )
            for name in contents:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("example", encoding="utf-8")
            selected = {path.relative_to(root).as_posix() for path in source_files(root)}
            self.assertEqual(
                selected,
                {
                    "README.md",
                    "README.zh-CN.md",
                    "THIRD_PARTY_NOTICES.md",
                    "THIRD_PARTY_NOTICES.zh-CN.md",
                    "start.bat",
                    "docs/usage.md",
                    "compressor/main.py",
                },
            )

    def test_archive_check_rejects_an_extra_development_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            readme = root / "README.md"
            readme.write_text("Lightpress", encoding="utf-8")
            archive_path = root / "source.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.write(readme, "Lightpress/README.md")
                archive.writestr("Lightpress/AGENTS.md", "local instructions")
            findings = check_source_archive(archive_path, [readme], root)
            self.assertEqual(findings, [dict(file="AGENTS.md", rule="unexpected_archive_file")])

    def test_report_detects_a_token_without_copying_its_value(self):
        token = "ghp_" + "x" * 30
        findings = scan_text("example.txt", token)
        self.assertEqual(findings, [dict(file="example.txt", line=1, rule="credential")])
        self.assertNotIn(token, str(findings))


if __name__ == "__main__":
    unittest.main()
