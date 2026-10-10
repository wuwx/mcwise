#!/usr/bin/env python
"""参赛合规自检脚本。

在提交报名前、以及每次 CI 运行时，自动核验本项目是否满足
「麦当劳程序员创意开发大赛」对参赛仓库的硬性要求：

1. 必需文件齐全且文件名完全正确；
2. ``CONTEST_DECLARATION.md`` 与官方原文**逐字节一致**（sha256 校验）；
3. 所有 JSON 文件语法合法；
4. ``mcp-config.example.json`` 只含环境变量占位符，不含真实 Token；
5. 仓库内不存在硬编码凭据、私钥、``.env`` 等敏感内容。

本地运行：
    python scripts/check_compliance.py

退出码：0 = 全部通过；1 = 存在不合规项。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from stdio_utf8 import force_utf8_stdio

REPO_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
# 校验规则
# --------------------------------------------------------------------------- #
REQUIRED_FILES = {
    "README.md": "项目介绍、安装方法、使用示例、目标用户",
    "CONTEST_DECLARATION.md": "参赛声明（文件名与内容均不可改动）",
    "MCP_INTEGRATION.md": "MCP Server / Tool / 调用流程 / 业务价值",
    "mcp-config.example.json": "脱敏 MCP 配置（仅环境变量占位符）",
}

BONUS_FILES = {
    "workbuddy.md": "WorkBuddy 专项奖励（可选，需真实使用 WorkBuddy 时提交）",
}

# 官方原文 CONTEST_DECLARATION.md 的 sha256（来源：M-China/mcd-developer-innovation-challenge）
OFFICIAL_DECLARATION_SHA256 = "cd28101bcb29cc8fb24b372fe91ce6b42c4a1487a54e01f7ade0c8c6a84241b7"

ENV_PLACEHOLDER_RE = re.compile(r"\$\{[A-Z0-9_]+\}")

FORBIDDEN_PATHS = [
    ".env",
    ".env.local",
    "mcp-config.json",
    "token.txt",
    "secrets",
]

# (正则, 说明) —— 注意：以下模式在源码中不会自我命中
SECRET_PATTERNS: list[tuple[bytes, str]] = [
    (re.compile(rb"Bearer\s+(?!\$\{)[A-Za-z0-9\-_.]{24,}"), "疑似硬编码 MCP Token"),
    (re.compile(rb"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----"), "私钥内容"),
    (re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,}"), "疑似 GitHub Token"),
    (re.compile(rb"\bsk-[A-Za-z0-9]{32,}"), "疑似 API Key"),
]

SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".workbuddy",
}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".pyc",
    ".so",
    ".dll",
}
MAX_SCAN_BYTES = 2 * 1024 * 1024


# --------------------------------------------------------------------------- #
# 结果收集
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.checks = 0

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        self.checks += 1
        mark = "✓" if ok else "✗"
        line = f"  {mark} {label}"
        if detail:
            line += f"  —  {detail}"
        print(line)
        if not ok:
            self.failures.append(label)
        return ok

    def section(self, title: str) -> None:
        print(f"\n{title}")


# --------------------------------------------------------------------------- #
# 各项检查
# --------------------------------------------------------------------------- #
def check_required_files(root: Path, report: Report) -> None:
    report.section("[1/5] 必需文件")
    for name, desc in REQUIRED_FILES.items():
        path = root / name
        report.check(path.is_file(), f"{name}", desc)

    report.section("[2/5] 专项奖励文件（可选）")
    for name, desc in BONUS_FILES.items():
        path = root / name
        if path.is_file():
            report.check(True, f"{name}", f"已提交 — {desc}")
        else:
            report.checks += 1
            print(f"  ○ {name}  —  未提交（不参与该项奖励，不影响报名）")


def check_declaration(root: Path, report: Report, expected_sha: str) -> None:
    report.section("[3/5] 参赛声明原文一致性")
    path = root / "CONTEST_DECLARATION.md"
    if not path.is_file():
        report.check(False, "CONTEST_DECLARATION.md 存在", "文件缺失，无法校验")
        return

    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    report.check(
        actual == expected_sha,
        "内容与官方原文逐字节一致",
        f"sha256 {actual[:16]}…" if actual == expected_sha else f"实际 {actual[:16]}… ≠ 期望 {expected_sha[:16]}…",
    )
    report.check(b"\r\n" not in data, "换行符为 LF（无 CRLF 污染）")


def check_json(root: Path, report: Report) -> None:
    report.section("[4/5] JSON 语法与脱敏")
    json_files = sorted(p for p in root.rglob("*.json") if not any(part in SKIP_DIR_NAMES for part in p.parts))
    if not json_files:
        report.check(False, "发现 JSON 文件", "未找到任何 JSON 文件")
        return

    for path in json_files:
        rel = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError as exc:  # pragma: no cover
            report.check(False, rel, f"读取失败：{exc}")
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            report.check(False, rel, "含 UTF-8 BOM，部分解析器会报错")
            continue
        try:
            json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            report.check(False, rel, f"解析失败：{exc}")
            continue
        report.check(True, rel, "语法合法")

    # 脱敏专项校验
    cfg_path = root / "mcp-config.example.json"
    if not cfg_path.is_file():
        return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return

    servers = cfg.get("mcpServers") if isinstance(cfg, dict) else None
    report.check(isinstance(servers, dict) and bool(servers), "mcp-config.example.json 含 mcpServers 配置")

    text = cfg_path.read_text(encoding="utf-8")
    has_placeholder = bool(ENV_PLACEHOLDER_RE.search(text))
    report.check(has_placeholder, "使用环境变量占位符", f"匹配到 {ENV_PLACEHOLDER_RE.pattern}")
    auth_hits = [m.group(0) for m in re.finditer(rb"Bearer\s+(?!\$\{)[A-Za-z0-9\-_.]{8,}", cfg_path.read_bytes())]
    report.check(not auth_hits, "Authorization 中无真实 Token", f"发现 {len(auth_hits)} 处可疑值" if auth_hits else "")


def check_secrets(root: Path, report: Report) -> None:
    report.section("[5/5] 敏感信息扫描")

    found_paths = [
        p.relative_to(root).as_posix()
        for name in FORBIDDEN_PATHS
        for p in root.rglob(name)
        if not any(part in SKIP_DIR_NAMES for part in p.parts)
    ]
    report.check(not found_paths, "无 .env / 真实配置文件入库", ", ".join(found_paths) if found_paths else "")

    scanned = 0
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            data = path.read_bytes()
        except OSError:  # pragma: no cover
            continue
        scanned += 1
        for pattern, desc in SECRET_PATTERNS:
            if pattern.search(data):
                hits.append(f"{path.relative_to(root).as_posix()} → {desc}")
    report.check(not hits, f"无硬编码凭据（已扫描 {scanned} 个文件）", "; ".join(hits))


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def run(root: Path, expected_sha: str) -> int:
    report = Report()
    print("=" * 68)
    print("麦麦智囊 McWise — 麦当劳程序员创意开发大赛 参赛合规自检")
    print(f"仓库根目录：{root}")
    print("=" * 68)

    check_required_files(root, report)
    check_declaration(root, report, expected_sha)
    check_json(root, report)
    check_secrets(root, report)

    print("\n" + "=" * 68)
    if report.failures:
        print(f"结果：✗ 未通过 — {len(report.failures)}/{report.checks} 项不合规")
        for item in report.failures:
            print(f"  · {item}")
        print("=" * 68)
        return 1
    print(f"结果：✓ 全部通过（共 {report.checks} 项检查）")
    print("=" * 68)
    return 0


def main(argv: list[str] | None = None) -> int:
    # 自检结果含中文，Windows 默认代码页会直接抛 UnicodeEncodeError。
    force_utf8_stdio()

    parser = argparse.ArgumentParser(description="参赛仓库合规自检")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="仓库根目录（默认自动推断）")
    parser.add_argument(
        "--expected-sha256",
        default=OFFICIAL_DECLARATION_SHA256,
        help="期望的 CONTEST_DECLARATION.md sha256",
    )
    args = parser.parse_args(argv)
    return run(args.root.resolve(), args.expected_sha256.lower())


if __name__ == "__main__":
    raise SystemExit(main())
