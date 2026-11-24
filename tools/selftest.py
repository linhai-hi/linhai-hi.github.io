#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py —— 闸门自测（docs/00 验收硬标准：假手机号/假 token/缺字段必须被拦截）

在临时目录构造陷阱样例，运行 gate.py 并断言每类违规被拦截、干净样例通过。
全部为**构造的假数据**（非真实号码/证件/密钥；18 位身份证用 GB 11643 标准示例位）。

用法：python tools/selftest.py   （退出码 0=全部通过）
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GATE = Path(__file__).resolve().parent / "gate.py"
PYTHON = sys.executable

VALID_FM = """---
title: 闸门自测样例
type: page
status: published
date: 2026-11-22
privacy-checked: true
---
"""

# ---- 构造的假数据（独立常量；刻意避开占位符白名单形态）----
FAKE_GHP = "ghp_4qW9rT2xB7nK1mZ8vLcP5hY3jF6dS0aGeQz7"         # 36 位
FAKE_SK = "sk-Qw3ErTy9UiOp1AsDf2GhJk5Lz8Xc6Vb4Mn"             # 34 位
FAKE_GOOGLE = "AIzaSyD7q3BhHxkNvWqPzXyZnAbCdEfGhIjKLm7"       # 35 位
FAKE_JWT = ("eyJhbGciOiJIUzI1NiJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
FAKE_ID18 = "11010519491231002X"   # GB 11643-1999 标准示例位（本会话自算校验通过）
FAKE_ID15 = "110105491231002"      # 构造：省级行政区 + 合法出生段
FAKE_BANK = "4111111111111111"     # 公开测试卡号（Luhn 通过）

REDLINES = """# 自测用私有禁词清单
ProjectBlueOak
regex: TestSecret[A-Z0-9]{4,}
"""

# 每个陷阱一个文件：content, 期望拦截的规则 id
TRAPS = [
    ("假手机号", "trap-phone.md", VALID_FM + "有事请拨 13000000000。\n", "mobile"),
    ("假手机号(分段)", "trap-phone-spaced.md", VALID_FM + "备用号 138-0013-8000。\n", "mobile-spaced"),
    ("假身份证(18位)", "trap-id18.md", VALID_FM + f"样例证号 {FAKE_ID18}。\n", "id-card-18"),
    ("假身份证(15位)", "trap-id15.md", VALID_FM + f"旧证样例 {FAKE_ID15}。\n", "id-card-15"),
    ("假银行卡", "trap-bank.md", VALID_FM + f"测试卡号 {FAKE_BANK}。\n", "bank-card"),
    ("假银行卡(分组)", "trap-bank-spaced.md", VALID_FM + "测试卡号 4111 1111 1111 1111。\n", "bank-card-spaced"),
    ("假GitHub令牌", "trap-ghp.md", VALID_FM + f"token: {FAKE_GHP}\n", "token-github"),
    ("假OpenAI密钥", "trap-sk.md", VALID_FM + f"key: {FAKE_SK}\n", "token-openai"),
    ("假GoogleKey", "trap-google.md", VALID_FM + f"key: {FAKE_GOOGLE}\n", "token-google"),
    ("假JWT", "trap-jwt.md", VALID_FM + f"auth: {FAKE_JWT}\n", "token-jwt"),
    ("密钥赋值行", "trap-keyword.md", VALID_FM + "appSecret: 9f8e7d6c5b4a3210fedcba9876543210\n", "keyword-secret"),
    ("正文邮箱", "trap-email.md", VALID_FM + "联络邮箱 contact.personal@notreal-domain.test\n", "email"),
    ("私有禁词", "trap-redlines-word.md", VALID_FM + "本项目内部代号 ProjectBlueOak，仅测试。\n", "redlines-exact"),
    ("私有禁词(正则)", "trap-redlines-regex.md", VALID_FM + "测试串 TestSecretAB12CD34。\n", "redlines-regex"),
    ("缺privacy-checked", "trap-fm-privacy.md",
     "---\ntitle: 样例\ntype: page\nstatus: published\ndate: 2026-11-22\n---\n正文\n", "frontmatter-privacy-checked"),
    ("retell缺source", "trap-fm-source.md",
     "---\ntitle: 样例\ntype: retell\nstatus: published\ndate: 2026-11-22\nprivacy-checked: true\n---\n复述正文\n",
     "frontmatter-source"),
    ("status=draft", "trap-fm-draft.md",
     "---\ntitle: 样例\ntype: page\nstatus: draft\ndate: 2026-11-22\nprivacy-checked: true\n---\n正文\n",
     "frontmatter-status"),
    ("type非法", "trap-fm-type.md",
     "---\ntitle: 样例\ntype: blog\nstatus: published\ndate: 2026-11-22\nprivacy-checked: true\n---\n正文\n",
     "frontmatter-type"),
    ("JPEG含EXIF", "trap-exif.jpg", b"\xff\xd8\xff\xe1\x00\x20Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00" + b"\x00" * 16, "exif-jpeg"),
    ("HEIC禁入", "trap.heic", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1", "image-forbidden-format"),
]


def run_gate(args):
    return subprocess.run([PYTHON, str(GATE)] + args,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    # 工作目录放工具目录下（沙箱/只读环境可能禁写系统临时目录），结束后整体清掉
    base = Path(__file__).resolve().parent / ".selftest-work"
    shutil.rmtree(base, ignore_errors=True)
    tmp = base / "cases"
    tmp.mkdir(parents=True)
    passed, failed = 0, 0
    results = []
    try:
        redlines = tmp / "redlines.md"
        redlines.write_text(REDLINES, encoding="utf-8")
        for name, fname, content, rule in TRAPS:
            p = tmp / fname
            p.write_bytes(content if isinstance(content, bytes)
                          else content.encode("utf-8"))
            r = run_gate(["check", "--dir", str(tmp), "--redlines", str(redlines)])
            ok = (r.returncode == 1) and (rule in r.stdout)
            results.append((name, f"exit={r.returncode}", "PASS" if ok else "FAIL"))
            passed, failed = passed + ok, failed + (not ok)

        # 干净目录必须通过（含占位符形态 token，不应误报）
        clean = base / "clean"
        clean.mkdir()
        (clean / "clean-pass.md").write_text(
            VALID_FM + "这是一篇干净样例：2026-11-22 写于城市级地点，方法论有效。\n"
                       "占位密钥形如 sk-xxxx（占位，勿填真实值），不应触发。\n",
            encoding="utf-8")
        r = run_gate(["check", "--dir", str(clean), "--redlines", str(redlines)])
        ok = r.returncode == 0 and "mobile" not in r.stdout and "token" not in r.stdout
        results.append(("干净样例+占位符放行", f"exit={r.returncode}", "PASS" if ok else "FAIL"))
        passed, failed = passed + ok, failed + (not ok)

        # project 通路 1：干净 vault → 投影成功
        pv1, ps1 = base / "vault1", base / "site1"
        pv1.mkdir(parents=True)
        (pv1 / "redlines.md").write_text("# 空\n", encoding="utf-8")
        (pv1 / "profile.md").write_text(
            "# 样例\n```yaml\ndisplay_name: 自测样例\nrole: 闸门自测样例角色\n"
            "summary: 用于验证投影通路的样例描述。\ncity: 样例市\ncountry: CN\n"
            "topics: 测试, 样例\ncapabilities: 样例能力一, 样例能力二\n"
            "work_email:\ngithub_url:\nsite_url:\n```\n", encoding="utf-8")
        r = run_gate(["project", "--vault", str(pv1), "--site", str(ps1)])
        ok = r.returncode == 0 and (ps1 / "_data" / "identity.json").exists()
        results.append(("投影:干净vault→成功", f"exit={r.returncode}", "PASS" if ok else "FAIL"))
        passed, failed = passed + ok, failed + (not ok)

        # project 通路 2：vault 带假手机号 → 拦截且不写盘
        pv2, ps2 = base / "vault2", base / "site2"
        pv2.mkdir(parents=True)
        (pv2 / "redlines.md").write_text("# 空\n", encoding="utf-8")
        (pv2 / "profile.md").write_text(
            "# 样例\n```yaml\ndisplay_name: 自测样例\nrole: 闸门自测样例角色\n"
            "summary: 样例描述，联系电话 13000000000。\ncity: 样例市\ncountry: CN\n```\n",
            encoding="utf-8")
        r = run_gate(["project", "--vault", str(pv2), "--site", str(ps2)])
        ok = (r.returncode == 1 and "mobile" in r.stdout
              and not (ps2 / "_data" / "identity.json").exists())
        results.append(("投影:vault含手机号→拦截不写盘", f"exit={r.returncode}", "PASS" if ok else "FAIL"))
        passed, failed = passed + ok, failed + (not ok)

        # project 通路 3：work_email 已填（合法公开字段）→ 投影放行（回归：docs/01 A13 白名单一致性）
        pv3, ps3 = base / "vault3", base / "site3"
        pv3.mkdir(parents=True)
        (pv3 / "redlines.md").write_text("# 空\n", encoding="utf-8")
        (pv3 / "profile.md").write_text(
            "# 样例\n```yaml\ndisplay_name: 自测样例\nrole: 闸门自测样例角色\n"
            "summary: 用于验证工作邮箱字段的样例描述。\ncity: 样例市\ncountry: CN\n"
            "topics: 测试\ncapabilities: 样例能力\n"
            "work_email: sample.contact@example.com\ngithub_url:\nsite_url:\n```\n",
            encoding="utf-8")
        r = run_gate(["project", "--vault", str(pv3), "--site", str(ps3)])
        ok = r.returncode == 0 and (ps3 / "_data" / "identity.json").exists()
        results.append(("投影:含工作邮箱→放行(A13回归)", f"exit={r.returncode}", "PASS" if ok else "FAIL"))
        passed, failed = passed + ok, failed + (not ok)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("=" * 64)
    print("闸门自测结果（验收硬标准：docs/00 §5 阶段 1b）")
    print("=" * 64)
    for name, detail, verdict in results:
        print(f"  [{verdict}] {name}  ({detail})")
    print("-" * 64)
    print(f"通过 {passed} / 失败 {failed} / 共 {len(results)}")
    if failed:
        print("FAIL —— 闸门未达验收硬标准，禁止进入发布流程。")
        return 1
    print("PASS —— 全部陷阱被拦截，干净样例放行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
