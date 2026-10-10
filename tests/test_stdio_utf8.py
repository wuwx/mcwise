#!/usr/bin/env python
"""标准流编码回归测试。

复现并锁定 GitHub Actions 上真实出现过的故障：

    File "...\\lib\\encodings\\cp1252.py", line 19, in encode
    UnicodeEncodeError: 'charmap' codec can't encode characters in position 11-15

原因是 Windows（含 GitHub Actions 的 ``windows-latest`` runner）把
``sys.stdout`` 绑定到系统 ANSI 代码页（英文系统 ``cp1252``、中文系统
``cp936``）而非 UTF-8，输出中文即崩溃。

测试通过 ``PYTHONIOENCODING=cp1252`` 在**所有平台**上复现同一条件，
因此本文件在 Linux / macOS 上同样具备回归保护能力，不必依赖 Windows runner。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stdio_utf8 import ENCODING, STDIO_NAMES, force_utf8_stdio

SUBPROCESS_TIMEOUT = 120

# 故意把子进程的标准流压到 Windows 遗留代码页：PYTHONIOENCODING 的优先级高于 PYTHONUTF8，
# 因此在任何平台上都能稳定复现「非 UTF-8 标准流」这一条件。
LEGACY_CODEPAGE_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "cp1252",
    "PYTHONUTF8": "0",
}

SOLVERS = ("nutrition", "deals", "points", "campaigns")


def has_cjk(text: str) -> bool:
    """判断文本中是否含中日韩统一表意文字（用于确认中文真的写出来了）。"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def decode_utf8(data: bytes) -> str:
    """严格按 UTF-8 解码；若不是合法 UTF-8 会抛 UnicodeDecodeError。"""
    return data.decode("utf-8")


# --------------------------------------------------------------------------- #
# 单元测试：加固函数本身
# --------------------------------------------------------------------------- #
class RecordingStream:
    """支持 reconfigure 的假流，记录调用参数。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


class ClosedStream:
    """reconfigure 抛 ValueError 的假流（模拟已关闭的流）。"""

    def reconfigure(self, **kwargs: str) -> None:
        raise ValueError("I/O operation on closed file")


class TestForceUtf8Stdio(unittest.TestCase):
    def test_constant_is_utf8(self):
        self.assertEqual(ENCODING, "utf-8")
        self.assertEqual(STDIO_NAMES, ("stdin", "stdout", "stderr"))

    def test_switches_all_three_streams(self):
        streams = {name: RecordingStream() for name in STDIO_NAMES}
        with contextlib.ExitStack() as stack:
            for name, stream in streams.items():
                stack.enter_context(mock.patch.object(sys, name, stream))
            switched = force_utf8_stdio()

        self.assertEqual(switched, list(STDIO_NAMES))
        for name, stream in streams.items():
            with self.subTest(stream=name):
                self.assertEqual(len(stream.calls), 1)
                self.assertEqual(stream.calls[0]["encoding"], "utf-8")
                # 编码问题绝不能让程序崩溃：无法表示的字符降级为占位符
                self.assertEqual(stream.calls[0]["errors"], "replace")

    def test_stream_without_reconfigure_is_skipped(self):
        """StringIO 等对象没有 reconfigure，应被跳过而不是抛 AttributeError。"""
        with (
            mock.patch.object(sys, "stdin", io.StringIO()),
            mock.patch.object(sys, "stdout", RecordingStream()),
            mock.patch.object(sys, "stderr", RecordingStream()),
        ):
            self.assertEqual(force_utf8_stdio(), ["stdout", "stderr"])

    def test_none_stream_is_skipped(self):
        """pythonw.exe 等无控制台场景下标准流可能为 None。"""
        with (
            mock.patch.object(sys, "stdin", None),
            mock.patch.object(sys, "stdout", RecordingStream()),
            mock.patch.object(sys, "stderr", None),
        ):
            self.assertEqual(force_utf8_stdio(), ["stdout"])

    def test_closed_stream_is_tolerated(self):
        with (
            mock.patch.object(sys, "stdin", ClosedStream()),
            mock.patch.object(sys, "stdout", ClosedStream()),
            mock.patch.object(sys, "stderr", ClosedStream()),
        ):
            self.assertEqual(force_utf8_stdio(), [])

    def test_is_idempotent(self):
        stdout = RecordingStream()
        with mock.patch.object(sys, "stdout", stdout):
            force_utf8_stdio()
            force_utf8_stdio()
        self.assertEqual(len(stdout.calls), 2)


# --------------------------------------------------------------------------- #
# 端到端测试：在遗留代码页下运行真实 CLI
# --------------------------------------------------------------------------- #
class TestCliUnderLegacyCodepage(unittest.TestCase):
    maxDiff = None

    def run_script(self, script: str, *args: str, stdin_bytes: bytes | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            cwd=str(ROOT),
            input=stdin_bytes,
            capture_output=True,
            env=LEGACY_CODEPAGE_ENV,
            timeout=SUBPROCESS_TIMEOUT,
        )

    def test_env_reproduces_the_bug_without_hardening(self):
        """反证：同一环境变量下，未加固的脚本必定崩溃。

        这条断言保证其余测试不是因为「环境恰好是 UTF-8」才通过的。
        """
        proc = subprocess.run(
            [sys.executable, "-c", "print('麦麦智囊')"],
            capture_output=True,
            env=LEGACY_CODEPAGE_ENV,
            timeout=SUBPROCESS_TIMEOUT,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(b"UnicodeEncodeError", proc.stderr)

    def test_all_solvers_emit_utf8_chinese(self):
        for cmd in SOLVERS:
            with self.subTest(command=cmd):
                proc = self.run_script("cli.py", cmd, "--input", f"examples/{cmd}_input.json")
                self.assertEqual(proc.returncode, 0, decode_utf8(proc.stderr))
                text = decode_utf8(proc.stdout)
                self.assertTrue(text.strip(), "CLI 输出为空")
                self.assertTrue(has_cjk(text), f"{cmd} 输出不含中文：{text[:120]!r}")

    def test_json_output_is_machine_consumable(self):
        proc = self.run_script("cli.py", "points", "--input", "examples/points_input.json", "--json")
        self.assertEqual(proc.returncode, 0, decode_utf8(proc.stderr))
        payload = json.loads(decode_utf8(proc.stdout))
        self.assertGreater(payload["plan"]["used_points"], 0)

    def test_intents_and_chain_are_readable(self):
        for args in (("intents",), ("chain", "nutrition_plan"), ("chain", "one_tap_order")):
            with self.subTest(args=args):
                proc = self.run_script("cli.py", *args)
                self.assertEqual(proc.returncode, 0, decode_utf8(proc.stderr))
                self.assertTrue(has_cjk(decode_utf8(proc.stdout)))

    def test_help_text_is_readable(self):
        """加固必须在解析参数之前完成，否则中文帮助信息会先崩溃。"""
        proc = self.run_script("cli.py", "--help")
        self.assertEqual(proc.returncode, 0, decode_utf8(proc.stderr))
        self.assertTrue(has_cjk(decode_utf8(proc.stdout)))

    def test_stdin_payload_with_chinese(self):
        """--stdin 读中文 JSON：stdin 也必须被加固，否则解析报文就会失败。"""
        raw = (ROOT / "examples" / "deals_input.json").read_bytes()
        self.assertTrue(has_cjk(decode_utf8(raw)), "夹具本身应含中文，否则本测试无意义")
        proc = self.run_script("cli.py", "deals", "--stdin", "--json", stdin_bytes=raw)
        self.assertEqual(proc.returncode, 0, decode_utf8(proc.stderr))
        self.assertTrue(has_cjk(decode_utf8(proc.stdout)))

    def test_compliance_checker_emits_utf8_chinese(self):
        proc = self.run_script("check_compliance.py")
        self.assertEqual(proc.returncode, 0, decode_utf8(proc.stderr))
        self.assertTrue(has_cjk(decode_utf8(proc.stdout)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
