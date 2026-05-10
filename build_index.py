#!/usr/bin/env python3
"""由 data/*.txt 生成章节化、段落化的 data_structured/*.json。"""
from __future__ import annotations

from server import build_structured_data


def main() -> None:
    documents = build_structured_data()
    chapter_count = sum(document["chapterCount"] for document in documents)
    segment_count = sum(document["segmentCount"] for document in documents)
    print(f"已生成 {len(documents)} 本書的結構化資料。")
    print(f"章節數：{chapter_count}，檢索段落數：{segment_count}")
    print("輸出目錄：data_structured/")


if __name__ == "__main__":
    main()
