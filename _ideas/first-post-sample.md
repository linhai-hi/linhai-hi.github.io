---
title: "示例文章：把第一条灵感写下来（结构验证用，可删除）"
type: ideas
status: published
date: 2026-11-22
privacy-checked: true
---
这是**站点结构验证用的示例文章**，不含任何真实个人信息；正式运营前可整篇删除。

## 写作与发布路径（docs/00 §4.3 / docs/01 §4–5）

1. 在 `_inbox/` 随手落笔（`_inbox` 在 site 外，不受构建，但 🟥 红线对草稿同样适用——docs/02 §0）；
2. 加工：脱敏（docs/02 F2-🟡 清单逐条执行）+ 补齐硬字段；
3. 过闸门：`python site/tools/gate.py check`——**命中即中止**，不是警告；
4. 移入对应集合目录（如 `_ideas/`），文件名用英文 kebab-case；
5. push → CI 闸门复查 → 通过才构建部署。

## front-matter 硬字段（缺失即构建失败）

```yaml
title: 必填
type: ideas | reading | review | exams | plugins | aitips | retell | pitfalls | page
status: published          # site/ 内一律 published，草稿只活在 _inbox/
date: YYYY-MM-DD
privacy-checked: true      # 不是 true = 拦截
source: 作者+链接+日期      # 仅 type: retell 必填
```
