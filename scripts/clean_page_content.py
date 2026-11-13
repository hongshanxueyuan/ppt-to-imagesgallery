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
BLOCKQUOTE_PREFIX_RE = re.compile(r"(?m)^ {0,3}(?:>[ ]*)+")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(?<!\\)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
LIST_ITEM_RE = re.compile(r"^([ \t]*)(?:[-+*]|\d+[.)])([ \t]+)")


def _protect_markdown_code(text: str) -> tuple[str, dict[str, str]]:
    decoded = text
    while True:
        next_decoded = unescape(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    # The sentinel must remain absent even after entity decoding and HTML tag removal.
    used = set(decoded)
    sentinel = next(chr(value) for value in range(0xE000, 0x110000) if chr(value) not in used)
    protected = {}

    def protect(value: str) -> str:
        token = f"{sentinel}{len(protected)}{sentinel}"
        protected[token] = value
        return token

    lines = []
    fence = None
    indented_code = False
    previous_blank = True
    lists = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        marker = FENCE_RE.match(line)
        list_item = LIST_ITEM_RE.match(line)
        indent = len(line) - len(line.lstrip(" ")) if not line.startswith("\t") else 4
        code_indent = lists[-1][1] + 4 if lists else 4
        if fence is not None:
            lines.append(protect(line))
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and not line[marker.end():].strip():
                fence = None
        elif indent >= code_indent and (indented_code or previous_blank):
            indented_code = True
            lines.append(protect(line))
        elif marker:
            fence = marker.group(1)
            indented_code = False
            if lists and indent <= lists[0][0]:
                lists = []
            lines.append(protect(line))
        elif not line.strip():
            lines.append("")
        else:
            indented_code = False
            if list_item:
                item_indent = len(list_item.group(1).replace("\t", "    "))
                while lists and lists[-1][0] >= item_indent:
                    lists.pop()
                lists.append((item_indent, len(line[:list_item.end()].replace("\t", "    "))))
            elif lists and indent <= lists[0][0]:
                lists = []
            lines.append(INLINE_CODE_RE.sub(lambda match: protect(match.group(0)), line))
        previous_blank = not line.strip()
    return "\n".join(lines), protected


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
    """Decode HTML, remove markup, and strip line-leading blockquote prefixes."""
    decoded, protected = _protect_markdown_code(text)
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
    visible_text = BLOCKQUOTE_PREFIX_RE.sub("", visible_text)
    lines = []
    fence = None
    for line in visible_text.split("\n"):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            lines.append(line)
        elif fence is not None or line.startswith(("    ", "\t")):
            lines.append(line)
        elif line.strip():
            match = re.fullmatch(r"([ \t]*)(.*?)([ \t]*)", line)
            leading, body, trailing = match.groups()
            # Two or more trailing spaces are a Markdown hard line break.
            lines.append(leading + HORIZONTAL_WHITESPACE_RE.sub(" ", body) + ("  " if len(trailing) >= 2 else ""))
        else:
            lines.append("")
    result = "\n".join(lines).strip("\n")
    for token, original in protected.items():
        result = result.replace(token, original)
    return result
