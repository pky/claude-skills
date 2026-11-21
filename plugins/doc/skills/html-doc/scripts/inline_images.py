#!/usr/bin/env python3
"""HTML の画像を data URI として埋め込む。"""

from base64 import b64encode
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from struct import unpack_from
import sys


MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
UNCHANGED_PREFIXES = ("data:", "http://", "https://", "//", "#")
PNG_IHDR_PREFIX = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
ATTRIBUTE = re.compile(
    r"""
    (?P<name>[^\s=/>'"]+)
    (?:[ \t\n\r\f]* = [ \t\n\r\f]*
       (?:"(?P<double>[^"]*)" | '(?P<single>[^']*)' | (?P<bare>[^ \t\n\r\f>]+))
    )?
    """,
    re.VERBOSE,
)


class ImageSources(HTMLParser):
    CDATA_CONTENT_ELEMENTS = (
        "script", "style", "iframe", "noembed", "noframes", "textarea", "title", "xmp",
    )

    def __init__(self, html):
        super().__init__()
        self.line_starts = [0, *(match.end() for match in re.finditer("\n", html))]
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        raw_tag = self.get_starttag_text()
        line, column = self.getpos()
        tag_start = self.line_starts[line - 1] + column
        # パーサーが見つけたタグから属性値の範囲を取得する。
        for attribute in ATTRIBUTE.finditer(raw_tag, len("<img")):
            if attribute["name"].lower() != "src" or attribute.lastgroup == "name":
                continue
            start, end = attribute.span(attribute.lastgroup)
            self.sources.append((
                tag_start + start, tag_start + end, tag_start, tag_start + len(raw_tag), attrs,
            ))
            break


def png_svg(image_path, contents, uri, attributes):
    # PNG の署名、チャンクヘッダー、IHDR のデータと CRC で計 33 バイト。
    if len(contents) < 33 or not contents.startswith(PNG_IHDR_PREFIX):
        raise ValueError(f"PNG の IHDR を読めない: {str(image_path)!r}")
    width, height = unpack_from(">II", contents, len(PNG_IHDR_PREFIX))
    if not width or not height:
        raise ValueError(f"PNG の幅または高さが 0: {str(image_path)!r}")

    svg_attributes = ['xmlns="http://www.w3.org/2000/svg"', 'role="img"']
    title = ""
    if "alt" in attributes:
        alt = escape(attributes["alt"] or "")
        svg_attributes.append(f'aria-label="{alt}"')
        title = f"<title>{alt}</title>"
    svg_attributes.append(f'viewBox="0 0 {width} {height}"')
    for name in ("id", "class", "width", "height"):
        if name in attributes:
            svg_attributes.append(f'{name}="{escape(attributes[name] or "")}"')
    return (
        f'<svg {" ".join(svg_attributes)}>{title}'
        f'<image href="{uri}" width="{width}" height="{height}"/></svg>'
    )


def embed_images(html, directory):
    parser = ImageSources(html)
    parser.feed(html)
    parser.close()

    parts = []
    previous_end = count = 0
    for start, end, tag_start, tag_end, attrs in parser.sources:
        src = unescape(html[start:end])
        if src.startswith(UNCHANGED_PREFIXES):
            continue
        image_path = directory / src
        mime = MIME_TYPES.get(image_path.suffix.lower())
        if mime is None:
            raise ValueError(f"未対応の画像拡張子: {str(image_path)!r}")
        contents = image_path.read_bytes()
        payload = b64encode(contents).decode("ascii")
        replacement = f"data:{mime};base64,{payload}"
        if mime == "image/png":
            start, end = tag_start, tag_end
            replacement = png_svg(image_path, contents, replacement, dict(attrs))
        parts.extend((html[previous_end:start], replacement))
        previous_end = end
        count += 1
    parts.append(html[previous_end:])
    return "".join(parts), count


def main(args):
    if len(args) != 2:
        print("使い方: inline_images.py <in.html> <out.html>", file=sys.stderr)
        return 2

    source, output = map(Path, args)
    try:
        html = source.read_bytes().decode("utf-8", errors="surrogateescape")
    except (OSError, ValueError) as error:
        print(f"入力 HTML を読めない {str(source)!r}: {error}", file=sys.stderr)
        return 2

    try:
        if output.exists() and source.samefile(output):
            raise ValueError(f"入力と出力が同じファイル: {str(output)!r}")
        result, count = embed_images(html, source.parent)
        output.write_bytes(result.encode("utf-8", errors="surrogateescape"))
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"inlined {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
