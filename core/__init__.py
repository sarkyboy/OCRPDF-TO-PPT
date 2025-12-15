"""
核心功能模块
- ocr: OCR文字识别功能
- history: 撤销/重做历史管理
- page_manager: 页面管理功能
- canvas_ops: 画布操作功能
"""

from .ocr import init_ocr, ocr_single_box, ocr_all_boxes
from .history import save_state, undo, redo
from .page_manager import save_current_page, load_current_page, prev_page, next_page

__all__ = [
    'init_ocr', 'ocr_single_box', 'ocr_all_boxes',
    'save_state', 'undo', 'redo',
    'save_current_page', 'load_current_page', 'prev_page', 'next_page'
]
