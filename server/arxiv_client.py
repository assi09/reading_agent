"""Thin read-only wrapper around the public arXiv Atom API.

No MCP code lives here, so this module can be tested and reused independently.
"""

import re

import feedparser
import httpx

from server.models import Paper

ARXIV_API_URL = "https://export.arxiv.org/api/query"
TIMEOUT_SECONDS = 20.0

# New-style IDs (2507.19570, optionally v2) and old-style IDs (hep-th/9901001).
_NEW_ID = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_OLD_ID = re.compile(r"^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")
_URL_PREFIX = re.compile(r"^(https?://)?(www\.)?(export\.)?arxiv\.org/(abs|pdf)/")


class ArxivError(Exception):
    """Raised when arXiv cannot be reached or returns something unusable."""


class InvalidArxivId(ValueError):
    """Raised when a string is not a syntactically valid arXiv identifier."""


def normalize_arxiv_id(raw: str) -> str:
    """Turn an ID or arXiv URL into a version-less ID, or raise InvalidArxivId."""
    candidate = _URL_PREFIX.sub("", raw.strip()).removesuffix(".pdf")
    if not (_NEW_ID.match(candidate) or _OLD_ID.match(candidate)):
        raise InvalidArxivId(
            f"'{raw}' is not a valid arXiv ID. Expected something like '2507.19570' "
            "or 'hep-th/9901001'."
        )
    return re.sub(r"v\d+$", "", candidate)


def build_phrase_query(query: str) -> str:
    """Exact phrase in the title or abstract: the most on-topic matches."""
    phrase = query.replace('"', "")
    return f'ti:"{phrase}" OR abs:"{phrase}"'


def build_keyword_query(query: str) -> str:
    """Every word anywhere in the record: broader fallback when the phrase finds nothing."""
    return " AND ".join(f"all:{word}" for word in query.replace('"', "").split())


def _parse_entry(entry) -> Paper:
    raw_id = entry.id.rsplit("/abs/", 1)[-1]
    return Paper(
        arxiv_id=re.sub(r"v\d+$", "", raw_id),
        title=" ".join(entry.title.split()),
        authors=[a.name for a in entry.get("authors", [])],
        published=entry.get("published", "")[:10],
        summary=" ".join(entry.get("summary", "").split()),
        url=f"https://arxiv.org/abs/{re.sub(r'v\d+$', '', raw_id)}",
        primary_category=entry.get("arxiv_primary_category", {}).get("term"),
    )


def _fetch(params: dict) -> feedparser.FeedParserDict:
    try:
        response = httpx.get(ARXIV_API_URL, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ArxivError(f"arXiv did not respond within {TIMEOUT_SECONDS:.0f}s.") from exc
    except httpx.HTTPError as exc:
        raise ArxivError(f"arXiv is unavailable ({exc}).") from exc
    feed = feedparser.parse(response.text)
    if feed.bozo and not feed.entries:
        raise ArxivError("arXiv returned a response that could not be parsed.")
    return feed


def search(query: str, max_results: int, sort_by: str) -> tuple[int, list[Paper]]:
    """Search arXiv. Returns (total_matches, papers)."""
    params = {
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate" if sort_by == "date" else "relevance",
        "sortOrder": "descending",
    }
    feed = _fetch({**params, "search_query": build_phrase_query(query)})
    if not feed.entries and len(query.split()) > 1:
        feed = _fetch({**params, "search_query": build_keyword_query(query)})
    total = int(feed.feed.get("opensearch_totalresults", len(feed.entries)))
    return total, [_parse_entry(e) for e in feed.entries]


def get_paper(arxiv_id: str) -> Paper | None:
    """Look up a single paper by (normalized) ID. Returns None if arXiv has no such paper."""
    feed = _fetch({"id_list": arxiv_id, "max_results": 1})
    if not feed.entries:
        return None
    return _parse_entry(feed.entries[0])
