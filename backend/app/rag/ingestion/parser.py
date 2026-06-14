"""Parser for EUR-Lex ELI-structured HTML (AI Act, GDPR).

Both regulations share the same markup: articles live in
`div.eli-subdivision[id=art_N]` with an `oj-ti-art` number line and an
`oj-sti-art` subtitle; numbered paragraphs are direct child divs; lettered
points sit in two-column tables. Recitals live in `div.eli-subdivision[id=rct_N]`.

Annexes live in `div.eli-container[id=anx_ROMAN]` with two `oj-doc-ti` title
lines. Their bodies mix three shapes: numbered points as `<table>` rows
(sub-points nested as inner tables), numbered points as
`div.oj-enumeration-spacing`, and unnumbered tables (dash lists) or plain
paragraphs that read as preamble. Some annexes group points into sections
(`oj-ti-grseq-1` headings) where point numbering restarts, so section labels
are folded into paragraph refs.
"""

import re
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning


def _make_soup(html: str) -> BeautifulSoup:
    # EUR-Lex serves XHTML with an XML declaration; the lxml HTML parser handles
    # it fine, so silence the advisory warning at the call site (a module-level
    # filter is reset by pytest's warning capture).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(html, "lxml")


def _attr(tag: Tag, name: str) -> str:
    """A tag attribute as a plain string (bs4 may return a list for multi-valued
    attributes; ids and our class checks are always single-valued here)."""
    value = tag.get(name, "")
    if isinstance(value, list):
        return " ".join(value)
    return value or ""


@dataclass
class ParsedParagraph:
    ref: str  # e.g. "Art. 6(1)" or "Recital 4"
    text: str


@dataclass
class ParsedDocument:
    kind: str  # article | recital | annex
    ref: str  # e.g. "Art. 6", "Recital 4", "Annex III"
    title: str
    paragraphs: list[ParsedParagraph] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs)


_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _flatten_block(block: Tag) -> str:
    """Flatten a paragraph container: plain <p> text plus '(a) point' table rows."""
    parts: list[str] = []
    for el in block.find_all(["p", "tr"], recursive=True):
        if el.name == "tr":
            cells = [_clean(td.get_text(" ")) for td in el.find_all("td")]
            cells = [c for c in cells if c]
            if cells:
                parts.append(" ".join(cells))
        elif el.name == "p" and not el.find_parent("table"):
            text = _clean(el.get_text(" "))
            if text:
                parts.append(text)
    # Dedupe while preserving order (nested find_all can revisit content)
    return " ".join(dict.fromkeys(parts))


def parse_articles(soup: BeautifulSoup) -> list[ParsedDocument]:
    docs: list[ParsedDocument] = []
    for div in soup.find_all("div", class_="eli-subdivision", id=re.compile(r"^art_\d+$")):
        number = _attr(div, "id").removeprefix("art_")
        title_el = div.find("p", class_="oj-sti-art")
        title = _clean(title_el.get_text(" ")) if title_el else ""
        doc = ParsedDocument(kind="article", ref=f"Art. {number}", title=title)

        # Numbered paragraphs are child divs with ids like "006.001".
        para_divs = [
            c
            for c in div.find_all("div", recursive=False)
            if re.fullmatch(r"\d+\.\d+", _attr(c, "id"))
        ]
        if para_divs:
            for i, p_div in enumerate(para_divs, start=1):
                text = _flatten_block(p_div)
                if text:
                    doc.paragraphs.append(ParsedParagraph(ref=f"Art. {number}({i})", text=text))
        else:
            # Unnumbered article: everything except the title lines is one block.
            for el in div.find_all("p", class_=["oj-ti-art", "oj-sti-art"]):
                el.decompose()
            text = _flatten_block(div)
            if text:
                doc.paragraphs.append(ParsedParagraph(ref=f"Art. {number}", text=text))
        if doc.paragraphs:
            docs.append(doc)
    return docs


def parse_recitals(soup: BeautifulSoup) -> list[ParsedDocument]:
    docs: list[ParsedDocument] = []
    for div in soup.find_all("div", class_="eli-subdivision", id=re.compile(r"^rct_\d+$")):
        number = _attr(div, "id").removeprefix("rct_")
        text = _flatten_block(div)
        # Strip the leading "(N)" marker that comes from the numbering column.
        text = re.sub(rf"^\({number}\)\s*", "", text)
        if text:
            ref = f"Recital {number}"
            docs.append(
                ParsedDocument(
                    kind="recital",
                    ref=ref,
                    title="",
                    paragraphs=[ParsedParagraph(ref=ref, text=text)],
                )
            )
    return docs


_ANNEX_ID = re.compile(r"^anx_([IVXLCDM]+)$")
_POINT_NUM = re.compile(r"^\d+(?:\.\d+)*\.$")
_SECTION = re.compile(r"^Section\s+([A-Za-z0-9]+)")


def _flatten_annex_container(el: Tag) -> str:
    """Flatten a point container. For tables, walk only top-level rows: nested
    sub-point tables are inlined by get_text in document order, which keeps
    their '(a)' markers without revisiting rows (and thus without duplicates).
    Handles cells that hold bare <span> text instead of <p> (e.g. Annex I)."""
    if el.name != "table":
        return _clean(el.get_text(" "))
    parts: list[str] = []
    for tr in el.find_all("tr"):
        if tr.find_parent("table") is not el:
            continue
        cells = [_clean(td.get_text(" ")) for td in tr.find_all("td", recursive=False)]
        cells = [c for c in cells if c]
        if cells:
            parts.append(" ".join(cells))
    return " ".join(parts)


def _annex_point_number(el: Tag) -> str | None:
    first_p = el.find("p")
    if first_p is None:
        return None
    text = _clean(first_p.get_text(" "))
    return text if _POINT_NUM.fullmatch(text) else None


def parse_annexes(soup: BeautifulSoup) -> list[ParsedDocument]:
    docs: list[ParsedDocument] = []
    for div in soup.find_all("div", class_="eli-container", id=_ANNEX_ID):
        id_match = _ANNEX_ID.match(str(div.get("id", "")))
        if id_match is None:  # find_all already filtered on the pattern
            continue
        ref = f"Annex {id_match.group(1)}"
        titles = [
            _clean(p.get_text(" ")) for p in div.find_all("p", class_="oj-doc-ti", recursive=False)
        ]
        title = titles[1] if len(titles) > 1 else ""
        doc = ParsedDocument(kind="annex", ref=ref, title=title)

        section = ""  # current section label, e.g. "A" or "1"
        run: list[str] = []  # preamble/heading text accumulated since last flush
        run_ends_in_heading = False

        def para_ref(num: str | None = None) -> str:
            base = f"{ref} Sec. {section}" if section else ref  # noqa: B023
            return f"{base}({num})" if num else base

        def flush() -> None:
            nonlocal run, run_ends_in_heading
            text = " ".join(run).strip()
            if text:
                doc.paragraphs.append(ParsedParagraph(ref=para_ref(), text=text))  # noqa: B023
            run = []
            run_ends_in_heading = False

        for child in div.find_all(recursive=False):
            raw_classes: str | list[str] = child.get("class") or []
            classes = [raw_classes] if isinstance(raw_classes, str) else list(raw_classes)
            if child.name == "p" and "oj-doc-ti" in classes:
                continue
            if child.name == "p" and "oj-ti-grseq-1" in classes:
                text = _clean(child.get_text(" "))
                if not text:
                    continue
                # A heading after body text starts a new paragraph; consecutive
                # headings (e.g. "Section 1" + its descriptive line) stay together.
                if run and not run_ends_in_heading:
                    flush()
                m = _SECTION.match(text)
                if m:
                    section = m.group(1)
                run.append(text)
                run_ends_in_heading = True
                continue
            if child.name == "p":
                text = _clean(child.get_text(" "))
                if text:
                    run.append(text)
                    run_ends_in_heading = False
                continue
            if child.name in ("table", "div"):
                num = _annex_point_number(child)
                text = _flatten_annex_container(child)
                if num is None:
                    # Unnumbered content (dash lists, wrapper divs) reads as preamble.
                    if text:
                        run.append(text)
                        run_ends_in_heading = False
                    continue
                flush()
                body = re.sub(rf"^{re.escape(num)}\s*", "", text)
                if body:
                    doc.paragraphs.append(ParsedParagraph(ref=para_ref(num.rstrip(".")), text=body))
        flush()
        if doc.paragraphs:
            docs.append(doc)
    return docs


def parse_corpus_html(html: str) -> list[ParsedDocument]:
    soup = _make_soup(html)
    return parse_articles(soup) + parse_annexes(soup) + parse_recitals(soup)
