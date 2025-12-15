"""
启动脚本（在仓库/包目录内也可运行）。

用法：
  python run_ppt_editor.py
  python run_ppt_editor.py --smoke
  python run_ppt_editor.py --show-py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _dump_python_code(base_path: Path, *, recursive: bool, max_bytes: int) -> int:
    if not base_path.exists():
        print(f"[show-py] 路径不存在: {base_path}", file=sys.stderr)
        return 2

    if base_path.is_file():
        py_files = [base_path]
    else:
        pattern = "**/*.py" if recursive else "*.py"
        py_files = [
            p
            for p in base_path.glob(pattern)
            if p.is_file()
            and "__pycache__" not in p.parts
            and ".venv" not in p.parts
            and "venv" not in p.parts
        ]
        py_files.sort(key=lambda p: str(p).lower())

    if not py_files:
        print(f"[show-py] 未找到 .py 文件: {base_path}")
        return 0

    for py_file in py_files:
        header_path = py_file
        try:
            header_path = py_file.relative_to(base_path)
        except Exception:
            pass

        print(f"\n# === {header_path} ===")
        data = py_file.read_bytes()
        if max_bytes > 0 and len(data) > max_bytes:
            shown = data[:max_bytes]
            truncated = True
        else:
            shown = data
            truncated = False

        sys.stdout.write(shown.decode("utf-8", errors="replace"))
        if not shown.endswith(b"\n"):
            sys.stdout.write("\n")
        if truncated:
            sys.stdout.write(f"# [truncated: {max_bytes}/{len(data)} bytes]\n")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_ppt_editor.py")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="只创建窗口与UI后立即退出（用于冒烟测试）",
    )
    parser.add_argument(
        "--show-py",
        action="store_true",
        help="打印指定路径(默认当前工作目录)下的 .py 文件内容并退出",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="用于 --show-py 的目录或文件路径（默认：.）",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="递归扫描子目录（用于 --show-py）",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=200_000,
        help="单个文件最多打印字节数（0 表示不限制；用于 --show-py）",
    )
    args = parser.parse_args(argv)

    if args.show_py:
        return _dump_python_code(
            Path(args.path),
            recursive=args.recursive,
            max_bytes=args.max_bytes,
        )

    # 让 `import ppt_editor_modular` 在“位于包目录内运行脚本”时也能成功：
    #   d:\code\pptocr\ppt_editor_modular\run_ppt_editor.py
    # 需要把父目录 d:\code\pptocr 加到 sys.path。
    this_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(this_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    import tkinter as tk
    from ppt_editor_modular.editor_main import ModernPPTEditor

    root = tk.Tk()
    _ = ModernPPTEditor(root)
    if args.smoke:
        root.update_idletasks()
        root.destroy()
        return 0

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
