"""
允许使用 `python -m ppt_editor_modular` 启动。
"""

from __future__ import annotations

import argparse
import tkinter as tk

from .editor_main import ModernPPTEditor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ppt_editor_modular")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="只创建窗口与UI后立即退出（用于冒烟测试）",
    )
    args = parser.parse_args(argv)

    root = tk.Tk()
    app = ModernPPTEditor(root)
    if args.smoke:
        root.update_idletasks()
        root.destroy()
        return 0

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

