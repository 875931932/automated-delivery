import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_sensitive_data import scan_repository, scan_text


class SensitiveDataScanTests(unittest.TestCase):
    def test_only_published_author_contact_is_allowed_in_public_metadata(self):
        from scripts.check_sensitive_data import PUBLIC_EMAILS
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            public = next(iter(PUBLIC_EMAILS))
            (root / "author_info.json").write_text(public, encoding="utf-8")
            self.assertEqual(scan_repository(root), [])
            (root / "author_info.json").write_text(public + " private" + "@example.test", encoding="utf-8")
            (root / "private.txt").write_text(public, encoding="utf-8")
            self.assertEqual(scan_repository(root), [("author_info.json", "email"), ("private.txt", "email")])

    def test_detects_personal_data_and_credentials_without_returning_values(self):
        phone = "138" + "0013" + "8000"
        email = "qa" + "@" + "example.test"
        identity = "110101" + "19900101" + "123" + "X"
        token = "sk-" + ("x" * 24)
        private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
        user_path = "C:" + "\\" + "Users" + "\\" + "example" + "\\" + "project"
        text = "\n".join(
            (phone, email, identity, token, private_key_marker, user_path)
        )

        categories = scan_text(text)

        self.assertEqual(
            set(categories),
            {
                "mainland_phone",
                "email",
                "mainland_id",
                "private_key",
                "credential_token",
                "windows_user_path",
            },
        )
        self.assertNotIn(phone, " ".join(categories))
        self.assertNotIn(email, " ".join(categories))
        self.assertNotIn(identity, " ".join(categories))
        self.assertNotIn(token, " ".join(categories))
        self.assertNotIn("example", " ".join(categories))

    def test_repository_has_no_common_personal_data_or_credentials(self):
        root = Path(__file__).resolve().parents[1]

        self.assertEqual(scan_repository(root), [])

    def test_repository_scan_includes_ignored_files_but_skips_tool_data(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / ".gitignore").write_text("private.txt\n", encoding="utf-8")
            (root / "private.txt").write_text(
                "138001" + "38000", encoding="utf-8"
            )
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text(
                "138001" + "38001", encoding="utf-8"
            )
            (root / ".codegraph").mkdir()
            (root / ".codegraph" / "index.txt").write_text(
                "138001" + "38002", encoding="utf-8"
            )

            findings = scan_repository(root)

        self.assertEqual(findings, [("private.txt", "mainland_phone")])


if __name__ == "__main__":
    unittest.main()
