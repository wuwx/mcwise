"""参赛合规自检脚本的单元测试。

核心目的：证明 ``check_compliance.py`` **确实能抓到违规**，而不是永远返回通过。

运行方式：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_compliance as cc

DECL_BODY = "# 参赛声明\n\n## 原创性声明\n\n参赛项目系原创开发。\n".encode()
DECL_SHA = hashlib.sha256(DECL_BODY).hexdigest()

# 以下"违规样例"在运行时拼接，避免自检脚本对自己的测试夹具误报。
# 拼接后的字符串才会命中 SECRET_PATTERNS，源码字面量不会。
FAKE_TOKEN = "Bearer " + "eyJhbGciOiJIUzI1NiJ9" + "abcdefghijklmnopqrstuvwxyz"
FAKE_PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow\n"


def make_fixture(base: Path, *, with_decl: bool = True, decl_body: bytes | None = None) -> Path:
    """构造一个最小合规仓库。"""
    base.mkdir(parents=True, exist_ok=True)
    (base / "README.md").write_text("# demo\n", encoding="utf-8")
    (base / "MCP_INTEGRATION.md").write_text("# mcp\n", encoding="utf-8")
    (base / "mcp-config.example.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mcd-mcp": {
                        "type": "streamablehttp",
                        "url": "https://mcp.mcd.cn",
                        "headers": {"Authorization": "Bearer ${MCD_MCP_TOKEN}"},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if with_decl:
        (base / "CONTEST_DECLARATION.md").write_bytes(DECL_BODY if decl_body is None else decl_body)
    return base


class ComplianceFixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mcwise-compliance-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_check(self, root: Path) -> int:
        """静音执行自检，只关心退出码。"""
        with contextlib.redirect_stdout(io.StringIO()):
            return cc.run(root, DECL_SHA)

    # ---- 正向 ----
    def test_clean_repo_passes(self):
        root = make_fixture(self.tmp / "clean")
        self.assertEqual(self.run_check(root), 0)

    # ---- 反向：必须能抓到违规 ----
    def test_missing_required_file_fails(self):
        root = make_fixture(self.tmp / "missing")
        os.remove(root / "MCP_INTEGRATION.md")
        self.assertEqual(self.run_check(root), 1)

    def test_modified_declaration_fails(self):
        root = make_fixture(self.tmp / "tampered")
        (root / "CONTEST_DECLARATION.md").write_bytes(DECL_BODY + b"\nextra\n")
        self.assertEqual(self.run_check(root), 1)

    def test_crlf_in_declaration_fails(self):
        root = make_fixture(self.tmp / "crlf")
        (root / "CONTEST_DECLARATION.md").write_bytes(DECL_BODY.replace(b"\n", b"\r\n"))
        # sha256 变了 + 含 CRLF，双重违规
        self.assertEqual(self.run_check(root), 1)

    def test_real_token_in_config_fails(self):
        root = make_fixture(self.tmp / "token")
        cfg = json.loads((root / "mcp-config.example.json").read_text(encoding="utf-8"))
        cfg["mcpServers"]["mcd-mcp"]["headers"]["Authorization"] = FAKE_TOKEN
        (root / "mcp-config.example.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.assertEqual(self.run_check(root), 1)

    def test_env_file_present_fails(self):
        root = make_fixture(self.tmp / "dotenv")
        (root / ".env").write_text("MCD_MCP_TOKEN=abc\n", encoding="utf-8")
        self.assertEqual(self.run_check(root), 1)

    def test_json_bom_fails(self):
        root = make_fixture(self.tmp / "bom")
        (root / "bad.json").write_bytes(b"\xef\xbb\xbf" + b'{"a": 1}')
        self.assertEqual(self.run_check(root), 1)

    def test_private_key_fails(self):
        root = make_fixture(self.tmp / "key")
        (root / "leak.txt").write_text(FAKE_PRIVATE_KEY, encoding="utf-8")
        self.assertEqual(self.run_check(root), 1)

    # ---- 脚本自身不自我误报 ----
    def test_checker_does_not_self_trigger(self):
        """脚本源码里含有检测模式字符串，但不应自我命中。"""
        data = (SCRIPTS / "check_compliance.py").read_bytes()
        for pattern, desc in cc.SECRET_PATTERNS:
            self.assertIsNone(pattern.search(data), f"自检脚本被自己的规则误报：{desc}")


class RepoItselfTest(unittest.TestCase):
    """对整个仓库做一次真实校验。"""

    def test_repository_is_compliant(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cc.run(ROOT, cc.OFFICIAL_DECLARATION_SHA256), 0)

    def test_official_hash_format(self):
        self.assertRegex(cc.OFFICIAL_DECLARATION_SHA256, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
