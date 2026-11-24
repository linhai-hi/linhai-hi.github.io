#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段 2 AI 可见层生成器（docs/01 定稿）。

生成物（均为静态文件，随 git 提交；CI 不运行本脚本，本地/发布前执行）：
  - raw/<栏目>/<文章>.md   每篇文章的 Markdown 原文路由（无 front-matter，Jekyll 按静态文件原样复制）
  - raw/about.md            关于页原文路由
  - llms.txt                站点索引（llmstxt.org 规范形态：H1 + 摘要 + 分组链接）
  - llms-full.txt           全站 Markdown 原文合集（供 LLM 检索与引用）

用法（在 site 仓库根目录运行）：
  python tools/ai_layer.py gen

注意：不含邮箱等联系字段（闸门邮箱层只放行 about.md/index.md 与 .json 投影产物；
工作邮箱由 /ai-profile.json 的 contact 字段承载）。
"""
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent

COLUMNS = [
    ("ideas", "灵感闪念", "随手记录的想法与观察"),
    ("reading", "读书笔记", "读过的书与提炼"),
    ("review", "项目与问题复盘", "项目过程与问题解决的复盘"),
    ("exams", "考试经验", "考试与考证经验"),
    ("plugins", "插件与工具开发", "自建插件、脚本与工具"),
    ("aitips", "AI 使用技巧", "AI 工具的使用方法与心得"),
    ("retell", "复述学习", "学习他人优质内容后的复述与再输出（注明出处）"),
    ("pitfalls", "难题与坑", "踩过的坑与解决方案"),
]


def read_conf_url() -> str:
    try:
        for line in (SITE / "_config.yml").read_text(encoding="utf-8").splitlines():
            m = re.match(r"^url:\s*\"?([^\"#]+)\"?\s*$", line)
            if m and m.group(1).strip():
                return m.group(1).strip()
    except OSError:
        pass
    return "https://linhai-hi.github.io"


def parse_fm(text: str):
    """返回 (front-matter dict, body)。无 FM 时返回 ({}, 原文)。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm, body


def gen() -> int:
    base = read_conf_url()
    raw_root = SITE / "raw"
    posts = []  # (col, name, title, date, body, url)

    for col, _title, _desc in COLUMNS:
        d = SITE / f"_{col}"
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            fm, body = parse_fm(text)
            title = fm.get("title", p.stem)
            date = fm.get("date", "")
            out = raw_root / col / p.name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body.rstrip() + "\n", encoding="utf-8")
            posts.append((col, p.stem, title, date, body.rstrip(),
                          f"{base}/{col}/{p.stem}/"))

    # about 原文路由
    about_body = ""
    about = SITE / "about.md"
    if about.is_file():
        _fm, about_body = parse_fm(about.read_text(encoding="utf-8"))
        out = raw_root / "about.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(about_body.rstrip() + "\n", encoding="utf-8")

    posts.sort(key=lambda x: (x[3], x[1]), reverse=True)

    # llms.txt
    lines = [
        "# 林海 · AI 内容创作者",
        "",
        "> 林海，AI 内容创作者。持续记录真实使用 AI 解决问题的方法与心得，"
        "把每一次实践沉淀为可复用的经验。",
        "",
        "## 关于",
        "",
        f"- [关于林海]({base}/about/): 身份、联系方式与 AI 档案入口。",
        f"- [AI 档案（机器可读 JSON）]({base}/ai-profile.json): schema v1 结构化身份卡。",
        "",
        "## 栏目",
        "",
    ]
    for col, title, desc in COLUMNS:
        lines.append(f"- [{title}]({base}/{col}/): {desc}。")
    lines += ["", "## 文章", ""]
    if posts:
        for _col, _name, title, date, _body, url in posts:
            lines.append(f"- [{title}]({url}): {date}")
    else:
        lines.append("（暂无文章）")
    lines.append("")
    (SITE / "llms.txt").write_text("\n".join(lines), encoding="utf-8")

    # llms-full.txt
    full = [
        "# 林海 · AI 内容创作者 — 全站原文",
        "",
        "> 本文件为全站 Markdown 原文合集，供 LLM 检索与引用；引用时请标注出处链接与日期。",
        "",
    ]
    if about_body:
        full += ["## 关于", "", about_body.rstrip(), ""]
    full += ["## 文章", ""]
    for _col, _name, title, date, body, url in posts:
        full += [f"### {title}", "", f"> 原文：{url}｜{date}", "", body.rstrip(), ""]

    (SITE / "llms-full.txt").write_text("\n".join(full), encoding="utf-8")

    print(f"[AI-LAYER] llms.txt: {len(posts)} 篇文章索引（url 基址 {base}）")
    print(f"[AI-LAYER] llms-full.txt: 全站原文合集已生成")
    print(f"[AI-LAYER] raw/: 每篇文章 Markdown 原文路由已生成（{len(posts)} + about）")
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] != "gen":
        print("用法: python tools/ai_layer.py gen")
        return 2
    return gen()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
