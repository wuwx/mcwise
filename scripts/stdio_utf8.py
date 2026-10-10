#!/usr/bin/env python
"""标准流编码加固。

**问题背景**

Python 在 Windows 上会把 ``sys.stdout`` / ``sys.stderr`` 绑定到系统的
「ANSI 代码页」——英文系统是 ``cp1252``，简体中文系统是 ``cp936``，
而不是 UTF-8。只要程序向终端或管道写出中文，就会抛出：

    UnicodeEncodeError: 'charmap' codec can't encode characters ...

这在 GitHub Actions 的 ``windows-latest`` runner 上**必然复现**（该 runner
的代码页是 1252），且与 Python 版本无关，3.9 与 3.13 表现一致。重定向到
文件或 ``/dev/null`` 并不能规避——编码发生在写入流的那一刻。

**解决方式**

在进程入口把三个标准流显式切到 UTF-8，不依赖宿主自身的 locale 或用户
是否设置了 ``PYTHONUTF8``。注意 ``PYTHONIOENCODING`` 的优先级**高于**
``PYTHONUTF8``，因此仅设置环境变量并不足以防御，运行时重设才是可靠手段。
"""

from __future__ import annotations

import sys

ENCODING = "utf-8"

STDIO_NAMES = ("stdin", "stdout", "stderr")


def force_utf8_stdio(errors: str = "replace") -> list[str]:
    """把 ``stdin`` / ``stdout`` / ``stderr`` 切换到 UTF-8，返回成功切换的流名。

    ``errors`` 默认 ``"replace"``：极端情况下宁可输出占位字符，也不要让
    程序因为编码问题直接崩溃。

    以下情况会被静默跳过，**绝不因为加固编码本身而让程序启动失败**：

    * 流为 ``None``（``pythonw.exe`` 等无控制台场景）；
    * 流没有 ``reconfigure``（如 ``io.StringIO``、被测试框架接管的标准流）；
    * 流已关闭或底层管道不可用（``ValueError`` / ``OSError``）。
    """
    switched: list[str] = []
    for name in STDIO_NAMES:
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=ENCODING, errors=errors)
        except (ValueError, OSError, AttributeError):
            # ValueError: 流已关闭；OSError: 底层管道不可用
            continue
        switched.append(name)
    return switched
