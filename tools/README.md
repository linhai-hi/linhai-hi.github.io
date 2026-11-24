# site/tools —— 投影 + 发布闸门

| 文件 | 用途 |
|---|---|
| `gate.py` | 唯一实现（守则第 3 条）：`project`（vault→site 投影）与 `check`（发布前扫描） |
| `selftest.py` | 闸门自测：构造假手机号/假 token/缺字段样例，验证全部被拦截（docs/00 验收硬标准） |
| `hooks/pre-push` | 可选本地钩子：`git config core.hooksPath tools/hooks` 后每次 push 前强制过闸门 |
| `exif-allowlist.txt` | EXIF 白名单（文件级留痕；闸门唯一的人工豁免口，仅此一处） |

## 用法

```bash
python tools/gate.py project            # vault/profile.md → site/_data/identity.json（本地）
python tools/gate.py check              # 发布前扫描（pre-push 与 CI 共用同一实现）
python tools/selftest.py                # 自测（任何修改 gate.py 之后必须重跑）
```

退出码：`0` 通过 · `1` 拦截 · `2` 用法/配置错误。**命中即中止，不是警告。**

规则清单、误报/漏报边界、占位符白名单：见 `../docs/01-方案与选型.md` §5 与 `../docs/02-发布红线定稿.md` F5。
