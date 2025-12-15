"""
常量模块 - 从原始文件精确提取
全局配色（仿PowerPoint）
"""

from pptx.util import Emu

# === 全局配色（仿PowerPoint） ===
COLOR_THEME = "#B7472A"           # PowerPoint红色主题
COLOR_THEME_HOVER = "#C85A3F"     # 悬停色
COLOR_RIBBON_BG = "#F5F5F5"       # Ribbon工具栏背景
COLOR_RIBBON_ROW2 = "#E8E8E8"     # 第二行背景
COLOR_CANVAS_BG = "#E0E0E0"       # 画布背景
COLOR_SIDEBAR_BG = "#FAFAFA"      # 侧边栏背景
COLOR_WHITE = "#FFFFFF"
COLOR_TEXT = "#333333"
COLOR_BLUE = "#1976D2"
COLOR_GREEN = "#43A047"
COLOR_ORANGE = "#FB8C00"
COLOR_PURPLE = "#8E24AA"
COLOR_RED = "#E53935"
COLOR_GRAY = "#607D8B"
FONT_FAMILY = "微软雅黑"


def Px(pixels):
    """像素转EMU单位"""
    return Emu(int(pixels) * 9525)
