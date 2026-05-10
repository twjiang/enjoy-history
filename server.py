#!/usr/bin/env python3
"""本地十三经/二十四史文献检索服务。"""
from __future__ import annotations

import json
import mimetypes
import re
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STRUCTURED_DIR = ROOT / "data_structured"
CATALOG_PATH = STRUCTURED_DIR / "catalog.json"
CHAPTER_RE = re.compile(r"^(?:【(.+?)】|##\s+(.+?))\s*$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?])")
MAX_SEGMENT_LEN = 260
DEFAULT_DETAIL_LIMIT = 100

try:
    import opencc  # type: ignore

    _CONVERTER = opencc.OpenCC("s2t.json")
except Exception:  # pragma: no cover - optional dependency
    _CONVERTER = None

_BOOKS: list[dict[str, Any]] | None = None


def to_traditional(text: str) -> str:
    if _CONVERTER is None:
        return text
    return _CONVERTER.convert(text)


def normalize(text: str) -> str:
    return text.lower()


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def build_query_groups(query: str) -> tuple[list[list[str]], list[str]]:
    raw_terms = [term.strip() for term in re.split(r"\s+", query.strip()) if term.strip()]
    groups: list[list[str]] = []
    highlight_terms: list[str] = []
    for term in raw_terms:
        variants = unique([term, to_traditional(term)])
        groups.append([normalize(item) for item in variants])
        highlight_terms.extend(variants)
    return groups, unique(highlight_terms)


def split_long_piece(piece: str) -> list[str]:
    if len(piece) <= MAX_SEGMENT_LEN:
        return [piece]
    return [piece[i : i + MAX_SEGMENT_LEN] for i in range(0, len(piece), MAX_SEGMENT_LEN)]


def split_segments(line: str) -> list[str]:
    line = line.strip()
    if not line:
        return []

    pieces = [piece for piece in SENTENCE_SPLIT_RE.split(line) if piece]
    segments: list[str] = []
    current = ""

    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) > MAX_SEGMENT_LEN:
            if current:
                segments.append(current)
                current = ""
            segments.extend(split_long_piece(piece))
        elif len(current) + len(piece) <= MAX_SEGMENT_LEN:
            current += piece
        else:
            if current:
                segments.append(current)
            current = piece

    if current:
        segments.append(current)
    return segments or [line]


def parse_chapters(text: str) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    current_title = "未分章"
    current_lines: list[tuple[int, str]] = []
    current_start_line = 1

    def flush() -> None:
        nonlocal current_lines
        while current_lines and not current_lines[0][1].strip():
            current_lines.pop(0)
        while current_lines and not current_lines[-1][1].strip():
            current_lines.pop()

        if not current_lines:
            return
        if current_title == "未分章" and not chapters and all(line.strip().startswith("#") for _, line in current_lines if line.strip()):
            current_lines = []
            return

        chapter_index = len(chapters)
        content = "\n".join(line for _, line in current_lines)
        start_line = current_lines[0][0]
        end_line = current_lines[-1][0]
        segments: list[dict[str, Any]] = []
        segment_index = 0

        for source_line_number, line in current_lines:
            for segment in split_segments(line):
                segments.append(
                    {
                        "segmentIndex": segment_index,
                        "lineNumber": source_line_number,
                        "text": segment,
                    }
                )
                segment_index += 1

        chapters.append(
            {
                "chapterIndex": chapter_index,
                "chapterTitle": current_title,
                "startLine": start_line,
                "endLine": end_line,
                "content": content,
                "segments": segments,
            }
        )
        current_lines = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        match = CHAPTER_RE.match(line)
        if match:
            flush()
            current_title = (match.group(1) or match.group(2) or "").strip() or "未分章"
            current_start_line = line_number + 1
            current_lines = []
        else:
            if not current_lines and not raw_line.strip():
                continue
            current_lines.append((line_number, raw_line))

    flush()
    if not chapters:
        chapters.append(
            {
                "chapterIndex": 0,
                "chapterTitle": current_title,
                "startLine": current_start_line,
                "endLine": current_start_line,
                "content": "",
                "segments": [],
            }
        )
    return chapters


def book_to_document(path: Path) -> dict[str, Any]:
    title = path.stem
    text = path.read_text(encoding="utf-8", errors="ignore")
    chapters = parse_chapters(text)
    segment_count = sum(len(chapter["segments"]) for chapter in chapters)
    return {
        "schemaVersion": 1,
        "title": title,
        "filename": path.name,
        "sourcePath": str(path.relative_to(ROOT)),
        "chapterCount": len(chapters),
        "segmentCount": segment_count,
        "chapters": chapters,
    }


def build_structured_data() -> list[dict[str, Any]]:
    STRUCTURED_DIR.mkdir(exist_ok=True)
    documents: list[dict[str, Any]] = []

    for path in sorted(DATA_DIR.glob("*.txt"), key=lambda item: item.name):
        document = book_to_document(path)
        output_path = STRUCTURED_DIR / f"{document['title']}.json"
        output_path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        documents.append(document)

    catalog = {
        "schemaVersion": 1,
        "sourceDir": "data",
        "bookCount": len(documents),
        "chapterCount": sum(document["chapterCount"] for document in documents),
        "segmentCount": sum(document["segmentCount"] for document in documents),
        "books": [
            {
                "title": document["title"],
                "filename": document["filename"],
                "structuredPath": f"data_structured/{document['title']}.json",
                "chapterCount": document["chapterCount"],
                "segmentCount": document["segmentCount"],
            }
            for document in documents
        ],
    }
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return documents


def structured_data_is_current() -> bool:
    if not CATALOG_PATH.exists():
        return False
    txt_paths = list(DATA_DIR.glob("*.txt"))
    if not txt_paths:
        return False
    for txt_path in txt_paths:
        json_path = STRUCTURED_DIR / f"{txt_path.stem}.json"
        if not json_path.exists() or json_path.stat().st_mtime < txt_path.stat().st_mtime:
            return False
    return True


def load_structured_books() -> list[dict[str, Any]]:
    books: list[dict[str, Any]] = []
    for path in sorted(STRUCTURED_DIR.glob("*.json"), key=lambda item: item.name):
        if path.name == "catalog.json":
            continue
        books.append(json.loads(path.read_text(encoding="utf-8")))
    return books


def load_books() -> list[dict[str, Any]]:
    global _BOOKS
    if _BOOKS is not None:
        return _BOOKS

    if not DATA_DIR.exists():
        _BOOKS = []
        return _BOOKS

    if not structured_data_is_current():
        _BOOKS = build_structured_data()
    else:
        _BOOKS = load_structured_books()
    return _BOOKS


def find_book(name: str) -> dict[str, Any] | None:
    decoded = unquote(name).strip()
    for book in load_books():
        if book["title"] == decoded or book["filename"] == decoded:
            return book
    return None


def is_match(text: str, query_groups: list[list[str]]) -> bool:
    haystack = normalize(text)
    return all(any(variant in haystack for variant in group) for group in query_groups)


def make_snippet(text: str, query_groups: list[list[str]], radius: int = 80) -> str:
    haystack = normalize(text)
    positions = [
        haystack.find(variant)
        for group in query_groups
        for variant in group
        if variant and haystack.find(variant) >= 0
    ]
    if not positions:
        return text[: radius * 2]

    pos = min(positions)
    start = max(pos - radius, 0)
    end = min(pos + radius, len(text))
    prefix = "……" if start > 0 else ""
    suffix = "……" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def search_book(
    book: dict[str, Any],
    query_groups: list[list[str]],
    *,
    offset: int = 0,
    limit: int | None = None,
    collect_matches: bool = True,
) -> dict[str, Any]:
    total = 0
    matches: list[dict[str, Any]] = []
    end = None if limit is None else offset + limit

    for chapter in book["chapters"]:
        for segment in chapter["segments"]:
            if not is_match(segment["text"], query_groups):
                continue

            if collect_matches and total >= offset and (end is None or total < end):
                matches.append(
                    {
                        "book": book["title"],
                        "chapterIndex": chapter["chapterIndex"],
                        "chapterTitle": chapter["chapterTitle"],
                        "segmentIndex": segment["segmentIndex"],
                        "lineNumber": segment["lineNumber"],
                        "snippet": make_snippet(segment["text"], query_groups),
                    }
                )
            total += 1

    return {"total": total, "matches": matches}


def int_param(params: dict[str, list[str]], key: str, default: int) -> int:
    try:
        value = int(params.get(key, [str(default)])[0])
        return max(value, 0)
    except ValueError:
        return default


class LiteratureSearchHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api(parsed.path, parse_qs(parsed.query))
            return
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def guess_type(self, path: str) -> str:
        if path.endswith(".js"):
            return "application/javascript; charset=utf-8"
        if path.endswith(".css"):
            return "text/css; charset=utf-8"
        guessed = mimetypes.guess_type(path)[0]
        return guessed or "application/octet-stream"

    def handle_api(self, path: str, params: dict[str, list[str]]) -> None:
        if path == "/api/books":
            books = load_books()
            self.send_json(
                {
                    "bookCount": len(books),
                    "chapterCount": sum(book["chapterCount"] for book in books),
                    "segmentCount": sum(book.get("segmentCount", 0) for book in books),
                    "structured": structured_data_is_current(),
                    "books": [
                        {
                            "title": book["title"],
                            "filename": book["filename"],
                            "chapterCount": book["chapterCount"],
                            "segmentCount": book.get("segmentCount", 0),
                        }
                        for book in books
                    ],
                }
            )
            return

        if path == "/api/search":
            query = params.get("q", [""])[0].strip()
            limit = int_param(params, "limit", 10)
            query_groups, highlight_terms = build_query_groups(query)
            if not query_groups:
                self.send_json({"query": query, "highlightTerms": [], "bookCount": 0, "totalMatches": 0, "books": []})
                return

            books_payload = []
            total_matches = 0
            for book in load_books():
                result = search_book(book, query_groups, offset=0, limit=limit)
                if result["total"] == 0:
                    continue
                total_matches += result["total"]
                books_payload.append(
                    {
                        "book": book["title"],
                        "filename": book["filename"],
                        "chapterCount": book["chapterCount"],
                        "segmentCount": book.get("segmentCount", 0),
                        "total": result["total"],
                        "top": result["matches"],
                    }
                )

            books_payload.sort(key=lambda item: item["total"], reverse=True)
            self.send_json(
                {
                    "query": query,
                    "highlightTerms": highlight_terms,
                    "bookCount": len(books_payload),
                    "totalMatches": total_matches,
                    "books": books_payload,
                }
            )
            return

        if path == "/api/book":
            query = params.get("q", [""])[0].strip()
            name = params.get("name", [""])[0]
            offset = int_param(params, "offset", 0)
            limit = int_param(params, "limit", DEFAULT_DETAIL_LIMIT)
            book = find_book(name)
            if book is None:
                self.send_json({"error": "找不到指定書籍"}, HTTPStatus.NOT_FOUND)
                return
            query_groups, highlight_terms = build_query_groups(query)
            if not query_groups:
                self.send_json({"book": book["title"], "query": query, "highlightTerms": [], "total": 0, "offset": offset, "limit": limit, "matches": []})
                return
            result = search_book(book, query_groups, offset=offset, limit=limit)
            self.send_json(
                {
                    "book": book["title"],
                    "query": query,
                    "highlightTerms": highlight_terms,
                    "total": result["total"],
                    "offset": offset,
                    "limit": limit,
                    "matches": result["matches"],
                }
            )
            return

        if path == "/api/chapter":
            name = params.get("name", [""])[0]
            chapter_index = int_param(params, "chapter", 0)
            book = find_book(name)
            if book is None:
                self.send_json({"error": "找不到指定書籍"}, HTTPStatus.NOT_FOUND)
                return
            chapters = book["chapters"]
            if chapter_index >= len(chapters):
                self.send_json({"error": "找不到指定章節"}, HTTPStatus.NOT_FOUND)
                return
            query = params.get("q", [""])[0].strip()
            _, highlight_terms = build_query_groups(query)
            chapter = chapters[chapter_index]
            self.send_json(
                {
                    "book": book["title"],
                    "chapterIndex": chapter["chapterIndex"],
                    "chapterTitle": chapter["chapterTitle"],
                    "startLine": chapter.get("startLine"),
                    "endLine": chapter.get("endLine"),
                    "content": chapter["content"],
                    "highlightTerms": highlight_terms,
                }
            )
            return

        self.send_json({"error": "未知接口"}, HTTPStatus.NOT_FOUND)


def main() -> None:
    port = 8000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    server = ThreadingHTTPServer(("0.0.0.0", port), LiteratureSearchHandler)
    print(f"文獻檢索系統已啓動：http://127.0.0.1:{port}")
    print("將優先讀取 data_structured 結構化資料；若缺失或過期會自動由 data 重建。按 Ctrl+C 停止。")
    server.serve_forever()


if __name__ == "__main__":
    main()
