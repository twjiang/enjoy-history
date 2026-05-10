# Enjoy History 文獻檢索

本项目是一个本地运行的十三经、二十四史全文检索系统。

## 数据结构

原始繁体文本保存在 `data/*.txt`，每本书一个文件。系统会根据文本中的章节标记生成结构化数据，当前支持两类标题：

```text
【章节名】
## 卷一‧五帝本紀第一
```

生成结构化数据到 `data_structured/`：

```text
data_structured/
  catalog.json
  史記.json
  漢書.json
  ...
```

每本书的 JSON 结构包含：

- `title`：书名
- `filename`：原始文本文件名
- `chapterCount`：章节数
- `segmentCount`：可检索段落数
- `chapters[]`：章节列表
  - `chapterIndex`：章节索引
  - `chapterTitle`：章节名
  - `startLine` / `endLine`：在原始 txt 中的行号范围
  - `content`：章节全文
  - `segments[]`：用于检索的切分段落

## 当前功能

- 输入关键词，从全部书籍的结构化段落中检索匹配结果。
- 检索结果按书籍聚合，每本书默认展示 Top 10。
- 点击书籍可查看该书所有匹配结果，并支持继续加载。
- 每条匹配结果展示关联章节，点击可阅读完整章节并高亮关键词。
- 支持用空格输入多个关键词，检索同时包含所有关键词的段落。
- 若安装了 `opencc`，简体输入会自动转换为繁体一起检索。

## 生成/更新结构化数据

当 `data/*.txt` 有更新时，运行：

```bash
python3 build_index.py
```

`server.py` 启动时也会检查 `data_structured/` 是否缺失或过期；如果过期，会自动由 `data/*.txt` 重建。

## 启动

```bash
python3 server.py
```

然后打开：

```text
http://127.0.0.1:8000
```

也可以指定端口：

```bash
python3 server.py 8080
```

## 可选依赖

为了获得更好的简繁兼容检索，可安装 `opencc`：

```bash
python3 -m pip install opencc
```

如果不安装，也可以正常检索繁体关键词。
