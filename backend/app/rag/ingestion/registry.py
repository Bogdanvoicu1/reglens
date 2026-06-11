from dataclasses import dataclass


@dataclass(frozen=True)
class CorpusSpec:
    slug: str
    title: str
    celex: str
    version: str
    source_url: str


_EURLEX = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex}"

CORPORA: dict[str, CorpusSpec] = {
    "ai-act": CorpusSpec(
        slug="ai-act",
        title="Regulation (EU) 2024/1689 (Artificial Intelligence Act)",
        celex="32024R1689",
        version="OJ-2024-07-12",
        source_url=_EURLEX.format(celex="32024R1689"),
    ),
    "gdpr": CorpusSpec(
        slug="gdpr",
        title="Regulation (EU) 2016/679 (General Data Protection Regulation)",
        celex="32016R0679",
        version="OJ-2016-05-04",
        source_url=_EURLEX.format(celex="32016R0679"),
    ),
}
