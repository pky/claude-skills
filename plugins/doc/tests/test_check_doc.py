"""HTML 文書検査 CLI の公開契約を検証する。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1] / "skills/html-doc"
SCRIPT = SKILL / "scripts/check_doc.py"
TEMPLATE = SKILL / "assets/template.html"
HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>作業記録</title>
<style>@media print { body { color: black; } }</style>
</head>
<body>
<nav id="toc"><a href="#details">詳細</a></nav>
<section id="summary"><p>要約</p></section>
<time datetime="2026-11-20">11月20日</time>
<h2 id="details">詳細</h2>
<p>作業を完了した。</p>
</body>
</html>
"""
RESOURCE_REFERENCES = (
    ("</head>", '<link rel="stylesheet" href="{value}">'),
    ("</head>", '<script src="{value}"></script>'),
    ("</body>", '<img src="{value}" alt="図">'),
    ("</body>", '<video><source src="{value}"></video>'),
    ("</body>", '<iframe src="{value}"></iframe>'),
    ("</body>", '<video src="{value}"></video>'),
    ("</body>", '<audio src="{value}"></audio>'),
    ("</head>", '<style>p {{ background: url("{value}"); }}</style>'),
    ("</body>", """<p style='background: url("{value}")'>図</p>"""),
    ("</head>", '<style>@import "{value}";</style>'),
    ("</body>", """<p style='@import "{value}";'>図</p>"""),
)
EXTERNAL_VALUES = (
    "http://example.test/asset",
    "https://example.test/asset",
    "//example.test/asset",
    "assets/example.test",
    "/assets/example.test",
)


class CheckDocTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    def run_cli(self, *args):
        result = subprocess.run(
            ["python3", str(SCRIPT), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertNotIn(f"can't open file '{SCRIPT}'", result.stderr)
        return result

    def check_html(self, html):
        path = self.root / "document.html"
        path.write_text(html, encoding="utf-8")
        return self.run_cli(path)

    def assert_pass(self, result):
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stdout.splitlines(), ["PASS"])

    def assert_fail(self, html, *problem_values):
        result = self.check_html(html)
        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), len(problem_values) or 1, result.stdout)
        for line in lines:
            self.assertRegex(line, r"^FAIL: \s*\S")
            if problem_values:
                self.assertEqual(sum(value in line for value in problem_values), 1, line)
        for value in problem_values:
            self.assertEqual(sum(value in line for line in lines), 1, lines)

    def test_minimal_document_passes(self):
        self.assert_pass(self.check_html(HTML))

    def test_template_passes(self):
        self.assert_pass(self.run_cli(TEMPLATE))

    def test_external_resource_references_fail(self):
        for closing_tag, reference in RESOURCE_REFERENCES:
            for value in EXTERNAL_VALUES:
                with self.subTest(reference=reference, value=value):
                    html = HTML.replace(closing_tag, reference.format(value=value) + closing_tag)
                    self.assert_fail(html, value)

    def test_data_and_fragment_resource_references_pass(self):
        for closing_tag, reference in RESOURCE_REFERENCES:
            for value in ("data:text/plain,embedded", "#embedded"):
                with self.subTest(reference=reference, value=value):
                    html = HTML.replace(closing_tag, reference.format(value=value) + closing_tag)
                    self.assert_pass(self.check_html(html))

    def test_img_srcset_with_external_candidate_fails(self):
        html = HTML.replace(
            "</body>", '<img srcset="a.png 1x, data:image/png;base64,AA 2x"></body>',
        )
        self.assert_fail(html, "a.png")

    def test_img_srcset_with_only_data_candidates_passes(self):
        html = HTML.replace(
            "</body>",
            '<img srcset="data:image/png;base64,AA== 1x, data:image/png;base64,AQ== 2x"></body>',
        )
        self.assert_pass(self.check_html(html))

    def test_external_video_poster_object_data_and_embed_src_fail(self):
        for fragment, value in (
            ('<video poster="p.png"></video>', "p.png"),
            ('<object data="https://x.test/a"></object>', "https://x.test/a"),
            ('<embed src="e.svg">', "e.svg"),
        ):
            with self.subTest(fragment=fragment):
                self.assert_fail(HTML.replace("</body>", fragment + "</body>"), value)

    def test_css_import_url_is_one_reference(self):
        value = "https://example.test/print.css"
        html = HTML.replace("</head>", f'<style>@import url("{value}");</style></head>')
        self.assert_fail(html, value)

    def test_anchor_href_allows_external_and_local_references(self):
        for value in (*EXTERNAL_VALUES, "#no-such-heading"):
            with self.subTest(value=value):
                self.assert_pass(self.check_html(HTML.replace(
                    "</body>", f'<a href="{value}">参考資料</a></body>',
                )))

    def test_missing_toc_fails(self):
        self.assert_fail(HTML.replace('id="toc"', 'id="links"'))

    def test_toc_link_requires_h2_or_h3_target(self):
        for target in ("missing-heading", "not-a-heading"):
            with self.subTest(target=target):
                html = HTML.replace(
                    "</nav>", f'<a href="#{target}">補足</a></nav>',
                ).replace("</body>", '<p id="not-a-heading">補足</p></body>')
                self.assert_fail(html, target)

    def test_toc_link_to_h3_passes(self):
        html = HTML.replace(
            "</nav>", '<a href="#note">補足</a></nav>',
        ).replace("</body>", '<h3 id="note">補足</h3></body>')
        self.assert_pass(self.check_html(html))

    def test_toc_heading_needs_no_id_or_link(self):
        self.assert_pass(self.check_html(HTML.replace(
            '<nav id="toc">', '<nav id="toc"><h2>目次</h2>',
        )))

    def test_h2_outside_toc_requires_id(self):
        self.assert_fail(HTML.replace("</body>", "<h2>追記</h2></body>"))

    def test_h2_outside_toc_requires_link_from_toc(self):
        self.assert_fail(HTML.replace(
            "</body>", '<h2 id="appendix">追記</h2><a href="#appendix">追記</a></body>',
        ), "appendix")

    def test_time_requires_nonempty_datetime(self):
        time = '<time datetime="2026-11-20">11月20日</time>'
        for replacement in ("", "<time>11月20日</time>", '<time datetime="">11月20日</time>'):
            with self.subTest(replacement=replacement):
                self.assert_fail(HTML.replace(time, replacement))

    def test_missing_summary_section_fails(self):
        self.assert_fail(HTML.replace('<section id="summary">', '<div id="summary">')
                         .replace("</section>", "</div>"))

    def test_missing_print_media_fails(self):
        self.assert_fail(HTML.replace("@media print", "@media screen"))

    def test_print_media_can_be_in_a_later_style_element(self):
        html = HTML.replace(
            "<style>", "<style>p { color: black; }</style>\n<style>",
        )
        self.assert_pass(self.check_html(html))

    def test_print_media_in_list_or_with_condition_passes(self):
        for query in ("@media screen, print", "@media print and (min-width: 1px)"):
            with self.subTest(query=query):
                self.assert_pass(self.check_html(HTML.replace("@media print", query)))

    def test_print_media_only_in_css_comment_fails(self):
        html = HTML.replace("<style>", "<style>/* ").replace("</style>", " */</style>")
        self.assert_fail(html)

    def test_print_media_only_in_style_attribute_fails(self):
        html = HTML.replace("@media print", "@media screen").replace(
            "<p>作業を完了した。</p>",
            '<p style="@media print { color: black; }">作業を完了した。</p>',
        )
        self.assert_fail(html)

    def test_polite_words_in_body_text_fail(self):
        for word in ("です", "でした", "でしょう", "ます", "ました", "ません", "ましょう"):
            with self.subTest(word=word):
                self.assert_fail(HTML.replace("作業を完了した。", f"作業{word}。"), word)

    def test_polite_word_substrings_in_body_text_pass(self):
        for phrase in ("ですべて", "ですぐ", "ですでに", "ますます"):
            with self.subTest(phrase=phrase):
                self.assert_pass(self.check_html(HTML.replace("作業を完了した。", phrase)))

    def test_polite_words_before_punctuation_newline_or_particle_fail(self):
        for phrase, word in (("確認です。", "です"), ("行います\n", "ます"), ("ですが", "です")):
            with self.subTest(phrase=phrase):
                self.assert_fail(HTML.replace("作業を完了した。", phrase), word)

    def test_polite_word_in_title_fails(self):
        self.assert_fail(HTML.replace("<title>作業記録</title>", "<title>手順書です</title>"), "です")

    def test_polite_word_failure_reports_actual_line_and_surrounding_text(self):
        sentence = "手順を確認です。次に進む"
        html = HTML.replace("<p>作業を完了した。</p>", f"<p>\n\n\n{sentence}\n</p>")
        line_number = html.splitlines().index(sentence) + 1

        result = self.check_html(html)
        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, result.stdout)
        self.assertRegex(lines[0], r"^FAIL: \s*\S")
        self.assertRegex(lines[0], rf"(?<!\d){line_number}(?!\d)")
        self.assertIn(sentence, lines[0])

    def test_polite_words_in_exempt_text_and_attributes_pass(self):
        for fragment in (
            '<script>const label = "完了です";</script>',
            '<style>p::after { content: "完了です"; }</style>',
            "<code>完了です</code>",
            "<pre>完了です</pre>",
            '<img src="#embedded" alt="完了です">',
            '<p title="完了です">結果</p>',
        ):
            with self.subTest(fragment=fragment):
                self.assert_pass(self.check_html(HTML.replace("</body>", fragment + "</body>")))

    def test_reports_both_violations_on_separate_lines(self):
        url = "https://example.test/chart.png"
        html = HTML.replace(
            "</body>", f'<img src="{url}" alt="図"><p>結果です。</p></body>',
        )
        self.assert_fail(html, url, "です")

    def test_missing_file_exits_with_code_two_and_reason(self):
        result = self.run_cli(self.root / "missing.html")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(result.stderr.strip())

    def test_wrong_argument_count_exits_with_code_two_and_reason(self):
        path = self.root / "document.html"
        path.write_text(HTML, encoding="utf-8")
        for args in ((), (path, path)):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
