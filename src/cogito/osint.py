from __future__ import annotations

import html
import re
import sqlite3
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .db import default_db_path
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
    return research_target_with_receipt(conn, target=target, source=source, limit=limit)["created"]


def research_target_with_receipt(
    conn: sqlite3.Connection,
    *,
    target: str,
    source: str,
    limit: int = 8,
) -> dict[str, Any]:
    target_name = target.removeprefix("@")
    collection = collect_osint_documents(source, limit=limit)
    documents = collection["documents"]
    created: list[dict[str, Any]] = []
    saved_chunks: list[dict[str, str]] = []
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
                saved_chunks.append(
                    {
                        "store": "user_memory",
                        "id": memory["id"],
                        "source_url": document["url"],
                        "preview": preview_text(chunk),
                    }
                )
            else:
                item = add_persona_knowledge(
                    conn,
                    persona_name=target_name,
                    text=chunk,
                    knowledge_type="public_research",
                    source_url=document["url"],
                    confidence=0.65,
                )
                created.append(item)
                saved_chunks.append(
                    {
                        "store": "persona_rag",
                        "id": item["id"],
                        "source_url": document["url"],
                        "preview": preview_text(chunk),
                    }
                )
    return collection | {"target": target, "created": created, "saved_chunks": saved_chunks}


def research_target_with_browser_receipt(
    conn: sqlite3.Connection,
    *,
    target: str,
    source: str,
    limit: int = 8,
    wait_seconds: float = 10.0,
) -> dict[str, Any]:
    collection = collect_browser_documents(source, limit=limit, wait_seconds=wait_seconds)
    return save_research_collection(conn, target=target, collection=collection)


def save_research_collection(
    conn: sqlite3.Connection,
    *,
    target: str,
    collection: dict[str, Any],
) -> dict[str, Any]:
    target_name = target.removeprefix("@")
    documents = collection["documents"]
    created: list[dict[str, Any]] = []
    saved_chunks: list[dict[str, str]] = []
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
                saved_chunks.append(
                    {
                        "store": "user_memory",
                        "id": memory["id"],
                        "source_url": document["url"],
                        "preview": preview_text(chunk),
                    }
                )
            else:
                item = add_persona_knowledge(
                    conn,
                    persona_name=target_name,
                    text=chunk,
                    knowledge_type="public_research",
                    source_url=document["url"],
                    confidence=0.65,
                )
                created.append(item)
                saved_chunks.append(
                    {
                        "store": "persona_rag",
                        "id": item["id"],
                        "source_url": document["url"],
                        "preview": preview_text(chunk),
                    }
                )
    return collection | {"target": target, "created": created, "saved_chunks": saved_chunks}


def collect_osint_documents(source: str, *, limit: int) -> dict[str, Any]:
    urls: list[str] = []
    if is_url(source):
        urls.append(source)
        query = query_from_url(source)
    else:
        query = source
    discovered = search_web(query, limit=limit)
    urls.extend(discovered)
    documents = []
    scanned: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            text = fetch_readable_text(url)
        except Exception as exc:
            failed.append({"url": url, "error": str(exc)})
            continue
        if text:
            document = {"url": url, "text": text}
            documents.append(document)
            scanned.append({"url": url, "chars": len(text), "preview": preview_text(text)})
        else:
            failed.append({"url": url, "error": "no readable text"})
        if len(documents) >= limit:
            break
    return {
        "query": query,
        "seed_urls": [source] if is_url(source) else [],
        "discovered_urls": discovered,
        "scanned_sources": scanned,
        "failed_sources": failed,
        "documents": documents,
    }


def collect_browser_documents(source: str, *, limit: int, wait_seconds: float) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("browser research needs playwright; run: .venv/bin/pip install -e .") from exc

    query = query_from_url(source) if is_url(source) else source
    target_url = source if is_url(source) else "https://duckduckgo.com/?" + urllib.parse.urlencode({"q": source})
    profile_dir = browser_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                channel="chrome",
                viewport={"width": 1440, "height": 1000},
            )
        except Exception:
            try:
                context = p.chromium.launch_persistent_context(
                    str(profile_dir),
                    headless=False,
                    viewport={"width": 1440, "height": 1000},
                )
            except Exception as exc:
                raise RuntimeError(
                    "browser research needs Chrome or Playwright Chromium; "
                    "install Chrome or run: .venv/bin/python -m playwright install chromium"
                ) from exc
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        if wait_seconds > 0:
            page.wait_for_timeout(int(wait_seconds * 1000))
        current_url = page.url
        title = page.title()
        text = page.locator("body").inner_text(timeout=10_000)
        links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(a => a.href).filter(Boolean).slice(0, 50)",
        )
        context.close()
    documents = [{"url": current_url, "text": f"{title}\n{text}"}] if text.strip() else []
    return {
        "query": query,
        "seed_urls": [source] if is_url(source) else [],
        "discovered_urls": [url for url in links if isinstance(url, str)][:limit],
        "scanned_sources": [
            {"url": current_url, "chars": len(text), "preview": preview_text(text)}
        ] if text.strip() else [],
        "failed_sources": [] if text.strip() else [{"url": current_url, "error": "no visible text"}],
        "documents": documents,
        "browser_profile": str(profile_dir),
    }


def browser_profile_dir() -> Path:
    return default_db_path().parent / "browser-profile"


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


def preview_text(value: str, *, max_chars: int = 160) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."
