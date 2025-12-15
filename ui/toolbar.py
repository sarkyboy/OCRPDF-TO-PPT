"""
工具栏模块 - UI组件
从 editor_main.py 提取的工具栏创建函数
注意：这是独立模块，主程序仍使用 editor_main.py 中的完整代码
"""

import tkinter as tk


def create_tool_btn(parent, text, command, color, bg=None, font_family="微软雅黑"):
    """创建工具栏按钮"""
    if bg is None:
        bg = "#F5F5F5"  # COLOR_RIBBON_BG
    btn = tk.Button(parent, text=text, command=command,
                   bg=color, fg="white", font=(font_family, 9),
                   padx=8, cursor="hand2", relief=tk.FLAT, bd=0)
    btn.pack(side=tk.LEFT, padx=2)
    return btn


def create_separator(parent, bg=None):
    """创建分隔线"""
    if bg is None:
        bg = "#F5F5F5"  # COLOR_RIBBON_BG
    sep_frame = tk.Frame(parent, bg=bg)
    sep_frame.pack(side=tk.LEFT, padx=6)
    sep_line = tk.Frame(sep_frame, bg="#ccc", width=1, height=20)
    sep_line.pack()


def create_toolbar(editor):
    """
    创建工具栏
    此函数需要传入编辑器实例，以便绑定回调
    """
    # 此处为模板，实际使用请参考 editor_main.py 中的 create_toolbar 方法
    pass
