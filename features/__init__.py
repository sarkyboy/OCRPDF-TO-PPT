"""
功能模块
- inpaint: 涂抹擦除功能
- ai_replace: AI图片替换功能
- export: 导出功能（PPT、PDF、图片）
- project: 项目保存/加载
"""

from .inpaint import toggle_inpaint_mode, generate_bg_from_custom_mask
from .ai_replace import toggle_ai_replace_mode, apply_ai_replace
from .export import generate_multi_page_ppt, export_as_pdf, export_as_images
from .project import save_project, load_project

__all__ = [
    'toggle_inpaint_mode', 'generate_bg_from_custom_mask',
    'toggle_ai_replace_mode', 'apply_ai_replace',
    'generate_multi_page_ppt', 'export_as_pdf', 'export_as_images',
    'save_project', 'load_project'
]
