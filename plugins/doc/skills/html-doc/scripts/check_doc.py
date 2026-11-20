#!/usr/bin/env python3
"""単一の HTML 文書が html-doc の契約を満たすか検査する。"""

from html.parser import HTMLParser
from pathlib import Path
import re
import sys


RESOURCE_ATTRIBUTES = {
    "link": "href",
    "script": "src",
    "img": "src",
    "source": "src",
    "iframe": "src",
    "video": "src",
    "audio": "src",
}
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
EXEMPT_TEXT = {"head", "script", "style", "code", "pre"}
POLITE_WORD = re.compile("です|でした|でしょう|ます|ました|ません|ましょう")
CSS_COMMENT = r"/\*[\s\S]*?(?:\*/|\Z)"
CSS_SPACE = rf"(?:[ \t\n\r\f]|{CSS_COMMENT})"
CSS_STRING = r""""(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'"""
CSS_TOKENS = re.compile(
    rf"""
    {CSS_COMMENT}
    | (?<![\w-]) @import (?![\w-]) {CSS_SPACE}* (?P<import_value>{CSS_STRING})
    | (?<![\w@-]) url\( [ \t\n\r\f]*
      (?P<url_value>{CSS_STRING}|(?:\\[\s\S]|[^"'()\\])*?) [ \t\n\r\f]* \)
    | (?<![\w-]) (?P<print_media>@media {CSS_SPACE}+ print(?![\w-]))
    | {CSS_STRING}
    """,
    re.IGNORECASE | re.VERBOSE,
)


class DocumentCheck(HTMLParser):
    CDATA_CONTENT_ELEMENTS = (
        "script", "style", "iframe", "noembed", "noframes", "textarea", "title", "xmp",
    )

    def __init__(self):
        super().__init__()
        self.elements = []
        self.failures = []
        self.has_toc = False
        self.toc_links = []
        self.heading_ids = set()
        self.outside_headings = []
        self.has_datetime = False
        self.has_summary = False
        self.has_print_media = False

    def check_reference(self, location, value):
        if not value.startswith(("data:", "#")):
            self.failures.append(f"{location} の外部参照 {value!r}")

    def check_css(self, css, location):
        for token in CSS_TOKENS.finditer(css):
            value = token["import_value"]
            if value is None:
                value = token["url_value"]
            if value is not None:
                if value.startswith(('"', "'")):
                    value = value[1:-1]
                self.check_reference(location, value)
            elif token["print_media"] and location == "<style>":
                self.has_print_media = True

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        resource = RESOURCE_ATTRIBUTES.get(tag)
        if resource in attributes:
            self.check_reference(f"<{tag} {resource}>", attributes[resource] or "")
        if attributes.get("style"):
            self.check_css(attributes["style"], f"<{tag} style>")

        if tag == "nav" and element_id == "toc":
            self.has_toc = True
        elif tag == "section" and element_id == "summary":
            self.has_summary = True
        elif tag == "time" and "datetime" in attributes:
            self.has_datetime = True
            if not (attributes["datetime"] or "").strip():
                self.failures.append('<time> の datetime が空 ("")')

        inside_toc = ("nav", "toc", None) in self.elements
        heading_text = None
        if tag == "a" and inside_toc:
            href = attributes.get("href") or ""
            if href.startswith("#"):
                self.toc_links.append(href[1:])
        elif tag in {"h2", "h3"}:
            if element_id:
                self.heading_ids.add(element_id)
            if tag == "h2" and not inside_toc:
                heading_text = []
                self.outside_headings.append((element_id, heading_text, self.getpos()[0]))

        if tag not in VOID_ELEMENTS:
            self.elements.append((tag, element_id, heading_text))

    def handle_endtag(self, tag):
        for index in range(len(self.elements) - 1, -1, -1):
            if self.elements[index][0] == tag:
                del self.elements[index:]
                break

    def handle_data(self, data):
        if self.elements and self.elements[-1][0] == "style":
            self.check_css(data, "<style>")
        if any(tag in EXEMPT_TEXT for tag, _, _ in self.elements):
            return

        for _, _, heading_text in reversed(self.elements):
            if heading_text is not None:
                heading_text.append(data)
                break
        for word in POLITE_WORD.finditer(data):
            self.failures.append(f"本文の敬体表現 {word[0]!r}（{self.getpos()[0]} 行目）")

    def finish(self):
        if not self.has_toc:
            self.failures.append('<nav id="toc"> がない')
        for target in self.toc_links:
            if target not in self.heading_ids:
                self.failures.append(f"目次のリンク {'#' + target!r} に対応する h2 または h3 がない")
        linked_ids = set(self.toc_links)
        for element_id, heading_text, line in self.outside_headings:
            if not element_id:
                heading = "".join(heading_text).strip()
                self.failures.append(f"h2 {heading!r} に id がない（{line} 行目）")
            elif self.has_toc and element_id not in linked_ids:
                self.failures.append(f"h2 の id {element_id!r} への目次リンクがない")
        if not self.has_datetime:
            self.failures.append("<time datetime> がない")
        if not self.has_summary:
            self.failures.append('<section id="summary"> がない')
        if not self.has_print_media:
            self.failures.append("<style> に @media print がない")
        return self.failures


def main(args):
    if len(args) != 1:
        print("使い方: check_doc.py <file.html>", file=sys.stderr)
        return 2
    try:
        html = Path(args[0]).read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"HTML を読めない {args[0]!r}: {error}", file=sys.stderr)
        return 2

    check = DocumentCheck()
    check.feed(html)
    check.close()
    failures = check.finish()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
