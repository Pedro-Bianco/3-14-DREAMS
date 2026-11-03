"""Where the deep research searches and reads, without any account (maintainer's choice):
Wikipedia (official API, PT and EN), Google News headlines, and DuckDuckGo only while it is not
blocking. Measured on 2026-11-03: DuckDuckGo answers "202" (anti-bot) from the 3rd search in a row
and then stays blocked even with 12 s between searches; the Wikipedia API answered 10/10 in 3.4 s.
"""

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from pidreams import USER_AGENT

log = logging.getLogger(__name__)

_AGENT = {"User-Agent": USER_AGENT}
PAGE_CHARS = 6000            # per source: enough for the notes, and 12 of them never meet in one prompt
_DDG_PAUSE_S = 30 * 60       # once DuckDuckGo blocks, leave it alone for a while
_ddg_blocked_until = 0.0


# Wikipedia limits by address when a lot comes at once (3 researches in a few minutes: ~75 calls).
# After a few 429s in one research it is left alone instead of waiting ~20 s per source.
# Per language: the Portuguese Wikipedia limited this address while the English one kept answering.
_wiki_limited: dict[str, int] = {}


def wiki_limited(lang: str | None = None) -> bool:
    """One language (or, with None, every language tried) is refusing calls right now."""
    if lang is not None:
        return _wiki_limited.get(lang, 0) >= 3
    return bool(_wiki_limited) and all(n >= 3 for n in _wiki_limited.values())


def reset_wiki_limit() -> None:
    _wiki_limited.clear()


_WIKI_GAP_S = 0.6          # between Wikipedia calls: at ~0.17 s apart it answered 429 after a busy day
_last_wiki = 0.0


def _get(url: str, timeout: float = 15, headers: dict | None = None) -> bytes:
    """GET with a polite pace for Wikipedia and up to 2 retries on 429, waiting what it asks."""
    global _last_wiki
    wiki = "wikipedia.org" in url
    for attempt in range(3):
        if wiki:
            wait = _last_wiki + _WIKI_GAP_S - time.time()
            if wait > 0:
                time.sleep(wait)
            _last_wiki = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or _AGENT), timeout=timeout) as r:
                if r.status == 202:
                    raise BlockedError("202")
                return r.read()
        except urllib.error.HTTPError as e:
            lang = url.split("//")[1].split(".")[0] if wiki else ""
            if e.code == 429 and wiki:
                _wiki_limited[lang] = _wiki_limited.get(lang, 0) + 1
            if e.code != 429 or attempt == 2 or (wiki and wiki_limited(lang)):
                raise
            delay = min(10.0, float(e.headers.get("Retry-After") or 2 * (attempt + 1)))
            log.info(f"[Research] 429 from {url.split('/')[2]}; waiting {delay:.0f} s")
            time.sleep(delay)


class BlockedError(Exception):
    pass


# ── Wikipedia ──

def wiki_search(query: str, lang: str = "pt", limit: int = 2) -> list[dict]:
    """[{title, url, lang, text}] of the best articles, with each one's opening section, in ONE call
    (search + extracts together): reading a whole article per source made ~25 calls a research and
    Wikipedia started answering 429."""
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "generator": "search", "gsrsearch": query, "gsrlimit": limit, "prop": "extracts",
         "exintro": 1, "explaintext": 1, "exlimit": "max", "redirects": 1, "format": "json"})
    pages = json.loads(_get(url)).get("query", {}).get("pages", {})
    hits = sorted(pages.values(), key=lambda p: p.get("index", 99))
    return [{"title": p["title"], "lang": lang, "origin": f"wikipedia-{lang}", "text": p.get("extract", ""),
             "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(p['title'].replace(' ', '_'))}"}
            for p in hits]


def wiki_text(title: str, lang: str = "pt") -> str:
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title, "format": "json"})
    pages = json.loads(_get(url))["query"]["pages"]
    return next(iter(pages.values())).get("extract", "")


# ── news and the open web ──

def news(query: str) -> list[dict]:
    """Recent headlines about the topic, as one source: [{title, url, text}] (empty if none)."""
    from pidreams.monitor import sources as monitor_sources
    try:
        items = monitor_sources.parse_google_rss(_get(
            "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": f"{query} when:30d", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}),
            12, {"User-Agent": "Mozilla/5.0 PI-dreams"}), limit=10)
    except Exception as e:
        log.warning(f"[Research] news: {e}")
        return []
    if not items:
        return []
    lines = "\n".join(f"- {i['title']} ({i['source']}, {i['date']})" for i in items)
    return [{"title": f"Manchetes recentes sobre {query} (Google Notícias)", "origin": "noticias",
             "url": "https://news.google.com/search?" + urllib.parse.urlencode({"q": query, "hl": "pt-BR"}),
             "text": lines}]


def web_search(query: str, limit: int = 3) -> list[dict]:
    """[{title, url}] from DuckDuckGo, or [] while it is blocking (no retries: it only gets worse)."""
    global _ddg_blocked_until
    if time.time() < _ddg_blocked_until:
        return []
    from pidreams.agent import tools
    try:
        body = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query), 12,
                    tools._BROWSER_HEADERS).decode("utf-8", "ignore")
    except Exception as e:
        _ddg_blocked_until = time.time() + _DDG_PAUSE_S
        log.info(f"[Research] DuckDuckGo unavailable ({e}); skipping it for {_DDG_PAUSE_S // 60} min")
        return []
    return parse_ddg(body)[:limit]


def parse_ddg(body: str) -> list[dict]:
    import html as html_mod
    out = []
    for href, title in re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        m = re.search(r"uddg=([^&]+)", href)
        url = urllib.parse.unquote(m.group(1)) if m else html_mod.unescape(href)
        if url.startswith("http") and "duckduckgo.com" not in url:
            out.append({"title": html_mod.unescape(re.sub("<[^>]+>", "", title)).strip(), "url": url, "origin": "web"})
    return out


def page_text(url: str) -> str:
    """Readable text of an ordinary page ("" when it has none without JavaScript)."""
    from pidreams.agent import tools
    text = tools._scrape_static(url)
    return text if len(text.strip()) >= tools._SCRAPE_JS_THRESHOLD else ""


def useful_part(text: str, keywords: list[str], limit: int = PAGE_CHARS) -> str:
    """The start of the text plus the paragraphs that mention the questions' words, up to `limit`."""
    if len(text) <= limit:
        return text
    words = {w for k in keywords for w in re.findall(r"\w{5,}", k.lower())}
    paragraphs = [p for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    head, picked, size = [], [], 0
    for p in paragraphs[:3]:
        head.append(p)
        size += len(p)
    for p in paragraphs[3:]:
        if size >= limit:
            break
        if any(w in p.lower() for w in words):
            picked.append(p)
            size += len(p)
    return "\n".join(head + picked)[:limit]
