from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re


BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "body",
    "caption",
    "dd",
    "details",
    "dialog",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "legend",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "summary",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}
HIDDEN_TAGS = {"script", "style"}
HORIZONTAL_WHITESPACE_RE = re.compile(r"[^\S\n]+")
INCOMPLETE_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s[^<>]*)?$")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_tag: str | None = None

    def _add_line_break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.hidden_tag:
            return
        if tag in HIDDEN_TAGS:
            self._add_line_break()
            self.hidden_tag = tag
            return
        if tag == "br" or tag in BLOCK_TAGS:
            self._add_line_break()

    def handle_endtag(self, tag: str) -> None:
        if self.hidden_tag:
            if tag == self.hidden_tag:
                self.hidden_tag = None
                self._add_line_break()
            return
        if tag in BLOCK_TAGS:
            self._add_line_break()

    def handle_data(self, data: str) -> None:
        if not self.hidden_tag:
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        return


def clean_page_content(text: str) -> str:
    """Decode HTML character references and remove markup from page speech."""
    decoded = text
    while True:
        next_decoded = unescape(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded

    parser = _VisibleTextParser()
    parser.feed(decoded)
    incomplete_tag = parser.rawdata
    parser.close()

    visible_text = "".join(parser.parts)
    if not parser.hidden_tag and INCOMPLETE_TAG_RE.fullmatch(incomplete_tag):
        visible_text += incomplete_tag
    visible_text = visible_text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines = [HORIZONTAL_WHITESPACE_RE.sub(" ", line).strip() for line in visible_text.split("\n")]
    return "\n".join(lines).strip()
