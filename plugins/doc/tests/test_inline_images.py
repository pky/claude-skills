"""HTML 画像埋め込み CLI の公開契約を検証する。"""

import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/html-doc/scripts/inline_images.py"


class InlineImagesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.source = self.root / "input/document.html"
        self.source.parent.mkdir()
        self.output = self.root / "result.html"
        self.original_output = b"previous output\r\n"

    def run_cli(self, *args):
        result = subprocess.run(
            ["python3", str(SCRIPT), *map(str, args)], cwd=self.root,
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertNotIn(f"can't open file '{SCRIPT}'", result.stderr)
        return result

    def assert_inlined(self, count):
        result = self.run_cli(self.source, self.output)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stdout.splitlines(), [f"inlined {count}"])
        return self.output.read_bytes()

    def image(self, name, contents):
        path = self.source.parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def test_relative_and_absolute_images_use_extension_mime_and_original_bytes(self):
        images = (
            ("images/chart.PnG", "image/png"),
            ("photo.JPG", "image/jpeg"),
            ("photo.Jpeg", "image/jpeg"),
            ("animation.gif", "image/gif"),
            ("cover.webp", "image/webp"),
            ("absolute icon.svg", "image/svg+xml"),
        )
        expected = []
        tags = []
        for index, (name, mime) in enumerate(images):
            contents = b"\x00\xff\r\n" + bytes([index])
            path = self.image(name, contents)
            src = str(path) if name.endswith(".svg") else name
            expected.append((mime, contents))
            tags.append(f'<img src="{src}">\n')
        self.source.write_text("".join(tags), encoding="utf-8")

        html = self.assert_inlined(len(images))
        uris = re.findall(rb'<img src="data:([^;]+);base64,([^"]+)">', html)
        self.assertEqual(len(uris), len(expected), html)
        for (mime, payload), (expected_mime, contents) in zip(uris, expected):
            with self.subTest(mime=expected_mime, contents=contents):
                self.assertEqual(mime.decode("ascii"), expected_mime)
                self.assertEqual(base64.b64decode(payload, validate=True), contents)

    def test_changes_only_src_values_and_preserves_original_input(self):
        contents = b"\x00image\xff\r\n"
        self.image("local.png", contents)
        html = (
            "<!doctype html>\r\n"
            "<p>図 local.png</p>\n"
            "<!-- <img src='comment.png'> -->\r\n"
            '<script>const tag = "<img src=\'script.png\'>";</script>\r\n'
            "<iframe src='local.png'></iframe>\n"
            """\t<img  alt='図 local.png' src = 'local.png' data-src="local.png" />\r\n"""
            '<img\n  src="local.png" title="図">\r\n'
            '<img src="https://example.test/external.png">'
        ).encode("utf-8")
        self.source.write_bytes(html)
        self.output.write_bytes(self.original_output)
        uri = b"data:image/png;base64," + base64.b64encode(contents)
        expected = html.replace(b"src = 'local.png'", b"src = '" + uri + b"'")
        expected = expected.replace(b'<img\n  src="local.png"', b'<img\n  src="' + uri + b'"')
        self.assertEqual(self.assert_inlined(2), expected)
        self.assertEqual(self.source.read_bytes(), html)

    def test_leaves_external_data_and_fragment_sources_untouched(self):
        html = b"""<img src="data:image/png;base64,AA==">
<img src="http://example.test/chart.png">
<img src="https://example.test/chart.png">
<img src="//example.test/chart.png">
<img src="#chart">
"""
        self.source.write_bytes(html)
        self.assertEqual(self.assert_inlined(0), html)

    def assert_image_failure(self, html, *, reason_value=None):
        self.source.write_text(html, encoding="utf-8")
        for existing_output in (False, True):
            with self.subTest(existing_output=existing_output):
                if existing_output:
                    self.output.write_bytes(self.original_output)
                result = self.run_cli(self.source, self.output)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue(result.stderr.strip())
                if reason_value is not None:
                    self.assertIn(reason_value, result.stderr)
                if existing_output:
                    self.assertEqual(self.output.read_bytes(), self.original_output)
                else:
                    self.assertFalse(self.output.exists())

    def test_missing_image_reports_path_without_creating_or_changing_output(self):
        self.image("good.png", b"existing image")
        self.assert_image_failure(
            '<img src="good.png"><img src="images/missing.png">',
            reason_value="images/missing.png",
        )

    def test_unsupported_extension_does_not_create_or_change_output(self):
        self.image("good.png", b"existing image")
        self.image("chart.bmp", b"unsupported image")
        self.assert_image_failure('<img src="good.png"><img src="chart.bmp">')

    def test_rejects_input_as_output_without_changing_it(self):
        self.image("local.png", b"existing image")
        html = b'<img src="local.png">\r\n'
        self.source.write_bytes(html)
        os.link(self.source, self.output)
        for output in (self.source, self.output):
            with self.subTest(output=output):
                result = self.run_cli(self.source, output)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue(result.stderr.strip())
                self.assertEqual(self.source.read_bytes(), html)
                self.assertEqual(output.read_bytes(), html)

    def test_missing_input_exits_with_code_two(self):
        result = self.run_cli(self.source, self.output)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_wrong_argument_count_exits_with_code_two(self):
        self.source.write_text("<p>図なし</p>", encoding="utf-8")
        for args in ((), (self.source,), (self.source, self.output, "extra")):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2, result.stderr)


if __name__ == "__main__":
    unittest.main()
