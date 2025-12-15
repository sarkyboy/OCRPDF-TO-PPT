"""
PPT编辑器模块化版本
====================

从 modern_ppt_editor_full_enhanced.py (5859行) 拆分而来
功能100%保持不变

目录结构:
---------
ppt_editor_modular/
├── __init__.py           # 包入口
├── editor_main.py        # 主编辑器类 (完整原始代码 - 5859行)
├── config.py             # 配置管理
├── constants.py          # 颜色和字体常量
├── textbox.py            # TextBox数据类
├── ai_image_api_module.py # AI图片API管理器
├── ui/                   # UI组件模块
│   ├── __init__.py
│   ├── toolbar.py        # 工具栏
│   ├── thumbnail.py      # 缩略图面板
│   ├── canvas_area.py    # 画布区域
│   ├── property_panel.py # 属性面板
│   └── status_bar.py     # 状态栏和标题栏
├── core/                 # 核心功能模块
│   ├── __init__.py
│   ├── ocr.py           # OCR文字识别
│   ├── history.py       # 撤销/重做
│   └── page_manager.py  # 页面管理
└── features/            # 功能模块
    ├── __init__.py
    ├── inpaint.py       # 涂抹擦除
    ├── ai_replace.py    # AI图片替换
    ├── export.py        # 导出(PPT/PDF/图片)
    └── project.py       # 项目保存/加载

使用方法:
---------
方式1: 运行启动脚本
    python run_ppt_editor.py

方式2: 作为模块导入
    from ppt_editor_modular import ModernPPTEditor
    import tkinter as tk
    root = tk.Tk()
    app = ModernPPTEditor(root)
    root.mainloop()

依赖库:
-------
必需:
- tkinter (Python内置)
- Pillow (PIL)
- opencv-python (cv2)
- numpy
- requests
- paddleocr
- paddlepaddle
- python-pptx

可选:
- PyMuPDF (fitz) - PDF支持

注意事项:
---------
1. editor_main.py 包含完整的原始代码，确保100%功能不变
2. ui/core/features 子模块为模板文件，供将来扩展参考
3. 配置文件保存在项目根目录的 ppt_editor_config.json
4. 自动保存目录在项目根目录的 autosave/

版本: 1.0.0
原始文件: modern_ppt_editor_full_enhanced.py
"""

# 版本信息
__version__ = '1.0.0'
__author__ = 'PPT Editor Team'

# 导入主编辑器
from .editor_main import ModernPPTEditor, TextBox

# 导入配置函数
from .config import load_config, save_config, get_base_dir

# 导入常量
from .constants import (
    COLOR_THEME, COLOR_THEME_HOVER, COLOR_RIBBON_BG, COLOR_RIBBON_ROW2,
    COLOR_CANVAS_BG, COLOR_SIDEBAR_BG, COLOR_WHITE, COLOR_TEXT,
    COLOR_BLUE, COLOR_GREEN, COLOR_ORANGE, COLOR_PURPLE, COLOR_RED, COLOR_GRAY,
    FONT_FAMILY, Px
)

# 导入AI API
from .ai_image_api_module import AIImageAPIManager, blend_images

# 导出列表
__all__ = [
    # 主类
    'ModernPPTEditor',
    'TextBox',
    # 配置
    'load_config',
    'save_config',
    'get_base_dir',
    # AI API
    'AIImageAPIManager',
    'blend_images',
    # 常量
    'COLOR_THEME', 'COLOR_THEME_HOVER', 'COLOR_RIBBON_BG', 'COLOR_RIBBON_ROW2',
    'COLOR_CANVAS_BG', 'COLOR_SIDEBAR_BG', 'COLOR_WHITE', 'COLOR_TEXT',
    'COLOR_BLUE', 'COLOR_GREEN', 'COLOR_ORANGE', 'COLOR_PURPLE', 'COLOR_RED', 'COLOR_GRAY',
    'FONT_FAMILY', 'Px'
]
