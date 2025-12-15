"""
现代化PPT编辑器 - 仿PowerPoint界面
UI风格：参考PowerPoint的现代布局
- 顶部：红色标题栏 + 双行工具栏
- 左侧：页面缩略图导航
- 中间：主编辑画布
- 右侧：属性面板
- 底部：红色状态栏
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser, simpledialog
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageFilter, ImageChops, ImageOps
import json
import os
import threading
import logging
import cv2
import numpy as np
import tempfile
import copy
import math
from datetime import datetime
import requests
import base64
from io import BytesIO
import uuid

# AI图片生成API支持
from .ai_image_api_module import AIImageAPIManager, blend_images

# PDF支持 - 使用PyMuPDF，更简单，不需要Poppler
try:
    import fitz  # PyMuPDF
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("提示: 安装 PyMuPDF 可支持PDF导入")
    print("      pip install PyMuPDF")


logging.getLogger("ppocr").setLevel(logging.WARNING)

from .config import get_base_dir, load_config, save_config
from .constants import (
    COLOR_THEME,
    COLOR_THEME_HOVER,
    COLOR_RIBBON_BG,
    COLOR_RIBBON_ROW2,
    COLOR_CANVAS_BG,
    COLOR_SIDEBAR_BG,
    COLOR_WHITE,
    COLOR_TEXT,
    COLOR_BLUE,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_GRAY,
    FONT_FAMILY,
    Px,
)
from .textbox import TextBox

from .core import history as history_core
from .core import ocr as ocr_core
from .core.font_fit import fit_font_size_pt
from .core import page_manager as page_manager_core
from .features import export as export_feature
from .features import project as project_feature
from .features import inpaint as inpaint_feature
from .features import ai_replace as ai_replace_feature

from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR


class ModernPPTEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("PPT编辑器专业版 - 增强版")
        self.root.geometry("1500x900")
        self.root.configure(bg=COLOR_RIBBON_BG)

        # 加载配置
        self.config = load_config()

        # 多页支持
        self.pages = []
        self.current_page_index = 0

        # 当前页数据
        self.original_img_path = None
        self.clean_bg_path = None
        self.original_image = None
        self.display_image = None
        self.tk_image = None
        self.scale = 1.0

        # 文本框
        self.text_boxes = []
        # 图层（每页持久化在 page["layers"]，这里是当前页引用）
        self.layers = []
        self.selected_layer_index = -1
        self.selected_box_index = -1
        self.selected_boxes = []

        # 预览模式
        # raw: 只看原始编辑底图（不叠加图层）
        # edit: 编辑视图（叠加背景/图层 + 框）
        # ppt: PPT效果（叠加背景/图层 + 渲染文字）
        self.current_preview_mode = "raw"
        self.ppt_preview_image = None

        # 撤销/重做 - 全局历史系统
        self.history = []  # 格式: [{"type": "xxx", "data": {...}, "page_index": N}, ...]
        self.history_index = -1
        self.max_history = 50

        # 绘制状态
        self.is_drawing = False
        self.draw_start_x = 0
        self.draw_start_y = 0
        self.temp_rect_id = None
        self.is_dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_resizing = False
        self.resize_handle = None
        self.is_selecting = False  # 框选模式
        self.select_start_x = 0
        self.select_start_y = 0
        # 图层拖动（从图层面板选中后，在画布上拖动）
        self.is_layer_dragging = False
        self._layer_drag_start_canvas = None
        self._layer_drag_origin_xy = None

        # 绘制模式
        self.draw_mode = True

        # OCR模型
        self.ocr = None

        # 缩略图
        self.thumbnail_images = []
        # 复制粘贴支持
        self.clipboard_boxes = []

        # 涂抹模式相关
        self.inpaint_mode = False  # 是否处于涂抹模式
        self.inpaint_tool = "brush"  # brush 或 rect
        self.inpaint_brush_size = 30  # 笔刷大小
        self.inpaint_mask_layer = None  # PIL Image (L模式)，白色=需要修复的区域
        self.inpaint_draw_layer = None  # ImageDraw对象
        self.inpaint_last_pos = None  # 笔刷上一个位置
        self.inpaint_rect_start = None  # 矩形框选起始点
        self.inpaint_temp_rect_id = None  # 临时矩形视觉ID
        self.inpaint_strokes = []  # 涂抹历史记录（用于撤销）

        # AI图片替换模式相关
        self.ai_replace_mode = False  # 是否处于AI替换模式
        self.ai_replace_rect_start = None  # 框选起始点
        self.ai_replace_rect_end = None  # 框选结束点
        self.ai_replace_selection = None  # 当前选中的区域 (x1, y1, x2, y2)
        self.ai_replace_rect_id = None  # 选框的canvas ID

        # AI图片API管理器
        self.ai_api_manager = AIImageAPIManager()
        # 加载AI API配置
        if "ai_image_api" in self.config:
            self.ai_api_manager.load_config(self.config)

        # 自动保存
        self.autosave_timer = None
        self.project_file_path = None
        self.has_unsaved_changes = False

        # 创建自动保存目录
        AUTOSAVE_DIR = os.path.join(get_base_dir(), "autosave")
        os.makedirs(AUTOSAVE_DIR, exist_ok=True)
        self.autosave_dir = AUTOSAVE_DIR


        # 创建界面
        self.create_ui()

        # 绑定快捷键
        self.bind_shortcuts()

        # 后台加载 OCR（按需使用；不阻塞 UI）
        if self.config.get("ocr_autoload", True):
            threading.Thread(target=self.init_ocr, daemon=True).start()

        # 启动自动保存
        if self.config.get("autosave_enabled", True):
            self.start_autosave()

        # 窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)


    def _imread_unicode(self, filepath):
        """
        安全读取包含中文路径的图片
        解决OpenCV无法读取中文路径的问题
        """
        try:
            # 使用numpy读取文件，然后解码为图片
            img_array = np.fromfile(filepath, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            return img
        except Exception as e:
            print(f"读取图片失败: {filepath}, 错误: {e}")
            return None

    def init_ocr(self):
        return ocr_core.init_ocr(self)

    def create_ui(self):
        """创建界面"""
        # === 顶部标题栏 ===
        self.create_title_bar()

        # === 工具栏 ===
        self.create_toolbar()

        # === 主内容区 ===
        self.main_container = tk.Frame(self.root, bg=COLOR_CANVAS_BG)
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # 左侧：页面缩略图
        self.create_thumbnail_panel()

        # 中间：主编辑区
        self.create_canvas_area()

        # 右侧：属性面板
        self.create_property_panel()

        # === 底部状态栏 ===
        self.create_status_bar()

    def create_title_bar(self):
        """创建顶部标题栏 - PowerPoint红色风格"""
        title_bar = tk.Frame(self.root, bg=COLOR_THEME, height=32)
        title_bar.pack(fill=tk.X, side=tk.TOP)
        title_bar.pack_propagate(False)

        # 左侧标题
        title_label = tk.Label(title_bar, text="PPT编辑器专业版",
                              bg=COLOR_THEME, fg="white",
                              font=(FONT_FAMILY, 11, "bold"))
        title_label.pack(side=tk.LEFT, padx=15)

        # 右侧页码信息
        self.title_page_label = tk.Label(title_bar, text="第 0/0 页",
                                         bg=COLOR_THEME, fg="white",
                                         font=(FONT_FAMILY, 10))
        self.title_page_label.pack(side=tk.RIGHT, padx=15)

        # 自动保存状态指示器
        self.autosave_indicator = tk.Label(title_bar, text="●",
                                          bg=COLOR_THEME, fg="#4CAF50",
                                          font=(FONT_FAMILY, 16))
        self.autosave_indicator.pack(side=tk.RIGHT, padx=5)

    def create_toolbar(self):
        """创建顶部工具栏 - 三行布局（适配小屏幕）"""
        toolbar = tk.Frame(self.root, bg=COLOR_RIBBON_BG, relief=tk.FLAT)
        toolbar.pack(fill=tk.X, side=tk.TOP)

        # 底部边框线
        border_line = tk.Frame(toolbar, bg="#ddd", height=1)
        border_line.pack(fill=tk.X, side=tk.BOTTOM)

        # === 第一行：文件、检测、识别 ===
        row1 = tk.Frame(toolbar, bg=COLOR_RIBBON_BG)
        row1.pack(fill=tk.X, padx=10, pady=(6, 2))

        # 文件组
        tk.Label(row1, text="文件:", bg=COLOR_RIBBON_BG, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
        self.create_tool_btn(row1, "导入图片", self.load_multiple_images, COLOR_GREEN)
        self.create_tool_btn(row1, "导入背景", self.load_multiple_backgrounds, COLOR_BLUE)
        self.create_tool_btn(row1, "新建空白", self.create_blank_page, "#2196F3")
        if PDF_SUPPORT:
            self.create_tool_btn(row1, "导入PDF", self.import_pdf, "#D32F2F")

        self.create_tool_btn(row1, "保存项目", self.save_project, COLOR_GRAY)
        self.create_tool_btn(row1, "打开项目", self.load_project, COLOR_GRAY)

        self.create_separator(row1)

        # 检测组
        tk.Label(row1, text="检测:", bg=COLOR_RIBBON_BG, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
        self.create_tool_btn(row1, "当前页", self.auto_detect_text_regions, COLOR_ORANGE)
        self.create_tool_btn(row1, "全部页", self.auto_detect_all_pages, "#EF6C00")

        self.create_separator(row1)

        # 识别组
        tk.Label(row1, text="识别:", bg=COLOR_RIBBON_BG, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
        self.create_tool_btn(row1, "当前页", self.ocr_all_boxes, COLOR_PURPLE)
        self.create_tool_btn(row1, "全部页", self.ocr_all_pages, "#6A1B9A")

        self.create_separator(row1)

        # 自动字号组
        tk.Label(row1, text="字号:", bg=COLOR_RIBBON_BG, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
        self.create_tool_btn(row1, "当前页", self.auto_font_size_all, "#00ACC1")
        self.create_tool_btn(row1, "全部页", self.auto_font_size_all_pages, "#00838F")

        # 右侧：导出和设置
        settings_btn = tk.Button(row1, text="⚙ 设置", command=self.show_settings_dialog,
                                bg="#546E7A", fg="white", font=(FONT_FAMILY, 9),
                                padx=8, pady=2, cursor="hand2", relief=tk.FLAT, bd=0)
        settings_btn.pack(side=tk.RIGHT, padx=5)

        self.create_tool_btn_right(row1, "导出图片", self.export_as_images, "#F57C00")
        self.create_tool_btn_right(row1, "导出PDF", self.export_as_pdf, "#C62828")
        self.create_tool_btn_right(row1, "生成PPT", self.generate_multi_page_ppt, COLOR_RED)

        # === 第二行：涂抹、AI替换、背景生成 ===
        row2 = tk.Frame(toolbar, bg=COLOR_RIBBON_ROW2)
        row2.pack(fill=tk.X, padx=10, pady=(2, 2))

        # 涂抹工具组
        tk.Label(row2, text="涂抹:", bg=COLOR_RIBBON_ROW2, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        # 涂抹模式开关
        self.inpaint_mode_btn = self.create_tool_btn(row2, "进入涂抹", self.toggle_inpaint_mode, "#FF6F00", bg=COLOR_RIBBON_ROW2)

        # 工具选择（初始隐藏）
        self.inpaint_tools_frame = tk.Frame(row2, bg=COLOR_RIBBON_ROW2)
        self.inpaint_tools_frame.pack(side=tk.LEFT)

        self.brush_btn = tk.Button(self.inpaint_tools_frame, text="笔刷",
                                   command=lambda: self.switch_inpaint_tool("brush"),
                                   bg="#FFE0B2", relief=tk.SUNKEN, font=(FONT_FAMILY, 9),
                                   padx=8, pady=3, cursor="hand2")
        self.brush_btn.pack(side=tk.LEFT, padx=2)

        self.rect_btn = tk.Button(self.inpaint_tools_frame, text="框选",
                                  command=lambda: self.switch_inpaint_tool("rect"),
                                  bg=COLOR_RIBBON_ROW2, relief=tk.RAISED, font=(FONT_FAMILY, 9),
                                  padx=8, pady=3, cursor="hand2")
        self.rect_btn.pack(side=tk.LEFT, padx=2)

        # 笔刷大小（初始隐藏）
        self.brush_size_frame = tk.Frame(row2, bg=COLOR_RIBBON_ROW2)
        self.brush_size_frame.pack(side=tk.LEFT)

        tk.Label(self.brush_size_frame, text="大小:", bg=COLOR_RIBBON_ROW2,
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=3)
        self.brush_size_scale = tk.Scale(self.brush_size_frame, from_=5, to=100,
                                         orient=tk.HORIZONTAL, length=80,
                                         command=self.update_brush_size,
                                         bg=COLOR_RIBBON_ROW2, highlightthickness=0)
        self.brush_size_scale.set(30)
        self.brush_size_scale.pack(side=tk.LEFT)

        # 涂抹操作按钮（初始隐藏）
        self.inpaint_actions_frame = tk.Frame(row2, bg=COLOR_RIBBON_ROW2)
        self.inpaint_actions_frame.pack(side=tk.LEFT)

        tk.Button(self.inpaint_actions_frame, text="清空",
                 command=self.clear_inpaint_mask,
                 bg="#FFCDD2", font=(FONT_FAMILY, 9), padx=8, pady=3,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Button(self.inpaint_actions_frame, text="生成图层",
                 command=self.generate_bg_from_custom_mask,
                 bg="#A5D6A7", font=(FONT_FAMILY, 9, "bold"), padx=12, pady=3,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 初始隐藏工具栏
        self.inpaint_tools_frame.pack_forget()
        self.brush_size_frame.pack_forget()
        self.inpaint_actions_frame.pack_forget()

        self.create_separator(row2, bg=COLOR_RIBBON_ROW2)

        # AI替换工具组
        tk.Label(row2, text="AI替换:", bg=COLOR_RIBBON_ROW2, fg="#666",
                 font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        # AI替换模式开关
        self.ai_replace_mode_btn = self.create_tool_btn(
            row2,
            "AI替换",
            self.toggle_ai_replace_mode,
            "#E91E63",
            bg=COLOR_RIBBON_ROW2,
        )

        # AI 文字生图（不需要框选，生成后作为图层）
        self.create_tool_btn(row2, "文字生图", self.ai_text_to_image_layer, "#7B1FA2", bg=COLOR_RIBBON_ROW2)

        # AI整页生成背景（把当前页整图发给AI生成，返回设为背景）
        self.create_tool_btn(row2, "整页生成", self.ai_generate_fullpage_background, "#6A1B9A", bg=COLOR_RIBBON_ROW2)

        # AI API配置按钮
        self.create_tool_btn(row2, "API设置", self.open_ai_api_settings, "#9C27B0", bg=COLOR_RIBBON_ROW2)

        self.create_separator(row2, bg=COLOR_RIBBON_ROW2)

        # IOPaint 去字（结果作为图层叠加，不替换原图/背景）
        tk.Label(row2, text="去字(层):", bg=COLOR_RIBBON_ROW2, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
        self.create_tool_btn(row2, "当前页", self.auto_generate_background_current, "#E91E63", bg=COLOR_RIBBON_ROW2)
        self.create_tool_btn(row2, "全部页", self.auto_generate_background_all, "#C2185B", bg=COLOR_RIBBON_ROW2)

        self.create_separator(row2, bg=COLOR_RIBBON_ROW2)

        # 预览模式
        tk.Label(row2, text="预览:", bg=COLOR_RIBBON_ROW2, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        self.preview_mode_var = tk.StringVar(value="raw")
        self.preview_orig_btn = tk.Button(row2, text="原图", command=lambda: self.set_preview_mode("raw"),
                                          bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 9),
                                          padx=8, cursor="hand2", relief=tk.FLAT, bd=0)
        self.preview_orig_btn.pack(side=tk.LEFT, padx=2)

        self.preview_edit_btn = tk.Button(row2, text="叠加", command=lambda: self.set_preview_mode("edit"),
                                          bg="#757575", fg="white", font=(FONT_FAMILY, 9),
                                          padx=8, cursor="hand2", relief=tk.FLAT, bd=0)
        self.preview_edit_btn.pack(side=tk.LEFT, padx=2)

        self.preview_ppt_btn = tk.Button(row2, text="PPT效果", command=lambda: self.set_preview_mode("ppt"),
                                         bg="#757575", fg="white", font=(FONT_FAMILY, 9),
                                         padx=8, cursor="hand2", relief=tk.FLAT, bd=0)
        self.preview_ppt_btn.pack(side=tk.LEFT, padx=2)

        # === 第三行：编辑工具和视图 ===
        row3 = tk.Frame(toolbar, bg=COLOR_RIBBON_BG)
        row3.pack(fill=tk.X, padx=10, pady=(2, 6))

        # 编辑工具
        tk.Label(row3, text="编辑:", bg=COLOR_RIBBON_BG, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        self.draw_mode_var = tk.BooleanVar(value=True)
        self.draw_btn = tk.Button(row3, text="画框模式", command=self.toggle_draw_mode_btn,
                                  bg=COLOR_GREEN, fg="white", font=(FONT_FAMILY, 9),
                                  padx=8, cursor="hand2", relief=tk.FLAT, bd=0)
        self.draw_btn.pack(side=tk.LEFT, padx=2)


        self.create_tool_btn(row3, "复制", self.copy_boxes, "#009688")
        self.create_tool_btn(row3, "粘贴", self.paste_boxes, "#00ACC1")
        self.create_tool_btn(row3, "删除框", self.delete_selected_box, COLOR_RED)
        self.create_tool_btn(row3, "清空全部", self.clear_all_boxes, "#795548")
        self.create_tool_btn(row3, "撤销", self.undo, "#78909C")
        self.create_tool_btn(row3, "重做", self.redo, "#78909C")

        self.create_separator(row3)

        # 缩放控制
        tk.Label(row3, text="视图:", bg=COLOR_RIBBON_BG, fg="#666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
        self.create_tool_btn(row3, "适应窗口", self.fit_image_to_canvas, "#455A64")
        self.create_tool_btn(row3, "100%", self.zoom_to_100, "#455A64")

        self.zoom_label = tk.Label(row3, text="100%", bg=COLOR_RIBBON_BG, fg="#333",
                                   font=(FONT_FAMILY, 9), padx=10)
        self.zoom_label.pack(side=tk.LEFT)

        # 快捷键提示
        tk.Label(row3, text="Ctrl+滚轮缩放 | 双击编辑 | Ctrl+点击多选",
                bg=COLOR_RIBBON_BG, fg="#999", font=(FONT_FAMILY, 8)).pack(side=tk.LEFT, padx=10)

    def create_tool_btn(self, parent, text, command, color, bg=None):
        """创建工具栏按钮"""
        if bg is None:
            bg = COLOR_RIBBON_BG
        btn = tk.Button(parent, text=text, command=command,
                       bg=color, fg="white", font=(FONT_FAMILY, 9),
                       padx=8, cursor="hand2", relief=tk.FLAT, bd=0)
        btn.pack(side=tk.LEFT, padx=2)
        return btn

    def create_tool_btn_right(self, parent, text, command, color, bg=None):
        """创建靠右对齐的工具栏按钮"""
        if bg is None:
            bg = COLOR_RIBBON_BG
        btn = tk.Button(parent, text=text, command=command,
                       bg=color, fg="white", font=(FONT_FAMILY, 9),
                       padx=8, cursor="hand2", relief=tk.FLAT, bd=0)
        btn.pack(side=tk.RIGHT, padx=2)
        return btn

    def create_separator(self, parent, bg=None):
        """创建分隔线"""
        if bg is None:
            bg = COLOR_RIBBON_BG
        sep_frame = tk.Frame(parent, bg=bg)
        sep_frame.pack(side=tk.LEFT, padx=6)
        sep_line = tk.Frame(sep_frame, bg="#ccc", width=1, height=20)
        sep_line.pack()

    def create_icon_button(self, parent, text, command, color, icon=""):
        """创建图标按钮"""
        btn_text = f"{icon}\n{text}" if icon else text
        btn = tk.Button(parent, text=btn_text, command=command,
                       bg=color, fg="white", font=("微软雅黑", 8),
                       width=5, height=2, cursor="hand2", relief=tk.GROOVE, bd=2)
        btn.pack(side=tk.LEFT, padx=2, pady=2)

        # 悬停效果
        def on_enter(e):
            btn.config(relief=tk.RAISED)
        def on_leave(e):
            btn.config(relief=tk.GROOVE)
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    def toggle_draw_mode_btn(self):
        """切换绘制模式"""
        self.draw_mode = not self.draw_mode
        self.draw_mode_var.set(self.draw_mode)
        if self.draw_mode:
            self.draw_btn.config(bg=COLOR_GREEN, text="画框模式")
            self.canvas.config(cursor="crosshair")
        else:
            self.draw_btn.config(bg="#9E9E9E", text="选择模式")
            self.canvas.config(cursor="")

    def set_preview_mode(self, mode):
        """设置预览模式"""
        self.preview_mode_var.set(mode)
        self.current_preview_mode = mode
        # 颜色状态
        self.preview_orig_btn.config(bg=COLOR_BLUE if mode == "raw" else "#757575", fg="white")
        if hasattr(self, "preview_edit_btn"):
            self.preview_edit_btn.config(bg=COLOR_BLUE if mode == "edit" else "#757575", fg="white")
        self.preview_ppt_btn.config(bg=COLOR_BLUE if mode == "ppt" else "#757575", fg="white")
        self.refresh_canvas()

    def create_thumbnail_panel(self):
        """创建左侧缩略图面板"""
        self.thumbnail_panel = tk.Frame(self.main_container, bg=COLOR_SIDEBAR_BG, width=180)
        self.thumbnail_panel.pack(side=tk.LEFT, fill=tk.Y)
        self.thumbnail_panel.pack_propagate(False)

        # 标题栏
        title_frame = tk.Frame(self.thumbnail_panel, bg=COLOR_BLUE, height=30)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="  页面列表", bg=COLOR_BLUE, fg="white",
                font=(FONT_FAMILY, 10, "bold"), anchor="w").pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 缩略图容器（可滚动）
        container = tk.Frame(self.thumbnail_panel, bg=COLOR_SIDEBAR_BG)
        container.pack(fill=tk.BOTH, expand=True)

        self.thumbnail_canvas = tk.Canvas(container, bg=COLOR_SIDEBAR_BG, highlightthickness=0, width=160)
        scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL, command=self.thumbnail_canvas.yview)

        self.thumbnail_frame = tk.Frame(self.thumbnail_canvas, bg=COLOR_SIDEBAR_BG)

        self.thumbnail_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.thumbnail_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.thumbnail_window = self.thumbnail_canvas.create_window((0, 0), window=self.thumbnail_frame, anchor=tk.NW)

        self.thumbnail_frame.bind("<Configure>",
            lambda e: self.thumbnail_canvas.configure(scrollregion=self.thumbnail_canvas.bbox("all")))

        # 鼠标滚轮
        self.thumbnail_canvas.bind("<MouseWheel>",
            lambda e: self.thumbnail_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # 页面导航按钮
        nav_frame = tk.Frame(self.thumbnail_panel, bg="#f5f5f5", height=40)
        nav_frame.pack(fill=tk.X, side=tk.BOTTOM)
        nav_frame.pack_propagate(False)

        tk.Button(nav_frame, text="上一页", command=self.prev_page,
                 bg="#e0e0e0", font=(FONT_FAMILY, 9), width=6, cursor="hand2",
                 relief=tk.FLAT).pack(side=tk.LEFT, padx=5, pady=5)

        self.page_label = tk.Label(nav_frame, text="0/0", bg="#f5f5f5",
                                   font=(FONT_FAMILY, 10, "bold"))
        self.page_label.pack(side=tk.LEFT, expand=True)

        tk.Button(nav_frame, text="下一页", command=self.next_page,
                 bg="#e0e0e0", font=(FONT_FAMILY, 9), width=6, cursor="hand2",
                 relief=tk.FLAT).pack(side=tk.RIGHT, padx=5, pady=5)

    def create_canvas_area(self):
        """创建中间画布区域"""
        canvas_container = tk.Frame(self.main_container, bg=COLOR_CANVAS_BG)
        canvas_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 画布
        self.canvas = tk.Canvas(canvas_container, bg="#c0c0c0", highlightthickness=0)

        # 滚动条
        v_scroll = tk.Scrollbar(canvas_container, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scroll = tk.Scrollbar(canvas_container, orient=tk.HORIZONTAL, command=self.canvas.xview)

        self.canvas.config(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 绑定画布事件
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<Control-ButtonPress-1>", self.on_canvas_ctrl_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)  # 右键菜单

        # Ctrl+滚轮缩放
        self.canvas.bind("<Control-MouseWheel>", self.on_canvas_zoom)
        # 普通滚轮滚动
        self.canvas.bind("<MouseWheel>", self.on_canvas_scroll)

        # 占位提示
        self.placeholder_label = tk.Label(self.canvas,
            text="点击上方「导入图片」按钮开始\n\n支持批量导入多张图片",
            bg="#c0c0c0", fg="#666666", font=(FONT_FAMILY, 14), justify=tk.CENTER)
        self.canvas.create_window(400, 300, window=self.placeholder_label)

    def create_property_panel(self):
        """创建右侧属性面板"""
        self.right_panel = tk.Frame(self.main_container, bg=COLOR_WHITE, width=280)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        self.right_panel.pack_propagate(False)

        # 标题
        title_frame = tk.Frame(self.right_panel, bg=COLOR_BLUE, height=30)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="  属性设置", bg=COLOR_BLUE, fg="white",
                font=(FONT_FAMILY, 10, "bold"), anchor="w").pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 分页：属性 / 图层（更接近 PS 的面板体验）
        self.right_notebook = ttk.Notebook(self.right_panel)
        self.right_notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        props_tab = tk.Frame(self.right_notebook, bg=COLOR_WHITE)
        layers_tab = tk.Frame(self.right_notebook, bg=COLOR_WHITE)
        self.right_notebook.add(props_tab, text="属性")
        self.right_notebook.add(layers_tab, text="图层")
        self.layers_tab = layers_tab

        # 可滚动容器（属性页）
        canvas = tk.Canvas(props_tab, bg=COLOR_WHITE, highlightthickness=0)
        self.prop_canvas = canvas
        scrollbar = tk.Scrollbar(props_tab, orient=tk.VERTICAL, command=canvas.yview)

        self.prop_frame = tk.Frame(canvas, bg=COLOR_WHITE)

        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        canvas_window = canvas.create_window((0, 0), window=self.prop_frame, anchor=tk.NW)

        self.prop_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # === 文本框列表 ===
        self.create_section_header(self.prop_frame, "文本框列表")

        list_frame = tk.Frame(self.prop_frame, bg=COLOR_WHITE)
        list_frame.pack(fill=tk.X, padx=10, pady=5)

        self.box_listbox = tk.Listbox(list_frame, height=5, bg="#f5f5f5",
                                       font=(FONT_FAMILY, 9), selectbackground=COLOR_BLUE,
                                       selectforeground="white", relief=tk.FLAT, bd=1)
        self.box_listbox.pack(fill=tk.X)
        self.box_listbox.bind("<<ListboxSelect>>", self.on_listbox_select)

        # === 文本内容 ===
        self.create_section_header(self.prop_frame, "文本内容")

        text_frame = tk.Frame(self.prop_frame, bg=COLOR_WHITE)
        text_frame.pack(fill=tk.X, padx=10, pady=5)

        self.text_entry = tk.Text(text_frame, height=3, bg="#f5f5f5",
                                  font=(FONT_FAMILY, 10), relief=tk.FLAT, bd=1, wrap=tk.WORD)
        self.text_entry.pack(fill=tk.X)
        self.text_entry.bind("<KeyRelease>", self.on_text_change)

        # OCR识别按钮
        ocr_btn_frame = tk.Frame(text_frame, bg=COLOR_WHITE)
        ocr_btn_frame.pack(fill=tk.X, pady=5)

        tk.Button(ocr_btn_frame, text="🔍 OCR识别此框", command=self.ocr_single_box,
                 bg=COLOR_PURPLE, fg="white", font=(FONT_FAMILY, 9, "bold"),
                 cursor="hand2", relief=tk.FLAT).pack(fill=tk.X)

        # === 位置和大小 ===
        self.create_section_header(self.prop_frame, "位置和大小")

        pos_frame = tk.Frame(self.prop_frame, bg=COLOR_WHITE)
        pos_frame.pack(fill=tk.X, padx=10, pady=5)

        # X, Y
        row1 = tk.Frame(pos_frame, bg=COLOR_WHITE)
        row1.pack(fill=tk.X, pady=2)

        tk.Label(row1, text="X:", bg=COLOR_WHITE, font=(FONT_FAMILY, 9), width=3).pack(side=tk.LEFT)
        self.x_entry = tk.Entry(row1, width=6, font=(FONT_FAMILY, 9), relief=tk.FLAT, bg="#f5f5f5")
        self.x_entry.pack(side=tk.LEFT, padx=2)
        self.x_entry.bind("<KeyRelease>", self.on_position_change)

        tk.Label(row1, text="Y:", bg=COLOR_WHITE, font=(FONT_FAMILY, 9), width=3).pack(side=tk.LEFT, padx=(10, 0))
        self.y_entry = tk.Entry(row1, width=6, font=(FONT_FAMILY, 9), relief=tk.FLAT, bg="#f5f5f5")
        self.y_entry.pack(side=tk.LEFT, padx=2)
        self.y_entry.bind("<KeyRelease>", self.on_position_change)

        # 宽, 高
        row2 = tk.Frame(pos_frame, bg=COLOR_WHITE)
        row2.pack(fill=tk.X, pady=2)

        tk.Label(row2, text="宽:", bg=COLOR_WHITE, font=(FONT_FAMILY, 9), width=3).pack(side=tk.LEFT)
        self.w_entry = tk.Entry(row2, width=6, font=(FONT_FAMILY, 9), relief=tk.FLAT, bg="#f5f5f5")
        self.w_entry.pack(side=tk.LEFT, padx=2)
        self.w_entry.bind("<KeyRelease>", self.on_position_change)

        tk.Label(row2, text="高:", bg=COLOR_WHITE, font=(FONT_FAMILY, 9), width=3).pack(side=tk.LEFT, padx=(10, 0))
        self.h_entry = tk.Entry(row2, width=6, font=(FONT_FAMILY, 9), relief=tk.FLAT, bg="#f5f5f5")
        self.h_entry.pack(side=tk.LEFT, padx=2)
        self.h_entry.bind("<KeyRelease>", self.on_position_change)

        # === 字体样式 ===
        self.create_section_header(self.prop_frame, "字体样式")

        font_frame = tk.Frame(self.prop_frame, bg=COLOR_WHITE)
        font_frame.pack(fill=tk.X, padx=10, pady=5)

        # 字体和字号
        row3 = tk.Frame(font_frame, bg=COLOR_WHITE)
        row3.pack(fill=tk.X, pady=2)

        self.fontname_var = tk.StringVar(value="微软雅黑")
        font_combo = ttk.Combobox(row3, textvariable=self.fontname_var, width=10,
                                  values=["微软雅黑", "宋体", "黑体", "楷体", "仿宋", "Arial"])
        font_combo.pack(side=tk.LEFT, padx=2)
        font_combo.bind("<<ComboboxSelected>>", self.on_font_change)

        self.fontsize_var = tk.StringVar(value="16")
        size_combo = ttk.Combobox(row3, textvariable=self.fontsize_var, width=5,
                                  values=["8", "10", "12", "14", "16", "18", "20", "24", "28", "32", "36", "48", "60", "72", "80", "100", "120", "150", "200"])
        size_combo.pack(side=tk.LEFT, padx=2)
        size_combo.bind("<<ComboboxSelected>>", self.on_font_change)

        # 样式按钮
        row4 = tk.Frame(font_frame, bg=COLOR_WHITE)
        row4.pack(fill=tk.X, pady=5)

        self.bold_var = tk.BooleanVar(value=False)
        self.bold_btn = tk.Button(row4, text="B 加粗", command=self.toggle_bold,
                                  bg="#e0e0e0", font=(FONT_FAMILY, 9),
                                  width=6, cursor="hand2", relief=tk.FLAT)
        self.bold_btn.pack(side=tk.LEFT, padx=2)

        self.italic_var = tk.BooleanVar(value=False)
        self.italic_btn = tk.Button(row4, text="I 斜体", command=self.toggle_italic,
                                    bg="#e0e0e0", font=(FONT_FAMILY, 9),
                                    width=6, cursor="hand2", relief=tk.FLAT)
        self.italic_btn.pack(side=tk.LEFT, padx=2)

        self.color_btn = tk.Button(row4, text="颜色", command=self.choose_color,
                                   bg="#000000", fg="white", width=5, cursor="hand2", relief=tk.FLAT)
        self.color_btn.pack(side=tk.LEFT, padx=2)

        # 自动字号按钮
        tk.Button(row4, text="自动字号", command=self.auto_font_size,
                 bg=COLOR_PURPLE, fg="white", font=(FONT_FAMILY, 8),
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=5)

        # 对齐按钮
        row5 = tk.Frame(font_frame, bg=COLOR_WHITE)
        row5.pack(fill=tk.X, pady=5)

        tk.Label(row5, text="对齐:", bg=COLOR_WHITE, font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        self.align_var = tk.StringVar(value="left")

        align_btn_frame = tk.Frame(row5, bg=COLOR_WHITE)
        align_btn_frame.pack(side=tk.LEFT, padx=5)

        self.align_left_btn = tk.Button(align_btn_frame, text="左", command=lambda: self.set_align("left"),
                                        bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 9), width=3,
                                        cursor="hand2", relief=tk.FLAT)
        self.align_left_btn.pack(side=tk.LEFT, padx=1)

        self.align_center_btn = tk.Button(align_btn_frame, text="中", command=lambda: self.set_align("center"),
                                          bg="#e0e0e0", fg="#333", font=(FONT_FAMILY, 9), width=3,
                                          cursor="hand2", relief=tk.FLAT)
        self.align_center_btn.pack(side=tk.LEFT, padx=1)

        self.align_right_btn = tk.Button(align_btn_frame, text="右", command=lambda: self.set_align("right"),
                                         bg="#e0e0e0", fg="#333", font=(FONT_FAMILY, 9), width=3,
                                         cursor="hand2", relief=tk.FLAT)
        self.align_right_btn.pack(side=tk.LEFT, padx=1)

        # === 批量应用 ===
        self.create_section_header(self.prop_frame, "批量应用")

        batch_frame = tk.Frame(self.prop_frame, bg=COLOR_WHITE)
        batch_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(batch_frame, text="Ctrl+点击多选，勾选要应用的属性：",
                bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8), wraplength=220).pack(anchor="w")

        # 勾选项
        check_row1 = tk.Frame(batch_frame, bg=COLOR_WHITE)
        check_row1.pack(fill=tk.X, pady=2)

        self.apply_fontsize_var = tk.BooleanVar(value=False)
        tk.Checkbutton(check_row1, text="字号", variable=self.apply_fontsize_var,
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        self.apply_fontname_var = tk.BooleanVar(value=False)
        tk.Checkbutton(check_row1, text="字体", variable=self.apply_fontname_var,
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        self.apply_color_var = tk.BooleanVar(value=False)
        tk.Checkbutton(check_row1, text="颜色", variable=self.apply_color_var,
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        check_row2 = tk.Frame(batch_frame, bg=COLOR_WHITE)
        check_row2.pack(fill=tk.X, pady=2)

        self.apply_bold_var = tk.BooleanVar(value=False)
        tk.Checkbutton(check_row2, text="加粗", variable=self.apply_bold_var,
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        self.apply_italic_var = tk.BooleanVar(value=False)
        tk.Checkbutton(check_row2, text="斜体", variable=self.apply_italic_var,
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        self.apply_align_var = tk.BooleanVar(value=False)
        tk.Checkbutton(check_row2, text="对齐", variable=self.apply_align_var,
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        tk.Button(batch_frame, text="应用到选中框", command=self.apply_style_to_selected,
                 bg=COLOR_ORANGE, fg="white", font=(FONT_FAMILY, 9),
                 cursor="hand2", relief=tk.FLAT).pack(fill=tk.X, pady=5)

        # === 对齐工具 ===
        self.create_section_header(self.prop_frame, "多框对齐")

        align_frame = tk.Frame(self.prop_frame, bg=COLOR_WHITE)
        align_frame.pack(fill=tk.X, padx=10, pady=5)

        # 全选按钮
        select_all_frame = tk.Frame(align_frame, bg=COLOR_WHITE)
        select_all_frame.pack(fill=tk.X, pady=(0, 5))

        tk.Button(select_all_frame, text="全选当前页所有框 (Ctrl+A)", command=self.select_all_boxes,
                 bg="#FF9800", fg="white", font=(FONT_FAMILY, 9, "bold"),
                 cursor="hand2", relief=tk.FLAT).pack(fill=tk.X)

        tk.Label(align_frame, text="Ctrl+点击选中多个框：",
                bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8)).pack(anchor="w", pady=(5, 0))

        # 水平对齐
        h_align_frame = tk.Frame(align_frame, bg=COLOR_WHITE)
        h_align_frame.pack(fill=tk.X, pady=3)

        tk.Label(h_align_frame, text="水平:", bg=COLOR_WHITE, font=(FONT_FAMILY, 8), fg="#666").pack(side=tk.LEFT)

        tk.Button(h_align_frame, text="左", command=lambda: self.align_boxes("left"),
                 bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 8), width=4,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(h_align_frame, text="中", command=lambda: self.align_boxes("center_h"),
                 bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 8), width=4,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(h_align_frame, text="右", command=lambda: self.align_boxes("right"),
                 bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 8), width=4,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 垂直对齐
        v_align_frame = tk.Frame(align_frame, bg=COLOR_WHITE)
        v_align_frame.pack(fill=tk.X, pady=3)

        tk.Label(v_align_frame, text="垂直:", bg=COLOR_WHITE, font=(FONT_FAMILY, 8), fg="#666").pack(side=tk.LEFT)

        tk.Button(v_align_frame, text="上", command=lambda: self.align_boxes("top"),
                 bg=COLOR_GREEN, fg="white", font=(FONT_FAMILY, 8), width=4,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(v_align_frame, text="中", command=lambda: self.align_boxes("center_v"),
                 bg=COLOR_GREEN, fg="white", font=(FONT_FAMILY, 8), width=4,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(v_align_frame, text="下", command=lambda: self.align_boxes("bottom"),
                 bg=COLOR_GREEN, fg="white", font=(FONT_FAMILY, 8), width=4,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 分隔线
        tk.Frame(align_frame, bg="#e0e0e0", height=1).pack(fill=tk.X, pady=8)

        # 均匀分布
        tk.Label(align_frame, text="均匀分布（需要3个或以上）：",
                bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8)).pack(anchor="w")

        dist_frame = tk.Frame(align_frame, bg=COLOR_WHITE)
        dist_frame.pack(fill=tk.X, pady=3)

        tk.Button(dist_frame, text="水平等间距", command=lambda: self.distribute_boxes("horizontal"),
                 bg=COLOR_PURPLE, fg="white", font=(FONT_FAMILY, 8), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(dist_frame, text="垂直等间距", command=lambda: self.distribute_boxes("vertical"),
                 bg=COLOR_PURPLE, fg="white", font=(FONT_FAMILY, 8), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 分隔线
        tk.Frame(align_frame, bg="#e0e0e0", height=1).pack(fill=tk.X, pady=8)

        # 尺寸统一
        tk.Label(align_frame, text="尺寸统一（以第一个选中框为基准）：",
                bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8)).pack(anchor="w")

        size_frame = tk.Frame(align_frame, bg=COLOR_WHITE)
        size_frame.pack(fill=tk.X, pady=3)

        tk.Button(size_frame, text="统一宽", command=lambda: self.unify_size("width"),
                 bg="#00897B", fg="white", font=(FONT_FAMILY, 8), width=7,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(size_frame, text="统一高", command=lambda: self.unify_size("height"),
                 bg="#00897B", fg="white", font=(FONT_FAMILY, 8), width=7,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(size_frame, text="统一大小", command=lambda: self.unify_size("both"),
                 bg="#00897B", fg="white", font=(FONT_FAMILY, 8), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 分隔线
        tk.Frame(align_frame, bg="#e0e0e0", height=1).pack(fill=tk.X, pady=8)

        # 对齐到画布
        tk.Label(align_frame, text="对齐到画布中心：",
                bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8)).pack(anchor="w")

        canvas_align_frame = tk.Frame(align_frame, bg=COLOR_WHITE)
        canvas_align_frame.pack(fill=tk.X, pady=3)

        tk.Button(canvas_align_frame, text="水平居中", command=lambda: self.align_to_canvas("h"),
                 bg="#D32F2F", fg="white", font=(FONT_FAMILY, 8), width=9,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(canvas_align_frame, text="垂直居中", command=lambda: self.align_to_canvas("v"),
                 bg="#D32F2F", fg="white", font=(FONT_FAMILY, 8), width=9,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(canvas_align_frame, text="完全居中", command=lambda: self.align_to_canvas("center"),
                 bg="#D32F2F", fg="white", font=(FONT_FAMILY, 8), width=9,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 批量位移
        tk.Frame(align_frame, bg="#e0e0e0", height=1).pack(fill=tk.X, pady=8)

        tk.Label(align_frame, text="批量位移（像素）：",
                bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8)).pack(anchor="w")

        # 位移输入框
        offset_input_frame = tk.Frame(align_frame, bg=COLOR_WHITE)
        offset_input_frame.pack(fill=tk.X, pady=3)

        tk.Label(offset_input_frame, text="移动:", bg=COLOR_WHITE, font=(FONT_FAMILY, 8), fg="#666").pack(side=tk.LEFT)

        self.offset_px_var = tk.StringVar(value="10")
        offset_entry = tk.Entry(offset_input_frame, textvariable=self.offset_px_var,
                               width=5, font=(FONT_FAMILY, 9), relief=tk.FLAT, bg="#f5f5f5")
        offset_entry.pack(side=tk.LEFT, padx=3)

        tk.Label(offset_input_frame, text="px", bg=COLOR_WHITE, font=(FONT_FAMILY, 8), fg="#666").pack(side=tk.LEFT)

        # 方向按钮
        offset_btn_frame = tk.Frame(align_frame, bg=COLOR_WHITE)
        offset_btn_frame.pack(fill=tk.X, pady=3)

        # 上按钮
        tk.Button(offset_btn_frame, text="↑", command=lambda: self.batch_offset(0, -1),
                 bg=COLOR_ORANGE, fg="white", font=(FONT_FAMILY, 10, "bold"), width=3,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=1)

        # 下按钮
        tk.Button(offset_btn_frame, text="↓", command=lambda: self.batch_offset(0, 1),
                 bg=COLOR_ORANGE, fg="white", font=(FONT_FAMILY, 10, "bold"), width=3,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=1)

        # 左按钮
        tk.Button(offset_btn_frame, text="←", command=lambda: self.batch_offset(-1, 0),
                 bg=COLOR_ORANGE, fg="white", font=(FONT_FAMILY, 10, "bold"), width=3,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=1)

        # 右按钮
        tk.Button(offset_btn_frame, text="→", command=lambda: self.batch_offset(1, 0),
                 bg=COLOR_ORANGE, fg="white", font=(FONT_FAMILY, 10, "bold"), width=3,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=1)

        # === 当前页背景 ===
        self.create_section_header(self.prop_frame, "当前页背景")

        bg_frame = tk.Frame(self.prop_frame, bg=COLOR_WHITE)
        bg_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(bg_frame, text="背景图会自动调整为与原图相同大小",
                bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8), wraplength=220).pack(anchor="w")

        bg_btn_frame = tk.Frame(bg_frame, bg=COLOR_WHITE)
        bg_btn_frame.pack(fill=tk.X, pady=5)

        tk.Button(bg_btn_frame, text="设置背景", command=self.load_current_page_background,
                 bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 9),
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Button(bg_btn_frame, text="清除背景", command=self.clear_current_page_background,
                 bg=COLOR_RED, fg="white", font=(FONT_FAMILY, 9),
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 背景状态显示
        self.bg_status_label = tk.Label(bg_frame, text="未设置背景",
                                        bg=COLOR_WHITE, fg="#999", font=(FONT_FAMILY, 8))
        self.bg_status_label.pack(anchor="w", pady=2)

        # 图层面板已移动到右侧“图层”Tab（更易找到，也更像 PS）。

        # 图层页
        self.create_layers_panel(layers_tab)
        self.update_layer_listbox()

    def create_layers_panel(self, parent):
        """创建图层面板（独立 Tab）"""
        # === 图层 ===
        header = tk.Frame(parent, bg=COLOR_WHITE)
        header.pack(fill=tk.X, padx=10, pady=(10, 6))
        tk.Label(header, text="图层", bg=COLOR_WHITE, fg=COLOR_TEXT, font=(FONT_FAMILY, 10, "bold")).pack(
            side=tk.LEFT
        )
        tk.Button(
            header,
            text="刷新",
            command=lambda: (self.update_layer_listbox(), self.refresh_canvas()),
            bg="#455A64",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        ).pack(side=tk.RIGHT)

        layer_frame = tk.Frame(parent, bg=COLOR_WHITE)
        layer_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        tree_frame = tk.Frame(layer_frame, bg=COLOR_WHITE)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("vis", "opacity", "lock")
        self.layer_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="tree headings",
            height=12,
            selectmode="browse",
        )
        self.layer_tree.heading("#0", text="图层")
        self.layer_tree.heading("vis", text="显")
        self.layer_tree.heading("opacity", text="透明")
        self.layer_tree.heading("lock", text="锁")

        self.layer_tree.column("#0", width=160, anchor=tk.W)
        self.layer_tree.column("vis", width=38, anchor=tk.CENTER)
        self.layer_tree.column("opacity", width=60, anchor=tk.CENTER)
        self.layer_tree.column("lock", width=45, anchor=tk.CENTER)

        self.layer_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.layer_tree.bind("<<TreeviewSelect>>", self.on_layer_select)
        self.layer_tree.bind("<Double-1>", lambda e: self.rename_selected_layer())
        # 图层面板交互：点击“显”列快速显示/隐藏，拖拽行调整图层顺序
        self.layer_tree.bind("<Button-1>", self.on_layer_tree_click, add=True)
        self.layer_tree.bind("<ButtonPress-1>", self.on_layer_drag_start, add=True)
        self.layer_tree.bind("<B1-Motion>", self.on_layer_drag_motion, add=True)
        self.layer_tree.bind("<ButtonRelease-1>", self.on_layer_drag_release, add=True)

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.layer_tree.yview)
        self.layer_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        layer_btn_frame = tk.Frame(layer_frame, bg=COLOR_WHITE)
        layer_btn_frame.pack(fill=tk.X, pady=(8, 6))

        # 先放右侧按钮，避免被左侧按钮挤出可视区域
        tk.Button(
            layer_btn_frame,
            text="删除",
            command=self.delete_selected_layer,
            bg=COLOR_RED,
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        ).pack(side=tk.RIGHT, padx=2)

        tk.Button(
            layer_btn_frame,
            text="导入图层",
            command=self.import_layer_from_file,
            bg=COLOR_BLUE,
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        ).pack(side=tk.RIGHT, padx=2)

        tk.Button(
            layer_btn_frame,
            text="显隐",
            command=self.toggle_selected_layer,
            bg="#607D8B",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            layer_btn_frame,
            text="预览",
            command=self.preview_selected_layer,
            bg="#455A64",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            layer_btn_frame,
            text="改名",
            command=self.rename_selected_layer,
            bg="#455A64",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            layer_btn_frame,
            text="锁定",
            command=self.toggle_selected_layer_lock,
            bg="#6D4C41",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=2)

        # 图层顺序调整（独立行，避免被挤出）
        layer_order_frame = tk.Frame(layer_frame, bg=COLOR_WHITE)
        layer_order_frame.pack(fill=tk.X, pady=(4, 6))

        tk.Label(layer_order_frame, text="图层顺序:", bg=COLOR_WHITE, fg="#666666",
                font=(FONT_FAMILY, 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(
            layer_order_frame,
            text="↑ 上移",
            command=self.move_layer_up,
            bg="#607D8B",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
            width=8
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            layer_order_frame,
            text="↓ 下移",
            command=self.move_layer_down,
            bg="#607D8B",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
            width=8
        ).pack(side=tk.LEFT, padx=2)

        tk.Label(layer_order_frame, text="(调整图层叠放顺序)", bg=COLOR_WHITE, fg="#999",
                font=(FONT_FAMILY, 8)).pack(side=tk.LEFT, padx=5)

        # 图层变换（位置/缩放/裁剪/锁定）
        transform_frame = tk.Frame(layer_frame, bg=COLOR_WHITE)
        transform_frame.pack(fill=tk.X, pady=(2, 6))

        self.layer_x_var = tk.IntVar(value=0)
        self.layer_y_var = tk.IntVar(value=0)
        self.layer_scale_var = tk.IntVar(value=100)  # %
        self.layer_lock_var = tk.BooleanVar(value=False)

        xy_row = tk.Frame(transform_frame, bg=COLOR_WHITE)
        xy_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(xy_row, text="X:", bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
        self.layer_x_entry = tk.Entry(xy_row, textvariable=self.layer_x_var, width=6, font=(FONT_FAMILY, 9), relief=tk.FLAT, bg="#f5f5f5")
        self.layer_x_entry.pack(side=tk.LEFT, padx=(2, 8))
        tk.Label(xy_row, text="Y:", bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)
        self.layer_y_entry = tk.Entry(xy_row, textvariable=self.layer_y_var, width=6, font=(FONT_FAMILY, 9), relief=tk.FLAT, bg="#f5f5f5")
        self.layer_y_entry.pack(side=tk.LEFT, padx=(2, 8))
        self.layer_lock_check = tk.Checkbutton(xy_row, text="锁定", variable=self.layer_lock_var, bg=COLOR_WHITE, font=(FONT_FAMILY, 9), command=self._on_layer_lock_toggle)
        self.layer_lock_check.pack(side=tk.LEFT)

        self.layer_x_entry.bind("<Return>", lambda e: self._apply_layer_transform_from_ui())
        self.layer_y_entry.bind("<Return>", lambda e: self._apply_layer_transform_from_ui())

        tk.Label(transform_frame, text="缩放(%):", bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8)).pack(anchor="w")
        self.layer_scale_slider = tk.Scale(
            transform_frame,
            from_=10,
            to=300,
            orient=tk.HORIZONTAL,
            length=240,
            variable=self.layer_scale_var,
            bg=COLOR_WHITE,
            highlightthickness=0,
            command=lambda v: self._on_layer_scale_change(v),
        )
        self.layer_scale_slider.pack(fill=tk.X)
        self.layer_scale_slider.bind("<ButtonPress-1>", self._begin_layer_scale_drag, add=True)
        self.layer_scale_slider.bind("<ButtonRelease-1>", self._end_layer_scale_drag, add=True)

        crop_row = tk.Frame(transform_frame, bg=COLOR_WHITE)
        crop_row.pack(fill=tk.X, pady=(4, 0))
        self.layer_crop_btn = tk.Button(crop_row, text="裁剪", command=self.crop_selected_layer, bg=COLOR_ORANGE, fg="white",
                                        font=(FONT_FAMILY, 9), cursor="hand2", relief=tk.FLAT)
        self.layer_crop_btn.pack(side=tk.LEFT, padx=2)
        self.layer_reset_crop_btn = tk.Button(crop_row, text="重置裁剪", command=self.reset_selected_layer_crop, bg="#607D8B", fg="white",
                                              font=(FONT_FAMILY, 9), cursor="hand2", relief=tk.FLAT)
        self.layer_reset_crop_btn.pack(side=tk.LEFT, padx=2)
        self.layer_cutout_btn = tk.Button(
            crop_row,
            text="纯色抠图",
            command=self.solid_color_cutout_selected_layer,
            bg="#00897B",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        )
        self.layer_cutout_btn.pack(side=tk.LEFT, padx=2)

        # OCR检测识别按钮
        ocr_row = tk.Frame(transform_frame, bg=COLOR_WHITE)
        ocr_row.pack(fill=tk.X, pady=(4, 0))
        tk.Label(ocr_row, text="OCR:", bg=COLOR_WHITE, fg="#666666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=(0, 2))

        self.layer_ocr_detect_btn = tk.Button(
            ocr_row,
            text="检测",
            command=self.detect_text_in_selected_layers,
            bg="#FF9800",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        )
        self.layer_ocr_detect_btn.pack(side=tk.LEFT, padx=2)

        self.layer_ocr_recognize_btn = tk.Button(
            ocr_row,
            text="识别",
            command=self.recognize_text_in_selected_layers,
            bg="#FF6F00",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        )
        self.layer_ocr_recognize_btn.pack(side=tk.LEFT, padx=2)

        # 去除文本背景按钮
        remove_bg_row = tk.Frame(transform_frame, bg=COLOR_WHITE)
        remove_bg_row.pack(fill=tk.X, pady=(4, 0))
        tk.Label(remove_bg_row, text="去字:", bg=COLOR_WHITE, fg="#666666",
                font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=(0, 2))

        self.layer_remove_text_bg_btn = tk.Button(
            remove_bg_row,
            text="去除文本背景",
            command=self.remove_text_background_from_layer,
            bg="#E91E63",
            fg="white",
            font=(FONT_FAMILY, 9),
            cursor="hand2",
            relief=tk.FLAT,
        )
        self.layer_remove_text_bg_btn.pack(side=tk.LEFT, padx=2)

        tk.Label(layer_frame, text="透明度:", bg=COLOR_WHITE, fg="#666666", font=(FONT_FAMILY, 8)).pack(anchor="w")
        self.layer_opacity_scale = tk.Scale(
            layer_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            length=240,
            command=self.on_layer_opacity_change,
            bg=COLOR_WHITE,
            highlightthickness=0,
        )
        self.layer_opacity_scale.set(100)
        self.layer_opacity_scale.pack(fill=tk.X, pady=(0, 5))
        self.layer_opacity_scale.bind("<ButtonPress-1>", self._begin_layer_opacity_drag, add=True)
        self.layer_opacity_scale.bind("<ButtonRelease-1>", self._end_layer_opacity_drag, add=True)

    def create_section_header(self, parent, text):
        """创建属性面板分组标题"""
        header = tk.Frame(parent, bg="#e3f2fd")
        header.pack(fill=tk.X, pady=(10, 5))

        label = tk.Label(header, text=text, bg="#e3f2fd", fg="#1565C0",
                        font=(FONT_FAMILY, 9, "bold"), padx=10, pady=3)
        label.pack(fill=tk.X)
        return header

    def scroll_to_layers(self):
        """切换到右侧“图层”Tab（或回退到旧的滚动定位）。"""
        try:
            nb = getattr(self, "right_notebook", None)
            tab = getattr(self, "layers_tab", None)
            if nb is not None and tab is not None:
                nb.select(tab)
                return
        except Exception:
            pass

        # 兼容旧布局：在滚动属性面板中定位到“图层”
        try:
            canvas = getattr(self, "prop_canvas", None)
            header = getattr(self, "layers_section_header", None)
            frame = getattr(self, "prop_frame", None)
            if canvas is None or header is None or frame is None:
                return
            canvas.update_idletasks()
            frame.update_idletasks()
            y = header.winfo_y()
            total = max(1, frame.winfo_height())
            canvas.yview_moveto(y / total)
        except Exception:
            pass

    def select_layer_by_id(self, layer_id: str):
        """在图层面板中选中指定图层，并同步 UI。"""
        try:
            if not self.pages or not hasattr(self, "layer_tree"):
                return
            page = self.pages[self.current_page_index]
            layers = page.get("layers", [])
            idx = -1
            for i, layer in enumerate(layers):
                if layer and layer.get("id") == layer_id:
                    idx = i
                    break
            self.selected_layer_index = idx
            self.update_layer_listbox()
            try:
                self.layer_tree.selection_set(layer_id)
                self.layer_tree.focus(layer_id)
            except Exception:
                pass
        except Exception:
            pass

    def create_status_bar(self):
        """创建底部状态栏 - PowerPoint红色主题"""
        self.status_bar = tk.Frame(self.root, bg=COLOR_THEME, height=28)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_bar.pack_propagate(False)

        self.status_label = tk.Label(self.status_bar, text="就绪 - 请导入图片开始编辑",
                                     bg=COLOR_THEME, fg="white",
                                     font=(FONT_FAMILY, 9), padx=10)
        self.status_label.pack(side=tk.LEFT)

        self.status_info = tk.Label(self.status_bar, text="",
                                    bg=COLOR_THEME, fg="white",
                                    font=(FONT_FAMILY, 9), padx=10)
        self.status_info.pack(side=tk.RIGHT)

    def update_status(self, text):
        """更新状态栏"""
        self.status_label.config(text=text)

    def bind_shortcuts(self):
        """绑定快捷键"""
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())
        self.root.bind("<Delete>", lambda e: self.delete_selected_box())
        self.root.bind("<Left>", lambda e: self.prev_page())
        self.root.bind("<Right>", lambda e: self.next_page())
        self.root.bind("<Control-s>", lambda e: self.save_project())
        self.root.bind("<Control-o>", lambda e: self.load_project())
        # 新增快捷键
        self.root.bind("<Control-a>", lambda e: self.select_all_boxes())
        self.root.bind("<Control-c>", lambda e: self.copy_boxes())
        self.root.bind("<Control-v>", lambda e: self.paste_boxes())
        self.root.bind("<Left>", lambda e: self.move_box_by_key(-10, 0))
        self.root.bind("<Right>", lambda e: self.move_box_by_key(10, 0))
        self.root.bind("<Up>", lambda e: self.move_box_by_key(0, -10))
        self.root.bind("<Down>", lambda e: self.move_box_by_key(0, 10))
        self.root.bind("<Control-Left>", lambda e: self.move_box_by_key(-1, 0))
        self.root.bind("<Control-Right>", lambda e: self.move_box_by_key(1, 0))
        self.root.bind("<Control-Up>", lambda e: self.move_box_by_key(0, -1))
        self.root.bind("<Control-Down>", lambda e: self.move_box_by_key(0, 1))
        self.root.bind("<Prior>", lambda e: self.prev_page())
        self.root.bind("<Next>", lambda e: self.next_page())


    # ==================== 页面管理 ====================

    # 编辑用的最大图片尺寸（超过此尺寸会缩放以提高性能）
    MAX_EDIT_SIZE = 1920

    def _resize_image_for_edit(self, img):
        """缩放图片用于编辑，返回缩放后的图片和缩放比例"""
        w, h = img.size
        if max(w, h) <= self.MAX_EDIT_SIZE:
            return img, 1.0

        scale = self.MAX_EDIT_SIZE / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return resized, scale

    def load_multiple_images(self):
        """批量加载多张原图"""
        file_paths = filedialog.askopenfilenames(
            title="选择多张原图（按顺序选择）",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp")]
        )
        if not file_paths:
            return

        if self.pages:
            self.save_current_page()

        clear_existing = False
        if self.pages:
            result = messagebox.askyesnocancel(
                "提示", f"已有 {len(self.pages)} 页，是否清空？\n\n是 - 清空后导入\n否 - 追加\n取消 - 取消"
            )
            if result is None:
                return
            elif result:
                self.pages = []
                clear_existing = True

        start_index = len(self.pages)

        for path in file_paths:
            original_img = Image.open(path)
            original_size = original_img.size  # 保存原始尺寸

            # 缩放图片用于编辑
            edit_img, edit_scale = self._resize_image_for_edit(original_img)

            page_data = {
                "original_path": path,
                "original_size": original_size,  # 原始尺寸
                "edit_scale": edit_scale,  # 编辑缩放比例
                "bg_path": None,
                "bg_original_path": None,  # 背景原图路径
                "image": edit_img,  # 编辑用的缩放图片
                "text_boxes": [],
                "layers": []
            }
            self.pages.append(page_data)

        self.current_page_index = start_index
        self.load_current_page()
        self.update_page_label()
        self.update_thumbnails()

        # 隐藏占位符
        self.placeholder_label.place_forget()

        # 显示是否有缩放
        any_scaled = any(p["edit_scale"] < 1.0 for p in self.pages[start_index:])
        if any_scaled:
            self.update_status(f"已导入 {len(file_paths)} 张图片（大图已自动缩放以提高性能），共 {len(self.pages)} 页")
        else:
            self.update_status(f"已导入 {len(file_paths)} 张图片，共 {len(self.pages)} 页")

    def load_multiple_backgrounds(self):
        """批量加载背景图 - 自动调整大小与编辑图一致"""
        if not self.pages:
            messagebox.showwarning("提示", "请先导入原图")
            return

        file_paths = filedialog.askopenfilenames(
            title="选择背景图",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp")]
        )
        if not file_paths:
            return

        matched = 0
        for bg_path in file_paths:
            bg_name = os.path.splitext(os.path.basename(bg_path))[0].lower()
            for page in self.pages:
                orig_name = os.path.splitext(os.path.basename(page["original_path"]))[0].lower()
                if bg_name == orig_name or orig_name in bg_name or bg_name in orig_name:
                    # 调整背景图大小与编辑图一致
                    resized_bg_path = self._resize_bg_to_match(bg_path, page["image"].size)
                    page["bg_path"] = resized_bg_path
                    matched += 1
                    break

        # 如果没有匹配到，按顺序分配
        if matched == 0 and len(file_paths) == len(self.pages):
            for i, bg_path in enumerate(file_paths):
                resized_bg_path = self._resize_bg_to_match(bg_path, self.pages[i]["image"].size)
                self.pages[i]["bg_path"] = resized_bg_path
            matched = len(file_paths)

        # 更新当前页背景路径
        if self.pages and self.current_page_index < len(self.pages):
            self.clean_bg_path = self.pages[self.current_page_index].get("bg_path")

        # 刷新显示
        self.update_bg_status()
        self.update_thumbnails()
        self.refresh_canvas()
        self.update_status(f"已匹配 {matched}/{len(self.pages)} 张背景图")

    def create_blank_page(self):
        """创建空白页面"""
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("新建空白图")
        dialog.geometry("450x400")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="新建空白图", font=(FONT_FAMILY, 14, "bold")).pack(pady=(20, 10))

        # 比例选择
        ratio_frame = tk.LabelFrame(dialog, text="选择比例", font=(FONT_FAMILY, 10, "bold"),
                                    padx=15, pady=15)
        ratio_frame.pack(fill=tk.X, padx=20, pady=(0, 15))

        ratio_var = tk.StringVar(value="16:9")

        ratios = [
            ("16:9 (1920×1080)", "16:9"),
            ("9:16 (1080×1920)", "9:16"),
            ("4:3 (1600×1200)", "4:3"),
            ("3:4 (1200×1600)", "3:4"),
            ("1:1 (1200×1200)", "1:1"),
        ]

        for text, value in ratios:
            tk.Radiobutton(ratio_frame, text=text, variable=ratio_var, value=value,
                          font=(FONT_FAMILY, 10)).pack(anchor="w", pady=2)

        # 颜色选择
        color_frame = tk.LabelFrame(dialog, text="背景颜色", font=(FONT_FAMILY, 10, "bold"),
                                    padx=15, pady=15)
        color_frame.pack(fill=tk.X, padx=20, pady=(0, 15))

        selected_color = tk.StringVar(value="#FFFFFF")

        color_display_row = tk.Frame(color_frame)
        color_display_row.pack(fill=tk.X, pady=5)

        tk.Label(color_display_row, text="当前颜色:", font=(FONT_FAMILY, 9)).pack(side=tk.LEFT)

        color_display = tk.Label(color_display_row, text="      ", bg="#FFFFFF",
                                relief=tk.RIDGE, borderwidth=2, width=10)
        color_display.pack(side=tk.LEFT, padx=10)

        color_label = tk.Label(color_display_row, text="#FFFFFF", font=(FONT_FAMILY, 9))
        color_label.pack(side=tk.LEFT)

        def choose_color():
            color = colorchooser.askcolor(title="选择背景颜色",
                                         initialcolor=selected_color.get())
            if color[1]:
                selected_color.set(color[1])
                color_display.config(bg=color[1])
                color_label.config(text=color[1])

        tk.Button(color_frame, text="选择颜色", command=choose_color,
                 bg=COLOR_THEME, fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10), padx=15, pady=5).pack(pady=5)

        # 按钮
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=20)

        def on_create():
            ratio = ratio_var.get()
            color_hex = selected_color.get()

            # 计算尺寸
            ratio_sizes = {
                "16:9": (1920, 1080),
                "9:16": (1080, 1920),
                "4:3": (1600, 1200),
                "3:4": (1200, 1600),
                "1:1": (1200, 1200),
            }

            width, height = ratio_sizes.get(ratio, (1920, 1080))

            try:
                # 创建空白图片
                blank_img = Image.new("RGB", (width, height), color_hex)

                # 保存到临时文件
                temp_dir = os.path.join(get_base_dir(), "temp_blank_pages")
                os.makedirs(temp_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                temp_path = os.path.join(temp_dir, f"blank_{ratio.replace(':', 'x')}_{timestamp}.png")
                blank_img.save(temp_path)

                # 创建页面数据
                if self.pages:
                    self.save_current_page()

                # 询问是追加还是清空
                clear_existing = False
                if self.pages:
                    result = messagebox.askyesnocancel(
                        "提示", f"已有 {len(self.pages)} 页，是否清空？\n\n是 - 清空后添加\n否 - 追加\n取消 - 取消"
                    )
                    if result is None:
                        dialog.destroy()
                        return
                    elif result:
                        self.pages = []
                        clear_existing = True

                start_index = len(self.pages)

                # 缩放图片用于编辑
                edit_img, edit_scale = self._resize_image_for_edit(blank_img)

                page_data = {
                    "original_path": temp_path,
                    "original_size": (width, height),
                    "edit_scale": edit_scale,
                    "bg_path": None,
                    "bg_original_path": None,
                    "image": edit_img,
                    "text_boxes": [],
                    "layers": []
                }
                self.pages.append(page_data)

                self.current_page_index = start_index
                self.load_current_page()
                self.update_page_label()
                self.update_thumbnails()

                # 隐藏占位符
                self.placeholder_label.place_forget()

                dialog.destroy()
                self.update_status(f"已创建空白图 ({ratio})，共 {len(self.pages)} 页")
                messagebox.showinfo("成功", f"空白图创建成功！\n比例: {ratio}\n颜色: {color_hex}")

            except Exception as e:
                messagebox.showerror("错误", f"创建空白图失败:\n{e}")

        def on_cancel():
            dialog.destroy()

        tk.Button(btn_frame, text="创建", command=on_create,
                 bg="#2196F3", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10, "bold"), padx=25, pady=10).pack(side=tk.LEFT, padx=5)

        tk.Button(btn_frame, text="取消", command=on_cancel,
                 bg="#999", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10), padx=25, pady=10).pack(side=tk.LEFT, padx=5)

    def load_current_page_background(self):
        """为当前页单独设置背景图"""
        if not self.pages:
            messagebox.showwarning("提示", "请先导入原图")
            return

        file_path = filedialog.askopenfilename(
            title=f"选择第 {self.current_page_index + 1} 页的背景图",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp")]
        )
        if not file_path:
            return

        page = self.pages[self.current_page_index]
        edit_size = page["image"].size

        # 调整背景图大小与编辑图一致
        resized_bg_path = self._resize_bg_to_match(file_path, edit_size)
        page["bg_path"] = resized_bg_path
        self.clean_bg_path = resized_bg_path

        self.update_bg_status()
        self.update_thumbnails()
        self.refresh_canvas()
        self.update_status(f"第 {self.current_page_index + 1} 页背景已设置")

    def _resize_bg_to_match(self, bg_path, target_size):
        """调整背景图大小与目标尺寸一致，返回调整后的图片路径"""
        bg_img = Image.open(bg_path)

        # 如果大小已经一致，直接返回原路径
        if bg_img.size == target_size:
            return bg_path

        # 调整大小
        resized_img = bg_img.resize(target_size, Image.Resampling.LANCZOS)

        # 保存到临时文件
        bg_dir = os.path.dirname(bg_path)
        bg_name = os.path.splitext(os.path.basename(bg_path))[0]
        bg_ext = os.path.splitext(bg_path)[1]

        # 创建调整后的文件名
        resized_path = os.path.join(bg_dir, f"{bg_name}_resized_{target_size[0]}x{target_size[1]}{bg_ext}")

        # 如果已存在同名调整后的文件，检查是否需要重新生成
        if not os.path.exists(resized_path):
            if resized_img.mode == 'RGBA' and bg_ext.lower() in ['.jpg', '.jpeg']:
                resized_img = resized_img.convert('RGB')
            resized_img.save(resized_path, quality=95)

        return resized_path

    def clear_current_page_background(self):
        """清除当前页背景"""
        if not self.pages:
            return

        self.pages[self.current_page_index]["bg_path"] = None
        self.clean_bg_path = None
        self.update_bg_status()
        self.update_thumbnails()
        self.refresh_canvas()
        self.update_status(f"第 {self.current_page_index + 1} 页背景已清除")

    def update_bg_status(self):
        return page_manager_core.update_bg_status(self)

    def save_current_page(self):
        return page_manager_core.save_current_page(self)

    def load_current_page(self):
        return page_manager_core.load_current_page(self)

    def prev_page(self):
        return page_manager_core.prev_page(self)

    def next_page(self):
        return page_manager_core.next_page(self)

    def update_page_label(self):
        return page_manager_core.update_page_label(self)

    def update_status_info(self):
        return page_manager_core.update_status_info(self)

    def update_thumbnails(self):
        return page_manager_core.update_thumbnails(self)

    def show_thumbnail_menu(self, event, page_index):
        return page_manager_core.show_thumbnail_menu(self, event, page_index)

    def set_page_background(self, page_index):
        return page_manager_core.set_page_background(self, page_index)

    def clear_page_background(self, page_index):
        return page_manager_core.clear_page_background(self, page_index)

    def delete_page(self, page_index):
        return page_manager_core.delete_page(self, page_index)

    def highlight_current_thumbnail(self):
        return page_manager_core.highlight_current_thumbnail(self)

    def go_to_page(self, index):
        return page_manager_core.go_to_page(self, index)

    # ==================== 画布操作 ====================

    def fit_image_to_canvas(self):
        return page_manager_core.fit_image_to_canvas(self)

    def on_canvas_resize(self, event):
        return page_manager_core.on_canvas_resize(self, event)

    def on_canvas_zoom(self, event):
        return page_manager_core.on_canvas_zoom(self, event)

    def on_canvas_scroll(self, event):
        return page_manager_core.on_canvas_scroll(self, event)

    def zoom_to_100(self):
        return page_manager_core.zoom_to_100(self)

    def refresh_canvas(self):
        """刷新画布"""
        if not self.original_image:
            return

        if self.current_preview_mode == "ppt":
            self._draw_ppt_preview()
        elif self.current_preview_mode == "edit":
            self._draw_original_with_boxes()
        else:
            self._draw_raw_with_boxes()

        self.update_status_info()

    def _draw_raw_with_boxes(self):
        """绘制原始底图（不叠加背景/图层）+框"""
        self.canvas.delete("all")

        base_img = None
        try:
            if self.pages and 0 <= self.current_page_index < len(self.pages):
                base_img = self.pages[self.current_page_index].get("image")
        except Exception:
            base_img = None
        if base_img is None:
            base_img = self.original_image
        if base_img is None:
            return

        img_w, img_h = base_img.size
        display_w = int(img_w * self.scale)
        display_h = int(img_h * self.scale)

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        offset_x = max(0, (canvas_w - display_w) // 2)
        offset_y = max(0, (canvas_h - display_h) // 2)

        self.display_image = base_img.resize((display_w, display_h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=self.tk_image, tags="image")

        self.canvas_offset_x = offset_x
        self.canvas_offset_y = offset_y

        for idx, box in enumerate(self.text_boxes):
            self.draw_box(idx, box, offset_x, offset_y)

        # 蒙版功能已移除

        self.canvas.config(
            scrollregion=(
                0,
                0,
                max(canvas_w, display_w + offset_x * 2),
                max(canvas_h, display_h + offset_y * 2),
            )
        )
    def _draw_original_with_boxes(self):
        """绘制原图+框"""
        self.canvas.delete("all")

        base_img = self.get_current_page_composited_background()
        if base_img is None:
            return

        img_w, img_h = base_img.size
        display_w = int(img_w * self.scale)
        display_h = int(img_h * self.scale)

        # 居中显示
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        offset_x = max(0, (canvas_w - display_w) // 2)
        offset_y = max(0, (canvas_h - display_h) // 2)

        self.display_image = base_img.resize((display_w, display_h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=self.tk_image, tags="image")

        # 保存偏移量用于坐标转换
        self.canvas_offset_x = offset_x
        self.canvas_offset_y = offset_y

        for idx, box in enumerate(self.text_boxes):
            self.draw_box(idx, box, offset_x, offset_y)

        # 蒙版功能已移除

        self.canvas.config(scrollregion=(0, 0, max(canvas_w, display_w + offset_x * 2),
                                          max(canvas_h, display_h + offset_y * 2)))

    def _draw_ppt_preview(self):
        """绘制PPT预览"""
        base_img = self.get_current_page_composited_background()
        if base_img is None:
            return

        preview_img = base_img.copy().convert("RGBA")
        img_w, img_h = preview_img.size

        try:
            draw = ImageDraw.Draw(preview_img)

            for box in self.text_boxes:
                if not box.text:
                    continue

                pixel_font_size = int(box.font_size * 96 / 72)

                try:
                    font_path = self._get_font_path(box.font_name)
                    if font_path:
                        font = ImageFont.truetype(font_path, pixel_font_size)
                    else:
                        font = ImageFont.load_default()
                except:
                    font = ImageFont.load_default()

                color_hex = box.font_color.lstrip('#')
                r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)

                # Pillow 默认以左上角为原点绘制；不同字体会有 ascent/descent 导致视觉上“偏下”。
                # 优先使用 anchor 以文本自身中线对齐，实现垂直居中。
                center_y = box.y + box.height // 2
                if box.align == "center":
                    text_x = box.x + box.width // 2
                    anchor = "mm"
                elif box.align == "right":
                    text_x = box.x + box.width - 3
                    anchor = "rm"
                else:
                    text_x = box.x + 3
                    anchor = "lm"

                try:
                    draw.text((text_x, center_y), box.text, font=font, fill=(r, g, b, 255), anchor=anchor)
                except TypeError:
                    # 兼容旧版 Pillow（不支持 anchor 参数）：使用 bbox 偏移矫正到垂直居中
                    try:
                        bbox = draw.textbbox((0, 0), box.text, font=font)
                        text_w = bbox[2] - bbox[0]
                        text_h = bbox[3] - bbox[1]
                        y = box.y + (box.height - text_h) // 2 - bbox[1]
                        if box.align == "center":
                            x = box.x + (box.width - text_w) // 2 - bbox[0]
                        elif box.align == "right":
                            x = box.x + box.width - text_w - 3 - bbox[0]
                        else:
                            x = box.x + 3 - bbox[0]
                        draw.text((x, y), box.text, font=font, fill=(r, g, b, 255))
                    except Exception:
                        draw.text((box.x + 3, box.y + 2), box.text, font=font, fill=(r, g, b, 255))

        except Exception as e:
            print(f"绘制文字失败: {e}")

        preview_img = preview_img.convert("RGB")

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        # 保持当前缩放比例，不强制重置
        display_w = int(img_w * self.scale)
        display_h = int(img_h * self.scale)

        offset_x = max(0, (canvas_w - display_w) // 2)
        offset_y = max(0, (canvas_h - display_h) // 2)

        self.canvas_offset_x = offset_x
        self.canvas_offset_y = offset_y

        preview_img = preview_img.resize((display_w, display_h), Image.Resampling.LANCZOS)
        self.ppt_preview_image = ImageTk.PhotoImage(preview_img)

        self.canvas.delete("all")
        self.canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=self.ppt_preview_image)

        # 蒙版功能已移除

        for idx, box in enumerate(self.text_boxes):
            self._draw_ppt_edit_box(idx, box, offset_x, offset_y)

        self.canvas.config(scrollregion=(0, 0, max(canvas_w, display_w + offset_x * 2),
                                          max(canvas_h, display_h + offset_y * 2)))

    def get_current_page_composited_background(self):
        """
        获取当前页“底图”（背景/原图）+图层合成后的图片（不含文本渲染）。
        """
        if not self.pages:
            return self.original_image.copy() if self.original_image else None
        page = self.pages[self.current_page_index]
        return self.get_page_composited_background(page)

    def get_page_composited_background(self, page):
        """
        获取指定页“底图”（背景/原图）+图层合成后的图片（不含文本渲染）。
        坐标系以 page["image"] 为准（编辑尺寸）。
        """
        base_img = None
        bg_path = page.get("bg_path")
        if bg_path and os.path.exists(bg_path):
            try:
                base_img = Image.open(bg_path)
            except Exception:
                base_img = None

        if base_img is None:
            if page.get("image") is not None:
                base_img = page["image"].copy()
            else:
                return self.original_image.copy() if self.original_image else None

        edit_img = page.get("image")
        if edit_img is not None and base_img.size != edit_img.size:
            base_img = base_img.resize(edit_img.size, Image.Resampling.LANCZOS)

        base_rgba = base_img.convert("RGBA")

        layers = page.get("layers", [])
        # PS习惯：列表顶部为最上层；合成时应从底到顶绘制（反向遍历）
        for layer in reversed(layers):
            if not layer or not layer.get("visible", True):
                continue
            path = layer.get("path")
            if not path or not os.path.exists(path):
                continue

            try:
                overlay = Image.open(path).convert("RGBA")
            except Exception:
                continue

            # 裁剪（以图层原图坐标系为准）
            crop = layer.get("crop")
            if crop:
                try:
                    if isinstance(crop, dict):
                        x0 = int(crop.get("x0", 0))
                        y0 = int(crop.get("y0", 0))
                        x1 = int(crop.get("x1", overlay.size[0]))
                        y1 = int(crop.get("y1", overlay.size[1]))
                    else:
                        x0, y0, x1, y1 = [int(v) for v in crop]
                    x0 = max(0, min(overlay.size[0], x0))
                    y0 = max(0, min(overlay.size[1], y0))
                    x1 = max(0, min(overlay.size[0], x1))
                    y1 = max(0, min(overlay.size[1], y1))
                    if x1 > x0 and y1 > y0:
                        overlay = overlay.crop((x0, y0, x1, y1))
                except Exception:
                    pass

            # 缩放
            try:
                scale = float(layer.get("scale", 1.0))
            except Exception:
                scale = 1.0
            if scale <= 0:
                scale = 1.0
            if abs(scale - 1.0) > 1e-6:
                try:
                    new_w = max(1, int(round(overlay.size[0] * scale)))
                    new_h = max(1, int(round(overlay.size[1] * scale)))
                    overlay = overlay.resize((new_w, new_h), Image.Resampling.LANCZOS)
                except Exception:
                    pass

            opacity = float(layer.get("opacity", 1.0))
            opacity = max(0.0, min(opacity, 1.0))
            if opacity < 1.0:
                r, g, b, a = overlay.split()
                a = a.point(lambda v: int(v * opacity))
                overlay = Image.merge("RGBA", (r, g, b, a))

            x = int(layer.get("x", 0))
            y = int(layer.get("y", 0))
            base_rgba.paste(overlay, (x, y), overlay)

        return base_rgba.convert("RGB")

    def _ensure_page_layers(self, page):
        return page.setdefault("layers", [])

    def add_image_layer(self, page, image, name="AI图层", x=0, y=0, opacity=1.0, visible=True):
        """
        将一张 PIL Image 保存为图层并加入到页面 layers。
        """
        layers = self._ensure_page_layers(page)

        temp_dir = os.path.join(get_base_dir(), "temp_backgrounds")
        os.makedirs(temp_dir, exist_ok=True)

        layer_id = uuid.uuid4().hex[:10]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(temp_dir, f"layer_{layer_id}_{timestamp}.png")

        img = image.convert("RGBA") if image.mode != "RGBA" else image
        img.save(path)

        layer = {
            "id": layer_id,
            "name": name,
            "path": path,
            "x": int(x),
            "y": int(y),
            "scale": float(1.0),
            "crop": None,
            "locked": False,
            "opacity": float(opacity),
            "visible": bool(visible),
        }
        # 新图层默认置顶（更符合PS习惯）
        layers.insert(0, layer)
        return layer

    def update_layer_listbox(self):
        if not hasattr(self, "layer_tree"):
            return

        page = self.pages[self.current_page_index] if self.pages else None
        layers = page.get("layers", []) if page else []

        # 兼容：缺少 id 的图层补齐
        for layer in layers:
            if layer is not None and not layer.get("id"):
                layer["id"] = uuid.uuid4().hex[:10]
            if layer is not None:
                layer.setdefault("x", 0)
                layer.setdefault("y", 0)
                layer.setdefault("opacity", 1.0)
                layer.setdefault("visible", True)
                layer.setdefault("scale", 1.0)
                layer.setdefault("crop", None)
                layer.setdefault("locked", False)

        for iid in self.layer_tree.get_children(""):
            self.layer_tree.delete(iid)

        self._layer_thumb_refs = {}

        for i, layer in enumerate(layers):
            if not layer:
                continue
            vis = "✓" if layer.get("visible", True) else "×"
            opacity = int(float(layer.get("opacity", 1.0)) * 100)
            name = layer.get("name") or f"图层{i+1}"
            lock_flag = "锁" if layer.get("locked") else ""

            thumb = None
            path = layer.get("path")
            if path and os.path.exists(path):
                try:
                    img = Image.open(path).convert("RGBA")
                    img.thumbnail((48, 32), Image.Resampling.LANCZOS)
                    thumb = ImageTk.PhotoImage(img)
                    self._layer_thumb_refs[layer["id"]] = thumb
                except Exception:
                    thumb = None

            self.layer_tree.insert(
                "",
                "end",
                iid=layer["id"],
                text=name,
                image=thumb,
                values=(vis, f"{opacity}%", lock_flag),
            )

        # 恢复选择 + 同步透明度
        if self.selected_layer_index >= len(layers):
            self.selected_layer_index = -1

        page, layers, layer = self._get_selected_layer()
        if layer is not None:
            try:
                self.layer_tree.selection_set(layer["id"])
                self.layer_tree.focus(layer["id"])
            except Exception:
                pass
            try:
                opacity = float(layer.get("opacity", 1.0))
                self._layer_opacity_syncing = True
                self.layer_opacity_scale.set(int(opacity * 100))
            except Exception:
                self._layer_opacity_syncing = True
                self.layer_opacity_scale.set(100)
            finally:
                self._layer_opacity_syncing = False

            self._sync_layer_transform_controls(layer)
        else:
            self._layer_opacity_syncing = True
            self.layer_opacity_scale.set(100)
            self._layer_opacity_syncing = False
            self._sync_layer_transform_controls(None)

    def on_layer_select(self, event=None):
        if not self.pages:
            return
        page = self.pages[self.current_page_index]
        layers = page.get("layers", [])

        idx = -1
        if hasattr(self, "layer_tree"):
            sel = self.layer_tree.selection()
            if sel:
                selected_iid = sel[0]
                for i, layer in enumerate(layers):
                    if layer and layer.get("id") == selected_iid:
                        idx = i
                        break

        self.selected_layer_index = idx
        if 0 <= idx < len(layers):
            try:
                opacity = float(layers[idx].get("opacity", 1.0))
                self._layer_opacity_syncing = True
                self.layer_opacity_scale.set(int(opacity * 100))
            except Exception:
                self._layer_opacity_syncing = True
                self.layer_opacity_scale.set(100)
            finally:
                self._layer_opacity_syncing = False

            self._sync_layer_transform_controls(layers[idx])
        else:
            self._sync_layer_transform_controls(None)

        # 蒙版功能已移除

    def _get_selected_layer(self):
        if not self.pages:
            return None, None, None
        page = self.pages[self.current_page_index]
        layers = page.get("layers", [])

        idx = self.selected_layer_index
        if hasattr(self, "layer_tree"):
            sel = self.layer_tree.selection()
            if sel:
                selected_iid = sel[0]
                for i, layer in enumerate(layers):
                    if layer and layer.get("id") == selected_iid:
                        idx = i
                        break

        if idx is None or idx < 0 or idx >= len(layers):
            return page, layers, None

        self.selected_layer_index = idx
        return page, layers, layers[idx]

    def _layer_bbox(self, layer):
        """返回图层在页面坐标系下的包围盒 (x0,y0,x1,y1)，考虑裁剪与缩放。"""
        try:
            path = layer.get("path")
            if not path or not os.path.exists(path):
                return None
            w0, h0 = Image.open(path).size

            crop = layer.get("crop")
            if crop:
                try:
                    if isinstance(crop, dict):
                        x0 = int(crop.get("x0", 0))
                        y0 = int(crop.get("y0", 0))
                        x1 = int(crop.get("x1", w0))
                        y1 = int(crop.get("y1", h0))
                    else:
                        x0, y0, x1, y1 = [int(v) for v in crop]
                    x0 = max(0, min(w0, x0))
                    y0 = max(0, min(h0, y0))
                    x1 = max(0, min(w0, x1))
                    y1 = max(0, min(h0, y1))
                    if x1 > x0 and y1 > y0:
                        w0 = x1 - x0
                        h0 = y1 - y0
                except Exception:
                    pass

            try:
                scale = float(layer.get("scale", 1.0))
            except Exception:
                scale = 1.0
            if scale <= 0:
                scale = 1.0

            w = max(1, int(round(w0 * scale)))
            h = max(1, int(round(h0 * scale)))
            x = int(layer.get("x", 0))
            y = int(layer.get("y", 0))
            return x, y, x + w, y + h
        except Exception:
            return None

    def toggle_selected_layer(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        self.save_state("layers")
        layer["visible"] = not layer.get("visible", True)
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def delete_selected_layer(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        self.save_state("layers")
        del layers[self.selected_layer_index]
        self.selected_layer_index = min(self.selected_layer_index, len(layers) - 1)
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def move_layer_up(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        idx = self.selected_layer_index
        if idx <= 0:
            return
        self.save_state("layers")
        layers[idx - 1], layers[idx] = layers[idx], layers[idx - 1]
        self.selected_layer_index = idx - 1
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def move_layer_down(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        idx = self.selected_layer_index
        if idx >= len(layers) - 1:
            return
        self.save_state("layers")
        layers[idx + 1], layers[idx] = layers[idx], layers[idx + 1]
        self.selected_layer_index = idx + 1
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def on_layer_opacity_change(self, value):
        if getattr(self, "_layer_opacity_syncing", False):
            return
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        try:
            opacity = float(value) / 100.0
        except Exception:
            opacity = 1.0
        opacity = max(0.0, min(opacity, 1.0))
        prev = float(layer.get("opacity", 1.0))
        if abs(prev - opacity) < 1e-6:
            return
        # 拖动滑杆时避免刷屏历史：只在一次拖动的首次变更时保存快照
        if getattr(self, "_layer_opacity_drag_active", False):
            if not getattr(self, "_layer_opacity_saved", False):
                self.save_state("layers")
                self._layer_opacity_saved = True
        else:
            self.save_state("layers")
        layer["opacity"] = opacity
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def _begin_layer_opacity_drag(self, event=None):
        self._layer_opacity_drag_active = True
        self._layer_opacity_saved = False

    def _end_layer_opacity_drag(self, event=None):
        self._layer_opacity_drag_active = False
        self._layer_opacity_saved = False

    def _sync_layer_transform_controls(self, layer):
        """同步图层变换 UI（X/Y/缩放/锁定）到当前选择。"""
        if not hasattr(self, "layer_x_var"):
            return
        try:
            self._layer_transform_syncing = True
            if not layer:
                self.layer_x_var.set(0)
                self.layer_y_var.set(0)
                self.layer_scale_var.set(100)
                self.layer_lock_var.set(False)
                for w in (
                    getattr(self, "layer_x_entry", None),
                    getattr(self, "layer_y_entry", None),
                    getattr(self, "layer_scale_slider", None),
                    getattr(self, "layer_lock_check", None),
                    getattr(self, "layer_crop_btn", None),
                    getattr(self, "layer_reset_crop_btn", None),
                ):
                    try:
                        if w is not None:
                            w.config(state="disabled")
                    except Exception:
                        pass
                return

            layer.setdefault("x", 0)
            layer.setdefault("y", 0)
            layer.setdefault("scale", 1.0)
            layer.setdefault("crop", None)
            layer.setdefault("locked", False)

            self.layer_x_var.set(int(layer.get("x", 0)))
            self.layer_y_var.set(int(layer.get("y", 0)))
            try:
                s = float(layer.get("scale", 1.0))
            except Exception:
                s = 1.0
            self.layer_scale_var.set(int(max(10, min(300, round(s * 100)))))
            self.layer_lock_var.set(bool(layer.get("locked", False)))

            state = "disabled" if layer.get("locked") else "normal"
            for w in (
                getattr(self, "layer_x_entry", None),
                getattr(self, "layer_y_entry", None),
                getattr(self, "layer_scale_slider", None),
                getattr(self, "layer_crop_btn", None),
                getattr(self, "layer_reset_crop_btn", None),
            ):
                try:
                    if w is not None:
                        w.config(state=state)
                except Exception:
                    pass
            try:
                if getattr(self, "layer_lock_check", None) is not None:
                    self.layer_lock_check.config(state="normal")
            except Exception:
                pass
        finally:
            self._layer_transform_syncing = False

    def toggle_selected_layer_lock(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        self.save_state("layers")
        layer["locked"] = not bool(layer.get("locked", False))
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def _on_layer_lock_toggle(self):
        if getattr(self, "_layer_transform_syncing", False):
            return
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        self.save_state("layers")
        layer["locked"] = bool(self.layer_lock_var.get())
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def _apply_layer_transform_from_ui(self):
        if getattr(self, "_layer_transform_syncing", False):
            return
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        if layer.get("locked"):
            self.update_status("图层已锁定，无法修改位置/缩放/裁剪")
            self._sync_layer_transform_controls(layer)
            return

        try:
            x = int(self.layer_x_var.get())
            y = int(self.layer_y_var.get())
        except Exception:
            return
        old_x = int(layer.get("x", 0))
        old_y = int(layer.get("y", 0))
        if x == old_x and y == old_y:
            return
        self.save_state("layers")
        layer["x"] = x
        layer["y"] = y
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def _begin_layer_scale_drag(self, event=None):
        self._layer_scale_drag_active = True
        self._layer_scale_saved = False

    def _end_layer_scale_drag(self, event=None):
        self._layer_scale_drag_active = False
        self._layer_scale_saved = False

    def _on_layer_scale_change(self, value):
        if getattr(self, "_layer_transform_syncing", False):
            return
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        if layer.get("locked"):
            self.update_status("图层已锁定，无法修改位置/缩放/裁剪")
            self._sync_layer_transform_controls(layer)
            return
        try:
            scale_pct = int(float(value))
        except Exception:
            return
        scale_pct = max(10, min(300, scale_pct))
        new_scale = scale_pct / 100.0
        try:
            old_scale = float(layer.get("scale", 1.0))
        except Exception:
            old_scale = 1.0
        if abs(old_scale - new_scale) < 1e-6:
            return
        if getattr(self, "_layer_scale_drag_active", False):
            if not getattr(self, "_layer_scale_saved", False):
                self.save_state("layers")
                self._layer_scale_saved = True
        else:
            self.save_state("layers")
        layer["scale"] = new_scale
        self.refresh_canvas()
        self.mark_unsaved()
        self.update_layer_listbox()

    def solid_color_cutout_selected_layer(self):
        """对选定的图层进行纯色抠图"""
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            messagebox.showwarning("提示", "请先选择一个图层")
            return
        if layer.get("locked"):
            self.update_status("图层已锁定，无法编辑")
            return

        path = layer.get("path")
        if not path or not os.path.exists(path):
            messagebox.showwarning("提示", "图层文件不存在")
            return

        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开图层图片: {e}")
            return

        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("纯色抠图")
        dialog.geometry("900x600")
        dialog.transient(self.root)
        dialog.grab_set()

        # 主容器
        main_frame = tk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 左侧：图片预览
        left_frame = tk.Frame(main_frame, bg="#f0f0f0")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        tk.Label(left_frame, text="图片预览 (点击吸取颜色)",
                font=(FONT_FAMILY, 10, "bold"), bg="#f0f0f0").pack(pady=5)

        # 计算预览图尺寸
        max_w, max_h = 550, 500
        scale = min(1.0, max_w / img.size[0], max_h / img.size[1])
        disp_w = max(1, int(img.size[0] * scale))
        disp_h = max(1, int(img.size[1] * scale))
        preview_img = img.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        tk_preview = ImageTk.PhotoImage(preview_img)

        # 创建画布
        canvas = tk.Canvas(left_frame, width=disp_w, height=disp_h,
                          bg="#222", highlightthickness=1, highlightbackground="#999")
        canvas.pack(padx=5, pady=5)
        canvas.create_image(0, 0, anchor=tk.NW, image=tk_preview)
        canvas.image = tk_preview

        # 右侧：控制面板
        right_frame = tk.Frame(main_frame, bg=COLOR_WHITE, width=300)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(10, 0))
        right_frame.pack_propagate(False)

        tk.Label(right_frame, text="纯色抠图设置", font=(FONT_FAMILY, 12, "bold"),
                bg=COLOR_WHITE).pack(pady=(15, 20))

        # 颜色选择
        color_section = tk.LabelFrame(right_frame, text="颜色选择",
                                      font=(FONT_FAMILY, 10, "bold"),
                                      bg=COLOR_WHITE, padx=10, pady=10)
        color_section.pack(fill=tk.X, padx=15, pady=(0, 15))

        selected_color = tk.StringVar(value="#FFFFFF")
        eyedropper_mode = tk.BooleanVar(value=False)

        # 颜色显示
        color_display_frame = tk.Frame(color_section, bg=COLOR_WHITE)
        color_display_frame.pack(fill=tk.X, pady=5)

        tk.Label(color_display_frame, text="当前颜色:",
                font=(FONT_FAMILY, 9), bg=COLOR_WHITE).pack(side=tk.LEFT)

        color_display = tk.Label(color_display_frame, text="      ",
                                bg="#FFFFFF", relief=tk.RIDGE, borderwidth=2)
        color_display.pack(side=tk.LEFT, padx=10)

        color_label = tk.Label(color_display_frame, text="#FFFFFF",
                              font=(FONT_FAMILY, 9), bg=COLOR_WHITE)
        color_label.pack(side=tk.LEFT)

        def update_color_display(color_hex):
            selected_color.set(color_hex)
            color_display.config(bg=color_hex)
            color_label.config(text=color_hex)

        # 按钮行
        btn_row = tk.Frame(color_section, bg=COLOR_WHITE)
        btn_row.pack(fill=tk.X, pady=5)

        def choose_color():
            color = colorchooser.askcolor(title="选择要抠除的颜色",
                                         initialcolor=selected_color.get())
            if color[1]:
                update_color_display(color[1])
                eyedropper_mode.set(False)
                eyedropper_btn.config(relief=tk.FLAT, bg="#2196F3")
                canvas.config(cursor="")

        def toggle_eyedropper():
            if eyedropper_mode.get():
                eyedropper_mode.set(False)
                eyedropper_btn.config(relief=tk.FLAT, bg="#2196F3")
                canvas.config(cursor="")
            else:
                eyedropper_mode.set(True)
                eyedropper_btn.config(relief=tk.SUNKEN, bg="#1976D2")
                canvas.config(cursor="crosshair")

        tk.Button(btn_row, text="选择颜色", command=choose_color,
                 bg=COLOR_THEME, fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 9), padx=10, pady=5).pack(side=tk.LEFT, padx=(0, 5))

        eyedropper_btn = tk.Button(btn_row, text="🎨 吸管工具", command=toggle_eyedropper,
                                   bg="#2196F3", fg="white", relief=tk.FLAT,
                                   font=(FONT_FAMILY, 9), padx=10, pady=5)
        eyedropper_btn.pack(side=tk.LEFT)

        # 吸管工具点击事件
        def on_canvas_click(event):
            if not eyedropper_mode.get():
                return

            # 获取点击位置的颜色
            try:
                x = int(event.x / scale)
                y = int(event.y / scale)
                if 0 <= x < img.size[0] and 0 <= y < img.size[1]:
                    pixel = img.getpixel((x, y))
                    r, g, b = pixel[0], pixel[1], pixel[2]
                    color_hex = f"#{r:02x}{g:02x}{b:02x}"
                    update_color_display(color_hex)
                    # 取色后自动关闭吸管模式
                    eyedropper_mode.set(False)
                    eyedropper_btn.config(relief=tk.FLAT, bg="#2196F3")
                    canvas.config(cursor="")
            except Exception as e:
                print(f"吸管工具错误: {e}")

        canvas.bind("<Button-1>", on_canvas_click)

        # 容差设置
        tolerance_section = tk.LabelFrame(right_frame, text="容差设置",
                                         font=(FONT_FAMILY, 10, "bold"),
                                         bg=COLOR_WHITE, padx=10, pady=10)
        tolerance_section.pack(fill=tk.X, padx=15, pady=(0, 15))

        tk.Label(tolerance_section, text="颜色容差 (0-255):",
                font=(FONT_FAMILY, 9), bg=COLOR_WHITE).pack(anchor="w")

        tolerance_var = tk.IntVar(value=30)

        tolerance_frame = tk.Frame(tolerance_section, bg=COLOR_WHITE)
        tolerance_frame.pack(fill=tk.X, pady=5)

        tolerance_scale = tk.Scale(tolerance_frame, from_=0, to=255, orient=tk.HORIZONTAL,
                                   variable=tolerance_var, bg=COLOR_WHITE, length=220)
        tolerance_scale.pack(side=tk.LEFT)

        tolerance_value_label = tk.Label(tolerance_frame, text="30",
                                        font=(FONT_FAMILY, 9, "bold"),
                                        bg=COLOR_WHITE, width=3)
        tolerance_value_label.pack(side=tk.LEFT, padx=5)

        def update_tolerance_label(*args):
            tolerance_value_label.config(text=str(tolerance_var.get()))

        tolerance_var.trace('w', update_tolerance_label)

        tk.Label(tolerance_section, text="容差越大，抠除的颜色范围越广",
                font=(FONT_FAMILY, 8), fg="#666", bg=COLOR_WHITE).pack(anchor="w")

        # 按钮区域
        btn_frame = tk.Frame(right_frame, bg=COLOR_WHITE)
        btn_frame.pack(side=tk.BOTTOM, pady=20)

        def on_apply():
            color_hex = selected_color.get()
            tolerance = tolerance_var.get()

            try:
                # 将十六进制颜色转换为RGB
                color_hex = color_hex.lstrip('#')
                target_r = int(color_hex[0:2], 16)
                target_g = int(color_hex[2:4], 16)
                target_b = int(color_hex[4:6], 16)

                # 转换为numpy数组进行处理
                img_array = np.array(img)

                # 计算每个像素与目标颜色的距离
                diff = np.abs(img_array[:, :, 0].astype(int) - target_r) + \
                       np.abs(img_array[:, :, 1].astype(int) - target_g) + \
                       np.abs(img_array[:, :, 2].astype(int) - target_b)

                # 创建mask：距离小于容差的像素设为透明
                mask = diff <= tolerance * 3  # 乘以3因为是三个通道的总和
                img_array[mask, 3] = 0  # 将alpha通道设为0（透明）

                # 转换回PIL图像
                result_img = Image.fromarray(img_array, 'RGBA')

                # 保存处理后的图片
                temp_dir = os.path.join(get_base_dir(), "temp_cutout")
                os.makedirs(temp_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_path = os.path.join(temp_dir, f"cutout_{timestamp}.png")
                result_img.save(new_path)

                # 更新图层路径
                self.save_state("layers")
                layer["path"] = new_path

                # 刷新显示
                self.update_layer_listbox()
                self.refresh_canvas()
                self.mark_unsaved()

                dialog.destroy()
                messagebox.showinfo("成功", "纯色抠图完成！")

            except Exception as e:
                messagebox.showerror("错误", f"抠图失败: {e}")

        def on_cancel():
            dialog.destroy()

        tk.Button(btn_frame, text="应用", command=on_apply,
                 bg="#00897B", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10, "bold"), padx=25, pady=10).pack(pady=5)

        tk.Button(btn_frame, text="取消", command=on_cancel,
                 bg="#999", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10), padx=25, pady=10).pack(pady=5)

    def detect_text_in_selected_layers(self):
        """对选中的图层进行文字检测，在图层上直接检测文本位置并添加文本框到当前页面"""
        if not self.ocr:
            messagebox.showwarning("提示", "OCR未初始化")
            return

        page, layers, layer = self._get_selected_layer()
        if layer is None:
            messagebox.showwarning("提示", "请先选择一个图层")
            return

        path = layer.get("path")
        if not path or not os.path.exists(path):
            messagebox.showwarning("提示", "图层文件不存在")
            return

        current_page = self.pages[self.current_page_index]

        # 询问是否清空现有框
        if current_page.get("text_boxes"):
            result = messagebox.askyesnocancel(
                "提示", "是否清空现有文本框？\n\n是 - 清空后检测\n否 - 追加检测\n取消 - 取消"
            )
            if result is None:
                return
            elif result:
                current_page["text_boxes"] = []

        # 创建进度对话框
        progress_dialog = tk.Toplevel(self.root)
        progress_dialog.title("OCR检测中")
        progress_dialog.geometry("400x150")
        progress_dialog.transient(self.root)
        progress_dialog.grab_set()

        tk.Label(progress_dialog, text="正在检测图层中的文字区域...",
                font=(FONT_FAMILY, 11, "bold")).pack(pady=20)

        progress_label = tk.Label(progress_dialog, text="请稍候...",
                                 font=(FONT_FAMILY, 9), fg="#666")
        progress_label.pack(pady=10)

        def worker():
            try:
                # 读取图层图片
                layer_img = Image.open(path).convert("RGB")

                # 获取图层在页面中的位置
                layer_x = layer.get("x", 0)
                layer_y = layer.get("y", 0)
                layer_scale = layer.get("scale", 1.0)

                # 转换为OpenCV格式
                img_array = np.array(layer_img)
                img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

                img_h, img_w = img_bgr.shape[:2]

                # 保存临时文件供OCR使用
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                temp_path = temp_file.name
                temp_file.close()
                cv2.imwrite(temp_path, img_bgr)

                # OCR检测 - 使用与顶部菜单相同的逻辑
                result = self.ocr.predict(temp_path)
                os.remove(temp_path)

                if not result or len(result) == 0:
                    self.root.after(0, progress_dialog.destroy)
                    self.root.after(0, lambda: messagebox.showinfo("提示", "未检测到文字"))
                    return

                ocr_result = result[0]
                dt_polys = ocr_result.get('dt_polys', [])
                rec_texts = ocr_result.get('rec_texts', [])

                if not dt_polys:
                    self.root.after(0, progress_dialog.destroy)
                    self.root.after(0, lambda: messagebox.showinfo("提示", "未检测到文字"))
                    return

                # 将检测结果添加到当前页面的text_boxes
                text_boxes = current_page.get("text_boxes", [])
                added_count = 0

                for i, poly in enumerate(dt_polys):
                    # 计算文本框位置（相对于图层）
                    x_coords = [p[0] for p in poly]
                    y_coords = [p[1] for p in poly]

                    x_min = int(min(x_coords))
                    y_min = int(min(y_coords))
                    x_max = int(max(x_coords))
                    y_max = int(max(y_coords))

                    box_w = x_max - x_min
                    box_h = y_max - y_min

                    if box_w < 10 or box_h < 10:
                        continue

                    # 转换到页面坐标（考虑图层位置和缩放）
                    page_x = int(layer_x + x_min * layer_scale)
                    page_y = int(layer_y + y_min * layer_scale)
                    page_w = int(box_w * layer_scale)
                    page_h = int(box_h * layer_scale)

                    # 获取识别的文字
                    text = rec_texts[i] if i < len(rec_texts) else ""

                    # 创建文本框 - 使用标准格式
                    font_size = 12
                    if text:
                        font_size = fit_font_size_pt(text, page_w, page_h, editor=self)

                    text_box = {
                        "x": page_x,
                        "y": page_y,
                        "width": page_w,
                        "height": page_h,
                        "text": text,  # 已经有文字了
                        "font_name": "微软雅黑",
                        "font_size": font_size,
                        "font_color": "#000000",
                        "bold": False,
                        "italic": False,
                        "align": "left"
                    }
                    text_boxes.append(text_box)
                    added_count += 1

                current_page["text_boxes"] = text_boxes

                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, self.load_current_page)  # 重新加载页面，将字典转换为TextBox对象
                self.root.after(0, self.mark_unsaved)
                self.root.after(0, lambda c=added_count: messagebox.showinfo(
                    "成功", f"检测并识别完成！\n共检测到 {c} 个文本框\n文字已自动识别"))

            except Exception as e:
                import traceback
                traceback.print_exc()
                err_text = str(e)
                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, lambda t=err_text: messagebox.showerror("错误", f"OCR检测失败:\n{t}"))

        threading.Thread(target=worker, daemon=True).start()

    def remove_text_background_from_layer(self):
        """对选中的图层去除文本背景"""
        if not self.pages:
            messagebox.showwarning("提示", "请先导入图片")
            return

        page, layers, layer = self._get_selected_layer()
        if layer is None:
            messagebox.showwarning("提示", "请先选择一个图层")
            return

        path = layer.get("path")
        if not path or not os.path.exists(path):
            messagebox.showwarning("提示", "图层文件不存在")
            return

        current_page = self.pages[self.current_page_index]
        text_boxes = current_page.get("text_boxes", [])

        if not text_boxes:
            messagebox.showwarning("提示", "当前页没有文本框\n\n请先使用「检测」功能识别文本区域")
            return

        if not self.config.get("inpaint_enabled", True):
            messagebox.showwarning("提示", "背景生成功能已禁用\n\n请在设置中启用")
            return

        # 确认对话框
        result = messagebox.askyesno(
            "确认",
            f"即将对选中图层进行去字处理\n\n"
            f"当前页有 {len(text_boxes)} 个文本框\n"
            "系统将自动对这些文字区域进行修复\n\n"
            "提示：结果会作为新图层叠加，原图层不会被修改\n\n"
            "此操作需要调用 IOPaint API 服务\n"
            "处理时间约 5-30 秒\n\n"
            "是否继续？",
        )

        if not result:
            return

        # 保存图层快照便于撤销
        self.save_state("layers")

        self.update_status("正在对图层进行去字处理...")

        def generate_bg():
            try:
                # 读取图层图片
                layer_img = Image.open(path).convert("RGB")
                layer_x = layer.get("x", 0)
                layer_y = layer.get("y", 0)
                layer_scale = layer.get("scale", 1.0)

                # 创建蒙版 - 需要将页面坐标的text_boxes转换到图层坐标
                self.root.after(0, lambda: self.update_status("正在创建蒙版..."))

                # 创建图层大小的蒙版
                mask = Image.new("L", layer_img.size, 0)  # 全黑背景
                draw = ImageDraw.Draw(mask)

                for box in text_boxes:
                    # 将页面坐标转换回图层坐标
                    # page_x = layer_x + layer_img_x * layer_scale
                    # => layer_img_x = (page_x - layer_x) / layer_scale

                    box_x_on_layer = (box["x"] - layer_x) / layer_scale
                    box_y_on_layer = (box["y"] - layer_y) / layer_scale
                    box_w_on_layer = box["width"] / layer_scale
                    box_h_on_layer = box["height"] / layer_scale

                    # 检查文本框是否在图层范围内
                    if (box_x_on_layer + box_w_on_layer < 0 or box_x_on_layer > layer_img.size[0] or
                        box_y_on_layer + box_h_on_layer < 0 or box_y_on_layer > layer_img.size[1]):
                        continue

                    # 稍微扩大文本框区域
                    padding = 5
                    x1 = max(0, int(box_x_on_layer - padding))
                    y1 = max(0, int(box_y_on_layer - padding))
                    x2 = min(layer_img.size[0], int(box_x_on_layer + box_w_on_layer + padding))
                    y2 = min(layer_img.size[1], int(box_y_on_layer + box_h_on_layer + padding))

                    # 标记为白色（需要修复）
                    draw.rectangle([x1, y1, x2, y2], fill=255)

                # 调用API修复
                self.root.after(0, lambda: self.update_status("正在调用IOPaint API修复..."))
                result_img = self.call_inpaint_api(layer_img, mask)

                if result_img:
                    # 将修复后的图片作为新图层添加
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    layer_name = f"去字_{os.path.splitext(os.path.basename(path))[0]}_{timestamp}"

                    # 保存修复后的图片
                    temp_dir = os.path.join(get_base_dir(), "temp_inpaint")
                    os.makedirs(temp_dir, exist_ok=True)
                    new_path = os.path.join(temp_dir, f"{layer_name}.png")
                    result_img.save(new_path)

                    # 添加为新图层，继承原图层的位置和缩放
                    new_layer = self.add_image_layer(
                        current_page,
                        result_img.convert("RGBA"),
                        name=layer_name,
                        x=layer_x,
                        y=layer_y,
                        opacity=1.0,
                        visible=True
                    )
                    if new_layer:
                        new_layer["scale"] = layer_scale
                        new_layer["locked"] = False

                    self.root.after(0, self.update_thumbnails)
                    self.root.after(0, self.update_layer_listbox)
                    self.root.after(0, self.scroll_to_layers)
                    if new_layer and new_layer.get("id"):
                        self.root.after(0, lambda lid=new_layer["id"]: self.select_layer_by_id(lid))
                    self.root.after(0, self.refresh_canvas)
                    self.root.after(0, self.mark_unsaved)

                    self.root.after(0, lambda: self.update_status(f"已生成去字图层：{layer_name}"))
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "完成",
                            "去字处理完成！\n\n"
                            f"已去除 {len(text_boxes)} 个文字区域\n"
                            "结果已作为新图层叠加（右侧图层面板可见）\n\n"
                            "提示：Ctrl+Z 可以撤销",
                        ),
                    )
                else:
                    self.root.after(0, lambda: self.update_status("去字处理失败"))
                    self.root.after(0, lambda: messagebox.showerror("错误", "IOPaint API 调用失败"))

            except Exception as e:
                import traceback
                error_msg = traceback.format_exc()
                print(error_msg)
                self.root.after(0, lambda: self.update_status("去字处理出错"))
                self.root.after(0, lambda: messagebox.showerror("错误", f"去字处理失败:\n{str(e)}"))

        threading.Thread(target=generate_bg, daemon=True).start()

    def recognize_text_in_selected_layers(self):
        """对当前页面中的空文本框进行OCR识别"""
        if not self.ocr:
            messagebox.showwarning("提示", "OCR未初始化")
            return

        if not self.pages:
            messagebox.showwarning("提示", "请先导入图片")
            return

        current_page = self.pages[self.current_page_index]
        text_boxes = current_page.get("text_boxes", [])

        if not text_boxes:
            messagebox.showwarning("提示", "请先检测文本框")
            return

        # 统计空文本框
        empty_boxes = [box for box in text_boxes if not box.get("text")]

        if not empty_boxes:
            messagebox.showinfo("提示", "所有文本框都已有文字，无需识别")
            return

        # 创建进度对话框
        progress_dialog = tk.Toplevel(self.root)
        progress_dialog.title("OCR识别中")
        progress_dialog.geometry("400x150")
        progress_dialog.transient(self.root)
        progress_dialog.grab_set()

        tk.Label(progress_dialog, text=f"正在识别 {len(empty_boxes)} 个文本框...",
                font=(FONT_FAMILY, 11, "bold")).pack(pady=20)

        progress_label = tk.Label(progress_dialog, text="请稍候...",
                                 font=(FONT_FAMILY, 9), fg="#666")
        progress_label.pack(pady=10)

        def worker():
            try:
                # 使用当前页的编辑图片
                page_img = current_page["image"]
                img = np.array(page_img)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                img_h, img_w = img.shape[:2]
                recognized_count = 0

                for box_data in empty_boxes:
                    if box_data.get("text"):
                        continue

                    x, y, w, h = box_data["x"], box_data["y"], box_data["width"], box_data["height"]
                    expand_h, expand_w = int(h * 0.3), int(w * 0.1)

                    crop_x = max(0, x - expand_w)
                    crop_y = max(0, y - expand_h)
                    crop_x2 = min(x + w + expand_w, img_w)
                    crop_y2 = min(y + h + expand_h, img_h)

                    cropped = img[crop_y:crop_y2, crop_x:crop_x2]

                    temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    temp_path = temp_file.name
                    temp_file.close()
                    cv2.imwrite(temp_path, cropped)

                    try:
                        result = self.ocr.predict(temp_path)
                        os.remove(temp_path)

                        if result and len(result) > 0:
                            ocr_result = result[0]
                            rec_texts = ocr_result.get('rec_texts', [])
                            if rec_texts:
                                box_data["text"] = ''.join(rec_texts)
                                if box_data["text"]:
                                    box_data["font_size"] = fit_font_size_pt(
                                        box_data["text"],
                                        w,
                                        h,
                                        editor=self,
                                        font_name=box_data.get("font_name"),
                                    )
                                    recognized_count += 1
                    except:
                        try:
                            os.remove(temp_path)
                        except:
                            pass

                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, self.load_current_page)  # 重新加载页面，更新TextBox对象
                self.root.after(0, self.mark_unsaved)
                self.root.after(0, lambda c=recognized_count: messagebox.showinfo(
                    "成功", f"识别完成！\n成功识别 {c} 个文本框"))

            except Exception as e:
                import traceback
                traceback.print_exc()
                err_text = str(e)
                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, lambda t=err_text: messagebox.showerror("错误", f"OCR识别失败:\n{t}"))

        threading.Thread(target=worker, daemon=True).start()

    def ocr_selected_layer(self):
        """对选中的图层进行OCR识别，将识别结果添加到当前页面（已弃用，保留兼容性）"""
        self.detect_text_in_selected_layers()

    def reset_selected_layer_crop(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        if layer.get("locked"):
            self.update_status("图层已锁定，无法修改位置/缩放/裁剪")
            return
        if not layer.get("crop"):
            return
        self.save_state("layers")
        layer["crop"] = None
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def crop_selected_layer(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return
        if layer.get("locked"):
            self.update_status("图层已锁定，无法修改位置/缩放/裁剪")
            return
        path = layer.get("path")
        if not path or not os.path.exists(path):
            messagebox.showwarning("提示", "图层文件不存在")
            return

        try:
            src = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开图层图片: {e}")
            return

        win = tk.Toplevel(self.root)
        win.title("裁剪图层")
        win.geometry("900x700")
        win.transient(self.root)

        max_w, max_h = 860, 560
        scale = min(1.0, max_w / src.size[0], max_h / src.size[1])
        disp_w = max(1, int(src.size[0] * scale))
        disp_h = max(1, int(src.size[1] * scale))
        disp = src.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        tk_img = ImageTk.PhotoImage(disp)

        canvas = tk.Canvas(win, width=disp_w, height=disp_h, bg="#222", highlightthickness=0)
        canvas.pack(padx=10, pady=10)
        canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)
        canvas.image = tk_img

        rect_id = None
        start = {"x": 0, "y": 0}
        current = {"x0": 0, "y0": 0, "x1": disp_w, "y1": disp_h}

        # 初始化为已有 crop 或全图
        crop = layer.get("crop")
        if crop:
            try:
                if isinstance(crop, dict):
                    x0 = int(crop.get("x0", 0))
                    y0 = int(crop.get("y0", 0))
                    x1 = int(crop.get("x1", src.size[0]))
                    y1 = int(crop.get("y1", src.size[1]))
                else:
                    x0, y0, x1, y1 = [int(v) for v in crop]
                current["x0"] = int(x0 * scale)
                current["y0"] = int(y0 * scale)
                current["x1"] = int(x1 * scale)
                current["y1"] = int(y1 * scale)
            except Exception:
                pass

        rect_id = canvas.create_rectangle(
            current["x0"], current["y0"], current["x1"], current["y1"], outline="#00E5FF", width=2
        )

        def on_press(ev):
            start["x"], start["y"] = ev.x, ev.y
            current["x0"], current["y0"] = ev.x, ev.y
            current["x1"], current["y1"] = ev.x, ev.y
            canvas.coords(rect_id, ev.x, ev.y, ev.x, ev.y)

        def on_drag(ev):
            x0 = min(start["x"], ev.x)
            y0 = min(start["y"], ev.y)
            x1 = max(start["x"], ev.x)
            y1 = max(start["y"], ev.y)
            x0 = max(0, min(disp_w, x0))
            y0 = max(0, min(disp_h, y0))
            x1 = max(0, min(disp_w, x1))
            y1 = max(0, min(disp_h, y1))
            current["x0"], current["y0"], current["x1"], current["y1"] = x0, y0, x1, y1
            canvas.coords(rect_id, x0, y0, x1, y1)

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)

        btn_row = tk.Frame(win, bg=COLOR_WHITE)
        btn_row.pack(fill=tk.X, padx=10, pady=(0, 10))

        def apply_crop():
            x0, y0, x1, y1 = current["x0"], current["y0"], current["x1"], current["y1"]
            if x1 - x0 < 2 or y1 - y0 < 2:
                win.destroy()
                return
            rx0 = int(round(x0 / scale))
            ry0 = int(round(y0 / scale))
            rx1 = int(round(x1 / scale))
            ry1 = int(round(y1 / scale))
            rx0 = max(0, min(src.size[0], rx0))
            ry0 = max(0, min(src.size[1], ry0))
            rx1 = max(0, min(src.size[0], rx1))
            ry1 = max(0, min(src.size[1], ry1))
            if rx1 <= rx0 or ry1 <= ry0:
                win.destroy()
                return
            self.save_state("layers")
            layer["crop"] = {"x0": rx0, "y0": ry0, "x1": rx1, "y1": ry1}
            self.update_layer_listbox()
            self.refresh_canvas()
            self.mark_unsaved()
            win.destroy()

        tk.Button(btn_row, text="应用裁剪", command=apply_crop, bg=COLOR_GREEN, fg="white",
                  font=(FONT_FAMILY, 9), cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="取消", command=win.destroy, bg="#757575", fg="white",
                  font=(FONT_FAMILY, 9), cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=4)

    def import_layer_from_file(self):
        """从本地导入图片（包含 SVG）作为新图层。"""
        if not self.pages:
            messagebox.showwarning("提示", "请先导入图片")
            return

        file_path = filedialog.askopenfilename(
            title="选择要导入到图层的图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff *.svg"),
                ("所有文件", "*.*"),
            ],
        )
        if not file_path:
            return

        ext = os.path.splitext(file_path)[1].lower()
        img = None
        try:
            if ext == ".svg":
                try:
                    import cairosvg  # type: ignore
                except Exception:
                    messagebox.showerror(
                        "缺少依赖",
                        "当前环境未安装 SVG 渲染依赖，无法直接导入 SVG。\n\n"
                        "可选方案：\n"
                        "1) pip install cairosvg\n"
                        "2) 先把 SVG 导出为 PNG 再导入\n",
                    )
                    return
                from io import BytesIO

                png_bytes = cairosvg.svg2png(url=file_path)
                img = Image.open(BytesIO(png_bytes)).convert("RGBA")
            else:
                img = Image.open(file_path)
                if "A" in img.getbands():
                    img = img.convert("RGBA")
                else:
                    img = img.convert("RGB").convert("RGBA")
        except Exception as e:
            messagebox.showerror("错误", f"无法导入图片: {e}")
            return

        page = self.pages[self.current_page_index]
        base = page.get("image") or self.original_image
        if base is None:
            return
        base_w, base_h = base.size

        # 默认缩放到画面内（不放大）
        s = 1.0
        try:
            s = min(1.0, base_w / max(1, img.size[0]), base_h / max(1, img.size[1])) * 0.9
            s = max(0.05, min(1.0, s))
        except Exception:
            s = 1.0

        x = int((base_w - img.size[0] * s) / 2)
        y = int((base_h - img.size[1] * s) / 2)

        name = os.path.splitext(os.path.basename(file_path))[0] or "导入图层"

        self.save_state("layers")
        layer = self.add_image_layer(page, img, name=name, x=x, y=y, opacity=1.0, visible=True)
        if layer is not None:
            layer["scale"] = float(s)
            layer["crop"] = None
            layer["locked"] = True  # 默认锁定图层，防止误操作

        self.update_layer_listbox()
        self.scroll_to_layers()
        if layer and layer.get("id"):
            self.select_layer_by_id(layer["id"])
        self.refresh_canvas()
        self.mark_unsaved()
        self.update_status(f"已导入图层: {name}")

    def on_layer_tree_click(self, event):
        # 点击“显”列：快速显示/隐藏
        if not hasattr(self, "layer_tree"):
            return
        region = self.layer_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row = self.layer_tree.identify_row(event.y)
        col = self.layer_tree.identify_column(event.x)
        if not row:
            return
        if col == "#1":  # vis 列
            try:
                self.layer_tree.selection_set(row)
                self.layer_tree.focus(row)
            except Exception:
                pass
            self.on_layer_select()
            self.toggle_selected_layer()
            return "break"
        if col == "#3":  # lock 列
            try:
                self.layer_tree.selection_set(row)
                self.layer_tree.focus(row)
            except Exception:
                pass
            self.on_layer_select()
            self.toggle_selected_layer_lock()
            return "break"

    def on_layer_drag_start(self, event):
        if not hasattr(self, "layer_tree"):
            return
        region = self.layer_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.layer_tree.identify_column(event.x)
        if col in ("#1", "#3"):  # vis/lock 列点击不触发拖拽
            return
        self._layer_drag_iid = self.layer_tree.identify_row(event.y)
        self._layer_drag_moved = False

    def on_layer_drag_motion(self, event):
        if not hasattr(self, "layer_tree"):
            return
        dragged = getattr(self, "_layer_drag_iid", None)
        if not dragged:
            return
        target = self.layer_tree.identify_row(event.y)
        if not target or target == dragged:
            return
        try:
            target_index = self.layer_tree.index(target)
            self.layer_tree.move(dragged, "", target_index)
            self._layer_drag_moved = True
        except Exception:
            pass

    def on_layer_drag_release(self, event):
        if not hasattr(self, "layer_tree") or not self.pages:
            self._layer_drag_iid = None
            self._layer_drag_moved = False
            return
        if not getattr(self, "_layer_drag_moved", False):
            self._layer_drag_iid = None
            return

        page = self.pages[self.current_page_index]
        layers = page.get("layers", [])
        if not layers:
            self._layer_drag_iid = None
            self._layer_drag_moved = False
            return

        new_order = list(self.layer_tree.get_children(""))
        old_order = [layer.get("id") for layer in layers if layer]
        if new_order and old_order and new_order != old_order:
            self.save_state("layers")
            layer_map = {layer.get("id"): layer for layer in layers if layer and layer.get("id")}
            rebuilt = [layer_map[iid] for iid in new_order if iid in layer_map]
            page["layers"] = rebuilt
            self.layers = page.get("layers", [])
            # 保持选择同步
            try:
                sel = self.layer_tree.selection()
                if sel:
                    selected_iid = sel[0]
                    for i, layer in enumerate(rebuilt):
                        if layer and layer.get("id") == selected_iid:
                            self.selected_layer_index = i
                            break
            except Exception:
                pass
            self.update_layer_listbox()
            self.refresh_canvas()
            self.mark_unsaved()

        self._layer_drag_iid = None
        self._layer_drag_moved = False

    def preview_selected_layer(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return

        path = layer.get("path")
        if not path or not os.path.exists(path):
            messagebox.showwarning("提示", "图层文件不存在")
            return

        try:
            overlay = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开图层图片: {e}")
            return

        # 预览时应用透明度/裁剪/缩放效果（更直观）
        crop = layer.get("crop")
        if crop:
            try:
                if isinstance(crop, dict):
                    x0 = int(crop.get("x0", 0))
                    y0 = int(crop.get("y0", 0))
                    x1 = int(crop.get("x1", overlay.size[0]))
                    y1 = int(crop.get("y1", overlay.size[1]))
                else:
                    x0, y0, x1, y1 = [int(v) for v in crop]
                x0 = max(0, min(overlay.size[0], x0))
                y0 = max(0, min(overlay.size[1], y0))
                x1 = max(0, min(overlay.size[0], x1))
                y1 = max(0, min(overlay.size[1], y1))
                if x1 > x0 and y1 > y0:
                    overlay = overlay.crop((x0, y0, x1, y1))
            except Exception:
                pass

        try:
            scale = float(layer.get("scale", 1.0))
        except Exception:
            scale = 1.0
        if scale <= 0:
            scale = 1.0
        if abs(scale - 1.0) > 1e-6:
            try:
                overlay = overlay.resize(
                    (max(1, int(round(overlay.size[0] * scale))), max(1, int(round(overlay.size[1] * scale)))),
                    Image.Resampling.LANCZOS,
                )
            except Exception:
                pass

        opacity = float(layer.get("opacity", 1.0))
        opacity = max(0.0, min(opacity, 1.0))
        if opacity < 1.0:
            r, g, b, a = overlay.split()
            a = a.point(lambda v: int(v * opacity))
            overlay = Image.merge("RGBA", (r, g, b, a))

        win = tk.Toplevel(self.root)
        win.title(layer.get("name") or "图层预览")
        win.transient(self.root)

        img = overlay.copy()
        img.thumbnail((820, 600), Image.Resampling.LANCZOS)
        tk_img = ImageTk.PhotoImage(img)

        label = tk.Label(win, image=tk_img, bg="white")
        label.image = tk_img
        label.pack(padx=10, pady=10)

    def rename_selected_layer(self):
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return

        current_name = layer.get("name") or "图层"
        new_name = simpledialog.askstring("重命名图层", "请输入新名称：", initialvalue=current_name, parent=self.root)
        if not new_name:
            return
        self.save_state("layers")
        layer["name"] = new_name.strip()
        self.update_layer_listbox()
        self.mark_unsaved()

    def set_selected_layer_mask_from_file(self):
        # 图层蒙版功能已移除（此前会导致卡死/闪退）。
        messagebox.showinfo("提示", "图层蒙版功能已移除（避免卡死）。")
        return
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return

        file_path = filedialog.askopenfilename(
            title="选择蒙版图片（白=显示，黑=隐藏）",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp")],
        )
        if not file_path:
            return

        try:
            src = Image.open(file_path)
            # 优先使用 alpha（很多蒙版 PNG 用透明度表达）
            if "A" in src.getbands():
                mask_img = src.convert("RGBA").split()[-1]
            else:
                mask_img = src.convert("L")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开蒙版图片: {e}")
            return

        temp_dir = os.path.join(get_base_dir(), "temp_backgrounds")
        os.makedirs(temp_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        layer_id = (layer.get("id") or uuid.uuid4().hex[:10])[:10]
        mask_path = os.path.join(temp_dir, f"mask_{layer_id}_{timestamp}.png")

        try:
            mask_img.save(mask_path)
        except Exception as e:
            messagebox.showerror("错误", f"保存蒙版失败: {e}")
            return

        self.save_state("layers")
        layer["mask_path"] = mask_path
        layer.setdefault("mask_invert", False)
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def clear_selected_layer_mask(self):
        # 图层蒙版功能已移除（此前会导致卡死/闪退）。
        messagebox.showinfo("提示", "图层蒙版功能已移除（避免卡死）。")
        return
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return

        if "mask_path" in layer:
            self.save_state("layers")
            layer.pop("mask_path", None)
            layer.pop("mask_invert", None)
            self.update_layer_listbox()
            self.refresh_canvas()
            self.mark_unsaved()

    def invert_selected_layer_mask(self):
        # 图层蒙版功能已移除（此前会导致卡死/闪退）。
        messagebox.showinfo("提示", "图层蒙版功能已移除（避免卡死）。")
        return
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            return

        if not layer.get("mask_path") or not os.path.exists(layer.get("mask_path")):
            messagebox.showwarning("提示", "当前图层没有蒙版")
            return

        self.save_state("layers")
        layer["mask_invert"] = not bool(layer.get("mask_invert", False))
        self.update_layer_listbox()
        self.refresh_canvas()
        self.mark_unsaved()

    def enter_mask_edit_mode(self):
        # 图层蒙版编辑功能已移除（此前会导致卡死/闪退）。
        try:
            self.layer_mask_edit_mode = False
            self.canvas.delete("mask_overlay")
            self.canvas.delete("mask_edit_rect")
        except Exception:
            pass
        messagebox.showinfo("提示", "图层蒙版编辑已移除（避免卡死）。")
        return
        page, layers, layer = self._get_selected_layer()
        if layer is None:
            messagebox.showwarning("提示", "请先选择一个图层")
            return

        # 后续可能会创建 mask_path / 修正尺寸，先记录图层快照用于撤销
        self.save_state("layers")

        path = layer.get("path")
        if not path or not os.path.exists(path):
            messagebox.showwarning("提示", "图层文件不存在，无法编辑蒙版")
            return

        try:
            # 只取尺寸，避免大图 convert 导致界面假死
            overlay_size = Image.open(path).size
        except Exception as e:
            messagebox.showerror("错误", f"无法打开图层图片: {e}")
            return

        # 关闭可能冲突的模式
        self.inpaint_mode = False
        self.ai_replace_mode = False
        self.draw_mode = False
        self.is_drawing = False
        self.is_dragging = False
        self.is_resizing = False
        self.is_selecting = False
        self.canvas.delete("temp_rect")
        self.canvas.delete("selection_rect")

        # 准备蒙版（默认全白 = 全显示）
        temp_dir = os.path.join(get_base_dir(), "temp_backgrounds")
        os.makedirs(temp_dir, exist_ok=True)

        if not layer.get("id"):
            layer["id"] = uuid.uuid4().hex[:10]

        mask_path = layer.get("mask_path")
        if not mask_path or not os.path.exists(mask_path):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            mask_path = os.path.join(temp_dir, f"mask_{layer['id']}_{timestamp}.png")
            Image.new("L", overlay_size, 255).save(mask_path)
            layer["mask_path"] = mask_path
            layer.setdefault("mask_invert", False)
        else:
            try:
                existing = Image.open(mask_path).convert("L")
                if existing.size != overlay_size:
                    existing = existing.resize(overlay_size, Image.Resampling.NEAREST)
                    existing.save(mask_path)
            except Exception:
                Image.new("L", overlay_size, 255).save(mask_path)
                layer["mask_path"] = mask_path
                layer.setdefault("mask_invert", False)

        try:
            self._mask_edit_mask = Image.open(mask_path).convert("L")
        except Exception:
            self._mask_edit_mask = Image.new("L", overlay_size, 255)

        self._mask_edit_draw = ImageDraw.Draw(self._mask_edit_mask)
        self._mask_edit_layer_id = layer.get("id")
        self._mask_edit_overlay_size = overlay_size
        self._mask_last_point = None
        self._mask_rect_id = None
        self._mask_rect_start = None
        self._mask_dirty = False
        self._mask_refresh_after = None

        self.layer_mask_edit_mode = True
        self.mask_edit_mode_var.set(True)
        self.update_status("蒙版编辑：左键刷/框选（图层面板可切换工具/模式）")
        self.update_layer_listbox()
        self.refresh_canvas()

    def exit_mask_edit_mode(self):
        # 图层蒙版编辑功能已移除（此前会导致卡死/闪退）。
        try:
            self.layer_mask_edit_mode = False
            self.canvas.delete("mask_overlay")
            self.canvas.delete("mask_edit_rect")
        except Exception:
            pass
        return
        if not getattr(self, "layer_mask_edit_mode", False):
            return

        self._mask_save_current()
        self.layer_mask_edit_mode = False
        try:
            self.mask_edit_mode_var.set(False)
        except Exception:
            pass
        self._mask_last_point = None
        self._mask_rect_start = None
        if self._mask_rect_id:
            try:
                self.canvas.delete(self._mask_rect_id)
            except Exception:
                pass
        self._mask_rect_id = None
        self.update_layer_listbox()
        self.refresh_canvas()
        if getattr(self, "_mask_dirty", False):
            self.mark_unsaved()
        self.update_status("已退出蒙版编辑")

    def _mask_save_current(self):
        try:
            if not self.pages:
                return
            page = self.pages[self.current_page_index]
            layer = self._mask_get_layer_by_id(page, getattr(self, "_mask_edit_layer_id", None))
            if layer is None:
                return
            mask_path = layer.get("mask_path")
            if not mask_path:
                return
            if hasattr(self, "_mask_edit_mask") and self._mask_edit_mask is not None:
                self._mask_edit_mask.save(mask_path)
        except Exception:
            pass

    def _mask_get_layer_by_id(self, page, layer_id):
        layers = page.get("layers", [])
        for layer in layers:
            if layer and layer.get("id") == layer_id:
                return layer
        return None

    def _mask_paint_value(self):
        try:
            mode = self.mask_paint_var.get()
        except Exception:
            mode = "hide"
        return 255 if mode == "show" else 0

    def _mask_on_press(self, canvas_x, canvas_y, img_x, img_y):
        if not self.pages:
            return
        page = self.pages[self.current_page_index]
        layer = self._mask_get_layer_by_id(page, getattr(self, "_mask_edit_layer_id", None))
        if layer is None:
            return

        tool = self.mask_tool_var.get() if hasattr(self, "mask_tool_var") else "brush"

        if tool == "rect":
            self._mask_rect_start = (img_x, img_y)
            if self._mask_rect_id:
                self.canvas.delete(self._mask_rect_id)
            x0 = int(canvas_x)
            y0 = int(canvas_y)
            self._mask_rect_id = self.canvas.create_rectangle(
                x0, y0, x0, y0,
                outline="#FF1744",
                width=2,
                dash=(4, 2),
                tags="mask_edit_rect",
            )
            return

        # brush
        self._mask_last_point = (img_x, img_y)
        self._mask_brush_paint_segment(img_x, img_y, img_x, img_y)
        self._mask_schedule_refresh()

    def _mask_on_drag(self, canvas_x, canvas_y, img_x, img_y):
        if not self.pages:
            return
        page = self.pages[self.current_page_index]
        layer = self._mask_get_layer_by_id(page, getattr(self, "_mask_edit_layer_id", None))
        if layer is None:
            return

        tool = self.mask_tool_var.get() if hasattr(self, "mask_tool_var") else "brush"

        if tool == "rect":
            if not self._mask_rect_id or not self._mask_rect_start:
                return
            start_canvas_x = (self._mask_rect_start[0] * self.scale) + getattr(self, 'canvas_offset_x', 0)
            start_canvas_y = (self._mask_rect_start[1] * self.scale) + getattr(self, 'canvas_offset_y', 0)
            self.canvas.coords(self._mask_rect_id, start_canvas_x, start_canvas_y, canvas_x, canvas_y)
            return

        # brush
        if not self._mask_last_point:
            self._mask_last_point = (img_x, img_y)
        last_x, last_y = self._mask_last_point
        self._mask_brush_paint_segment(last_x, last_y, img_x, img_y)
        self._mask_last_point = (img_x, img_y)
        self._mask_schedule_refresh()

    def _mask_on_release(self, canvas_x, canvas_y, img_x, img_y):
        if not self.pages:
            return
        page = self.pages[self.current_page_index]
        layer = self._mask_get_layer_by_id(page, getattr(self, "_mask_edit_layer_id", None))
        if layer is None:
            return

        tool = self.mask_tool_var.get() if hasattr(self, "mask_tool_var") else "brush"

        if tool == "rect" and self._mask_rect_start:
            x0, y0 = self._mask_rect_start
            x1, y1 = img_x, img_y
            self._mask_apply_rect(page, layer, x0, y0, x1, y1)
            if self._mask_rect_id:
                try:
                    self.canvas.delete(self._mask_rect_id)
                except Exception:
                    pass
            self._mask_rect_id = None
            self._mask_rect_start = None
            self._mask_save_current()
            self.update_layer_listbox()
            self.refresh_canvas()
            self.mark_unsaved()
            return

        self._mask_last_point = None
        if getattr(self, "_mask_dirty", False):
            self._mask_save_current()
            self.update_layer_listbox()
            self.refresh_canvas()
            self.mark_unsaved()

    def _mask_brush_paint_segment(self, img_x0, img_y0, img_x1, img_y1):
        if not hasattr(self, "_mask_edit_mask") or self._mask_edit_mask is None:
            return
        if not self.pages:
            return
        page = self.pages[self.current_page_index]
        layer = self._mask_get_layer_by_id(page, getattr(self, "_mask_edit_layer_id", None))
        if layer is None:
            return

        try:
            brush_size = int(self.mask_brush_size_var.get())
        except Exception:
            brush_size = 40
        brush_size = max(1, brush_size)

        paint_value = self._mask_paint_value()

        layer_x = int(layer.get("x", 0))
        layer_y = int(layer.get("y", 0))
        w, h = self._mask_edit_mask.size

        lx0 = int(round(img_x0)) - layer_x
        ly0 = int(round(img_y0)) - layer_y
        lx1 = int(round(img_x1)) - layer_x
        ly1 = int(round(img_y1)) - layer_y

        # 线段裁剪：只要端点都在外面也可能穿过，简单起见不做复杂裁剪
        if (lx0 < -brush_size and lx1 < -brush_size) or (ly0 < -brush_size and ly1 < -brush_size):
            return
        if (lx0 > w + brush_size and lx1 > w + brush_size) or (ly0 > h + brush_size and ly1 > h + brush_size):
            return

        try:
            self._mask_edit_draw.line([(lx0, ly0), (lx1, ly1)], fill=paint_value, width=brush_size, joint="curve")
        except Exception:
            self._mask_edit_draw.line([(lx0, ly0), (lx1, ly1)], fill=paint_value, width=brush_size)
        self._mask_dirty = True

    def _mask_apply_rect(self, page, layer, img_x0, img_y0, img_x1, img_y1):
        if not hasattr(self, "_mask_edit_mask") or self._mask_edit_mask is None:
            return

        layer_x = int(layer.get("x", 0))
        layer_y = int(layer.get("y", 0))
        w, h = self._mask_edit_mask.size

        x0 = int(min(img_x0, img_x1)) - layer_x
        y0 = int(min(img_y0, img_y1)) - layer_y
        x1 = int(max(img_x0, img_x1)) - layer_x
        y1 = int(max(img_y0, img_y1)) - layer_y

        x0 = max(0, min(w, x0))
        y0 = max(0, min(h, y0))
        x1 = max(0, min(w, x1))
        y1 = max(0, min(h, y1))
        if x1 <= x0 or y1 <= y0:
            return

        rect_mode = "局部绘制"
        try:
            rect_mode = self.mask_rect_mode_var.get()
        except Exception:
            rect_mode = "局部绘制"

        if rect_mode == "只显示选区(重建)":
            self._mask_edit_mask.paste(0, (0, 0, w, h))
            self._mask_edit_mask.paste(255, (x0, y0, x1, y1))
        elif rect_mode == "只隐藏选区(重建)":
            self._mask_edit_mask.paste(255, (0, 0, w, h))
            self._mask_edit_mask.paste(0, (x0, y0, x1, y1))
        else:
            paint_value = self._mask_paint_value()
            self._mask_edit_mask.paste(paint_value, (x0, y0, x1, y1))

        self._mask_edit_draw = ImageDraw.Draw(self._mask_edit_mask)
        self._mask_dirty = True

    def _mask_schedule_refresh(self):
        """蒙版编辑的刷新节流，避免每个鼠标事件都触发磁盘/渲染导致卡死。"""
        try:
            if self._mask_refresh_after is not None:
                self.root.after_cancel(self._mask_refresh_after)
        except Exception:
            pass
        try:
            self._mask_refresh_after = self.root.after(30, self.refresh_canvas)
        except Exception:
            self._mask_refresh_after = None

    def _draw_mask_edit_overlay(self, base_size, offset_x, offset_y, display_w, display_h):
        # 图层蒙版编辑功能已移除（此前会导致卡死/闪退）。
        return
        if not getattr(self, "layer_mask_edit_mode", False):
            return
        if not self.pages:
            return

        page = self.pages[self.current_page_index]
        layer = self._mask_get_layer_by_id(page, getattr(self, "_mask_edit_layer_id", None))
        if layer is None:
            return

        # 优先使用内存中的蒙版（编辑中），避免每次刷新都读写磁盘导致卡顿
        mask = None
        try:
            if (
                getattr(self, "layer_mask_edit_mode", False)
                and getattr(self, "_mask_edit_layer_id", None) == layer.get("id")
                and getattr(self, "_mask_edit_mask", None) is not None
            ):
                mask = self._mask_edit_mask
        except Exception:
            mask = None

        if mask is None:
            mask_path = layer.get("mask_path")
            if not mask_path or not os.path.exists(mask_path):
                return
            try:
                mask = Image.open(mask_path).convert("L")
            except Exception:
                return

        # 统一尺寸到图层尺寸（用 nearest，避免灰边/性能问题）
        try:
            overlay_path = layer.get("path")
            if not overlay_path or not os.path.exists(overlay_path):
                return
            overlay_size = Image.open(overlay_path).size
            if mask.size != overlay_size:
                mask = mask.resize(overlay_size, Image.Resampling.NEAREST)
        except Exception:
            return

        if layer.get("mask_invert"):
            try:
                mask = ImageOps.invert(mask)
            except Exception:
                pass

        # 隐藏区域显示为红色半透明：alpha = (255 - mask) * (opacity/100)
        try:
            opacity = int(getattr(self, "mask_overlay_opacity_var").get())
        except Exception:
            opacity = 55
        opacity = max(0, min(opacity, 90)) / 100.0
        hidden = ImageOps.invert(mask)
        hidden = hidden.point(lambda v, a=opacity: int(v * a))
        red = Image.new("RGBA", overlay_img.size, (255, 0, 0, 0))
        red.putalpha(hidden)

        base_w, base_h = base_size
        full = Image.new("RGBA", (base_w, base_h), (255, 0, 0, 0))
        x = int(layer.get("x", 0))
        y = int(layer.get("y", 0))
        full.paste(red, (x, y), red)

        full_disp = full.resize((display_w, display_h), Image.Resampling.NEAREST)
        self._mask_overlay_tk = ImageTk.PhotoImage(full_disp)
        self.canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=self._mask_overlay_tk, tags="mask_overlay")

    def _get_font_path(self, font_name):
        """获取字体路径"""
        font_map = {
            "微软雅黑": "C:/Windows/Fonts/msyh.ttc",
            "宋体": "C:/Windows/Fonts/simsun.ttc",
            "黑体": "C:/Windows/Fonts/simhei.ttf",
            "楷体": "C:/Windows/Fonts/simkai.ttf",
            "仿宋": "C:/Windows/Fonts/simfang.ttf",
            "Arial": "C:/Windows/Fonts/arial.ttf"
        }
        path = font_map.get(font_name)
        if path and os.path.exists(path):
            return path
        return font_map.get("微软雅黑")

    def draw_box(self, idx, box, offset_x, offset_y):
        """绘制文本框"""
        x1 = int(box.x * self.scale) + offset_x
        y1 = int(box.y * self.scale) + offset_y
        x2 = int((box.x + box.width) * self.scale) + offset_x
        y2 = int((box.y + box.height) * self.scale) + offset_y

        is_primary = (idx == self.selected_box_index)
        is_multi = (idx in self.selected_boxes)

        if is_primary:
            color, width = "#1976D2", 3
        elif is_multi:
            color, width = "#4CAF50", 2
        else:
            color, width = "#f44336", 2

        self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=width, tags=f"box_{idx}")

        # 序号
        self.canvas.create_oval(x1 + 5, y1 + 5, x1 + 22, y1 + 22, fill="#FF9800", outline="")
        self.canvas.create_text(x1 + 13, y1 + 13, text=str(idx + 1), fill="white", font=("Arial", 8, "bold"))

        # 文本预览
        if box.text and y2 - y1 > 30:
            preview = box.text[:15] + "..." if len(box.text) > 15 else box.text
            self.canvas.create_text(x1 + 5, y2 - 12, text=preview, fill="#333333",
                                   anchor=tk.NW, font=("微软雅黑", 8))

        # 选中手柄
        if is_primary:
            handle_size = 8
            handles = [(x1, y1), (x2, y1), (x1, y2), (x2, y2),
                      ((x1+x2)//2, y1), ((x1+x2)//2, y2), (x1, (y1+y2)//2), (x2, (y1+y2)//2)]
            for hx, hy in handles:
                self.canvas.create_rectangle(hx - handle_size//2, hy - handle_size//2,
                                            hx + handle_size//2, hy + handle_size//2,
                                            fill="#1976D2", outline="white")

    def _draw_ppt_edit_box(self, idx, box, offset_x, offset_y):
        """PPT预览模式下的编辑框"""
        x1 = int(box.x * self.scale) + offset_x
        y1 = int(box.y * self.scale) + offset_y
        x2 = int((box.x + box.width) * self.scale) + offset_x
        y2 = int((box.y + box.height) * self.scale) + offset_y

        is_primary = (idx == self.selected_box_index)
        is_multi = (idx in self.selected_boxes)

        if is_primary:
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#1976D2", width=2, dash=(4, 4))
            handle_size = 8
            handles = [(x1, y1), (x2, y1), (x1, y2), (x2, y2),
                      ((x1+x2)//2, y1), ((x1+x2)//2, y2), (x1, (y1+y2)//2), (x2, (y1+y2)//2)]
            for hx, hy in handles:
                self.canvas.create_rectangle(hx - handle_size//2, hy - handle_size//2,
                                            hx + handle_size//2, hy + handle_size//2,
                                            fill="#1976D2", outline="white")
        elif is_multi:
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#4CAF50", width=2, dash=(4, 4))
        else:
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#999999", width=1, dash=(2, 4))

    # ==================== 鼠标事件 ====================

    def on_canvas_press(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # 转换为图片坐标
        img_x = (canvas_x - getattr(self, 'canvas_offset_x', 0)) / self.scale
        img_y = (canvas_y - getattr(self, 'canvas_offset_y', 0)) / self.scale

        # 蒙版功能已移除

        # 图层拖动（仅拖动“当前选中图层”，避免与文本框操作冲突）
        page, layers, layer = self._get_selected_layer()
        if (
            layer is not None
            and self.current_preview_mode in ("edit", "ppt")
            and not self.inpaint_mode
            and not self.ai_replace_mode
            and not layer.get("locked")
            and layer.get("visible", True)
        ):
            bbox = self._layer_bbox(layer)
            if bbox is not None:
                x0, y0, x1, y1 = bbox
                if x0 <= img_x <= x1 and y0 <= img_y <= y1:
                    self.is_layer_dragging = True
                    self._layer_drag_start_canvas = (canvas_x, canvas_y)
                    self._layer_drag_origin_xy = (int(layer.get("x", 0)), int(layer.get("y", 0)))
                    self.save_state("layers")
                    return

        # 涂抹模式处理
        if self.inpaint_mode:
            self.handle_inpaint_press(img_x, img_y)
            return

        # AI替换模式处理
        if self.ai_replace_mode:
            self.handle_ai_replace_press(img_x, img_y)
            return

        if self.selected_box_index >= 0:
            handle = self.check_resize_handle(canvas_x, canvas_y)
            if handle:
                self.is_resizing = True
                self.resize_handle = handle
                self.drag_start_x = canvas_x
                self.drag_start_y = canvas_y
                return

        clicked_idx = self.find_box_at(img_x, img_y)

        if clicked_idx >= 0:
            self.select_box(clicked_idx)
            self.is_dragging = True
            self.drag_start_x = canvas_x
            self.drag_start_y = canvas_y
        elif self.draw_mode:
            # 画框模式
            self.is_drawing = True
            self.draw_start_x = img_x
            self.draw_start_y = img_y
        else:
            # 选择模式：开始框选
            self.is_selecting = True
            self.select_start_x = canvas_x
            self.select_start_y = canvas_y

    def on_canvas_ctrl_click(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        img_x = (canvas_x - getattr(self, 'canvas_offset_x', 0)) / self.scale
        img_y = (canvas_y - getattr(self, 'canvas_offset_y', 0)) / self.scale

        clicked_idx = self.find_box_at(img_x, img_y)

        if clicked_idx >= 0:
            if clicked_idx in self.selected_boxes:
                self.selected_boxes.remove(clicked_idx)
            else:
                self.selected_boxes.append(clicked_idx)

            if self.selected_boxes:
                self.selected_box_index = self.selected_boxes[-1]
            else:
                self.selected_box_index = -1

            self.refresh_canvas()
            self.update_property_panel()
            self.update_status(f"已选中 {len(self.selected_boxes)} 个框")

    def on_canvas_drag(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        # 蒙版功能已移除

        if getattr(self, "is_layer_dragging", False):
            page, layers, layer = self._get_selected_layer()
            if layer is None or layer.get("locked"):
                self.is_layer_dragging = False
                return
            start_cx, start_cy = getattr(self, "_layer_drag_start_canvas", (canvas_x, canvas_y))
            ox, oy = getattr(self, "_layer_drag_origin_xy", (int(layer.get("x", 0)), int(layer.get("y", 0))))
            dx = (canvas_x - start_cx) / self.scale
            dy = (canvas_y - start_cy) / self.scale
            layer["x"] = int(round(ox + dx))
            layer["y"] = int(round(oy + dy))
            try:
                self._layer_transform_syncing = True
                if hasattr(self, "layer_x_var"):
                    self.layer_x_var.set(int(layer["x"]))
                if hasattr(self, "layer_y_var"):
                    self.layer_y_var.set(int(layer["y"]))
            finally:
                self._layer_transform_syncing = False
            self.refresh_canvas()
            return

        # 涂抹模式处理
        if self.inpaint_mode:
            img_x = (canvas_x - getattr(self, 'canvas_offset_x', 0)) / self.scale
            img_y = (canvas_y - getattr(self, 'canvas_offset_y', 0)) / self.scale
            self.handle_inpaint_drag(img_x, img_y)
            return

        # AI替换模式处理
        if self.ai_replace_mode:
            self.handle_ai_replace_drag(canvas_x, canvas_y)
            return

        if self.is_resizing and self.selected_box_index >= 0:
            self.resize_selected_box(canvas_x, canvas_y)
        elif self.is_dragging and self.selected_box_index >= 0:
            self.drag_selected_box(canvas_x, canvas_y)
        elif self.is_drawing:
            self.draw_temp_rect(canvas_x, canvas_y)
        elif self.is_selecting:
            self.draw_selection_rect(canvas_x, canvas_y)

    def on_canvas_release(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        # 蒙版功能已移除

        if getattr(self, "is_layer_dragging", False):
            self.is_layer_dragging = False
            self.update_layer_listbox()
            self.refresh_canvas()
            self.mark_unsaved()
            return

        # 涂抹模式处理
        if self.inpaint_mode:
            img_x = (canvas_x - getattr(self, 'canvas_offset_x', 0)) / self.scale
            img_y = (canvas_y - getattr(self, 'canvas_offset_y', 0)) / self.scale
            self.handle_inpaint_release(img_x, img_y)
            return

        # AI替换模式处理
        if self.ai_replace_mode:
            self.handle_ai_replace_release(canvas_x, canvas_y)
            return

        if self.is_drawing:
            self.finish_drawing(canvas_x, canvas_y)
        elif self.is_selecting:
            self.finish_selection(canvas_x, canvas_y)

        self.is_drawing = False
        self.is_dragging = False
        self.is_resizing = False
        self.is_selecting = False
        self.resize_handle = None
        self.canvas.delete("temp_rect")
        self.canvas.delete("selection_rect")

    def on_canvas_double_click(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        img_x = (canvas_x - getattr(self, 'canvas_offset_x', 0)) / self.scale
        img_y = (canvas_y - getattr(self, 'canvas_offset_y', 0)) / self.scale

        clicked_idx = self.find_box_at(img_x, img_y)
        if clicked_idx >= 0:
            self.select_box(clicked_idx)
            self.show_inline_text_editor(clicked_idx)

    def on_canvas_right_click(self, event):
        """右键菜单"""
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        img_x = (canvas_x - getattr(self, 'canvas_offset_x', 0)) / self.scale
        img_y = (canvas_y - getattr(self, 'canvas_offset_y', 0)) / self.scale

        # 查找点击的文本框
        clicked_idx = self.find_box_at(img_x, img_y)

        # 创建右键菜单
        menu = tk.Menu(self.root, tearoff=0, font=(FONT_FAMILY, 9))

        if clicked_idx >= 0:
            # 点击在文本框上
            self.select_box(clicked_idx)

            menu.add_command(label="🔍 OCR识别此框", command=self.ocr_single_box,
                           font=(FONT_FAMILY, 9, "bold"))
            menu.add_separator()
            menu.add_command(label="✏️ 编辑文字", command=lambda: self.show_inline_text_editor(clicked_idx))
            menu.add_separator()
            menu.add_command(label="📋 复制 (Ctrl+C)", command=self.copy_boxes)
            menu.add_command(label="📄 粘贴 (Ctrl+V)", command=self.paste_boxes)
            menu.add_separator()
            menu.add_command(label="🗑️ 删除 (Del)", command=self.delete_selected_box,
                           foreground=COLOR_RED)
        else:
            # 点击在空白处
            if self.clipboard_boxes:
                menu.add_command(label="📄 粘贴 (Ctrl+V)", command=self.paste_boxes)
                menu.add_separator()

            menu.add_command(label="📐 开始画框", command=self.toggle_draw_mode_btn)

            if self.text_boxes:
                menu.add_separator()
                menu.add_command(label="🔍 OCR识别全部", command=self.ocr_all_boxes)

        # 显示菜单
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def find_box_at(self, x, y):
        for idx in range(len(self.text_boxes) - 1, -1, -1):
            box = self.text_boxes[idx]
            if box.x <= x <= box.x + box.width and box.y <= y <= box.y + box.height:
                return idx
        return -1

    def check_resize_handle(self, canvas_x, canvas_y):
        if self.selected_box_index < 0:
            return None

        box = self.text_boxes[self.selected_box_index]
        offset_x = getattr(self, 'canvas_offset_x', 0)
        offset_y = getattr(self, 'canvas_offset_y', 0)

        x1 = int(box.x * self.scale) + offset_x
        y1 = int(box.y * self.scale) + offset_y
        x2 = int((box.x + box.width) * self.scale) + offset_x
        y2 = int((box.y + box.height) * self.scale) + offset_y

        handle_size = 10
        handles = {
            "nw": (x1, y1), "ne": (x2, y1), "sw": (x1, y2), "se": (x2, y2),
            "n": ((x1+x2)//2, y1), "s": ((x1+x2)//2, y2),
            "w": (x1, (y1+y2)//2), "e": (x2, (y1+y2)//2)
        }

        for handle_type, (hx, hy) in handles.items():
            if abs(canvas_x - hx) < handle_size and abs(canvas_y - hy) < handle_size:
                return handle_type
        return None

    def draw_temp_rect(self, canvas_x, canvas_y):
        self.canvas.delete("temp_rect")

        offset_x = getattr(self, 'canvas_offset_x', 0)
        offset_y = getattr(self, 'canvas_offset_y', 0)

        x1 = int(self.draw_start_x * self.scale) + offset_x
        y1 = int(self.draw_start_y * self.scale) + offset_y
        x2 = int(canvas_x)
        y2 = int(canvas_y)

        self.canvas.create_rectangle(x1, y1, x2, y2, outline="#1976D2", width=2,
                                    dash=(5, 5), tags="temp_rect")

    def finish_drawing(self, canvas_x, canvas_y):
        offset_x = getattr(self, 'canvas_offset_x', 0)
        offset_y = getattr(self, 'canvas_offset_y', 0)

        x1 = self.draw_start_x
        y1 = self.draw_start_y
        x2 = (canvas_x - offset_x) / self.scale
        y2 = (canvas_y - offset_y) / self.scale

        if x1 > x2: x1, x2 = x2, x1
        if y1 > y2: y1, y2 = y2, y1

        width = x2 - x1
        height = y2 - y1

        if width < 10 or height < 10:
            return

        self.save_state()

        new_box = TextBox(int(x1), int(y1), int(width), int(height))
        self.text_boxes.append(new_box)
        self.select_box(len(self.text_boxes) - 1)
        self.refresh_canvas()
        self.update_listbox()
        self.mark_unsaved()

    def draw_selection_rect(self, canvas_x, canvas_y):
        """绘制框选区域"""
        self.canvas.delete("selection_rect")

        x1 = int(self.select_start_x)
        y1 = int(self.select_start_y)
        x2 = int(canvas_x)
        y2 = int(canvas_y)

        # 绘制半透明的蓝色选区矩形
        self.canvas.create_rectangle(x1, y1, x2, y2,
                                     outline="#2196F3", width=2,
                                     dash=(3, 3), tags="selection_rect")

    def finish_selection(self, canvas_x, canvas_y):
        """完成框选，选中选区内的所有框"""
        offset_x = getattr(self, 'canvas_offset_x', 0)
        offset_y = getattr(self, 'canvas_offset_y', 0)

        # 计算选区的图片坐标
        x1 = (self.select_start_x - offset_x) / self.scale
        y1 = (self.select_start_y - offset_y) / self.scale
        x2 = (canvas_x - offset_x) / self.scale
        y2 = (canvas_y - offset_y) / self.scale

        # 确保x1 < x2, y1 < y2
        if x1 > x2: x1, x2 = x2, x1
        if y1 > y2: y1, y2 = y2, y1

        # 选区太小则忽略
        if abs(x2 - x1) < 5 or abs(y2 - y1) < 5:
            return

        # 查找选区内的所有文本框
        selected_indices = []
        for idx, box in enumerate(self.text_boxes):
            # 检查文本框是否与选区相交或包含在选区内
            box_left = box.x
            box_right = box.x + box.width
            box_top = box.y
            box_bottom = box.y + box.height

            # 判断相交：选区的任意部分与框重叠
            if (box_left < x2 and box_right > x1 and
                box_top < y2 and box_bottom > y1):
                selected_indices.append(idx)

        # 选中找到的框
        if selected_indices:
            self.selected_boxes = selected_indices
            self.selected_box_index = selected_indices[0] if selected_indices else -1

            # 更新界面
            self.refresh_canvas()
            self.update_property_panel()

            # 更新列表框选择
            self.box_listbox.selection_clear(0, tk.END)
            for idx in self.selected_boxes:
                self.box_listbox.selection_set(idx)

            self.update_status(f"框选选中 {len(selected_indices)} 个文本框 ✓")
        else:
            # 没有选中任何框，清空选择
            self.selected_boxes = []
            self.selected_box_index = -1
            self.refresh_canvas()
            self.update_status("框选区域内没有文本框")

    def resize_selected_box(self, canvas_x, canvas_y):
        if self.selected_box_index < 0:
            return

        box = self.text_boxes[self.selected_box_index]
        dx = (canvas_x - self.drag_start_x) / self.scale
        dy = (canvas_y - self.drag_start_y) / self.scale

        if "w" in self.resize_handle:
            new_x = box.x + dx
            new_w = box.width - dx
            if new_w > 10:
                box.x = int(new_x)
                box.width = int(new_w)
        if "e" in self.resize_handle:
            new_w = box.width + dx
            if new_w > 10:
                box.width = int(new_w)
        if "n" in self.resize_handle:
            new_y = box.y + dy
            new_h = box.height - dy
            if new_h > 10:
                box.y = int(new_y)
                box.height = int(new_h)
        if "s" in self.resize_handle:
            new_h = box.height + dy
            if new_h > 10:
                box.height = int(new_h)

        self.drag_start_x = canvas_x
        self.drag_start_y = canvas_y
        self.refresh_canvas()
        self.update_property_panel()

    def drag_selected_box(self, canvas_x, canvas_y):
        if self.selected_box_index < 0:
            return

        box = self.text_boxes[self.selected_box_index]
        dx = (canvas_x - self.drag_start_x) / self.scale
        dy = (canvas_y - self.drag_start_y) / self.scale

        box.x = int(box.x + dx)
        box.y = int(box.y + dy)

        self.drag_start_x = canvas_x
        self.drag_start_y = canvas_y
        self.refresh_canvas()
        self.update_property_panel()

    # ==================== 选择与属性 ====================

    def select_box(self, idx):
        self.selected_box_index = idx
        self.selected_boxes = [idx] if idx >= 0 else []
        self.refresh_canvas()
        self.update_property_panel()

        self.box_listbox.selection_clear(0, tk.END)
        if idx >= 0:
            self.box_listbox.selection_set(idx)
            self.box_listbox.see(idx)

    def update_listbox(self):
        self.box_listbox.delete(0, tk.END)
        for idx, box in enumerate(self.text_boxes):
            text_preview = box.text[:15] + "..." if len(box.text) > 15 else box.text
            if not text_preview:
                text_preview = "(空)"
            self.box_listbox.insert(tk.END, f"{idx+1}. {text_preview}")

    def on_listbox_select(self, event):
        selection = self.box_listbox.curselection()
        if selection:
            self.select_box(selection[0])

    def update_property_panel(self):
        if self.selected_box_index < 0 or self.selected_box_index >= len(self.text_boxes):
            return

        box = self.text_boxes[self.selected_box_index]

        self.text_entry.delete("1.0", tk.END)
        self.text_entry.insert("1.0", box.text)

        self.x_entry.delete(0, tk.END)
        self.x_entry.insert(0, str(box.x))
        self.y_entry.delete(0, tk.END)
        self.y_entry.insert(0, str(box.y))
        self.w_entry.delete(0, tk.END)
        self.w_entry.insert(0, str(box.width))
        self.h_entry.delete(0, tk.END)
        self.h_entry.insert(0, str(box.height))

        self.fontsize_var.set(str(box.font_size))
        self.fontname_var.set(box.font_name)
        self.bold_var.set(box.bold)
        self.italic_var.set(box.italic)
        self.align_var.set(box.align)
        self.color_btn.config(bg=box.font_color)

        self.update_style_buttons()
        self.update_align_buttons()

    def update_style_buttons(self):
        if self.bold_var.get():
            self.bold_btn.config(bg="#1976D2", fg="white")
        else:
            self.bold_btn.config(bg="#e0e0e0", fg="black")

        if self.italic_var.get():
            self.italic_btn.config(bg="#1976D2", fg="white")
        else:
            self.italic_btn.config(bg="#e0e0e0", fg="black")

    def on_text_change(self, event=None):
        if self.selected_box_index < 0:
            return
        box = self.text_boxes[self.selected_box_index]
        box.text = self.text_entry.get("1.0", tk.END).strip()
        self.update_listbox()
        self.refresh_canvas()

    def on_position_change(self, event=None):
        if self.selected_box_index < 0:
            return
        box = self.text_boxes[self.selected_box_index]
        try:
            box.x = int(self.x_entry.get())
            box.y = int(self.y_entry.get())
            box.width = int(self.w_entry.get())
            box.height = int(self.h_entry.get())
            self.refresh_canvas()
        except ValueError:
            pass

    def on_font_change(self, event=None):
        if self.selected_box_index < 0:
            return
        box = self.text_boxes[self.selected_box_index]
        try:
            box.font_size = int(self.fontsize_var.get())
        except:
            pass
        box.font_name = self.fontname_var.get()
        self.refresh_canvas()

    def set_align(self, align):
        """设置对齐方式"""
        self.align_var.set(align)
        self.update_align_buttons()
        self.on_style_change()

    def update_align_buttons(self):
        """更新对齐按钮状态"""
        align = self.align_var.get()
        # 左对齐
        if align == "left":
            self.align_left_btn.config(bg="#1976D2", fg="white")
        else:
            self.align_left_btn.config(bg="#e0e0e0", fg="#333")
        # 居中
        if align == "center":
            self.align_center_btn.config(bg="#1976D2", fg="white")
        else:
            self.align_center_btn.config(bg="#e0e0e0", fg="#333")
        # 右对齐
        if align == "right":
            self.align_right_btn.config(bg="#1976D2", fg="white")
        else:
            self.align_right_btn.config(bg="#e0e0e0", fg="#333")

    def on_style_change(self):
        if self.selected_box_index < 0:
            return
        box = self.text_boxes[self.selected_box_index]
        box.bold = self.bold_var.get()
        box.italic = self.italic_var.get()
        box.align = self.align_var.get()
        self.refresh_canvas()

    def toggle_bold(self):
        self.bold_var.set(not self.bold_var.get())
        self.update_style_buttons()
        self.on_style_change()

    def toggle_italic(self):
        self.italic_var.set(not self.italic_var.get())
        self.update_style_buttons()
        self.on_style_change()

    def choose_color(self):
        if self.selected_box_index < 0:
            return
        box = self.text_boxes[self.selected_box_index]
        color = colorchooser.askcolor(color=box.font_color, title="选择文字颜色")
        if color[1]:
            box.font_color = color[1]
            self.color_btn.config(bg=color[1])
            self.refresh_canvas()

    # ==================== 其他操作 ====================

    def toggle_draw_mode(self):
        self.draw_mode = self.draw_mode_var.get()
        if self.draw_mode:
            self.canvas.config(cursor="crosshair")
        else:
            self.canvas.config(cursor="")

    def switch_preview_mode(self):
        self.current_preview_mode = self.preview_mode_var.get()
        self.refresh_canvas()

    def refresh_ppt_preview(self):
        self.preview_mode_var.set("ppt")
        self.current_preview_mode = "ppt"
        self.refresh_canvas()
        self.update_status("PPT预览已刷新 ✓")

    def show_inline_text_editor(self, box_idx):
        """内联文字编辑器"""
        if box_idx < 0 or box_idx >= len(self.text_boxes):
            return

        box = self.text_boxes[box_idx]

        edit_window = tk.Toplevel(self.root)
        edit_window.title(f"编辑文本框 {box_idx + 1}")
        edit_window.geometry("420x300")
        edit_window.configure(bg="#ffffff")
        edit_window.transient(self.root)
        edit_window.grab_set()

        mouse_x = self.root.winfo_pointerx()
        mouse_y = self.root.winfo_pointery()
        edit_window.geometry(f"+{mouse_x - 210}+{mouse_y - 150}")

        # 文字输入
        tk.Label(edit_window, text="文字内容", bg="#ffffff",
                fg="#333333", font=("微软雅黑", 9, "bold")).pack(anchor="w", padx=15, pady=(15, 5))

        text_input = tk.Text(edit_window, height=4, bg="#f5f5f5",
                            font=("微软雅黑", 11), relief=tk.GROOVE, bd=1, wrap=tk.WORD)
        text_input.pack(fill=tk.X, padx=15, pady=5)
        text_input.insert("1.0", box.text)
        text_input.focus_set()
        text_input.tag_add("sel", "1.0", "end")

        # 快捷设置
        quick_frame = tk.Frame(edit_window, bg="#ffffff")
        quick_frame.pack(fill=tk.X, padx=15, pady=10)

        tk.Label(quick_frame, text="字号:", bg="#ffffff", font=("微软雅黑", 9)).pack(side=tk.LEFT)
        font_size_var = tk.StringVar(value=str(box.font_size))
        ttk.Combobox(quick_frame, textvariable=font_size_var, width=5,
                    values=["8", "10", "12", "14", "16", "18", "20", "24", "28", "32", "36", "48", "60", "72", "80", "100", "120", "150", "200"]).pack(side=tk.LEFT, padx=5)

        tk.Label(quick_frame, text="对齐:", bg="#ffffff", font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=(15, 0))
        align_var = tk.StringVar(value=box.align)
        for val, txt in [("left", "左"), ("center", "中"), ("right", "右")]:
            tk.Radiobutton(quick_frame, text=txt, variable=align_var, value=val,
                          bg="#ffffff", font=("微软雅黑", 9)).pack(side=tk.LEFT)

        # 样式
        style_frame = tk.Frame(edit_window, bg="#ffffff")
        style_frame.pack(fill=tk.X, padx=15, pady=5)

        bold_var = tk.BooleanVar(value=box.bold)
        tk.Checkbutton(style_frame, text="加粗", variable=bold_var,
                      bg="#ffffff", font=("微软雅黑", 9)).pack(side=tk.LEFT)

        color_var = tk.StringVar(value=box.font_color)
        color_btn = tk.Button(style_frame, text="颜色", bg=box.font_color, width=6,
                             command=lambda: self._pick_color_for_editor(color_btn, color_var))
        color_btn.pack(side=tk.LEFT, padx=10)

        def auto_calc():
            text = text_input.get("1.0", tk.END).strip()
            if text:
                font_size_var.set(
                    str(
                        fit_font_size_pt(
                            text,
                            box.width,
                            box.height,
                            editor=self,
                            font_name=getattr(box, "font_name", None),
                        )
                    )
                )

        tk.Button(style_frame, text="自动字号", command=auto_calc,
                 bg="#9C27B0", fg="white", font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=10)

        # 按钮
        btn_frame = tk.Frame(edit_window, bg="#ffffff")
        btn_frame.pack(fill=tk.X, padx=15, pady=15)

        def save():
            box.text = text_input.get("1.0", tk.END).strip()
            try:
                box.font_size = int(font_size_var.get())
            except:
                pass
            box.align = align_var.get()
            box.bold = bold_var.get()
            box.font_color = color_var.get()
            edit_window.destroy()
            self.refresh_canvas()
            self.update_listbox()
            self.update_property_panel()

        tk.Button(btn_frame, text="确定", command=save,
                 bg="#4CAF50", fg="white", font=("微软雅黑", 10),
                 width=10, cursor="hand2").pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=edit_window.destroy,
                 bg="#9E9E9E", fg="white", font=("微软雅黑", 10),
                 width=10, cursor="hand2").pack(side=tk.LEFT, padx=5)

        edit_window.bind("<Control-Return>", lambda e: save())
        edit_window.bind("<Escape>", lambda e: edit_window.destroy())

    def _pick_color_for_editor(self, btn, color_var):
        color = colorchooser.askcolor(color=color_var.get(), title="选择颜色")
        if color[1]:
            color_var.set(color[1])
            btn.config(bg=color[1])

    # ==================== 撤销/重做 ====================

    # ==================== 撤销/重做系统（增强版）====================

    def save_state(self, operation_type="textboxes", extra_data=None):
        return history_core.save_state(self, operation_type=operation_type, extra_data=extra_data)

    def undo(self):
        return history_core.undo(self)

    def redo(self):
        return history_core.redo(self)

    def _restore_state(self, state):
        return history_core.restore_state(self, state)

    # ==================== 框操作 ====================

    def delete_selected_box(self):
        indices: list[int] = []
        if self.selected_boxes:
            indices.extend(self.selected_boxes)
        if self.selected_box_index >= 0:
            indices.append(self.selected_box_index)

        indices = sorted({i for i in indices if 0 <= i < len(self.text_boxes)})
        if not indices:
            return

        self.save_state()
        for idx in sorted(indices, reverse=True):
            del self.text_boxes[idx]

        deleted_n = len(indices)
        self.selected_box_index = -1
        self.selected_boxes = []
        self.refresh_canvas()
        self.update_listbox()
        self.mark_unsaved()
        self.update_status(f"\u5df2\u5220\u9664 {deleted_n} \u4e2a\u6846 \u2713")

    def clear_all_boxes(self):
        if messagebox.askyesno("确认", "确定清空所有文本框？"):
            self.save_state()
            self.text_boxes = []
            self.selected_box_index = -1
            self.selected_boxes = []
            self.refresh_canvas()
            self.update_listbox()

    def auto_font_size(self):
        if self.selected_box_index < 0:
            return
        box = self.text_boxes[self.selected_box_index]
        if not box.text:
            return
        box.font_size = fit_font_size_pt(
            box.text,
            box.width,
            box.height,
            editor=self,
            font_name=getattr(box, "font_name", None),
        )
        self.fontsize_var.set(str(box.font_size))
        self.refresh_canvas()

    def auto_font_size_all(self):
        for box in self.text_boxes:
            if not box.text:
                continue
            box.font_size = fit_font_size_pt(
                box.text,
                box.width,
                box.height,
                editor=self,
                font_name=getattr(box, "font_name", None),
            )
        self.update_property_panel()
        self.refresh_canvas()
        self.update_status("已为当前页所有框计算字号 ✓")

    def align_boxes(self, align_type):
        if len(self.selected_boxes) < 2:
            self.update_status("请Ctrl+点击选中至少2个框")
            return

        self.save_state()
        boxes = [self.text_boxes[i] for i in self.selected_boxes]

        if align_type == "left":
            min_x = min(b.x for b in boxes)
            for b in boxes: b.x = min_x
        elif align_type == "right":
            max_right = max(b.x + b.width for b in boxes)
            for b in boxes: b.x = max_right - b.width
        elif align_type == "center_h":
            avg = sum(b.x + b.width / 2 for b in boxes) / len(boxes)
            for b in boxes: b.x = int(avg - b.width / 2)
        elif align_type == "top":
            min_y = min(b.y for b in boxes)
            for b in boxes: b.y = min_y
        elif align_type == "bottom":
            max_bottom = max(b.y + b.height for b in boxes)
            for b in boxes: b.y = max_bottom - b.height
        elif align_type == "center_v":
            avg = sum(b.y + b.height / 2 for b in boxes) / len(boxes)
            for b in boxes: b.y = int(avg - b.height / 2)

        self.refresh_canvas()
        self.update_status(f"已对齐 {len(self.selected_boxes)} 个框 ✓")

    def batch_offset(self, dx_dir, dy_dir):
        """批量位移选中的文本框

        Args:
            dx_dir: X方向（-1左, 0无, 1右）
            dy_dir: Y方向（-1上, 0无, 1下）
        """
        # 至少要有一个选中的框（包括主选中框）
        boxes_to_move = []
        if self.selected_boxes:
            boxes_to_move = self.selected_boxes
        elif self.selected_box_index >= 0:
            boxes_to_move = [self.selected_box_index]

        if not boxes_to_move:
            self.update_status("请先选中至少一个文本框")
            return

        # 获取像素值
        try:
            pixels = int(self.offset_px_var.get())
            if pixels <= 0:
                self.update_status("像素值必须大于0")
                return
        except ValueError:
            self.update_status("请输入有效的像素数值")
            return

        # 保存状态用于撤销
        self.save_state()

        # 计算实际偏移量
        dx = dx_dir * pixels
        dy = dy_dir * pixels

        # 移动所有选中的框
        for idx in boxes_to_move:
            if 0 <= idx < len(self.text_boxes):
                box = self.text_boxes[idx]
                box.x = max(0, box.x + dx)  # 不能移出边界
                box.y = max(0, box.y + dy)

        # 更新界面
        self.refresh_canvas()
        self.update_property_panel()
        self.mark_unsaved()

        # 提示信息
        direction = ""
        if dx_dir == -1:
            direction = "左"
        elif dx_dir == 1:
            direction = "右"
        elif dy_dir == -1:
            direction = "上"
        elif dy_dir == 1:
            direction = "下"

        self.update_status(f"已将 {len(boxes_to_move)} 个框向{direction}移动 {pixels} 像素 ✓")

    def apply_style_to_selected(self):
        if len(self.selected_boxes) < 1:
            self.update_status("请先Ctrl+点击选中框")
            return

        any_selected = (self.apply_fontsize_var.get() or self.apply_fontname_var.get() or
                       self.apply_color_var.get() or self.apply_bold_var.get() or
                       self.apply_italic_var.get() or self.apply_align_var.get())

        if not any_selected:
            self.update_status("请先勾选要应用的属性")
            return

        self.save_state()

        try:
            font_size = int(self.fontsize_var.get())
        except:
            font_size = 16

        for idx in self.selected_boxes:
            if 0 <= idx < len(self.text_boxes):
                box = self.text_boxes[idx]
                if self.apply_fontsize_var.get(): box.font_size = font_size
                if self.apply_fontname_var.get(): box.font_name = self.fontname_var.get()
                if self.apply_bold_var.get(): box.bold = self.bold_var.get()
                if self.apply_italic_var.get(): box.italic = self.italic_var.get()
                if self.apply_align_var.get(): box.align = self.align_var.get()
                if self.apply_color_var.get(): box.font_color = self.color_btn.cget("bg")

        self.refresh_canvas()
        self.update_status(f"已应用样式到 {len(self.selected_boxes)} 个框 ✓")

    # ==================== OCR ====================

    def _prepare_image_for_ocr(self, img_path, edit_scale=1.0):
        """准备OCR用的图片，如果图片过大则缩放"""
        MAX_SIDE = 3000  # 最大边长限制

        img = Image.open(img_path)
        w, h = img.size

        # 先应用编辑缩放
        if edit_scale < 1.0:
            w = int(w * edit_scale)
            h = int(h * edit_scale)
            img = img.resize((w, h), Image.Resampling.LANCZOS)

        # 如果还是太大，再缩放
        if max(w, h) <= MAX_SIDE:
            # 保存到临时文件
            temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            temp_path = temp_file.name
            temp_file.close()
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            img.save(temp_path, quality=95)
            return temp_path, 1.0

        # 计算额外缩放比例
        extra_scale = MAX_SIDE / max(w, h)
        new_w = int(w * extra_scale)
        new_h = int(h * extra_scale)

        # 缩放图片
        resized_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 保存到临时文件
        temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        temp_path = temp_file.name
        temp_file.close()

        if resized_img.mode == 'RGBA':
            resized_img = resized_img.convert('RGB')
        resized_img.save(temp_path, quality=95)

        return temp_path, extra_scale

    def auto_detect_text_regions(self):
        if not self.original_image:
            self.update_status("请先加载图片")
            return
        if not self.ocr:
            self.update_status("OCR模型未加载")
            return

        if self.text_boxes:
            result = messagebox.askyesnocancel("提示", "是否清空现有框？\n是-清空  否-追加  取消-取消")
            if result is None:
                return
            elif result:
                self.text_boxes = []

        self.update_status("正在检测...")

        def detect():
            try:
                # 直接使用当前编辑图片，完全不缩放，保证坐标100%准确
                # PIL Image转为OpenCV格式
                img = np.array(self.original_image)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                img_h, img_w = img.shape[:2]

                # 保存临时文件用于OCR（不缩放！）
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                temp_path = temp_file.name
                temp_file.close()
                cv2.imwrite(temp_path, img)

                result = self.ocr.predict(temp_path)

                # 删除临时文件
                try:
                    os.remove(temp_path)
                except:
                    pass

                # 新版 PaddleOCR 返回 list，取第一个结果
                if not result or len(result) == 0:
                    self.root.after(0, lambda: self.update_status("未检测到文字"))
                    return

                ocr_result = result[0]
                dp = ocr_result.get("doc_preprocessor_res")
                dp_angle = None
                try:
                    dp_angle = dp.get("angle") if dp else None
                except Exception:
                    dp_angle = None
                dt_polys = ocr_result.get('dt_polys', [])
                rec_texts = ocr_result.get('rec_texts', [])

                if not dt_polys:
                    self.root.after(0, lambda: self.update_status("未检测到文字"))
                    return

                new_boxes = []
                for i, poly in enumerate(dt_polys):
                    x_coords = [p[0] for p in poly]
                    y_coords = [p[1] for p in poly]

                    # 完全使用OCR原始坐标，不做任何调整
                    x = int(min(x_coords))
                    y = int(min(y_coords))
                    w = int(max(x_coords) - min(x_coords))
                    h = int(max(y_coords) - min(y_coords))

                    if w < 10 or h < 10:
                        continue

                    box = TextBox(max(0, x), max(0, y), w, h)
                    if i < len(rec_texts):
                        box.text = rec_texts[i]
                    if box.text:
                        box.font_size = fit_font_size_pt(
                            box.text,
                            w,
                            h,
                            editor=self,
                            font_name=getattr(box, "font_name", None),
                        )
                    new_boxes.append(box)

                new_boxes.sort(key=lambda b: (b.y // 30, b.x))
                self.text_boxes.extend(new_boxes)

                self.root.after(0, self.refresh_canvas)
                self.root.after(0, self.update_listbox)
                if dp_angle not in (None, 0):
                    self.root.after(
                        0,
                        lambda a=dp_angle, n=len(new_boxes): self.update_status(
                            f"检测到 {n} 个文字区域（提示：OCR 文档预处理旋转了图片 {a}°，如叠框偏移可在配置关闭相关预处理）"
                        ),
                    )
                else:
                    self.root.after(0, lambda n=len(new_boxes): self.update_status(f"检测到 {n} 个文字区域"))

            except Exception as e:
                err_text = str(e)
                self.root.after(0, lambda t=err_text: self.update_status(f"检测失败: {t}"))

        threading.Thread(target=detect, daemon=True).start()

    def ocr_all_boxes(self):
        return ocr_core.ocr_all_boxes(self)

    def ocr_single_box(self):
        return ocr_core.ocr_single_box(self)

    # ==================== 批量操作 ====================

    def auto_detect_all_pages(self):
        if not self.pages or not self.ocr:
            self.update_status("请先导入图片")
            return

        self.save_current_page()

        def detect_all():
            total = len(self.pages)
            for i, page in enumerate(self.pages):
                self.root.after(0, lambda idx=i: self.update_status(f"检测第 {idx+1}/{total} 页..."))

                try:
                    # 直接使用该页的编辑图片，完全不缩放
                    page_img = page["image"]
                    img = np.array(page_img)
                    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                    # 保存临时文件（不缩放！）
                    temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    temp_path = temp_file.name
                    temp_file.close()
                    cv2.imwrite(temp_path, img)

                    result = self.ocr.predict(temp_path)

                    # 删除临时文件
                    try:
                        os.remove(temp_path)
                    except:
                        pass

                    if not result or len(result) == 0:
                        continue

                    ocr_result = result[0]
                    dt_polys = ocr_result.get('dt_polys', [])
                    rec_texts = ocr_result.get('rec_texts', [])

                    if not dt_polys:
                        continue

                    new_boxes = []
                    for j, poly in enumerate(dt_polys):
                        x_coords = [p[0] for p in poly]
                        y_coords = [p[1] for p in poly]

                        # 完全使用OCR原始坐标，不做任何调整
                        x = int(min(x_coords))
                        y = int(min(y_coords))
                        w = int(max(x_coords) - min(x_coords))
                        h = int(max(y_coords) - min(y_coords))

                        if w < 10 or h < 10:
                            continue

                        box_data = {
                            "x": max(0, x), "y": max(0, y), "width": w, "height": h,
                            "text": rec_texts[j] if j < len(rec_texts) else "",
                            "font_size": 16, "font_name": "微软雅黑", "font_color": "#000000",
                            "bold": False, "italic": False, "align": "left"
                        }

                        if box_data["text"]:
                            box_data["font_size"] = fit_font_size_pt(
                                box_data["text"],
                                w,
                                h,
                                editor=self,
                                font_name=box_data.get("font_name"),
                            )

                        new_boxes.append(box_data)

                    new_boxes.sort(key=lambda b: (b["y"] // 30, b["x"]))
                    page["text_boxes"] = new_boxes

                except Exception as e:
                    print(f"第 {i+1} 页检测失败: {e}")

            self.root.after(0, self.load_current_page)
            self.root.after(0, lambda: self.update_status(f"全部检测完成！共 {total} 页 ✓"))

        threading.Thread(target=detect_all, daemon=True).start()

    def ocr_all_pages(self):
        if not self.pages or not self.ocr:
            return

        self.save_current_page()

        def ocr_all():
            total = len(self.pages)
            for i, page in enumerate(self.pages):
                self.root.after(0, lambda idx=i: self.update_status(f"识别第 {idx+1}/{total} 页..."))

                boxes = page.get("text_boxes", [])
                if not boxes:
                    continue

                # 使用该页的编辑图片
                page_img = page["image"]
                img = np.array(page_img)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                img_h, img_w = img.shape[:2]

                for box_data in boxes:
                    if box_data.get("text"):
                        continue

                    x, y, w, h = box_data["x"], box_data["y"], box_data["width"], box_data["height"]
                    expand_h, expand_w = int(h * 0.3), int(w * 0.1)

                    crop_x = max(0, x - expand_w)
                    crop_y = max(0, y - expand_h)
                    crop_x2 = min(x + w + expand_w, img_w)
                    crop_y2 = min(y + h + expand_h, img_h)

                    cropped = img[crop_y:crop_y2, crop_x:crop_x2]

                    temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    temp_path = temp_file.name
                    temp_file.close()
                    cv2.imwrite(temp_path, cropped)

                    try:
                        result = self.ocr.predict(temp_path)
                        os.remove(temp_path)

                        if result and len(result) > 0:
                            ocr_result = result[0]
                            rec_texts = ocr_result.get('rec_texts', [])
                            if rec_texts:
                                box_data["text"] = ''.join(rec_texts)
                                if box_data["text"]:
                                    box_data["font_size"] = fit_font_size_pt(
                                        box_data["text"],
                                        w,
                                        h,
                                        editor=self,
                                        font_name=box_data.get("font_name"),
                                    )
                    except:
                        try:
                            os.remove(temp_path)
                        except:
                            pass

            self.root.after(0, self.load_current_page)
            self.root.after(0, lambda: self.update_status(f"全部识别完成！共 {total} 页 ✓"))

        threading.Thread(target=ocr_all, daemon=True).start()

    def auto_font_size_all_pages(self):
        if not self.pages:
            return

        self.save_current_page()

        for page in self.pages:
            for box_data in page.get("text_boxes", []):
                if not box_data.get("text"):
                    continue
                h, w = box_data["height"], box_data["width"]
                box_data["font_size"] = fit_font_size_pt(
                    box_data["text"],
                    w,
                    h,
                    editor=self,
                    font_name=box_data.get("font_name"),
                )

        self.load_current_page()
        self.update_status(f"全部 {len(self.pages)} 页字号已调整 ✓")

    # ==================== 项目保存/加载 ====================

    def save_project(self):
        return project_feature.save_project(self)

    def load_project(self):
        return project_feature.load_project(self)

    # ==================== PPT生成 ====================

    def generate_multi_page_ppt(self):
        return export_feature.generate_multi_page_ppt(self)

    # ==================== 设置对话框 ====================

    def show_settings_dialog(self):
        """显示设置对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("设置")
        dialog.geometry("680x820")  # 增加高度以容纳IOPaint配置
        dialog.configure(bg=COLOR_WHITE)
        dialog.transient(self.root)
        dialog.grab_set()

        # 居中显示
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 680) // 2
        y = (dialog.winfo_screenheight() - 820) // 2
        dialog.geometry(f"+{x}+{y}")

        # 标题
        title_frame = tk.Frame(dialog, bg=COLOR_THEME, height=40)
        title_frame.pack(fill=tk.X, side=tk.TOP)
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="  OCR模型设置", bg=COLOR_THEME, fg="white",
                font=(FONT_FAMILY, 12, "bold")).pack(side=tk.LEFT, pady=8)

        # 按钮区 - 固定在底部
        btn_frame = tk.Frame(dialog, bg=COLOR_WHITE, pady=15)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Button(btn_frame, text="保存并加载OCR", command=lambda: self._save_settings(dialog),
                 bg=COLOR_GREEN, fg="white", font=(FONT_FAMILY, 11, "bold"),
                 padx=30, pady=8, cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=20)

        tk.Button(btn_frame, text="取消", command=dialog.destroy,
                 bg="#9E9E9E", fg="white", font=(FONT_FAMILY, 11),
                 padx=30, pady=8, cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT)

        # 分隔线
        tk.Frame(dialog, bg="#ddd", height=1).pack(fill=tk.X, side=tk.BOTTOM)

        # 可滚动内容区 - 放在中间
        content_container = tk.Frame(dialog, bg=COLOR_WHITE)
        content_container.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        canvas = tk.Canvas(content_container, bg=COLOR_WHITE, highlightthickness=0)
        scrollbar = tk.Scrollbar(content_container, orient=tk.VERTICAL, command=canvas.yview)

        content = tk.Frame(canvas, bg=COLOR_WHITE, padx=20, pady=15)

        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        canvas_window = canvas.create_window((0, 0), window=content, anchor=tk.NW)

        # 更新滚动区域
        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        content.bind("<Configure>", on_frame_configure)

        # 调整canvas窗口宽度
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", on_canvas_configure)

        # 鼠标滚轮支持
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)

        # === 方式1: 指定已有模型目录 ===
        tk.Label(content, text="方式1: 指定已有模型目录", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        tk.Label(content, text="如果已有模型文件，直接选择模型所在目录",
                bg=COLOR_WHITE, fg="#666", font=(FONT_FAMILY, 9)).pack(anchor="w", pady=(0, 5))

        path_frame = tk.Frame(content, bg=COLOR_WHITE)
        path_frame.pack(fill=tk.X, pady=5)

        self.model_dir_var = tk.StringVar(value=self.config.get("model_dir", ""))
        path_entry = tk.Entry(path_frame, textvariable=self.model_dir_var,
                             font=(FONT_FAMILY, 10), width=45)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        browse_btn = tk.Button(path_frame, text="浏览...", command=self._browse_model_dir,
                              bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 9),
                              padx=10, cursor="hand2", relief=tk.FLAT)
        browse_btn.pack(side=tk.LEFT, padx=(10, 0))

        # === 方式2: 下载模型到指定目录 ===
        tk.Frame(content, bg="#ddd", height=1).pack(fill=tk.X, pady=15)

        tk.Label(content, text="方式2: 下载模型到指定目录", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        tk.Label(content, text="如果没有模型，选择一个目录后点击下载（需要联网，约200MB）",
                bg=COLOR_WHITE, fg="#666", font=(FONT_FAMILY, 9)).pack(anchor="w", pady=(0, 5))

        download_frame = tk.Frame(content, bg=COLOR_WHITE)
        download_frame.pack(fill=tk.X, pady=5)

        self.download_dir_var = tk.StringVar(value=os.path.join(get_base_dir(), ".paddlex", "official_models"))
        download_entry = tk.Entry(download_frame, textvariable=self.download_dir_var,
                                 font=(FONT_FAMILY, 10), width=45)
        download_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        browse_download_btn = tk.Button(download_frame, text="浏览...",
                                       command=lambda: self._browse_download_dir(),
                                       bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 9),
                                       padx=10, cursor="hand2", relief=tk.FLAT)
        browse_download_btn.pack(side=tk.LEFT, padx=(10, 0))

        # 下载按钮和进度
        download_btn_frame = tk.Frame(content, bg=COLOR_WHITE)
        download_btn_frame.pack(fill=tk.X, pady=10)

        self.download_btn = tk.Button(download_btn_frame, text="下载模型",
                                     command=lambda: self._download_models(dialog),
                                     bg=COLOR_ORANGE, fg="white", font=(FONT_FAMILY, 10, "bold"),
                                     padx=20, pady=5, cursor="hand2", relief=tk.FLAT)
        self.download_btn.pack(side=tk.LEFT)

        self.download_status_label = tk.Label(download_btn_frame, text="", bg=COLOR_WHITE,
                                             fg="#666", font=(FONT_FAMILY, 9))
        self.download_status_label.pack(side=tk.LEFT, padx=15)

        # 进度条
        progress_frame = tk.Frame(content, bg=COLOR_WHITE)
        progress_frame.pack(fill=tk.X, pady=5)

        self.download_progress = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.download_progress.pack(fill=tk.X)

        self.download_detail_label = tk.Label(progress_frame, text="", bg=COLOR_WHITE,
                                              fg="#999", font=(FONT_FAMILY, 8))
        self.download_detail_label.pack(anchor="w")

        # === 设备选择 ===
        tk.Frame(content, bg="#ddd", height=1).pack(fill=tk.X, pady=15)

        tk.Label(content, text="设备选择", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        tk.Label(content, text="选择OCR运行的设备（GPU需要安装PaddlePaddle-GPU版本）",
                bg=COLOR_WHITE, fg="#666", font=(FONT_FAMILY, 9)).pack(anchor="w", pady=(0, 5))

        device_frame = tk.Frame(content, bg=COLOR_WHITE)
        device_frame.pack(fill=tk.X, pady=5)

        self.device_var = tk.StringVar(value=self.config.get("ocr_device", "cpu"))

        tk.Radiobutton(device_frame, text="CPU - 兼容性好，适合所有电脑",
                      variable=self.device_var, value="cpu",
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 10)).pack(anchor="w", pady=3)
        tk.Radiobutton(device_frame, text="GPU - 速度快，需要NVIDIA显卡",
                      variable=self.device_var, value="gpu",
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 10)).pack(anchor="w", pady=3)

        # 提示信息
        tk.Label(device_frame,
                text="提示：使用GPU需要先安装 paddlepaddle-gpu\n如未安装，请运行：pip uninstall paddlepaddle && pip install paddlepaddle-gpu",
                bg=COLOR_WHITE, fg="#999", font=(FONT_FAMILY, 8), justify=tk.LEFT).pack(anchor="w", pady=(5, 0))

        # === IOPaint API 配置 ===
        tk.Frame(content, bg="#ddd", height=1).pack(fill=tk.X, pady=15)

        tk.Label(content, text="IOPaint API 配置（背景生成功能）", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        tk.Label(content, text="用于自动去除文字区域，生成干净的背景图",
                bg=COLOR_WHITE, fg="#666", font=(FONT_FAMILY, 9)).pack(anchor="w", pady=(0, 5))

        # 启用开关
        inpaint_switch_frame = tk.Frame(content, bg=COLOR_WHITE)
        inpaint_switch_frame.pack(fill=tk.X, pady=5)

        self.inpaint_enabled_var = tk.BooleanVar(value=self.config.get("inpaint_enabled", True))
        tk.Checkbutton(inpaint_switch_frame, text="启用背景生成功能",
                      variable=self.inpaint_enabled_var,
                      bg=COLOR_WHITE, font=(FONT_FAMILY, 10)).pack(anchor="w")

        # API地址配置
        api_frame = tk.Frame(content, bg=COLOR_WHITE)
        api_frame.pack(fill=tk.X, pady=5)

        tk.Label(api_frame, text="API地址:", bg=COLOR_WHITE, font=(FONT_FAMILY, 9)).pack(anchor="w")
        self.inpaint_api_var = tk.StringVar(value=self.config.get("inpaint_api_url", "http://127.0.0.1:8080/api/v1/inpaint"))
        api_entry = tk.Entry(api_frame, textvariable=self.inpaint_api_var,
                            font=(FONT_FAMILY, 10), width=50)
        api_entry.pack(fill=tk.X, pady=3)

        # 测试按钮
        test_btn_frame = tk.Frame(content, bg=COLOR_WHITE)
        test_btn_frame.pack(fill=tk.X, pady=5)

        tk.Button(test_btn_frame, text="测试连接", command=self._test_inpaint_api,
                 bg="#00897B", fg="white", font=(FONT_FAMILY, 9),
                 padx=15, pady=3, cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT)

        self.api_test_label = tk.Label(test_btn_frame, text="", bg=COLOR_WHITE,
                                       fg="#666", font=(FONT_FAMILY, 9))
        self.api_test_label.pack(side=tk.LEFT, padx=10)

        # 说明信息
        info_frame = tk.Frame(content, bg="#fff3cd", padx=10, pady=8)
        info_frame.pack(fill=tk.X, pady=5)

        tk.Label(info_frame, text="📌 使用说明", bg="#fff3cd",
                font=(FONT_FAMILY, 9, "bold"), fg="#856404").pack(anchor="w")
        tk.Label(info_frame,
                text="1. 安装IOPaint：pip install iopaint\n"
                     "2. 启动服务：iopaint start --host 127.0.0.1 --port 8080\n"
                     "3. 或使用在线服务（修改API地址）\n"
                     "4. 使用前请先测试连接",
                bg="#fff3cd", fg="#856404", font=(FONT_FAMILY, 8),
                justify=tk.LEFT).pack(anchor="w", pady=(3, 0))

        # 模型状态显示
        tk.Frame(content, bg="#ddd", height=1).pack(fill=tk.X, pady=10)

        status_frame = tk.Frame(content, bg="#f5f5f5", padx=10, pady=10)
        status_frame.pack(fill=tk.X)

        self.model_status_label = tk.Label(status_frame, text="", bg="#f5f5f5",
                                           font=(FONT_FAMILY, 9), justify=tk.LEFT)
        self.model_status_label.pack(anchor="w")

        self._check_model_status()

        # 绑定路径变化事件
        self.model_dir_var.trace_add("write", lambda *args: self._check_model_status())

    def _browse_model_dir(self):
        """浏览选择模型目录"""
        current_dir = self.model_dir_var.get()
        if not os.path.exists(current_dir):
            current_dir = get_base_dir()

        dir_path = filedialog.askdirectory(
            title="选择OCR模型目录（包含 PP-OCRv5_server_det 等文件夹）",
            initialdir=current_dir
        )
        if dir_path:
            self.model_dir_var.set(dir_path)

    def _browse_download_dir(self):
        """浏览选择下载目录"""
        current_dir = self.download_dir_var.get()
        if not os.path.exists(current_dir):
            current_dir = get_base_dir()

        dir_path = filedialog.askdirectory(
            title="选择模型下载目录",
            initialdir=current_dir
        )
        if dir_path:
            self.download_dir_var.set(dir_path)

    def _download_models(self, dialog):
        """下载OCR模型 - 使用直接URL下载"""
        download_dir = self.download_dir_var.get()

        if not download_dir:
            messagebox.showwarning("警告", "请先选择下载目录！")
            return

        # 创建目录
        os.makedirs(download_dir, exist_ok=True)

        # 禁用下载按钮
        self.download_btn.config(state=tk.DISABLED, text="下载中...")
        self.download_status_label.config(text="正在准备下载...")
        self.download_progress['value'] = 0

        # 需要下载的模型列表
        models_to_download = [
            ("PP-OCRv5_server_det", "文字检测模型", "PP-OCRv5_server_det_infer.tar"),
            ("PP-OCRv5_server_rec", "文字识别模型", "PP-OCRv5_server_rec_infer.tar"),
            ("PP-LCNet_x1_0_doc_ori", "文档方向分类", "PP-LCNet_x1_0_doc_ori_infer.tar"),
            ("PP-LCNet_x1_0_textline_ori", "文本行方向", "PP-LCNet_x1_0_textline_ori_infer.tar"),
            ("UVDoc", "文档矫正", "UVDoc_infer.tar"),
        ]

        base_url = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0"

        def download_task():
            import urllib.request
            import tarfile

            total_models = len(models_to_download)
            downloaded = 0

            for model_name, desc, tar_file in models_to_download:
                model_path = os.path.join(download_dir, model_name)

                # 如果模型已存在，跳过
                if os.path.exists(model_path):
                    downloaded += 1
                    progress = int((downloaded / total_models) * 100)
                    dialog.after(0, lambda p=progress, d=desc: self._update_download_progress(p, f"{d} 已存在，跳过"))
                    continue

                url = f"{base_url}/{tar_file}"
                tar_path = os.path.join(download_dir, tar_file)

                try:
                    # 更新状态
                    dialog.after(0, lambda d=desc: self.download_status_label.config(text=f"正在下载: {d}"))
                    dialog.after(0, lambda d=desc: self.download_detail_label.config(text=f"从 {url}"))

                    # 下载文件（带进度）
                    def reporthook(block_num, block_size, total_size):
                        if total_size > 0:
                            downloaded_size = block_num * block_size
                            percent = min(int((downloaded_size / total_size) * 100), 100)
                            size_mb = downloaded_size / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            # 计算总进度
                            model_progress = downloaded / total_models
                            file_progress = (downloaded_size / total_size) / total_models
                            overall = int((model_progress + file_progress) * 100)
                            dialog.after(0, lambda o=overall, s=size_mb, t=total_mb:
                                self._update_download_progress(o, f"下载中: {s:.1f}MB / {t:.1f}MB"))

                    urllib.request.urlretrieve(url, tar_path, reporthook)

                    # 解压
                    dialog.after(0, lambda d=desc: self.download_status_label.config(text=f"正在解压: {d}"))

                    with tarfile.open(tar_path, 'r:*') as tar:
                        tar.extractall(download_dir)

                    # 删除tar文件
                    os.remove(tar_path)

                    # 重命名文件夹（去掉_infer后缀）
                    infer_path = os.path.join(download_dir, f"{model_name}_infer")
                    if os.path.exists(infer_path) and not os.path.exists(model_path):
                        os.rename(infer_path, model_path)

                    downloaded += 1
                    progress = int((downloaded / total_models) * 100)
                    dialog.after(0, lambda p=progress, d=desc: self._update_download_progress(p, f"{d} 下载完成"))

                except Exception as e:
                    dialog.after(0, lambda d=desc, err=str(e):
                        self.download_status_label.config(text=f"{d} 下载失败: {err[:50]}"))
                    # 清理可能的残留文件
                    if os.path.exists(tar_path):
                        try:
                            os.remove(tar_path)
                        except:
                            pass

            # 下载完成
            dialog.after(0, lambda: self._download_complete(download_dir, dialog))

        threading.Thread(target=download_task, daemon=True).start()

    def _update_download_progress(self, progress, detail):
        """更新下载进度"""
        self.download_progress['value'] = progress
        self.download_detail_label.config(text=detail)

    def _download_complete(self, download_dir, dialog):
        """下载完成处理"""
        self.download_btn.config(state=tk.NORMAL, text="下载模型")
        self.download_progress['value'] = 100
        self.download_status_label.config(text="下载完成！")
        self.download_detail_label.config(text="")

        # 设置模型目录
        self.model_dir_var.set(download_dir)
        self._check_model_status()

        messagebox.showinfo("成功",
            f"模型下载完成！\n\n下载目录:\n{download_dir}\n\n已自动设置为模型目录，点击'保存并加载OCR'即可使用。")

    def _check_model_status(self):
        """检查模型状态"""
        model_dir = self.model_dir_var.get()

        required_models = [
            ("PP-OCRv5_server_det", "文字检测模型"),
            ("PP-OCRv5_server_rec", "文字识别模型"),
        ]
        optional_models = [
            ("PP-LCNet_x1_0_doc_ori", "文档方向分类"),
            ("PP-LCNet_x1_0_textline_ori", "文本行方向"),
            ("UVDoc", "文档矫正"),
        ]

        status_lines = []

        if not model_dir:
            status_lines.append("请选择或下载模型目录")
        elif not os.path.exists(model_dir):
            status_lines.append("目录不存在，请选择有效目录或下载模型")
        else:
            all_required = True
            for model_name, desc in required_models:
                model_path = os.path.join(model_dir, model_name)
                if os.path.exists(model_path):
                    status_lines.append(f"[OK] {desc} ({model_name})")
                else:
                    status_lines.append(f"[X] {desc} ({model_name}) - 缺失!")
                    all_required = False

            for model_name, desc in optional_models:
                model_path = os.path.join(model_dir, model_name)
                if os.path.exists(model_path):
                    status_lines.append(f"[OK] {desc} ({model_name})")
                else:
                    status_lines.append(f"[  ] {desc} ({model_name}) - 可选")

            if all_required:
                status_lines.insert(0, "当前模型状态: 可用\n")
            else:
                status_lines.insert(0, "当前模型状态: 缺少必需模型!\n")

        self.model_status_label.config(text="\n".join(status_lines))

    def _test_inpaint_api(self):
        """测试IOPaint API连接"""
        api_url = self.inpaint_api_var.get()

        if not api_url:
            self.api_test_label.config(text="❌ 请输入API地址", fg="red")
            return

        self.api_test_label.config(text="⏳ 测试中...", fg="blue")

        def test():
            try:
                # 创建一个小的测试图片和蒙版
                test_img = Image.new("RGB", (64, 64), (255, 255, 255))
                test_mask = Image.new("L", (64, 64), 0)

                # Base64编码
                def to_b64(img):
                    buffer = BytesIO()
                    img.save(buffer, "PNG")
                    return base64.b64encode(buffer.getvalue()).decode()

                payload = {
                    "image": to_b64(test_img),
                    "mask": to_b64(test_mask),
                    "ldm_steps": 1,
                    "hd_strategy": "Original"
                }

                response = requests.post(api_url, json=payload, timeout=10)

                if response.status_code == 200:
                    self.root.after(0, lambda: self.api_test_label.config(
                        text="✓ 连接成功！", fg="green"))
                else:
                    self.root.after(0, lambda: self.api_test_label.config(
                        text=f"❌ 错误: {response.status_code}", fg="red"))

            except requests.exceptions.ConnectionError:
                self.root.after(0, lambda: self.api_test_label.config(
                    text="❌ 无法连接，请检查服务是否启动", fg="red"))
            except Exception as e:
                self.root.after(0, lambda: self.api_test_label.config(
                    text=f"❌ 测试失败: {str(e)[:30]}", fg="red"))

        threading.Thread(target=test, daemon=True).start()

    def _save_settings(self, dialog):
        """保存设置并重新加载OCR"""
        new_model_dir = self.model_dir_var.get()
        new_device = self.device_var.get()  # 获取设备选择
        new_inpaint_enabled = self.inpaint_enabled_var.get()
        new_inpaint_api = self.inpaint_api_var.get()

        if not new_model_dir:
            messagebox.showwarning("警告", "请先选择模型目录！")
            return

        # 检查必需模型是否存在
        det_model = os.path.join(new_model_dir, "PP-OCRv5_server_det")
        rec_model = os.path.join(new_model_dir, "PP-OCRv5_server_rec")

        if not os.path.exists(det_model) or not os.path.exists(rec_model):
            result = messagebox.askyesno("警告",
                "模型目录缺少必需的模型文件！\n\n"
                "需要:\n- PP-OCRv5_server_det\n- PP-OCRv5_server_rec\n\n"
                "是否仍然保存？（OCR功能将无法使用）")
            if not result:
                return

        # 保存配置
        self.config["model_dir"] = new_model_dir
        self.config["ocr_device"] = new_device  # 保存设备选择
        self.config["inpaint_enabled"] = new_inpaint_enabled  # 保存IOPaint开关
        self.config["inpaint_api_url"] = new_inpaint_api  # 保存API地址
        save_config(self.config)

        # 关闭对话框
        dialog.destroy()

        # 重新加载OCR
        self.ocr = None
        device_name = "GPU" if new_device == "gpu" else "CPU"
        self.update_status(f"正在使用 {device_name} 加载OCR模型...")
        threading.Thread(target=self.init_ocr, daemon=True).start()

        messagebox.showinfo("成功",
            f"设置已保存！\n\n"
            f"OCR模型目录:\n{new_model_dir}\n\n"
            f"运行设备: {device_name}\n\n"
            f"背景生成功能: {'已启用' if new_inpaint_enabled else '已禁用'}\n"
            f"IOPaint API: {new_inpaint_api}\n\n"
            f"OCR模型正在后台加载...")



    # ==================== 新增功能：全选和复制粘贴 ====================

    def select_all_boxes(self):
        """全选当前页所有文本框"""
        if not self.text_boxes:
            self.update_status("当前页没有文本框")
            return

        # 选中所有框
        self.selected_boxes = list(range(len(self.text_boxes)))
        self.selected_box_index = 0 if self.text_boxes else -1

        # 刷新界面
        self.refresh_canvas()
        self.update_property_panel()

        # 更新列表框选择
        self.box_listbox.selection_clear(0, tk.END)
        for idx in self.selected_boxes:
            self.box_listbox.selection_set(idx)

        self.update_status(f"已选中当前页所有 {len(self.text_boxes)} 个文本框 ✓")

    def copy_boxes(self):
        """复制选中的文本框"""
        if not self.selected_boxes:
            self.update_status("请先选中要复制的文本框")
            return

        self.clipboard_boxes = []
        for idx in self.selected_boxes:
            if 0 <= idx < len(self.text_boxes):
                self.clipboard_boxes.append(self.text_boxes[idx].copy())

        self.update_status(f"已复制 {len(self.clipboard_boxes)} 个文本框")

    def paste_boxes(self):
        """粘贴文本框"""
        if not self.clipboard_boxes:
            self.update_status("剪贴板为空")
            return

        self.save_state()

        offset = 20
        new_boxes = []
        for box in self.clipboard_boxes:
            new_box = box.copy()
            new_box.x += offset
            new_box.y += offset
            self.text_boxes.append(new_box)
            new_boxes.append(new_box)

        start_idx = len(self.text_boxes) - len(new_boxes)
        self.selected_boxes = list(range(start_idx, len(self.text_boxes)))
        self.selected_box_index = self.selected_boxes[0] if self.selected_boxes else -1

        self.refresh_canvas()
        self.update_listbox()
        self.mark_unsaved()
        self.mark_unsaved()
        self.update_status(f"已粘贴 {len(new_boxes)} 个文本框")

    def move_box_by_key(self, dx, dy):
        """使用方向键移动文本框"""
        if self.selected_box_index < 0:
            return

        box = self.text_boxes[self.selected_box_index]
        box.x = max(0, box.x + dx)
        box.y = max(0, box.y + dy)

        self.refresh_canvas()
        self.update_property_panel()
        self.mark_unsaved()

    # ==================== 新增功能：完整对齐工具 ====================

    def show_align_dialog(self):
        """显示对齐工具对话框"""
        if len(self.selected_boxes) < 2:
            messagebox.showinfo("提示", "请先使用Ctrl+点击选中至少2个文本框")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("对齐与分布工具")
        dialog.geometry("450x550")
        dialog.configure(bg=COLOR_WHITE)
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 450) // 2
        y = (dialog.winfo_screenheight() - 550) // 2
        dialog.geometry(f"+{x}+{y}")

        title_frame = tk.Frame(dialog, bg=COLOR_THEME, height=40)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text=f"  对齐与分布 - 已选中 {len(self.selected_boxes)} 个框",
                bg=COLOR_THEME, fg="white",
                font=(FONT_FAMILY, 11, "bold")).pack(side=tk.LEFT, pady=8)

        content = tk.Frame(dialog, bg=COLOR_WHITE, padx=20, pady=15)
        content.pack(fill=tk.BOTH, expand=True)

        # 水平对齐
        tk.Label(content, text="水平对齐", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(5, 5))

        h_frame = tk.Frame(content, bg=COLOR_WHITE)
        h_frame.pack(fill=tk.X, pady=5)

        tk.Button(h_frame, text="左对齐", command=lambda: self.align_boxes("left"),
                 bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(h_frame, text="水平居中", command=lambda: self.align_boxes("center_h"),
                 bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(h_frame, text="右对齐", command=lambda: self.align_boxes("right"),
                 bg=COLOR_BLUE, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 垂直对齐
        tk.Label(content, text="垂直对齐", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(15, 5))

        v_frame = tk.Frame(content, bg=COLOR_WHITE)
        v_frame.pack(fill=tk.X, pady=5)

        tk.Button(v_frame, text="顶对齐", command=lambda: self.align_boxes("top"),
                 bg=COLOR_GREEN, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(v_frame, text="垂直居中", command=lambda: self.align_boxes("center_v"),
                 bg=COLOR_GREEN, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(v_frame, text="底对齐", command=lambda: self.align_boxes("bottom"),
                 bg=COLOR_GREEN, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 分布
        tk.Label(content, text="均匀分布 (需要3个或以上)", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(15, 5))

        dist_frame = tk.Frame(content, bg=COLOR_WHITE)
        dist_frame.pack(fill=tk.X, pady=5)

        tk.Button(dist_frame, text="水平等间距", command=lambda: self.distribute_boxes("horizontal"),
                 bg=COLOR_ORANGE, fg="white", font=(FONT_FAMILY, 9), width=15,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(dist_frame, text="垂直等间距", command=lambda: self.distribute_boxes("vertical"),
                 bg=COLOR_ORANGE, fg="white", font=(FONT_FAMILY, 9), width=15,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 尺寸统一
        tk.Label(content, text="尺寸统一 (以第一个选中框为基准)", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(15, 5))

        size_frame = tk.Frame(content, bg=COLOR_WHITE)
        size_frame.pack(fill=tk.X, pady=5)

        tk.Button(size_frame, text="统一宽度", command=lambda: self.unify_size("width"),
                 bg=COLOR_PURPLE, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(size_frame, text="统一高度", command=lambda: self.unify_size("height"),
                 bg=COLOR_PURPLE, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(size_frame, text="统一大小", command=lambda: self.unify_size("both"),
                 bg=COLOR_PURPLE, fg="white", font=(FONT_FAMILY, 9), width=10,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        # 对齐到画布
        tk.Label(content, text="对齐到画布", bg=COLOR_WHITE,
                font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(15, 5))

        canvas_frame = tk.Frame(content, bg=COLOR_WHITE)
        canvas_frame.pack(fill=tk.X, pady=5)

        tk.Button(canvas_frame, text="画布水平居中", command=lambda: self.align_to_canvas("h"),
                 bg="#00897B", fg="white", font=(FONT_FAMILY, 9), width=15,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(canvas_frame, text="画布垂直居中", command=lambda: self.align_to_canvas("v"),
                 bg="#00897B", fg="white", font=(FONT_FAMILY, 9), width=15,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        canvas_frame2 = tk.Frame(content, bg=COLOR_WHITE)
        canvas_frame2.pack(fill=tk.X, pady=5)

        tk.Button(canvas_frame2, text="画布完全居中", command=lambda: self.align_to_canvas("center"),
                 bg="#00897B", fg="white", font=(FONT_FAMILY, 9), width=32,
                 cursor="hand2", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Frame(content, bg="#ddd", height=1).pack(fill=tk.X, pady=15)
        tk.Button(content, text="关闭", command=dialog.destroy,
                 bg=COLOR_GRAY, fg="white", font=(FONT_FAMILY, 10),
                 width=15, cursor="hand2", relief=tk.FLAT).pack()

    def distribute_boxes(self, direction):
        """均匀分布文本框"""
        if len(self.selected_boxes) < 3:
            messagebox.showinfo("提示", "均匀分布需要至少选中3个文本框")
            return

        self.save_state()
        boxes = [self.text_boxes[i] for i in self.selected_boxes]

        if direction == "horizontal":
            boxes.sort(key=lambda b: b.x)
            first = boxes[0]
            last = boxes[-1]

            total_width = sum(b.width for b in boxes)
            total_space = (last.x + last.width) - first.x - total_width
            gap = total_space / (len(boxes) - 1) if len(boxes) > 1 else 0

            current_x = first.x + first.width
            for box in boxes[1:-1]:
                box.x = int(current_x + gap)
                current_x = box.x + box.width

        elif direction == "vertical":
            boxes.sort(key=lambda b: b.y)
            first = boxes[0]
            last = boxes[-1]

            total_height = sum(b.height for b in boxes)
            total_space = (last.y + last.height) - first.y - total_height
            gap = total_space / (len(boxes) - 1) if len(boxes) > 1 else 0

            current_y = first.y + first.height
            for box in boxes[1:-1]:
                box.y = int(current_y + gap)
                current_y = box.y + box.height

        self.refresh_canvas()
        self.mark_unsaved()
        self.update_status(f"已均匀分布 {len(self.selected_boxes)} 个框 ✓")

    def unify_size(self, size_type):
        """统一文本框大小"""
        if len(self.selected_boxes) < 2:
            self.update_status("请Ctrl+点击选中至少2个框")
            return

        self.save_state()
        boxes = [self.text_boxes[i] for i in self.selected_boxes]

        base_box = boxes[0]

        for box in boxes[1:]:
            if size_type in ["width", "both"]:
                box.width = base_box.width
            if size_type in ["height", "both"]:
                box.height = base_box.height

        self.refresh_canvas()
        self.mark_unsaved()
        self.update_status(f"已统一 {len(self.selected_boxes)} 个框的尺寸 ✓")

    def align_to_canvas(self, align_type):
        """对齐到画布中心"""
        if not self.selected_boxes or not self.original_image:
            return

        self.save_state()

        img_w, img_h = self.original_image.size
        center_x = img_w // 2
        center_y = img_h // 2

        for idx in self.selected_boxes:
            box = self.text_boxes[idx]

            if align_type == "h":
                box.x = center_x - box.width // 2
            elif align_type == "v":
                box.y = center_y - box.height // 2
            elif align_type == "center":
                box.x = center_x - box.width // 2
                box.y = center_y - box.height // 2

        self.refresh_canvas()
        self.mark_unsaved()
        self.update_status(f"已对齐到画布中心 ✓")

    # ==================== 新增功能：自动保存 ====================

    def start_autosave(self):
        """启动自动保存"""
        interval = self.config.get("autosave_interval", 300) * 1000
        self.autosave_timer = self.root.after(interval, self.auto_save)

    def stop_autosave(self):
        """停止自动保存"""
        if self.autosave_timer:
            self.root.after_cancel(self.autosave_timer)
            self.autosave_timer = None

    def auto_save(self):
        """自动保存"""
        if self.has_unsaved_changes and self.pages:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                autosave_path = os.path.join(self.autosave_dir, f"autosave_{timestamp}.json")

                self.save_current_page()

                pages_data = []
                for page in self.pages:
                    pages_data.append({
                        "original_path": page["original_path"],
                        "original_size": page.get("original_size", page["image"].size),
                        "edit_scale": page.get("edit_scale", 1.0),
                        "bg_path": page.get("bg_path"),
                        "bg_original_path": page.get("bg_original_path"),
                        "text_boxes": page.get("text_boxes", []),
                        "layers": page.get("layers", []),
                    })

                with open(autosave_path, 'w', encoding='utf-8') as f:
                    json.dump({"version": 3, "pages": pages_data, "current_page": self.current_page_index},
                             f, ensure_ascii=False, indent=2)

                self.cleanup_autosave_files()
                print(f"自动保存完成: {autosave_path}")

            except Exception as e:
                print(f"自动保存失败: {e}")

        self.start_autosave()

    def cleanup_autosave_files(self):
        """清理旧的自动保存文件"""
        try:
            autosave_files = [f for f in os.listdir(self.autosave_dir) if f.startswith("autosave_")]
            autosave_files.sort(reverse=True)

            for old_file in autosave_files[10:]:
                try:
                    os.remove(os.path.join(self.autosave_dir, old_file))
                except:
                    pass
        except:
            pass

    def mark_unsaved(self):
        """标记有未保存的更改"""
        self.has_unsaved_changes = True
        if hasattr(self, 'autosave_indicator'):
            self.autosave_indicator.config(fg="#FFC107")

    def mark_saved(self):
        """标记已保存"""
        self.has_unsaved_changes = False
        if hasattr(self, 'autosave_indicator'):
            self.autosave_indicator.config(fg="#4CAF50")

    def on_closing(self):
        """窗口关闭事件"""
        if self.has_unsaved_changes:
            result = messagebox.askyesnocancel(
                "未保存的更改",
                "是否保存当前项目？\n\n是 - 保存并退出\n否 - 不保存退出\n取消 - 返回编辑"
            )
            if result is None:
                return
            elif result:
                self.save_project()

        self.stop_autosave()
        self.root.destroy()

    # ==================== 新增功能：PDF导入 ====================

    def import_pdf(self):
        """导入PDF文件 - 使用PyMuPDF，简单快速"""
        if not PDF_SUPPORT:
            messagebox.showerror("需要安装库",
                "PDF转图片需要安装 PyMuPDF\n\n"
                "请运行以下命令:\n"
                "pip install PyMuPDF\n\n"
                "或者:\n"
                "1. 使用在线工具将PDF转为图片\n"
                "2. 然后用'导入图片'功能导入")
            return

        file_path = filedialog.askopenfilename(
            title="选择PDF文件",
            filetypes=[("PDF文件", "*.pdf")]
        )
        if not file_path:
            return

        self.update_status("正在转换PDF...")

        def convert_pdf():
            try:
                self.root.after(0, lambda: self.update_status("正在解析PDF..."))

                # 打开PDF
                doc = fitz.open(file_path)
                page_count = len(doc)

                if page_count == 0:
                    self.root.after(0, lambda: messagebox.showerror("错误", "PDF文件为空"))
                    doc.close()
                    return

                # 询问是否清空现有页面
                if self.pages:
                    result = messagebox.askyesnocancel(
                        "提示",
                        f"PDF共 {page_count} 页。\n\n是否清空现有页面？\n\n"
                        "是 - 清空后导入\n否 - 追加到现有页面\n取消 - 取消导入"
                    )
                    if result is None:
                        self.root.after(0, lambda: self.update_status("已取消"))
                        doc.close()
                        return
                    elif result:
                        self.root.after(0, lambda: setattr(self, 'pages', []))

                # 创建临时目录
                temp_dir = os.path.join(get_base_dir(), "temp_pdf_imports")
                os.makedirs(temp_dir, exist_ok=True)

                start_index = len(self.pages)

                # 转换每一页
                for page_num in range(page_count):
                    self.root.after(0, lambda idx=page_num+1, total=page_count:
                        self.update_status(f"正在转换第 {idx}/{total} 页..."))

                    # 获取页面
                    page = doc[page_num]

                    # 转换为图片（200 DPI高质量）
                    zoom = 200 / 72  # PDF默认72 DPI，提升到200 DPI
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat)

                    # 保存为PNG
                    pdf_basename = os.path.splitext(os.path.basename(file_path))[0]
                    temp_path = os.path.join(temp_dir, f"{pdf_basename}_page_{page_num+1:03d}.png")
                    pix.save(temp_path)

                    # 转换为PIL Image
                    img_data = pix.tobytes("png")
                    from io import BytesIO
                    img = Image.open(BytesIO(img_data))

                    # 添加到页面
                    original_size = img.size
                    edit_img, edit_scale = self._resize_image_for_edit(img)

                    page_data = {
                        "original_path": temp_path,
                        "original_size": original_size,
                        "edit_scale": edit_scale,
                        "bg_path": None,
                        "image": edit_img,
                        "text_boxes": [],
                        "layers": []
                    }
                    self.pages.append(page_data)

                # 关闭PDF
                doc.close()

                # 更新界面
                self.root.after(0, lambda: setattr(self, 'current_page_index', start_index))
                self.root.after(0, self.load_current_page)
                self.root.after(0, self.update_page_label)
                self.root.after(0, self.update_thumbnails)
                self.root.after(0, lambda: self.placeholder_label.place_forget())
                self.root.after(0, lambda: self.update_status(f"PDF转换成功！共 {page_count} 页"))
                self.root.after(0, lambda: messagebox.showinfo("成功",
                    f"PDF转换成功！\n\n"
                    f"共转换 {page_count} 页\n"
                    f"图片保存在：{temp_dir}\n\n"
                    f"现在可以进行OCR识别了"))

            except Exception as e:
                import traceback
                error_msg = traceback.format_exc()
                print(f"PDF转换失败:\n{error_msg}")
                self.root.after(0, lambda: messagebox.showerror("错误",
                    f"PDF转换失败:\n\n{str(e)}\n\n"
                    f"建议:\n"
                    f"1. 检查PDF文件是否损坏\n"
                    f"2. 或使用在线工具转换后导入图片"))
                self.root.after(0, lambda: self.update_status("PDF转换失败"))

        threading.Thread(target=convert_pdf, daemon=True).start()

    # ==================== 新增功能：PDF导出 ====================

    def export_as_pdf(self):
        return export_feature.export_as_pdf(self)

    # ==================== 新增功能：图片导出 ====================

    def export_as_images(self):
        return export_feature.export_as_images(self)

    def _show_image_format_dialog(self, folder_path):
        return export_feature._show_image_format_dialog(self, folder_path)

    def _do_export_images(self, folder_path, img_format, quality):
        return export_feature._do_export_images(self, folder_path, img_format, quality)

    # ==================== 新增功能：自定义涂抹模式 ====================

    def toggle_inpaint_mode(self):
        """切换涂抹模式"""
        return inpaint_feature.toggle_inpaint_mode(self)
        if not self.pages or not self.original_image:
            messagebox.showwarning("提示", "请先导入图片")
            return

        self.inpaint_mode = not self.inpaint_mode

        if self.inpaint_mode:
            # 进入涂抹模式
            self.inpaint_mode_btn.config(text="退出涂抹", bg="#FF5722")

            # 显示工具栏
            self.inpaint_tools_frame.pack(side=tk.LEFT, after=self.inpaint_mode_btn)
            self.brush_size_frame.pack(side=tk.LEFT, after=self.inpaint_tools_frame)
            self.inpaint_actions_frame.pack(side=tk.LEFT, after=self.brush_size_frame)

            # 检查是否有背景图
            page = self.pages[self.current_page_index]
            has_background = page.get("bg_path") and os.path.exists(page.get("bg_path", ""))

            # 决定使用哪个图作为底图
            if has_background:
                # 有背景图，基于背景图进行迭代修复
                base_image = Image.open(page["bg_path"])
                mode_desc = "背景图"
            else:
                # 没有背景图，基于原图
                base_image = self.original_image
                mode_desc = "原图"

            # 初始化蒙版层（使用当前底图的尺寸）
            if self.inpaint_mask_layer is None or \
               self.inpaint_mask_layer.size != base_image.size:
                self.inpaint_mask_layer = Image.new("L", base_image.size, 0)
                self.inpaint_draw_layer = ImageDraw.Draw(self.inpaint_mask_layer)
                self.inpaint_strokes = []

            # 切换画布光标
            if self.inpaint_tool == "brush":
                self.canvas.config(cursor="dot")
            else:
                self.canvas.config(cursor="tcross")

            # 清空文本框选中状态（避免干扰）
            self.selected_box_index = -1
            self.selected_boxes = []

            self.refresh_canvas()

            # 根据是否有背景图显示不同提示
            if has_background:
                self.update_status(f"涂抹模式已激活 - 基于背景图迭代修复")
                messagebox.showinfo("涂抹模式（迭代修复）",
                    "✅ 检测到已有背景图！\n\n"
                    "当前将基于背景图进行迭代修复\n\n"
                    "✏️ 笔刷工具 - 涂抹需要修复的区域\n"
                    "⬜ 框选工具 - 拉框标记区域\n"
                    "🎨 生成背景 - 修复标记区域\n\n"
                    "💡 适用场景：\n"
                    "- 之前生成的背景有遗漏\n"
                    "- 效果不满意需要补充\n"
                    "- 多次迭代优化背景")
            else:
                self.update_status("涂抹模式已激活 - 标记需要去除的区域")
                messagebox.showinfo("涂抹模式",
                    "已进入涂抹模式！\n\n"
                    "✏️ 笔刷工具 - 涂抹标记区域\n"
                    "⬜ 框选工具 - 拉框标记区域\n"
                    "🎨 点击「生成背景」处理标记区域\n\n"
                    "提示：可以与OCR检测结合使用\n"
                    "先OCR检测文字，再手动补充遗漏区域")
        else:
            # 退出涂抹模式
            self.inpaint_mode_btn.config(text="进入涂抹", bg="#FF6F00")

            # 隐藏工具栏
            self.inpaint_tools_frame.pack_forget()
            self.brush_size_frame.pack_forget()
            self.inpaint_actions_frame.pack_forget()

            # 恢复光标
            self.canvas.config(cursor="")

            # 清除涂抹视觉
            self.canvas.delete("inpaint_visual")
            self.canvas.delete("inpaint_temp")

            self.update_status("已退出涂抹模式")

    def switch_inpaint_tool(self, tool):
        """切换涂抹工具"""
        return inpaint_feature.switch_inpaint_tool(self, tool)
        self.inpaint_tool = tool

        if tool == "brush":
            self.brush_btn.config(relief=tk.SUNKEN, bg="#FFE0B2")
            self.rect_btn.config(relief=tk.RAISED, bg=COLOR_RIBBON_BG)
            self.canvas.config(cursor="dot")
        else:
            self.brush_btn.config(relief=tk.RAISED, bg=COLOR_RIBBON_BG)
            self.rect_btn.config(relief=tk.SUNKEN, bg="#FFE0B2")
            self.canvas.config(cursor="tcross")

    def update_brush_size(self, val):
        """更新笔刷大小"""
        return inpaint_feature.update_brush_size(self, val)
        self.inpaint_brush_size = int(float(val))

    def handle_inpaint_press(self, x, y):
        """涂抹模式 - 按下事件"""
        return inpaint_feature.handle_inpaint_press(self, x, y)
        if self.inpaint_tool == "brush":
            # 笔刷模式 - 开始涂抹
            r = self.inpaint_brush_size // 2
            self.inpaint_draw_layer.ellipse([x-r, y-r, x+r, y+r], fill=255, outline=255)
            self.inpaint_last_pos = (x, y)

            # 绘制视觉反馈
            self.draw_inpaint_visual_brush(x, y, r)

            # 记录笔画开始
            self.inpaint_strokes.append({"type": "brush", "points": [(x, y)]})

        else:
            # 矩形框选模式 - 记录起始点
            self.inpaint_rect_start = (x, y)

    def handle_inpaint_drag(self, x, y):
        """涂抹模式 - 拖拽事件"""
        return inpaint_feature.handle_inpaint_drag(self, x, y)
        if self.inpaint_tool == "brush":
            # 笔刷模式 - 连续涂抹
            r = self.inpaint_brush_size // 2
            self.inpaint_draw_layer.ellipse([x-r, y-r, x+r, y+r], fill=255, outline=255)

            # 连线（平滑）
            if self.inpaint_last_pos:
                self.inpaint_draw_layer.line([self.inpaint_last_pos, (x, y)],
                                            fill=255, width=self.inpaint_brush_size)

            self.inpaint_last_pos = (x, y)

            # 绘制视觉反馈
            self.draw_inpaint_visual_brush(x, y, r)

            # 记录笔画点
            if self.inpaint_strokes and self.inpaint_strokes[-1]["type"] == "brush":
                self.inpaint_strokes[-1]["points"].append((x, y))

        else:
            # 矩形框选模式 - 绘制临时矩形
            if self.inpaint_rect_start:
                self.draw_inpaint_temp_rect(x, y)

    def handle_inpaint_release(self, x, y):
        """涂抹模式 - 释放事件"""
        return inpaint_feature.handle_inpaint_release(self, x, y)
        if self.inpaint_tool == "brush":
            # 笔刷模式 - 结束笔画
            self.inpaint_last_pos = None

            # 保存当前笔画到历史（笔刷完成时保存）
            if self.inpaint_strokes and self.inpaint_strokes[-1]["type"] == "brush":
                self.save_state("inpaint_stroke", {
                    "stroke": self.inpaint_strokes[-1],
                    "mask_state": self.inpaint_strokes[:-1]  # 之前的状态
                })

        else:
            # 矩形框选模式 - 完成框选
            if self.inpaint_rect_start:
                sx, sy = self.inpaint_rect_start
                x1, y1 = min(sx, x), min(sy, y)
                x2, y2 = max(sx, x), max(sy, y)

                # 写入蒙版
                self.inpaint_draw_layer.rectangle([x1, y1, x2, y2], fill=255, outline=255)

                # 绘制永久视觉
                self.draw_inpaint_visual_rect(x1, y1, x2, y2)

                # 清除临时矩形
                self.canvas.delete("inpaint_temp")

                # 记录矩形
                rect_stroke = {
                    "type": "rect",
                    "coords": (x1, y1, x2, y2)
                }
                self.inpaint_strokes.append(rect_stroke)

                # 保存到历史
                self.save_state("inpaint_stroke", {
                    "stroke": rect_stroke,
                    "mask_state": self.inpaint_strokes[:-1]
                })

                self.inpaint_rect_start = None

    def draw_inpaint_visual_brush(self, x, y, radius):
        """绘制笔刷涂抹的视觉反馈"""
        return inpaint_feature.draw_inpaint_visual_brush(self, x, y, radius)
        # 转换为画布坐标
        canvas_x = x * self.scale + getattr(self, 'canvas_offset_x', 0)
        canvas_y = y * self.scale + getattr(self, 'canvas_offset_y', 0)
        canvas_r = radius * self.scale

        # 半透明红色圆形
        self.canvas.create_oval(
            canvas_x - canvas_r, canvas_y - canvas_r,
            canvas_x + canvas_r, canvas_y + canvas_r,
            fill="#ff0000", stipple="gray50", outline="",
            tags="inpaint_visual"
        )

    def draw_inpaint_temp_rect(self, x, y):
        """绘制临时矩形框选"""
        return inpaint_feature.draw_inpaint_temp_rect(self, x, y)
        if not self.inpaint_rect_start:
            return

        sx, sy = self.inpaint_rect_start

        # 转换为画布坐标
        canvas_sx = sx * self.scale + getattr(self, 'canvas_offset_x', 0)
        canvas_sy = sy * self.scale + getattr(self, 'canvas_offset_y', 0)
        canvas_x = x * self.scale + getattr(self, 'canvas_offset_x', 0)
        canvas_y = y * self.scale + getattr(self, 'canvas_offset_y', 0)

        # 删除旧的临时矩形
        self.canvas.delete("inpaint_temp")

        # 绘制新的临时矩形
        self.canvas.create_rectangle(
            canvas_sx, canvas_sy, canvas_x, canvas_y,
            outline="red", width=2, tags="inpaint_temp"
        )

    def draw_inpaint_visual_rect(self, x1, y1, x2, y2):
        """绘制矩形框选的永久视觉反馈"""
        return inpaint_feature.draw_inpaint_visual_rect(self, x1, y1, x2, y2)
        # 转换为画布坐标
        canvas_x1 = x1 * self.scale + getattr(self, 'canvas_offset_x', 0)
        canvas_y1 = y1 * self.scale + getattr(self, 'canvas_offset_y', 0)
        canvas_x2 = x2 * self.scale + getattr(self, 'canvas_offset_x', 0)
        canvas_y2 = y2 * self.scale + getattr(self, 'canvas_offset_y', 0)

        # 半透明红色矩形
        self.canvas.create_rectangle(
            canvas_x1, canvas_y1, canvas_x2, canvas_y2,
            fill="#ff0000", stipple="gray25", outline="red",
            tags="inpaint_visual"
        )

    def clear_inpaint_mask(self):
        """清空所有涂抹"""
        return inpaint_feature.clear_inpaint_mask(self)
        if not self.inpaint_strokes:
            messagebox.showinfo("提示", "当前没有涂抹内容")
            return

        result = messagebox.askyesno("确认", "确定要清空所有涂抹吗？")
        if not result:
            return

        # 清空蒙版
        self.inpaint_mask_layer = Image.new("L", self.original_image.size, 0)
        self.inpaint_draw_layer = ImageDraw.Draw(self.inpaint_mask_layer)
        self.inpaint_strokes = []

        # 清除视觉
        self.canvas.delete("inpaint_visual")
        self.canvas.delete("inpaint_temp")

        self.update_status("已清空所有涂抹")

    def rebuild_inpaint_mask(self):
        """重建涂抹蒙版（用于撤销后）"""
        return inpaint_feature.rebuild_inpaint_mask(self)
        # 重置蒙版
        self.inpaint_mask_layer = Image.new("L", self.original_image.size, 0)
        self.inpaint_draw_layer = ImageDraw.Draw(self.inpaint_mask_layer)

        # 清除视觉
        self.canvas.delete("inpaint_visual")

        # 重新绘制所有笔画
        for stroke in self.inpaint_strokes:
            if stroke["type"] == "brush":
                points = stroke["points"]
                r = self.inpaint_brush_size // 2

                for i, (x, y) in enumerate(points):
                    self.inpaint_draw_layer.ellipse([x-r, y-r, x+r, y+r], fill=255, outline=255)
                    if i > 0:
                        prev_x, prev_y = points[i-1]
                        self.inpaint_draw_layer.line([(prev_x, prev_y), (x, y)],
                                                    fill=255, width=self.inpaint_brush_size)
                    # 绘制视觉
                    self.draw_inpaint_visual_brush(x, y, r)

            elif stroke["type"] == "rect":
                x1, y1, x2, y2 = stroke["coords"]
                self.inpaint_draw_layer.rectangle([x1, y1, x2, y2], fill=255, outline=255)
                self.draw_inpaint_visual_rect(x1, y1, x2, y2)

    def generate_bg_from_custom_mask(self):
        """基于自定义涂抹蒙版生成背景"""
        return inpaint_feature.generate_bg_from_custom_mask(self)
        if not self.pages or not self.original_image:
            messagebox.showwarning("提示", "请先导入图片")
            return

        if not self.inpaint_mask_layer:
            messagebox.showwarning("提示", "请先涂抹标记需要去除的区域")
            return

        # 检查是否有涂抹内容
        if not self.inpaint_mask_layer.getbbox():
            messagebox.showwarning("提示", "当前没有涂抹内容\n\n请使用笔刷或框选工具标记需要去除的区域")
            return

        if not self.config.get("inpaint_enabled", True):
            messagebox.showwarning("提示", "背景生成功能已禁用\n\n请在设置中启用")
            return

        # 检查是否有背景图（决定使用哪个图作为底图）
        page = self.pages[self.current_page_index]
        has_background = page.get("bg_path") and os.path.exists(page.get("bg_path", ""))

        if has_background:
            base_image = Image.open(page["bg_path"])
            mode_desc = "背景图（迭代修复）"
        else:
            base_image = page["image"]
            mode_desc = "原图"

        # 确认对话框
        result = messagebox.askyesno("确认",
            f"即将基于{mode_desc}生成新背景图\n\n"
            f"底图：{mode_desc}\n"
            f"涂抹区域：将被AI智能填充\n\n"
            f"此操作需要调用IOPaint API服务\n"
            f"处理时间约 5-30 秒\n\n"
            f"是否继续？")

        if not result:
            return

        # 保存背景生成前的状态到历史（重要！）
        old_bg_path = page.get("bg_path")
        self.save_state("background", {
            "old_bg_path": old_bg_path,
            "new_bg_path": None  # 将在生成后填充
        })

        self.update_status(f"正在生成背景图（基于{mode_desc}）...")

        def generate_bg():
            try:
                # 调用API修复（使用底图而不是原图）
                self.root.after(0, lambda: self.update_status(f"正在调用IOPaint API修复（{mode_desc}）..."))
                result_img = self.call_inpaint_api(base_image, self.inpaint_mask_layer)

                if result_img:
                    # 保存到临时文件
                    temp_dir = os.path.join(get_base_dir(), "temp_backgrounds")
                    os.makedirs(temp_dir, exist_ok=True)

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    bg_path = os.path.join(temp_dir, f"bg_iter_page{self.current_page_index+1}_{timestamp}.png")
                    result_img.save(bg_path, quality=95)

                    # 更新历史记录中的new_bg_path
                    if self.history and self.history[-1]["type"] == "background":
                        self.history[-1]["data"]["new_bg_path"] = bg_path

                    # 更新为新的背景图
                    page["bg_path"] = bg_path
                    self.root.after(0, lambda: setattr(self, 'clean_bg_path', bg_path))

                    # 清空涂抹（已生成背景）
                    self.root.after(0, lambda: self.clear_inpaint_mask())

                    # 刷新界面
                    self.root.after(0, self.update_bg_status)
                    self.root.after(0, self.update_thumbnails)
                    self.root.after(0, self.refresh_canvas)

                    self.root.after(0, lambda: self.update_status(f"第 {self.current_page_index+1} 页背景生成成功！"))

                    if has_background:
                        msg = (f"迭代修复成功！\n\n"
                               f"✅ 已基于之前的背景图进行修复\n"
                               f"✅ 涂抹区域已被智能填充\n"
                               f"✅ 新背景已自动设置到当前页\n\n"
                               f"💡 如需继续修复，可再次进入涂抹模式\n"
                               f"💡 按Ctrl+Z可以撤销此次生成\n\n"
                               f"保存位置：\n{bg_path}")
                    else:
                        msg = (f"背景图生成成功！\n\n"
                               f"已根据涂抹区域去除内容\n"
                               f"背景已自动设置到当前页\n\n"
                               f"💡 按Ctrl+Z可以撤销此次生成\n\n"
                               f"保存位置：\n{bg_path}")

                    self.root.after(0, lambda: messagebox.showinfo("成功", msg))
                else:
                    self.root.after(0, lambda: self.update_status("背景生成失败"))

            except Exception as e:
                import traceback
                error_msg = traceback.format_exc()
                print(f"背景生成失败:\n{error_msg}")
                err_text = str(e)
                self.root.after(0, lambda t=err_text: messagebox.showerror("错误", f"背景生成失败:\n{t}"))
                self.root.after(0, lambda: self.update_status("背景生成失败"))

        threading.Thread(target=generate_bg, daemon=True).start()

    # ==================== 新增功能：IOPaint API 背景生成 ====================

    def call_inpaint_api(self, image_pil, mask_pil, crop_padding=128):
        """
        调用IOPaint API进行图像修复

        Args:
            image_pil: PIL Image，原图
            mask_pil: PIL Image (L模式)，蒙版（白色=需要修复的区域）
            crop_padding: 裁切padding大小

        Returns:
            PIL Image 或 None
        """
        return inpaint_feature.call_inpaint_api(self, image_pil, mask_pil, crop_padding=crop_padding)
        try:
            api_url = self.config.get("inpaint_api_url", "http://127.0.0.1:8080/api/v1/inpaint")

            # === 智能裁切逻辑（只处理有蒙版的区域）===
            mask_np = np.array(mask_pil)
            rows = np.any(mask_np, axis=1)
            cols = np.any(mask_np, axis=0)

            if not rows.any() or not cols.any():
                # 没有蒙版区域
                return image_pil.copy()

            y_min, y_max = np.where(rows)[0][[0, -1]]
            x_min, x_max = np.where(cols)[0][[0, -1]]

            W, H = image_pil.size
            pad = crop_padding
            x1 = max(0, x_min - pad)
            y1 = max(0, y_min - pad)
            x2 = min(W, x_max + pad)
            y2 = min(H, y_max + pad)

            crop_box = (x1, y1, x2, y2)
            crop_img = image_pil.crop(crop_box)
            crop_mask = mask_pil.crop(crop_box)

            # === Base64编码 ===
            def to_b64(img):
                buffer = BytesIO()
                img.save(buffer, "PNG")
                return base64.b64encode(buffer.getvalue()).decode()

            payload = {
                "image": to_b64(crop_img),
                "mask": to_b64(crop_mask),
                "ldm_steps": 30,
                "hd_strategy": "Original",
                "sd_sampler": "UniPC"
            }

            # === 调用API ===
            response = requests.post(api_url, json=payload, timeout=120)

            if response.status_code == 200:
                # 修复成功，合成回原图
                res_crop = Image.open(BytesIO(response.content))

                # 创建结果图
                final = image_pil.copy()

                # 使用高斯模糊平滑边缘
                blur_mask = crop_mask.filter(ImageFilter.GaussianBlur(3))
                orig_crop_area = final.crop(crop_box)
                blended = Image.composite(res_crop, orig_crop_area, blur_mask)
                final.paste(blended, (x1, y1))

                return final
            else:
                self.root.after(0, lambda: messagebox.showerror("API错误",
                    f"IOPaint API返回错误: {response.status_code}\n{response.text[:200]}"))
                return None

        except requests.exceptions.ConnectionError:
            self.root.after(0, lambda: messagebox.showerror("连接错误",
                "无法连接到IOPaint API服务！\n\n"
                "请确保IOPaint服务正在运行：\n"
                f"API地址：{api_url}\n\n"
                "启动命令：\n"
                "iopaint start --host 127.0.0.1 --port 8080"))
            return None
        except Exception as e:
            import traceback
            error_msg = traceback.format_exc()
            print(f"IOPaint API调用失败:\n{error_msg}")
            err_text = str(e)
            self.root.after(0, lambda t=err_text: messagebox.showerror("错误", f"修复失败:\n{t}"))
            return None

    def create_mask_from_boxes(self, image_size, text_boxes, padding=5):
        """
        根据文本框位置创建蒙版

        Args:
            image_size: (width, height) 图片尺寸
            text_boxes: 文本框列表
            padding: 文本框扩展边距

        Returns:
            PIL Image (L模式)，白色=需要修复的区域
        """
        return inpaint_feature.create_mask_from_boxes(self, image_size, text_boxes, padding=padding)
        mask = Image.new("L", image_size, 0)  # 全黑背景
        draw = ImageDraw.Draw(mask)

        img_w, img_h = image_size

        for box in text_boxes:
            # 稍微扩大文本框区域
            x1 = max(0, box.x - padding)
            y1 = max(0, box.y - padding)
            x2 = min(img_w, box.x + box.width + padding)
            y2 = min(img_h, box.y + box.height + padding)

            # 标记为白色（需要修复）
            draw.rectangle([x1, y1, x2, y2], fill=255)

        return mask

    def auto_generate_background_current(self):
        """为当前页自动生成修复图层（根据文本框位置；不替换原图/背景）"""
        if not self.pages:
            messagebox.showwarning("提示", "请先导入图片")
            return

        if not self.text_boxes:
            messagebox.showwarning("提示", "当前页没有文本框\n\n请先使用「检测」功能识别文本区域")
            return

        if not self.config.get("inpaint_enabled", True):
            messagebox.showwarning("提示", "背景生成功能已禁用\n\n请在设置中启用")
            return

        # 确认对话框
        result = messagebox.askyesno(
            "确认",
            f"即将为第 {self.current_page_index + 1} 页生成修复图层\n\n"
            f"当前页有 {len(self.text_boxes)} 个文本框\n"
            "系统将自动对这些文字区域进行修复\n\n"
            "提示：结果会作为图层叠加，不会直接替换原图/背景\n\n"
            "此操作需要调用 IOPaint API 服务\n"
            "处理时间约 5-30 秒\n\n"
            "是否继续？",
        )

        if not result:
            return

        page = self.pages[self.current_page_index]
        # 非破坏：保存“图层快照”便于 Ctrl+Z 撤销
        self.save_state("layers")

        self.update_status("正在生成修复图层...")

        def generate_bg():
            try:
                # 获取当前页数据
                img = page["image"]  # 编辑用的图片

                # 创建蒙版
                self.root.after(0, lambda: self.update_status("正在创建蒙版..."))
                mask = self.create_mask_from_boxes(img.size, self.text_boxes, padding=5)

                # 调用API修复
                self.root.after(0, lambda: self.update_status("正在调用IOPaint API修复..."))
                result_img = self.call_inpaint_api(img, mask)

                if result_img:
                    overlay = result_img.convert("RGBA")
                    alpha = mask.convert("L").filter(ImageFilter.GaussianBlur(3))
                    overlay.putalpha(alpha)

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    layer_name = f"IOPaint去字_{timestamp}"
                    layer = self.add_image_layer(page, overlay, name=layer_name, x=0, y=0, opacity=1.0, visible=True)

                    self.root.after(0, self.update_thumbnails)
                    self.root.after(0, self.update_layer_listbox)
                    self.root.after(0, self.scroll_to_layers)
                    if layer and layer.get("id"):
                        self.root.after(0, lambda lid=layer["id"]: self.select_layer_by_id(lid))
                    self.root.after(0, self.refresh_canvas)
                    self.root.after(0, self.mark_unsaved)

                    self.root.after(0, lambda: self.update_status(f"已生成修复图层：{layer_name}"))
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "完成",
                            "处理完成！\n\n"
                            f"已去除 {len(self.text_boxes)} 个文字区域\n"
                            "结果已作为图层叠加（右侧属性面板滚动到底部“图层”即可看到）\n\n"
                            "提示：Ctrl+Z 可以撤销",
                        ),
                    )
                else:
                    self.root.after(0, lambda: self.update_status("修复失败"))

            except Exception as e:
                import traceback
                error_msg = traceback.format_exc()
                print(f"修复失败:\n{error_msg}")
                err_text = str(e)
                self.root.after(0, lambda t=err_text: messagebox.showerror("错误", f"修复失败:\n{t}"))
                self.root.after(0, lambda: self.update_status("修复失败"))

        threading.Thread(target=generate_bg, daemon=True).start()

    def auto_generate_background_all(self):
        """批量为所有页生成修复图层（不替换原图/背景）"""
        if not self.pages:
            messagebox.showwarning("提示", "请先导入图片")
            return

        if not self.config.get("inpaint_enabled", True):
            messagebox.showwarning("提示", "背景生成功能已禁用\n\n请在设置中启用")
            return

        # 统计有文本框的页面
        pages_with_boxes = sum(1 for p in self.pages if p.get("text_boxes"))

        if pages_with_boxes == 0:
            messagebox.showwarning("提示", "所有页面都没有文本框\n\n请先使用「检测 - 全部页」功能")
            return

        # 确认对话框
        result = messagebox.askyesno(
            "批量修复（IOPaint）",
            f"即将为 {pages_with_boxes}/{len(self.pages)} 页生成修复图层\n\n"
            "提示：结果会作为图层叠加，不会直接替换原图/背景\n\n"
            "此操作可能需要较长时间\n"
            f"预计时间：{pages_with_boxes * 10} - {pages_with_boxes * 30} 秒\n\n"
            "处理期间可以继续编辑，但请勿关闭程序\n\n"
            "是否继续？",
        )

        if not result:
            return

        # 批量操作：保存“全页图层快照”以便 Ctrl+Z 一次撤销整个批量结果
        self.save_state("pages_layers")

        self.save_current_page()
        self.update_status("开始批量生成修复图层...")

        def generate_all_bg():
            try:
                success_count = 0
                fail_count = 0

                for page_idx, page in enumerate(self.pages):
                    text_boxes = page.get("text_boxes", [])

                    if not text_boxes:
                        continue

                    self.root.after(0, lambda idx=page_idx+1, total=len(self.pages):
                        self.update_status(f"正在处理第 {idx}/{total} 页..."))

                    try:
                        # 获取图片（需要从dict转为TextBox对象）
                        img = page["image"]
                        boxes = [TextBox.from_dict(b) if isinstance(b, dict) else b for b in text_boxes]

                        # 创建蒙版
                        mask = self.create_mask_from_boxes(img.size, boxes, padding=5)

                        # 调用API
                        result_img = self.call_inpaint_api(img, mask)

                        if result_img:
                            overlay = result_img.convert("RGBA")
                            alpha = mask.convert("L").filter(ImageFilter.GaussianBlur(3))
                            overlay.putalpha(alpha)

                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            layer_name = f"IOPaint批量修复_p{page_idx+1}_{timestamp}"
                            self.add_image_layer(page, overlay, name=layer_name, x=0, y=0, opacity=1.0, visible=True)
                            success_count += 1
                        else:
                            fail_count += 1

                    except Exception as e:
                        print(f"第 {page_idx+1} 页处理失败: {e}")
                        fail_count += 1
                        continue

                # 刷新界面
                self.root.after(0, self.load_current_page)
                self.root.after(0, self.update_thumbnails)
                self.root.after(0, self.update_layer_listbox)

                # 显示结果
                self.root.after(0, lambda: self.update_status(
                    f"批量处理完成！成功 {success_count} 页，失败 {fail_count} 页"))

                self.root.after(0, lambda: messagebox.showinfo("完成",
                    f"批量修复完成！\n\n"
                    f"成功：{success_count} 页\n"
                    f"失败：{fail_count} 页\n\n"
                    f"结果已作为图层叠加（右侧“图层”可隐藏/删除/调顺序）\n"
                    f"提示：Ctrl+Z 可撤销整个批量结果"))

            except Exception as e:
                import traceback
                error_msg = traceback.format_exc()
                print(f"批量生成失败:\n{error_msg}")
                err_text = str(e)
                self.root.after(0, lambda t=err_text: messagebox.showerror("错误", f"批量生成失败:\n{t}"))
                self.root.after(0, lambda: self.update_status("批量生成失败"))

        threading.Thread(target=generate_all_bg, daemon=True).start()

    # ==================== AI图片替换功能 ====================

    def toggle_ai_replace_mode(self):
        """切换AI替换模式"""
        return ai_replace_feature.toggle_ai_replace_mode(self)
        if not self.pages:
            messagebox.showwarning("提示", "请先导入图片")
            return

        self.save_current_page()
        self.ai_replace_mode = not self.ai_replace_mode

        if self.ai_replace_mode:
            self.ai_replace_mode_btn.config(text="退出AI替换", bg="#F50057")
            if self.inpaint_mode:
                self.toggle_inpaint_mode()
            self.ai_replace_selection = None
            if self.ai_replace_rect_id:
                self.canvas.delete(self.ai_replace_rect_id)
                self.ai_replace_rect_id = None
            self.update_status("AI替换模式已激活 - 框选要替换的区域")
            messagebox.showinfo("AI替换模式",
                "已进入AI替换模式！\n\n"
                "📐 操作步骤：\n"
                "1. 用鼠标框选要替换/编辑的区域\n"
                "2. 输入提示词描述想要的效果\n"
                "3. 等待AI生成并自动融合\n\n"
                "💡 提示：\n"
                "- 可以在原图或背景图上框选\n"
                "- 支持多次编辑和迭代")
        else:
            self.ai_replace_mode_btn.config(text="AI替换", bg="#E91E63")
            if self.ai_replace_rect_id:
                self.canvas.delete(self.ai_replace_rect_id)
                self.ai_replace_rect_id = None
            self.ai_replace_selection = None
            self.update_status("已退出AI替换模式")

    def handle_ai_replace_press(self, x, y):
        """AI替换模式 - 按下事件"""
        return ai_replace_feature.handle_ai_replace_press(self, x, y)
        self.ai_replace_rect_start = (x, y)

    def handle_ai_replace_drag(self, canvas_x, canvas_y):
        """AI替换模式 - 拖拽事件"""
        return ai_replace_feature.handle_ai_replace_drag(self, canvas_x, canvas_y)
        if not self.ai_replace_rect_start:
            return
        if self.ai_replace_rect_id:
            self.canvas.delete(self.ai_replace_rect_id)

        img_x, img_y = self.ai_replace_rect_start
        canvas_x1 = img_x * self.scale + getattr(self, 'canvas_offset_x', 0)
        canvas_y1 = img_y * self.scale + getattr(self, 'canvas_offset_y', 0)

        self.ai_replace_rect_id = self.canvas.create_rectangle(
            canvas_x1, canvas_y1, canvas_x, canvas_y,
            outline="#E91E63", width=3, dash=(5, 5))

    def handle_ai_replace_release(self, canvas_x, canvas_y):
        """AI替换模式 - 释放事件"""
        return ai_replace_feature.handle_ai_replace_release(self, canvas_x, canvas_y)
        if not self.ai_replace_rect_start:
            return

        img_x = (canvas_x - getattr(self, 'canvas_offset_x', 0)) / self.scale
        img_y = (canvas_y - getattr(self, 'canvas_offset_y', 0)) / self.scale

        x1, y1 = self.ai_replace_rect_start
        x1, x2 = min(x1, img_x), max(x1, img_x)
        y1, y2 = min(y1, img_y), max(y1, img_y)

        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            messagebox.showwarning("提示", "选框太小，请重新框选")
            if self.ai_replace_rect_id:
                self.canvas.delete(self.ai_replace_rect_id)
                self.ai_replace_rect_id = None
            self.ai_replace_rect_start = None
            return

        self.ai_replace_selection = (int(x1), int(y1), int(x2), int(y2))
        self.ai_replace_rect_start = None
        self.show_ai_replace_dialog()

    def show_ai_replace_dialog(self):
        """显示AI替换操作对话框"""
        return ai_replace_feature.show_ai_replace_dialog(self)
        if not self.ai_replace_selection:
            return

        x1, y1, x2, y2 = self.ai_replace_selection

        dialog = tk.Toplevel(self.root)
        dialog.title("AI图片替换/生成")
        dialog.geometry("500x350")
        dialog.transient(self.root)
        dialog.grab_set()

        # 标题
        title_frame = tk.Frame(dialog, bg="#E91E63", height=50)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        tk.Label(title_frame, text="AI 图片替换/生成",
                bg="#E91E63", fg="white",
                font=(FONT_FAMILY, 14, "bold")).pack(pady=10)

        # 内容区
        content_frame = tk.Frame(dialog, bg="white", padx=20, pady=20)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # 选区信息
        info_text = f"已选中区域: {x2-x1}×{y2-y1} 像素"
        tk.Label(content_frame, text=info_text,
                bg="white", fg="#666",
                font=(FONT_FAMILY, 9)).pack(anchor=tk.W, pady=(0, 10))

        # 提示词输入
        tk.Label(content_frame, text="提示词:",
                bg="white", fg="#333",
                font=(FONT_FAMILY, 10, "bold")).pack(anchor=tk.W, pady=(10, 5))

        prompt_frame = tk.Frame(content_frame, bg="white")
        prompt_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        prompt_text = tk.Text(prompt_frame, height=5, font=(FONT_FAMILY, 9),
                             relief=tk.SOLID, borderwidth=1)
        prompt_text.pack(fill=tk.BOTH, expand=True)

        api_type = self.ai_api_manager.config.get("api_type", "openai")
        use_gemini_args_var = tk.BooleanVar(value=False)
        gemini_image_size_var = tk.StringVar(value=self.ai_api_manager.config.get("gemini", {}).get("image_size", "1K"))
        # 默认用选区比例（更容易生成同宽高比的结果，减少裁切/留边）
        gemini_aspect_ratio_var = tk.StringVar(value=self._best_ratio_label(x2 - x1, y2 - y1))

        if api_type == "gemini":
            args_frame = tk.LabelFrame(content_frame, text="Gemini 参数（可选）", bg="white", fg="#333",
                                       font=(FONT_FAMILY, 9, "bold"), padx=10, pady=6)
            args_frame.pack(fill=tk.X, pady=(10, 0))

            tk.Checkbutton(
                args_frame,
                text="勾选后按本次参数生成",
                variable=use_gemini_args_var,
                bg="white",
                font=(FONT_FAMILY, 9),
            ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 6))

            tk.Label(args_frame, text="分辨率:", bg="white", font=(FONT_FAMILY, 9)).grid(row=1, column=0, sticky=tk.W)
            for i, val in enumerate(["1K", "2K", "4K"]):
                tk.Radiobutton(
                    args_frame,
                    text=val,
                    value=val,
                    variable=gemini_image_size_var,
                    bg="white",
                    font=(FONT_FAMILY, 9),
                ).grid(row=1, column=1 + i, sticky=tk.W, padx=6)

            tk.Label(args_frame, text="比例:", bg="white", font=(FONT_FAMILY, 9)).grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
            ratio_vals = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4"]
            for i, val in enumerate(ratio_vals):
                tk.Radiobutton(
                    args_frame,
                    text=val,
                    value=val,
                    variable=gemini_aspect_ratio_var,
                    bg="white",
                    font=(FONT_FAMILY, 9),
                ).grid(row=3 + i // 4, column=i % 4, sticky=tk.W, padx=6)

        # 快速模板
        tk.Label(content_frame, text="快速模板:",
                bg="white", fg="#666",
                font=(FONT_FAMILY, 9)).pack(anchor=tk.W, pady=(10, 5))

        template_frame = tk.Frame(content_frame, bg="white")
        template_frame.pack(anchor=tk.W)

        def set_prompt(template):
            prompt_text.delete("1.0", tk.END)
            prompt_text.insert("1.0", template)

        templates = [
            ("换成苹果", "Replace with a red apple"),
            ("去除物体", "Remove this object and generate clean background"),
            ("油画风格", "Transform to oil painting style"),
            ("卡通风格", "Transform to cartoon style")
        ]

        for i, (label, template) in enumerate(templates):
            btn = tk.Button(template_frame, text=label,
                          command=lambda t=template: set_prompt(t),
                          bg="#F5F5F5", relief=tk.FLAT,
                          font=(FONT_FAMILY, 8))
            btn.grid(row=i//2, column=i%2, padx=5, pady=2, sticky=tk.W)

        # 按钮区
        button_frame = tk.Frame(dialog, bg="white", pady=15)
        button_frame.pack(fill=tk.X)

        def on_generate():
            prompt = prompt_text.get("1.0", tk.END).strip()
            if not prompt:
                messagebox.showwarning("提示", "请输入提示词")
                return
            dialog.destroy()
            overrides = None
            if api_type == "gemini" and use_gemini_args_var.get():
                overrides = {
                    "image_size": gemini_image_size_var.get(),
                    "aspect_ratio": gemini_aspect_ratio_var.get(),
                }
            self.execute_ai_replace(prompt, overrides=overrides)

        def on_cancel():
            if self.ai_replace_rect_id:
                self.canvas.delete(self.ai_replace_rect_id)
                self.ai_replace_rect_id = None
            self.ai_replace_selection = None
            dialog.destroy()

        tk.Button(button_frame, text="生成/替换", command=on_generate,
                 bg="#E91E63", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10, "bold"),
                 padx=30, pady=8).pack(side=tk.LEFT, padx=(20, 10))

        tk.Button(button_frame, text="取消", command=on_cancel,
                 bg="#999", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10),
                 padx=30, pady=8).pack(side=tk.LEFT)

    def execute_ai_replace(self, prompt, overrides=None):
        """执行AI替换"""
        return ai_replace_feature.execute_ai_replace(self, prompt, overrides=overrides)
        if not self.ai_replace_selection:
            return

        x1, y1, x2, y2 = self.ai_replace_selection

        # 获取当前显示的图片（原图或背景图）
        current_page = self.pages[self.current_page_index]

        # 使用背景图（如果有）或原图
        if current_page.get("bg_path") and os.path.exists(current_page["bg_path"]):
            base_image = Image.open(current_page["bg_path"])
        else:
            base_image = current_page["image"].copy()

        # 裁剪选中区域
        crop_box = (x1, y1, x2, y2)
        cropped_image = base_image.crop(crop_box)

        # 创建蒙版（选中区域为白色）
        mask = Image.new("L", base_image.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rectangle([x1, y1, x2, y2], fill=255)

        # 裁剪蒙版
        cropped_mask = mask.crop(crop_box)

        # 显示进度对话框
        progress_dialog = tk.Toplevel(self.root)
        progress_dialog.title("AI处理中")
        progress_dialog.geometry("400x150")
        progress_dialog.transient(self.root)
        progress_dialog.grab_set()

        tk.Label(progress_dialog, text="AI正在处理图片...",
                font=(FONT_FAMILY, 11, "bold")).pack(pady=20)

        progress_label = tk.Label(progress_dialog, text="正在初始化...",
                                 font=(FONT_FAMILY, 9), fg="#666")
        progress_label.pack(pady=10)

        def update_progress(message):
            def _update():
                try:
                    if progress_label.winfo_exists():
                        progress_label.config(text=message)
                except Exception:
                    pass

            try:
                self.root.after(0, _update)
            except Exception:
                pass

        def process_in_thread():
            try:
                # 调用AI API
                result_image = self.ai_api_manager.image_to_image(
                    prompt,
                    cropped_image,
                    cropped_mask,
                    update_progress,
                    overrides=overrides,
                )

                if result_image:
                    # 先把AI返回结果落盘（方便排查/复用），再做无拉伸适配插入
                    temp_dir = os.path.join(get_base_dir(), "temp_backgrounds")
                    os.makedirs(temp_dir, exist_ok=True)

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    raw_path = os.path.join(temp_dir, f"ai_replace_raw_{timestamp}.png")
                    try:
                        result_image.save(raw_path)
                    except Exception:
                        try:
                            result_image.convert("RGB").save(raw_path)
                        except Exception:
                            pass

                    # 无变形贴回：等比缩放 + 居中裁切到选区尺寸
                    if result_image.size != cropped_image.size:
                        result_image = self._resize_cover_no_distort(result_image, cropped_image.size)

                    # 作为图层加入（不融合到背景，方便无损切换/隐藏/删除）
                    layer_name = f"AI替换 {timestamp}"
                    layer_img = result_image.convert("RGBA") if result_image.mode != "RGBA" else result_image
                    self.add_image_layer(current_page, layer_img, name=layer_name, x=x1, y=y1, opacity=1.0, visible=True)
                    try:
                        self.layers = current_page.get("layers", [])
                    except Exception:
                        pass

                    # 关闭进度对话框
                    self.root.after(0, progress_dialog.destroy)

                    # 刷新显示
                    self.root.after(0, self.update_layer_listbox)
                    self.root.after(0, self.refresh_canvas)
                    self.root.after(0, self.mark_unsaved)

                    # 清除选框
                    if self.ai_replace_rect_id:
                        self.root.after(0, lambda: self.canvas.delete(self.ai_replace_rect_id))
                        self.ai_replace_rect_id = None
                    self.ai_replace_selection = None

                    # 显示成功消息
                    self.root.after(0, lambda: messagebox.showinfo("成功",
                        "AI替换完成！\n\n"
                        "✅ 已作为图层叠加（右侧“图层”可隐藏/删除/调透明度）\n"
                        f"💾 原始返回已保存：{raw_path}\n\n"
                        "💡 可继续框选其他区域进行编辑"))

                    self.root.after(0, lambda: self.update_status("AI替换完成"))
                else:
                    raise Exception("AI API未返回结果")

            except Exception as e:
                print(f"AI替换失败: {e}")
                import traceback
                traceback.print_exc()
                err_text = str(e)

                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, lambda t=err_text: messagebox.showerror("错误",
                    f"AI替换失败:\n{t}\n\n"
                    f"请检查:\n"
                    f"1. API配置是否正确\n"
                    f"2. API Key是否有效\n"
                    f"3. 网络连接是否正常"))
                self.root.after(0, lambda: self.update_status("AI替换失败"))

        # 在后台线程执行
        threading.Thread(target=process_in_thread, daemon=True).start()

    def _resize_cover_no_distort(self, img, target_size):
        """
        等比缩放并居中裁切，保证填满目标尺寸且不拉伸变形。
        用于把AI返回图无变形贴回指定区域/画布。
        """
        target_w, target_h = target_size
        if target_w <= 0 or target_h <= 0:
            return img

        img_w, img_h = img.size
        if img_w <= 0 or img_h <= 0:
            return img

        if (img_w, img_h) == (target_w, target_h):
            return img

        scale = max(target_w / img_w, target_h / img_h)
        new_w = max(1, int(math.ceil(img_w * scale)))
        new_h = max(1, int(math.ceil(img_h * scale)))

        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        left = max(0, (new_w - target_w) // 2)
        top = max(0, (new_h - target_h) // 2)
        return resized.crop((left, top, left + target_w, top + target_h))

    def _resize_contain_no_distort(self, img, target_size, fill_color=None):
        """
        等比缩放并居中放置到目标画布（不裁切、不拉伸）。
        若比例不一致，会产生留边；留边颜色默认取左上角像素或透明。
        """
        target_w, target_h = target_size
        if target_w <= 0 or target_h <= 0:
            return img

        img_w, img_h = img.size
        if img_w <= 0 or img_h <= 0:
            return img

        if (img_w, img_h) == (target_w, target_h):
            return img

        scale = min(target_w / img_w, target_h / img_h)
        new_w = max(1, int(math.floor(img_w * scale)))
        new_h = max(1, int(math.floor(img_h * scale)))
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        if fill_color is None:
            if "A" in resized.mode:
                fill_color = (0, 0, 0, 0)
            else:
                try:
                    fill_color = resized.getpixel((0, 0))
                except Exception:
                    fill_color = (0, 0, 0)

        canvas = Image.new(resized.mode, (target_w, target_h), fill_color)
        left = (target_w - new_w) // 2
        top = (target_h - new_h) // 2
        if resized.mode == "RGBA":
            canvas.paste(resized, (left, top), mask=resized.split()[-1])
        else:
            canvas.paste(resized, (left, top))
        return canvas

    def _best_ratio_label(self, width, height):
        """从常用比例里选一个最接近的（用于 Gemini 的 aspectRatio）。"""
        if width <= 0 or height <= 0:
            return "auto"
        r = width / height
        candidates = {
            "1:1": 1.0,
            "16:9": 16 / 9,
            "9:16": 9 / 16,
            "4:3": 4 / 3,
            "3:4": 3 / 4,
        }
        best = min(candidates.items(), key=lambda kv: abs(kv[1] - r))[0]
        return best

    def ai_text_to_image_layer(self):
        """根据文字描述生成图片，并作为图层添加到当前页"""
        if not self.pages:
            messagebox.showwarning("提示", "请先导入图片")
            return

        current_page = self.pages[self.current_page_index]

        dialog = tk.Toplevel(self.root)
        dialog.title("AI文字生图")
        dialog.geometry("520x320")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="提示词（描述你希望生成的图片）",
                font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=15, pady=(15, 5))

        prompt_text = tk.Text(dialog, height=8, font=(FONT_FAMILY, 10), wrap=tk.WORD)
        prompt_text.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        prompt_text.insert("1.0", "请输入你想要生成的图片描述...")

        api_type = self.ai_api_manager.config.get("api_type", "openai")
        use_gemini_args_var = tk.BooleanVar(value=False)
        gemini_image_size_var = tk.StringVar(value=self.ai_api_manager.config.get("gemini", {}).get("image_size", "1K"))
        # 默认 1:1 比例
        gemini_aspect_ratio_var = tk.StringVar(value="1:1")

        if api_type == "gemini":
            args_frame = tk.LabelFrame(dialog, text="Gemini 参数（可选）", font=(FONT_FAMILY, 9, "bold"),
                                       padx=10, pady=6)
            args_frame.pack(fill=tk.X, padx=15, pady=(0, 10))

            tk.Checkbutton(
                args_frame,
                text="勾选后按本次参数生成",
                variable=use_gemini_args_var,
                font=(FONT_FAMILY, 9),
            ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 6))

            tk.Label(args_frame, text="分辨率:", font=(FONT_FAMILY, 9)).grid(row=1, column=0, sticky=tk.W)
            for i, val in enumerate(["1K", "2K", "4K"]):
                tk.Radiobutton(
                    args_frame,
                    text=val,
                    value=val,
                    variable=gemini_image_size_var,
                    font=(FONT_FAMILY, 9),
                ).grid(row=1, column=1 + i, sticky=tk.W, padx=6)

            tk.Label(args_frame, text="比例:", font=(FONT_FAMILY, 9)).grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
            ratio_vals = ["1:1", "16:9", "9:16", "4:3", "3:4"]
            for i, val in enumerate(ratio_vals):
                tk.Radiobutton(
                    args_frame,
                    text=val,
                    value=val,
                    variable=gemini_aspect_ratio_var,
                    font=(FONT_FAMILY, 9),
                ).grid(row=3 + i // 4, column=i % 4, sticky=tk.W, padx=6)

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=15, pady=12)

        def on_cancel():
            dialog.destroy()

        def on_generate():
            prompt = prompt_text.get("1.0", tk.END).strip()
            if not prompt or prompt == "请输入你想要生成的图片描述...":
                messagebox.showwarning("提示", "请输入有效的提示词")
                return
            dialog.destroy()
            overrides = None
            if api_type == "gemini" and use_gemini_args_var.get():
                overrides = {
                    "image_size": gemini_image_size_var.get(),
                    "aspect_ratio": gemini_aspect_ratio_var.get(),
                }
            self._execute_ai_text_to_image(prompt, overrides=overrides)

        tk.Button(btn_frame, text="生成并作为图层", command=on_generate,
                 bg="#7B1FA2", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10, "bold"),
                 padx=20, pady=8).pack(side=tk.LEFT)

        tk.Button(btn_frame, text="取消", command=on_cancel,
                 bg="#999", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10),
                 padx=20, pady=8).pack(side=tk.LEFT, padx=10)

    def _execute_ai_text_to_image(self, prompt, overrides=None):
        """后台执行纯文字生成图片"""
        if not self.pages:
            return

        current_page = self.pages[self.current_page_index]

        progress_dialog = tk.Toplevel(self.root)
        progress_dialog.title("AI处理中")
        progress_dialog.geometry("420x160")
        progress_dialog.transient(self.root)
        progress_dialog.grab_set()

        tk.Label(progress_dialog, text="AI正在根据文字生成图片...",
                font=(FONT_FAMILY, 11, "bold")).pack(pady=20)

        progress_label = tk.Label(progress_dialog, text="正在初始化...",
                                 font=(FONT_FAMILY, 9), fg="#666")
        progress_label.pack(pady=10)

        def update_progress(message):
            def _update():
                try:
                    if progress_label.winfo_exists():
                        progress_label.config(text=message)
                except Exception:
                    pass

            try:
                self.root.after(0, _update)
            except Exception:
                pass

        def worker():
            try:
                # 纯文字生成，不传入源图片
                result_image = self.ai_api_manager.generate_image(
                    prompt,
                    source_image=None,
                    mask_image=None,
                    progress_callback=update_progress,
                    overrides=overrides,
                )
                if not result_image:
                    raise Exception("AI API未返回结果")

                temp_dir = os.path.join(get_base_dir(), "temp_backgrounds")
                os.makedirs(temp_dir, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                raw_path = os.path.join(temp_dir, f"ai_text_to_image_raw_{timestamp}.png")
                try:
                    result_image.save(raw_path)
                except Exception:
                    try:
                        result_image.convert("RGB").save(raw_path)
                    except Exception:
                        pass

                # 将生成的图片添加为图层，保持原始尺寸
                layer_name = f"AI文字生图 {timestamp}"
                layer_img = result_image.convert("RGBA") if result_image.mode != "RGBA" else result_image
                # 将图层居中放置
                page_w, page_h = current_page.get("image").size if current_page.get("image") else (0, 0)
                img_w, img_h = layer_img.size
                x = max(0, (page_w - img_w) // 2)
                y = max(0, (page_h - img_h) // 2)
                self.add_image_layer(current_page, layer_img, name=layer_name, x=x, y=y, opacity=1.0, visible=True)
                try:
                    self.layers = current_page.get("layers", [])
                except Exception:
                    pass

                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, self.update_layer_listbox)
                self.root.after(0, self.refresh_canvas)
                self.root.after(0, lambda: self.update_status("文字生图完成（图层已添加）"))
                self.root.after(0, lambda: self.mark_unsaved())
                self.root.after(0, lambda: messagebox.showinfo("成功", f"文字生图完成！\n\n已作为图层添加。\n原始返回已保存：\n{raw_path}"))

            except Exception as e:
                import traceback
                traceback.print_exc()
                err_text = str(e)
                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, lambda t=err_text: messagebox.showerror("错误", f"文字生图失败:\n{t}"))
                self.root.after(0, lambda: self.update_status("文字生图失败"))

        threading.Thread(target=worker, daemon=True).start()

    def ai_generate_fullpage_background(self):
        """把当前页整图发送给AI生成，返回结果作为图层叠加到当前页"""
        if not self.pages:
            messagebox.showwarning("提示", "请先导入图片")
            return

        current_page = self.pages[self.current_page_index]

        dialog = tk.Toplevel(self.root)
        dialog.title("AI整页生成背景")
        dialog.geometry("520x320")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="提示词（描述你希望整页生成的效果）",
                font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=15, pady=(15, 5))

        prompt_text = tk.Text(dialog, height=8, font=(FONT_FAMILY, 10), wrap=tk.WORD)
        prompt_text.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        prompt_text.insert("1.0", "在保持整体风格一致的前提下，生成一张可用作背景的图片。")

        api_type = self.ai_api_manager.config.get("api_type", "openai")
        use_gemini_args_var = tk.BooleanVar(value=False)
        gemini_image_size_var = tk.StringVar(value=self.ai_api_manager.config.get("gemini", {}).get("image_size", "1K"))
        # 默认用当前页比例（更容易与原图对齐）
        page_w, page_h = current_page.get("image").size if current_page.get("image") else (0, 0)
        gemini_aspect_ratio_var = tk.StringVar(value=self._best_ratio_label(page_w, page_h))

        if api_type == "gemini":
            args_frame = tk.LabelFrame(dialog, text="Gemini 参数（可选）", font=(FONT_FAMILY, 9, "bold"),
                                       padx=10, pady=6)
            args_frame.pack(fill=tk.X, padx=15, pady=(0, 10))

            tk.Checkbutton(
                args_frame,
                text="勾选后按本次参数生成",
                variable=use_gemini_args_var,
                font=(FONT_FAMILY, 9),
            ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 6))

            tk.Label(args_frame, text="分辨率:", font=(FONT_FAMILY, 9)).grid(row=1, column=0, sticky=tk.W)
            for i, val in enumerate(["1K", "2K", "4K"]):
                tk.Radiobutton(
                    args_frame,
                    text=val,
                    value=val,
                    variable=gemini_image_size_var,
                    font=(FONT_FAMILY, 9),
                ).grid(row=1, column=1 + i, sticky=tk.W, padx=6)

            tk.Label(args_frame, text="比例:", font=(FONT_FAMILY, 9)).grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
            ratio_vals = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4"]
            for i, val in enumerate(ratio_vals):
                tk.Radiobutton(
                    args_frame,
                    text=val,
                    value=val,
                    variable=gemini_aspect_ratio_var,
                    font=(FONT_FAMILY, 9),
                ).grid(row=3 + i // 4, column=i % 4, sticky=tk.W, padx=6)

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=15, pady=12)

        def on_cancel():
            dialog.destroy()

        def on_generate():
            prompt = prompt_text.get("1.0", tk.END).strip()
            if not prompt:
                messagebox.showwarning("提示", "请输入提示词")
                return
            dialog.destroy()
            overrides = None
            if api_type == "gemini" and use_gemini_args_var.get():
                overrides = {
                    "image_size": gemini_image_size_var.get(),
                    "aspect_ratio": gemini_aspect_ratio_var.get(),
                }
            self._execute_ai_fullpage(prompt, overrides=overrides)

        tk.Button(btn_frame, text="生成并作为图层", command=on_generate,
                 bg="#6A1B9A", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10, "bold"),
                 padx=20, pady=8).pack(side=tk.LEFT)

        tk.Button(btn_frame, text="取消", command=on_cancel,
                 bg="#999", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 10),
                 padx=20, pady=8).pack(side=tk.LEFT, padx=10)

    def _execute_ai_fullpage(self, prompt, overrides=None):
        """后台执行整页AI生成"""
        if not self.pages:
            return

        current_page = self.pages[self.current_page_index]

        if current_page.get("bg_path") and os.path.exists(current_page["bg_path"]):
            base_image = Image.open(current_page["bg_path"])
        else:
            base_image = current_page["image"].copy()

        # 自动选择更高分辨率，尽量避免“生成图被放大后变糊”（用户 overrides 优先）
        try:
            auto_overrides = self.ai_api_manager.suggest_overrides(*base_image.size)
            overrides = {**auto_overrides, **(overrides or {})}
        except Exception:
            overrides = overrides

        progress_dialog = tk.Toplevel(self.root)
        progress_dialog.title("AI处理中")
        progress_dialog.geometry("420x160")
        progress_dialog.transient(self.root)
        progress_dialog.grab_set()

        tk.Label(progress_dialog, text="AI正在生成整页背景...",
                font=(FONT_FAMILY, 11, "bold")).pack(pady=20)

        progress_label = tk.Label(progress_dialog, text="正在初始化...",
                                 font=(FONT_FAMILY, 9), fg="#666")
        progress_label.pack(pady=10)

        def update_progress(message):
            def _update():
                try:
                    if progress_label.winfo_exists():
                        progress_label.config(text=message)
                except Exception:
                    pass

            try:
                self.root.after(0, _update)
            except Exception:
                pass

        def worker():
            try:
                result_image = self.ai_api_manager.generate_image(
                    prompt,
                    source_image=base_image,
                    mask_image=None,
                    progress_callback=update_progress,
                    overrides=overrides,
                )
                if not result_image:
                    raise Exception("AI API未返回结果")

                temp_dir = os.path.join(get_base_dir(), "temp_backgrounds")
                os.makedirs(temp_dir, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                raw_path = os.path.join(temp_dir, f"ai_fullpage_raw_{timestamp}.png")
                try:
                    result_image.save(raw_path)
                except Exception:
                    try:
                        result_image.convert("RGB").save(raw_path)
                    except Exception:
                        pass

                # 生成结果需要与编辑图同尺寸，且不允许拉伸变形
                if result_image.size != base_image.size:
                    # 整页背景优先不裁切（避免“对照不上”）：等比缩放+留边
                    result_image = self._resize_contain_no_distort(result_image, base_image.size)

                layer_name = f"AI整页 {timestamp}"
                layer_img = result_image.convert("RGBA") if result_image.mode != "RGBA" else result_image
                self.add_image_layer(current_page, layer_img, name=layer_name, x=0, y=0, opacity=1.0, visible=True)
                try:
                    self.layers = current_page.get("layers", [])
                except Exception:
                    pass

                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, self.update_layer_listbox)
                self.root.after(0, self.refresh_canvas)
                self.root.after(0, lambda: self.update_status("整页生成完成（图层已添加）"))
                self.root.after(0, lambda: self.mark_unsaved())
                self.root.after(0, lambda: messagebox.showinfo("成功", f"整页生成完成！\n\n已作为图层叠加。\n原始返回已保存：\n{raw_path}"))

            except Exception as e:
                import traceback
                traceback.print_exc()
                err_text = str(e)
                self.root.after(0, progress_dialog.destroy)
                self.root.after(0, lambda t=err_text: messagebox.showerror("错误", f"整页生成失败:\n{t}"))
                self.root.after(0, lambda: self.update_status("整页生成失败"))

        threading.Thread(target=worker, daemon=True).start()

    def open_ai_api_settings(self):
        """打开AI API配置对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("AI图片生成API配置")
        dialog.geometry("650x650")
        dialog.transient(self.root)
        dialog.grab_set()

        # 标题
        title_frame = tk.Frame(dialog, bg="#9C27B0", height=60)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        tk.Label(title_frame, text="AI 图片生成 API 配置",
                bg="#9C27B0", fg="white",
                font=(FONT_FAMILY, 16, "bold")).pack(pady=15)

        # 主内容
        main_frame = tk.Frame(dialog, bg="white", padx=30, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # API类型选择
        tk.Label(main_frame, text="API类型:",
                bg="white", fg="#333",
                font=(FONT_FAMILY, 11, "bold")).grid(row=0, column=0, sticky=tk.W, pady=(0, 10))

        api_type_var = tk.StringVar(value=self.ai_api_manager.config.get("api_type", "openai"))

        api_frame = tk.Frame(main_frame, bg="white")
        api_frame.grid(row=0, column=1, sticky=tk.W, pady=(0, 10))

        # 流式传输（仅OpenAI）
        stream_var = tk.BooleanVar(value=self.ai_api_manager.config.get("openai", {}).get("stream", True))

        def on_api_type_change():
            api_type = api_type_var.get()
            provider_cfg = self.ai_api_manager.config.get(api_type, {})

            key_var.set(provider_cfg.get("api_key", ""))
            host_var.set(provider_cfg.get("api_host", ""))
            if api_type == "openai":
                model_var.set(provider_cfg.get("model", "gpt-4o"))
                stream_var.set(self.ai_api_manager.config.get("openai", {}).get("stream", True))
            else:
                model_var.set(provider_cfg.get("model", "gemini-2.0-flash-exp-image-generation"))

        tk.Radiobutton(
            api_frame,
            text="OpenAI格式",
            variable=api_type_var,
            value="openai",
            bg="white",
            font=(FONT_FAMILY, 10),
            command=on_api_type_change,
        ).pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(
            api_frame,
            text="Gemini格式",
            variable=api_type_var,
            value="gemini",
            bg="white",
            font=(FONT_FAMILY, 10),
            command=on_api_type_change,
        ).pack(side=tk.LEFT, padx=10)

        # API Key
        tk.Label(main_frame, text="API Key:",
                bg="white", fg="#333",
                font=(FONT_FAMILY, 11, "bold")).grid(row=1, column=0, sticky=tk.W, pady=(15, 5))

        key_var = tk.StringVar(value=self.ai_api_manager.config.get(
            api_type_var.get(), {}).get("api_key", ""))

        key_entry = tk.Entry(main_frame, textvariable=key_var, width=45,
                            font=(FONT_FAMILY, 10), show="*")
        key_entry.grid(row=1, column=1, sticky=tk.W, pady=(15, 5))

        # API Host
        tk.Label(main_frame, text="API Host:",
                bg="white", fg="#333",
                font=(FONT_FAMILY, 11, "bold")).grid(row=2, column=0, sticky=tk.W, pady=(10, 5))

        host_var = tk.StringVar(value=self.ai_api_manager.config.get(
            api_type_var.get(), {}).get("api_host", ""))

        tk.Entry(main_frame, textvariable=host_var, width=45,
                font=(FONT_FAMILY, 10)).grid(row=2, column=1, sticky=tk.W, pady=(10, 5))

        # 模型名称
        tk.Label(main_frame, text="模型:",
                bg="white", fg="#333",
                font=(FONT_FAMILY, 11, "bold")).grid(row=3, column=0, sticky=tk.W, pady=(10, 5))

        model_var = tk.StringVar(value=self.ai_api_manager.config.get(
            api_type_var.get(), {}).get("model", "gemini-3-pro-image-preview"))

        tk.Entry(main_frame, textvariable=model_var, width=45,
                font=(FONT_FAMILY, 10)).grid(row=3, column=1, sticky=tk.W, pady=(10, 5))

        tk.Checkbutton(
            main_frame,
            text="启用流式传输（仅OpenAI格式有效）",
            variable=stream_var,
            bg="white",
            font=(FONT_FAMILY, 10),
        ).grid(row=4, column=1, sticky=tk.W, pady=(15, 5))

        # 说明文字
        info_text = (
            "获取API Key:\n"
            "• OpenAI: https://platform.openai.com/api-keys\n"
            "• Gemini: https://makersuite.google.com/app/apikey\n\n"
            "使用代理:\n"
            "如使用API代理，请修改API Host地址"
        )
        tk.Label(main_frame, text=info_text, bg="#F5F5F5",
                fg="#666", font=(FONT_FAMILY, 8),
                justify=tk.LEFT, anchor=tk.W,
                padx=10, pady=10).grid(row=5, column=0, columnspan=2,
                                       sticky=tk.W+tk.E, pady=(20, 0))

        # 按钮区
        button_frame = tk.Frame(dialog, bg="white", pady=15)
        button_frame.pack(fill=tk.X)

        def save_and_close():
            # 保存配置
            api_type = api_type_var.get()
            self.ai_api_manager.config["api_type"] = api_type
            self.ai_api_manager.config[api_type]["api_key"] = key_var.get()
            self.ai_api_manager.config[api_type]["api_host"] = host_var.get()
            self.ai_api_manager.config[api_type]["model"] = model_var.get()
            if api_type == "openai":
                self.ai_api_manager.config["openai"]["stream"] = stream_var.get()

            self.config = self.ai_api_manager.save_config(self.config)
            save_config(self.config)
            messagebox.showinfo("成功", "API配置已保存")
            dialog.destroy()

        def test_connection():
            api_type = api_type_var.get()
            messagebox.showinfo("提示", f"{api_type.upper()} API 配置已设置\n\n请在实际使用中测试")

        tk.Button(button_frame, text="保存配置", command=save_and_close,
                 bg="#9C27B0", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 11, "bold"),
                 padx=30, pady=10).pack(side=tk.LEFT, padx=(30, 10))

        tk.Button(button_frame, text="取消", command=dialog.destroy,
                 bg="#999", fg="white", relief=tk.FLAT,
                 font=(FONT_FAMILY, 11),
                 padx=30, pady=10).pack(side=tk.LEFT, padx=10)

        # 初始化一次字段，保证默认模型等字段正确
        on_api_type_change()


if __name__ == "__main__":
    root = tk.Tk()
    app = ModernPPTEditor(root)
    root.mainloop()
