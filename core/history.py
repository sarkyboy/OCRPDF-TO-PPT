"""
历史管理模块 - 撤销/重做

说明：
- 这里的函数以 editor 实例作为第一个参数（等价于原先的 self）。
- 逻辑从 editor_main.ModernPPTEditor 中抽出，保持行为一致。
"""

from __future__ import annotations

import copy
import os
from datetime import datetime

from ..textbox import TextBox


def save_state(editor, operation_type: str = "textboxes", extra_data: dict | None = None) -> None:
    """
    保存当前状态到历史记录

    Args:
        operation_type: 操作类型
            - "textboxes": 文本框编辑
            - "background": 背景图生成
            - "inpaint_stroke": 涂抹操作
            - "layers": 当前页图层状态
            - "pages_layers": 全部页图层状态（批量操作用）
        extra_data: 额外数据（根据操作类型不同）
    """
    state: dict = {
        "type": operation_type,
        "page_index": editor.current_page_index,
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
    }

    if operation_type == "textboxes":
        state["data"] = {"text_boxes": [box.to_dict() for box in editor.text_boxes]}

    elif operation_type == "background":
        page = editor.pages[editor.current_page_index]
        state["data"] = {
            "old_bg_path": (extra_data or {}).get("old_bg_path", page.get("bg_path")),
            "new_bg_path": (extra_data or {}).get("new_bg_path"),
        }

    elif operation_type == "inpaint_stroke":
        state["data"] = {
            "stroke": (extra_data or {}).get("stroke"),
            "mask_state": editor.inpaint_strokes.copy() if editor.inpaint_strokes else [],
        }

    elif operation_type == "layers":
        page = editor.pages[editor.current_page_index] if editor.pages else None
        state["data"] = {"layers": copy.deepcopy(page.get("layers", []) if page else [])}

    elif operation_type == "pages_layers":
        pages_layers = []
        if editor.pages:
            for page in editor.pages:
                pages_layers.append(copy.deepcopy(page.get("layers", [])))
        state["data"] = {"pages_layers": pages_layers}

    if editor.history_index < len(editor.history) - 1:
        editor.history = editor.history[: editor.history_index + 1]

    editor.history.append(state)

    if len(editor.history) > editor.max_history:
        editor.history.pop(0)
    else:
        editor.history_index += 1


def undo(editor) -> None:
    """撤销操作"""
    if editor.history_index <= 0:
        editor.update_status("无法撤销")
        return

    editor.history_index -= 1
    restore_state(editor, editor.history[editor.history_index])
    editor.update_status("撤销 ?")


def redo(editor) -> None:
    """重做操作"""
    if editor.history_index >= len(editor.history) - 1:
        editor.update_status("无法重做")
        return

    editor.history_index += 1
    restore_state(editor, editor.history[editor.history_index])
    editor.update_status("重做 ?")


def restore_state(editor, state: dict) -> None:
    """
    恢复历史状态

    Args:
        state: 历史记录项
    """
    operation_type = state["type"]
    page_index = state["page_index"]
    data = state["data"]

    if page_index != editor.current_page_index:
        editor.save_current_page()
        editor.current_page_index = page_index
        editor.load_current_page()

    if operation_type == "textboxes":
        editor.text_boxes = [TextBox.from_dict(box_data) for box_data in data["text_boxes"]]
        editor.selected_box_index = -1
        editor.selected_boxes = []
        editor.refresh_canvas()
        editor.update_listbox()

    elif operation_type == "background":
        page = editor.pages[editor.current_page_index]
        old_bg_path = data["old_bg_path"]

        if old_bg_path and os.path.exists(old_bg_path):
            page["bg_path"] = old_bg_path
            editor.clean_bg_path = old_bg_path
        else:
            page["bg_path"] = None
            editor.clean_bg_path = None

        editor.update_bg_status()
        editor.update_thumbnails()
        editor.refresh_canvas()

    elif operation_type == "inpaint_stroke":
        mask_state = data.get("mask_state", [])
        editor.inpaint_strokes = mask_state.copy()
        if editor.inpaint_mode and editor.original_image:
            editor.rebuild_inpaint_mask()

    elif operation_type == "layers":
        page = editor.pages[editor.current_page_index]
        page["layers"] = copy.deepcopy(data.get("layers", []))
        editor.layers = page.get("layers", [])
        if hasattr(editor, "update_layer_listbox"):
            editor.update_layer_listbox()
        editor.refresh_canvas()

    elif operation_type == "pages_layers":
        pages_layers = data.get("pages_layers", [])
        if editor.pages and pages_layers and len(pages_layers) == len(editor.pages):
            for i, layers in enumerate(pages_layers):
                editor.pages[i]["layers"] = copy.deepcopy(layers)
        page = editor.pages[editor.current_page_index] if editor.pages else None
        if page is not None:
            editor.layers = page.get("layers", [])
        if hasattr(editor, "update_layer_listbox"):
            editor.update_layer_listbox()
        editor.refresh_canvas()

    editor.mark_unsaved()
