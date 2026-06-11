"""Parser for EUR-Lex ELI-structured HTML (AI Act, GDPR).

Both regulations share the same markup: articles live in
`div.eli-subdivision[id=art_N]` with an `oj-ti-art` number line and an
`oj-sti-art` subtitle; numbered paragraphs are direct child divs; lettered
points sit in two-column tables. Recitals live in `div.eli-subdivision[id=rct_N]`.
"""

import re
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

# EUR-Lex serves XHTML with an XML declaration; the lxml HTML parser handles it
# fine, so silence the advisory warning.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


@dataclass
class ParsedParagraph:
    ref: str  # e.g. "Art. 6(1)" or "Recital 4"
    text: str


@dataclass
class ParsedDocument:
    kind: str  # article | recital
    ref: str  # e.g. "Art. 6" or "Recital 4"
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
    seen: set[str] = set()
    unique = [p for p in parts if not (p in seen or seen.add(p))]
    return " ".join(unique)


def parse_articles(soup: BeautifulSoup) -> list[ParsedDocument]:
    docs: list[ParsedDocument] = []
    for div in soup.find_all("div", class_="eli-subdivision", id=re.compile(r"^art_\d+$")):
        number = div.get("id", "").removeprefix("art_")
        title_el = div.find("p", class_="oj-sti-art")
        title = _clean(title_el.get_text(" ")) if title_el else ""
        doc = ParsedDocument(kind="article", ref=f"Art. {number}", title=title)

        # Numbered paragraphs are child divs with ids like "006.001".
        para_divs = [
            c
            for c in div.find_all("div", recursive=False)
            if re.fullmatch(r"\d+\.\d+", c.get("id", "") or "")
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
        number = div.get("id", "").removeprefix("rct_")
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


def parse_corpus_html(html: str) -> list[ParsedDocument]:
    soup = BeautifulSoup(html, "lxml")
    return parse_articles(soup) + parse_recitals(soup)
