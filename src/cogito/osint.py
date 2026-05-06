from __future__ import annotations

import html
import re
import sqlite3
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from .embeddings import ensure_memory_embedding
from .memory import add_memory, list_memories
from .persona_knowledge import add_persona_knowledge, chunk_text, list_persona_knowledge


USER_AGENT = "cogito-ergo-sum/0.1 (+local user research)"


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        if tag in {"p", "br", "li", "div", "section", "article", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
        if tag in {"p", "li", "div", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape(" ".join(self.parts))
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n\s+", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self.links.append(html.unescape(href))


def research_target(
    conn: sqlite3.Connection,
    *,
    target: str,
    source: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    target_name = target.removeprefix("@")
    documents = collect_osint_documents(source, limit=limit)
    created: list[dict[str, Any]] = []
    seen = existing_texts(conn, target_name)
    for document in documents:
        for chunk in chunk_text(document["text"], max_chars=700)[:3]:
            text = f"{chunk} (source: {document['url']})"
            normalized = normalize_text(text)
            if len(normalized) < 80 or normalized in seen:
                continue
            seen.add(normalized)
            if target_name == "me":
                memory = add_memory(
                    conn,
                    text=text,
                    memory_type="public_research",
                    sensitivity="professional",
                    contexts=["professional", "public", "web"],
                    confidence=0.65,
                )
                try:
                    memory = ensure_memory_embedding(conn, memory)
                except Exception:
                    pass
                created.append(memory)
            else:
                created.append(
                    add_persona_knowledge(
                        conn,
                        persona_name=target_name,
                        text=chunk,
                        knowledge_type="public_research",
                        source_url=document["url"],
                        confidence=0.65,
                    )
                )
    return created


def collect_osint_documents(source: str, *, limit: int) -> list[dict[str, str]]:
    urls: list[str] = []
    if is_url(source):
        urls.append(source)
        query = query_from_url(source)
    else:
        query = source
    urls.extend(search_web(query, limit=limit))
    documents = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            text = fetch_readable_text(url)
        except Exception:
            continue
        if text:
            documents.append({"url": url, "text": text})
        if len(documents) >= limit:
            break
    return documents


def search_web(query: str, *, limit: int) -> list[str]:
    search_url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    html_text = fetch_raw(search_url)
    parser = LinkExtractor()
    parser.feed(html_text)
    urls: list[str] = []
    for href in parser.links:
        url = unwrap_search_url(href)
        if not url or not url.startswith(("http://", "https://")):
            continue
        host = urllib.parse.urlparse(url).netloc.lower()
        if "duckduckgo.com" in host:
            continue
        if url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def fetch_readable_text(url: str) -> str:
    parser = TextExtractor()
    parser.feed(fetch_raw(url))
    return parser.text()


def fetch_raw(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as response:
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return ""
        return response.read(1_000_000).decode("utf-8", errors="replace")


def unwrap_search_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    if href.startswith("/l/"):
        return query.get("uddg", [""])[0]
    return href


def query_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path)
    parts = [
        part
        for part in re.split(r"[/_\-]+", path)
        if part
        and part not in {"in", "pub", "profile"}
        and not part.isdigit()
        and not re.search(r"\d", part)
    ]
    if parts:
        return " ".join(parts)
    return parsed.netloc


def is_url(value: str) -> bool:
    return urllib.parse.urlparse(value).scheme in {"http", "https"}


def existing_texts(conn: sqlite3.Connection, target_name: str) -> set[str]:
    if target_name == "me":
        return {normalize_text(memory["text"]) for memory in list_memories(conn)}
    try:
        return {
            normalize_text(item["text"] + (f" (source: {item['source_url']})" if item.get("source_url") else ""))
            for item in list_persona_knowledge(conn, persona_name=target_name)
        }
    except KeyError:
        return set()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()
