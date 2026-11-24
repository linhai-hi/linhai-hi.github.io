#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gate.py —— personal-site「投影 + 发布闸门」（fail-closed）

设计依据：docs/01-方案与选型.md §5、docs/02-发布红线定稿.md F5。
原则：命中即中止退出非零，不是警告；误报走"修内容"，不设内联旁路。

用法：
  python tools/gate.py check   [--dir DIR] [--redlines FILE] [--no-frontmatter] [--no-exif]
  python tools/gate.py project [--vault DIR] [--site DIR]

退出码：0 通过 · 1 拦截（发现违规） · 2 用法/配置错误
依赖：仅 Python 3.8+ 标准库（不装全局包）。

扫描规则三层（docs/01 §5.3）：
  1) 格式正则（边界断言）  2) 数学校验（GB11643 校验位 / Luhn）  3) 关键词上下文行
已知误报/漏报边界与占位符白名单见 docs/01 §5.5；命中输出一律掩码，防止日志二次泄露。
"""
import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

EXIT_OK, EXIT_BLOCKED, EXIT_USAGE = 0, 1, 2

# ---------------------------------------------------------------- 范围常量
CONTENT_EXTS = {".md", ".markdown"}
SCAN_EXTS = {".md", ".markdown", ".txt", ".html", ".json", ".yaml", ".yml",
             ".xml", ".csv", ".js", ".ts", ".css"}
JPEG_EXTS = {".jpg", ".jpeg"}
PNG_EXTS = {".png"}
FORBIDDEN_IMAGE_EXTS = {".heic", ".heif", ".hif"}  # 闸门无法校验 EXIF 的格式 → 一律拒绝

FM_EXEMPT_DIRS = {"_layouts", "_includes", "tools", ".github", "_data", "assets"}
SCAN_EXEMPT_DIRS = {"tools", ".github"}  # 工具源码含模式定义，扫描会自命中

# 邮箱规则：只允许出现在联系页白名单（docs/01 调整 A13）；.json 为投影产物（生成前已过闸门）
EMAIL_ALLOWED_NAMES = {"about.md", "index.md"}

ALLOWED_TYPES = {"ideas", "reading", "review", "exams",
                 "plugins", "aitips", "retell", "pitfalls", "page"}
SOURCE_REQUIRED_TYPES = {"retell"}
REQUIRED_FIELDS = ("title", "type", "status", "date", "privacy-checked")

# 占位符白名单（防自伤）：真实密钥几乎不会长成模板占位形态（推演，docs/01 §5.5）
PLACEHOLDER_RE = re.compile(
    r"(?i)(?:x{4,}|your[_-]?|example|placeholder|sample[_-]?|demo[_-]?"
    r"|<[^>]{1,60}>|\$\{[^}]{0,80}\}|\{\{[^}]{0,80}\}\}|\.{3,}|…"
    r"|示例|占位|待填|填这里|替换为|redacted|masked|no[-_]?key|\bnone\b|\bnull\b)"
)

EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])"
)

# ---------------------------------------------------------------- 校验器
_ID18_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID18_MAP = "10X98765432"
# GB/T 2260 省级行政区划代码前两位（宽松白名单，用于降低误报）
_REGION2 = {"11", "12", "13", "14", "15", "21", "22", "23", "31", "32", "33",
            "34", "35", "36", "37", "41", "42", "43", "44", "45", "46",
            "50", "51", "52", "53", "54", "61", "62", "63", "64", "65",
            "71", "81", "82"}


def _plausible_date(y, m, d):
    try:
        _dt.date(int(y), int(m), int(d))
        return True
    except ValueError:
        return False


def id18_valid(s: str) -> bool:
    """GB 11643-1999 18 位身份证号校验（含出生日期合理性与省级行政区校验）。"""
    if len(s) != 18 or not s[:17].isdigit():
        return False
    if s[17].upper() not in "0123456789X":
        return False
    if s[:2] not in _REGION2:
        return False
    if not _plausible_date(s[6:10], s[10:12], s[12:14]):
        return False
    total = sum(int(d) * w for d, w in zip(s[:17], _ID18_WEIGHTS))
    return s[17].upper() == _ID18_MAP[total % 11]


def id15_plausible(s: str) -> bool:
    """15 位旧身份证号：省级行政区 + YYMMDD 出生段合理性。"""
    if len(s) != 15 or not s.isdigit():
        return False
    if s[:2] not in _REGION2:
        return False
    year, month, day = s[6:8], s[8:10], s[10:12]
    if not ("00" < year <= "99"):
        return False
    return _plausible_date(1900 + int(year), month, day)


def luhn(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# ---------------------------------------------------------------- 扫描规则
# (rule_id, 正则, 说明, 校验函数 or None, 捕获组序号 or 0)
RULES = [
    ("mobile", r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])", "疑似手机号", None, 0),
    ("mobile-spaced", r"(?<![0-9])1[3-9][0-9][-\s][0-9]{4}[-\s][0-9]{4}(?![0-9])",
     "疑似手机号（分段写法 3-4-4）", None, 0),
    ("id-card-18", r"(?<![0-9Xx])[0-9]{17}[0-9Xx](?![0-9Xx])",
     "疑似身份证号（18 位，校验位通过才拦截）", id18_valid, 0),
    ("id-card-15", r"(?<![0-9])[0-9]{15}(?![0-9])",
     "疑似身份证号（15 位，出生段合理才拦截）", id15_plausible, 0),
    ("bank-card", r"(?<![0-9])[0-9]{13,19}(?![0-9])",
     "疑似银行卡号（Luhn 通过才拦截）", luhn, 0),
    ("bank-card-spaced", r"(?<![0-9])[0-9]{4}[-\s][0-9]{4}[-\s][0-9]{4}[-\s][0-9]{1,7}(?![0-9])",
     "疑似银行卡号（分组写法）", lambda s: luhn(re.sub(r"[-\s]", "", s)), 0),
    ("token-github", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|github_pat_[A-Za-z0-9_]{40,}",
     "疑似 GitHub 令牌", None, 0),
    ("token-openai", r"\bsk-(?!ant-)[A-Za-z0-9_-]{20,}", "疑似 OpenAI 风格密钥", None, 0),
    ("token-anthropic", r"\bsk-ant-[A-Za-z0-9_-]{20,}", "疑似 Anthropic 密钥", None, 0),
    ("token-google", r"\bAIza[0-9A-Za-z_-]{35}", "疑似 Google API Key", None, 0),
    ("token-slack", r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "疑似 Slack 令牌", None, 0),
    ("token-aws", r"\bAKIA[0-9A-Z]{16}", "疑似 AWS Access Key ID", None, 0),
    ("token-jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
     "疑似 JWT", None, 0),
    ("token-bearer", r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", "疑似 Bearer 令牌", None, 0),
    ("private-key", r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----",
     "私钥文件头", None, 0),
    ("keyword-secret",
     r"(?i)\b(?:api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|auth[_-]?token"
     r"|client[_-]?secret|app[_-]?secret|appsecret|private[_-]?key|refresh[_-]?token|token)\b"
     r"\s*[:=]\s*[\"']?([A-Za-z0-9+/_=.-]{8,})",
     "疑似密钥赋值（关键词上下文）", None, 1),
    ("keyword-secret-cn",
     r"(?:密钥|口令|访问令牌|密码)\s*[:：=]\s*[\"']?([A-Za-z0-9+/_=.-]{8,})",
     "疑似密钥赋值（中文关键词上下文）", None, 1),
]
RULES = [(rid, re.compile(pat), desc, fn, grp) for rid, pat, desc, fn, grp in RULES]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"https?://\S+")


class GateConfigError(Exception):
    pass


# ---------------------------------------------------------------- 基础设施
def read_text(path: Path) -> str:
    # utf-8-sig：兼容 Windows 编辑器/PowerShell 写出的 BOM，避免误报缺 front-matter
    return path.read_text(encoding="utf-8-sig")  # 非 UTF-8 → 异常，fail loud


def mask_line(line: str, spans) -> str:
    """命中串掩码输出，防止日志二次泄露（docs/01 调整 A12）。"""
    out = line
    for start, end in sorted(spans, key=lambda t: -t[0]):
        out = out[:start] + "█████" + out[end:]
    return out.strip()


def parse_frontmatter(text: str):
    """扁平 key:value 子集解析（docs/01 调整 A5：硬字段全为扁平标量）。"""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    fm = {}
    for raw in lines[1:end]:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z][\w-]*)\s*:\s*(.*)$", raw.rstrip())
        if not m:
            continue  # 嵌套/列表行：硬校验不覆盖（限制已文档化）
        fm[m.group(1).lower()] = m.group(2).strip().strip('"').strip("'")
    return fm


def iter_files(root: Path, exts, exempt_dirs):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in exempt_dirs for part in rel_parts[:-1]):
            continue
        if p.suffix.lower() in exts:
            yield p


def is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_RE.search(value))


# ---------------------------------------------------------------- 扫描核心
def scan_text(text: str, allow_email: bool):
    """返回 [(rule_id, line_no, masked_line)]。allow_email=True 时跳过邮箱规则。"""
    findings = []
    lines = text.splitlines()
    for lineno, line in enumerate(lines, 1):
        for rid, regex, _desc, fn, grp in RULES:
            for m in regex.finditer(line):
                value = m.group(grp) if grp else m.group(0)
                if not value or is_placeholder(value):
                    continue
                if fn is not None and not fn(value):
                    continue
                findings.append((rid, lineno, mask_line(line, [m.span(grp or 0)])))
        if not allow_email:
            for m in EMAIL_RE.finditer(line):
                value = m.group(0)
                if is_placeholder(value):
                    continue
                findings.append(("email", lineno,
                                 mask_line(line, [m.span(0)])))
    return findings


def load_redlines(path):
    """vault/redlines.md → (exact_words, regex_list)。坏正则 = 配置错误（fail loud）。

    解析规则（与 vault/redlines.md 模板约定一致）：
    空行/#注释与标题/> 引用说明跳过；`---` 等分隔线与 ``` 围栏跳过；行首 `- ` 视为列表条目剥掉；
    `regex: …` 为自定义正则；其余整行 = 禁词（大小写不敏感精确匹配）。
    """
    if path is None or not Path(path).exists():
        return [], []
    exact, regexes = [], []
    for raw in read_text(Path(path)).splitlines():
        s = raw.strip()
        if not s or s.startswith(("#", ">", "```")):
            continue
        if re.fullmatch(r"[-*_]{3,}", s):  # Markdown 分隔线，禁词解析必须跳过
            continue
        if s.startswith("- "):
            s = s[2:].strip()
        if not s:
            continue
        if s.startswith("regex:"):
            try:
                regexes.append(re.compile(s[len("regex:"):].strip()))
            except re.error as e:
                raise GateConfigError(f"redlines 自定义正则无效: {s!r}（{e}）")
        else:
            exact.append(s)
    return exact, regexes


def scan_redlines(text: str, exact, regexes):
    findings = []
    lines = text.splitlines()
    lower_words = [(w, w.lower()) for w in exact]
    for lineno, line in enumerate(lines, 1):
        low = line.lower()
        for w, wl in lower_words:
            idx = low.find(wl)
            if idx >= 0:
                findings.append(("redlines-exact", lineno,
                                 mask_line(line, [(idx, idx + len(w))])))
        for rx in regexes:
            for m in rx.finditer(line):
                findings.append(("redlines-regex", lineno,
                                 mask_line(line, [m.span(0)])))
    return findings


def check_frontmatter(path_rel: str, fm):
    if fm is None:
        return [("frontmatter-missing", 0,
                 f"{path_rel}: 缺少 front-matter 或未以 --- 闭合")]
    out = []
    for field in REQUIRED_FIELDS:
        v = fm.get(field)
        if v is None or str(v).strip() == "":
            out.append((f"frontmatter-{field}", 0,
                        f"{path_rel}: 硬字段缺失或为空 → {field}"))
    if fm.get("type") and fm["type"] not in ALLOWED_TYPES:
        out.append(("frontmatter-type", 0,
                    f"{path_rel}: type 非法 → {fm['type']}（允许: {sorted(ALLOWED_TYPES)}）"))
    if fm.get("status") and fm["status"] != "published":
        out.append(("frontmatter-status", 0,
                    f"{path_rel}: site/ 内 status 必须 published（草稿只活在 _inbox/），当前 → {fm['status']}"))
    if fm.get("date") and not DATE_RE.match(fm["date"]):
        out.append(("frontmatter-date", 0,
                    f"{path_rel}: date 格式须 YYYY-MM-DD → {fm['date']}"))
    if fm.get("privacy-checked") and str(fm["privacy-checked"]).lower() != "true":
        out.append(("frontmatter-privacy-checked", 0,
                    f"{path_rel}: privacy-checked 不是 true（『没检查』与『检查不过』都拦截）→ {fm['privacy-checked']}"))
    if fm.get("type") in SOURCE_REQUIRED_TYPES:
        src = fm.get("source", "")
        if not src or not URL_RE.search(src):
            out.append(("frontmatter-source", 0,
                        f"{path_rel}: type=retell 的 source 必填且须含 http(s) 链接（作者+链接+日期，docs/02 F3）"))
        elif len(URL_RE.sub("", src).strip()) < 2:
            out.append(("frontmatter-source", 0,
                        f"{path_rel}: source 除链接外须含作者/说明文字"))
    return out


def check_images(root: Path, allowlist_names, findings):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in SCAN_EXEMPT_DIRS for part in rel_parts[:-1]):
            continue
        ext = p.suffix.lower()
        rel = p.relative_to(root).as_posix()
        if ext in FORBIDDEN_IMAGE_EXTS:
            findings.append(("image-forbidden-format", 0,
                             f"{rel}: HEIC/HEIF 闸门无法校验 EXIF，禁止直接上传（请转 JPG/PNG/WebP 并清 EXIF）"))
            continue
        if p.name in allowlist_names:
            continue  # EXIF 白名单：文件级、显式留痕（评估否决 N3：仅此一处白名单，无行级旁路）
        if ext in JPEG_EXTS:
            try:
                head = p.read_bytes()[:65536]
            except OSError as e:
                findings.append(("image-unreadable", 0, f"{rel}: 无法读取（{e}）"))
                continue
            if b"Exif\x00\x00" in head:
                findings.append(("exif-jpeg", 0,
                                 f"{rel}: JPEG 含 EXIF（GPS/设备/时间风险），请清除后上传或加入 tools/exif-allowlist.txt"))
        elif ext in PNG_EXTS:
            try:
                head = p.read_bytes()[:1048576]
            except OSError as e:
                findings.append(("image-unreadable", 0, f"{rel}: 无法读取（{e}）"))
                continue
            if b"eXIf" in head:
                findings.append(("exif-png", 0,
                                 f"{rel}: PNG 含 eXIf 块，请清除后上传或加入 tools/exif-allowlist.txt"))


def resolve_redlines(args, root: Path):
    if args.redlines:
        return Path(args.redlines)
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / "vault" / "redlines.md",   # personal-site/vault
        root.parent / "vault" / "redlines.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ---------------------------------------------------------------- 子命令
def cmd_check(args) -> int:
    root = Path(args.dir).resolve() if args.dir else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"[GATE] 扫描目录不存在: {root}")
        return EXIT_USAGE

    findings = []
    notes = []

    # 1) front-matter 硬字段（docs/01 §4）
    if not args.no_frontmatter:
        for p in iter_files(root, CONTENT_EXTS, FM_EXEMPT_DIRS):
            try:
                text = read_text(p)
            except (UnicodeDecodeError, OSError) as e:
                findings.append(("file-not-utf8", 0,
                                 f"{p.relative_to(root).as_posix()}: 读取失败（须 UTF-8）: {e}"))
                continue
            findings.extend(check_frontmatter(p.relative_to(root).as_posix(),
                                              parse_frontmatter(text)))

    # 2) 敏感信息模式扫描（docs/01 §5.3）
    exact, regexes = [], []
    redlines_path = None if args.no_redlines else resolve_redlines(args, root)
    if redlines_path:
        try:
            exact, regexes = load_redlines(redlines_path)
        except GateConfigError as e:
            print(f"[GATE] 配置错误: {e}")
            return EXIT_USAGE
        notes.append(f"私有禁词清单: {len(exact)} 条禁词 + {len(regexes)} 条正则（{redlines_path}）")
    else:
        notes.append("私有禁词清单: 不可用（CI 环境正常现象；本地 pre-push 必须可用）")

    for p in iter_files(root, SCAN_EXTS, SCAN_EXEMPT_DIRS):
        try:
            text = read_text(p)
        except (UnicodeDecodeError, OSError) as e:
            findings.append(("file-not-utf8", 0,
                             f"{p.relative_to(root).as_posix()}: 读取失败（须 UTF-8）: {e}"))
            continue
        allow_email = (p.name.lower() in EMAIL_ALLOWED_NAMES) or (p.suffix.lower() == ".json")
        for rid, lineno, masked in scan_text(text, allow_email):
            findings.append((rid, lineno,
                             f"{p.relative_to(root).as_posix()}:{lineno} | {masked}"))
        for rid, lineno, masked in scan_redlines(text, exact, regexes):
            findings.append((rid, lineno,
                             f"{p.relative_to(root).as_posix()}:{lineno} | {masked}"))

    # 3) 图片 EXIF / 不可校验格式（docs/02 F2-🟡5）
    if not args.no_exif:
        allowlist = set()
        wl = Path(__file__).resolve().parent / "exif-allowlist.txt"
        if wl.exists():
            for line in read_text(wl).splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    allowlist.add(s)
        check_images(root, allowlist, findings)

    for note in notes:
        print(f"[GATE] {note}")

    if findings:
        print(f"[GATE] ✋ 拦截：{len(findings)} 项违规（fail-closed，命中即中止）")
        for rid, _lineno, msg in findings:
            print(f"  - [{rid}] {msg}")
        print("[GATE] 处置：修内容（误报同样走修订，无内联旁路）；图片清 EXIF 或留痕白名单。")
        return EXIT_BLOCKED

    print("[GATE] ✅ 通过：未发现敏感信息违规，front-matter 硬字段完整。")
    return EXIT_OK


def _extract_yaml_block(text: str) -> str:
    m = re.search(r"```yaml\s*\n(.*?)```", text, re.S)
    if not m:
        raise GateConfigError("vault/profile.md 缺少 ```yaml 元数据块（模板见 vault/profile.md）")
    return m.group(1)


def cmd_project(args) -> int:
    here = Path(__file__).resolve()
    vault_dir = Path(args.vault).resolve() if args.vault else here.parent.parent.parent / "vault"
    site_dir = Path(args.site).resolve() if args.site else here.parent.parent
    profile = vault_dir / "profile.md"
    if not profile.exists():
        print(f"[GATE] vault/profile.md 不存在: {profile}")
        return EXIT_USAGE
    try:
        text = read_text(profile)
    except (UnicodeDecodeError, OSError) as e:
        print(f"[GATE] vault/profile.md 读取失败（须 UTF-8）: {e}")
        return EXIT_USAGE

    try:
        block = _extract_yaml_block(text)
    except GateConfigError as e:
        print(f"[GATE] {e}")
        return EXIT_USAGE

    fm = {}
    for raw in block.splitlines():
        m = re.match(r"^([A-Za-z][\w-]*)\s*:\s*(.*)$", raw.rstrip())
        if m:
            fm[m.group(1).lower()] = m.group(2).strip().strip('"').strip("'")

    required = ["display_name", "role", "summary"]
    missing = [k for k in required if not fm.get(k)]
    placeholdered = [k for k in required if fm.get(k) and is_placeholder(fm[k])]
    if missing or placeholdered:
        print("[GATE] vault/profile.md 元数据未就绪："
              f"缺失={missing} 仍是占位符={placeholdered}。投影中止（不生成半成品）。")
        return EXIT_USAGE

    def _split(v):
        return [t.strip() for t in re.split(r"[,，]", v or "") if t.strip()]

    identity = {
        "schema_version": 1,
        "name": fm["display_name"],
        "role": fm["role"],
        "summary": fm["summary"],
        "canonical_url": fm.get("site_url", ""),
        "languages": ["zh-CN"],
        "location": {"city": fm.get("city", ""), "country": fm.get("country", "CN")},
        "topics": _split(fm.get("topics")),
        "capabilities": _split(fm.get("capabilities")),
        "contact": {"email": fm.get("work_email", ""),
                    "github": fm.get("github_url", ""),
                    "policy": "仅工作联络"},
        "links": ([{"rel": "github", "url": fm["github_url"]}] if fm.get("github_url") else []),
        "content": {
            "columns": [
                {"slug": "ideas", "title": "灵感闪念", "url": "/ideas/"},
                {"slug": "reading", "title": "读书笔记", "url": "/reading/"},
                {"slug": "review", "title": "项目与问题复盘", "url": "/review/"},
                {"slug": "exams", "title": "考试经验", "url": "/exams/"},
                {"slug": "plugins", "title": "插件与工具开发", "url": "/plugins/"},
                {"slug": "aitips", "title": "AI 使用技巧", "url": "/aitips/"},
                {"slug": "retell", "title": "复述学习", "url": "/retell/"},
                {"slug": "pitfalls", "title": "难题与坑", "url": "/pitfalls/"},
            ],
            "formats": ["html", "markdown"],
        },
        "ai_reading": {
            "llms_txt": "/llms.txt",
            "llms_full": "/llms-full.txt",
            "citation_hint": "引用时请标注出处链接与 last_updated 日期",
        },
        "last_updated": _dt.date.today().isoformat(),
        "disclaimer": "本文件为本人自述信息，仅供参考，不构成任何授权或许可；"
                      "robots.txt 与 llms.txt 不构成访问许可。",
    }
    content = json.dumps(identity, ensure_ascii=False, indent=2) + "\n"

    # 生成内容先过全套闸门，命中即不写盘（Milburn：只有 public-safe 子集离开 vault）
    exact, regexes = load_redlines(vault_dir / "redlines.md")
    scan_hits = scan_text(content, allow_email=True)  # identity.json 是设计内投影产物：contact.email 为白名单字段（docs/01 A13，与 check 模式 .json 放行一致）；真实敏感层（手机/证件/密钥）与私有禁词仍全量拦截
    scan_hits += scan_redlines(content, exact, regexes)
    if scan_hits:
        print(f"[GATE] ✋ 投影拦截：identity.json 生成内容命中 {len(scan_hits)} 项，不写盘：")
        for rid, _n, masked in scan_hits:
            print(f"  - [{rid}] {masked}")
        return EXIT_BLOCKED

    out = site_dir / "_data" / "identity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"[GATE] ✅ 投影完成 → {out}")
    print("[GATE] 仅映射白名单字段（display_name/role/summary/city/country/site_url/"
          "work_email/github_url/topics/capabilities）；vault 其余文件一律不外传。")
    return EXIT_OK


# ---------------------------------------------------------------- 入口
def main(argv):
    # 强制 UTF-8 输出：Windows 管道默认 GBK 会把规则名一起编码坏（CI 日志/自测断言都依赖可解析输出）
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="personal-site 投影+发布闸门（fail-closed）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="发布前扫描（pre-push / CI 共用）")
    p_check.add_argument("--dir", help="扫描目录（默认 site 根）")
    p_check.add_argument("--redlines", help="私有禁词清单路径（默认自动定位 vault/redlines.md）")
    p_check.add_argument("--no-frontmatter", action="store_true")
    p_check.add_argument("--no-exif", action="store_true")
    p_check.add_argument("--no-redlines", action="store_true")
    p_check.set_defaults(fn=cmd_check)

    p_proj = sub.add_parser("project", help="vault→site 公开子集投影（本地）")
    p_proj.add_argument("--vault", help="vault 目录（默认 ../vault）")
    p_proj.add_argument("--site", help="site 目录（默认 site 根）")
    p_proj.set_defaults(fn=cmd_project)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except GateConfigError as e:
        print(f"[GATE] 配置错误: {e}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
