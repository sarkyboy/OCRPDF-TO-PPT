"""
项目管理功能模块 - 保存/加载项目

说明：
- 这里的函数以 editor 实例作为第一个参数（等价于原先的 self）。
"""

from __future__ import annotations

import json
import os

from tkinter import filedialog, messagebox
from PIL import Image


def save_project(editor) -> None:
    editor.save_current_page()

    file_path = filedialog.asksaveasfilename(
        defaultextension=".json",
        filetypes=[("JSON文件", "*.json")],
    )
    if not file_path:
        return

    pages_data: list[dict] = []
    for page in editor.pages:
        pages_data.append(
            {
                "original_path": page["original_path"],
                "original_size": page.get("original_size", page["image"].size),
                "edit_scale": page.get("edit_scale", 1.0),
                "bg_path": page.get("bg_path"),
                "bg_original_path": page.get("bg_original_path"),
                "text_boxes": page.get("text_boxes", []),
                "layers": page.get("layers", []),
            }
        )

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(
            {"version": 3, "pages": pages_data, "current_page": editor.current_page_index},
            f,
            ensure_ascii=False,
            indent=2,
        )

    editor.update_status(f"项目已保存: {len(editor.pages)} 页 ?")
    editor.mark_saved()


def load_project(editor) -> None:
    file_path = filedialog.askopenfilename(filetypes=[("JSON文件", "*.json")])
    if not file_path:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        editor.pages = []
        for page_info in data.get("pages", []):
            if os.path.exists(page_info["original_path"]):
                original_img = Image.open(page_info["original_path"])
                original_size = page_info.get("original_size", original_img.size)

                edit_img, edit_scale = editor._resize_image_for_edit(original_img)

                editor.pages.append(
                    {
                        "original_path": page_info["original_path"],
                        "original_size": original_size,
                        "edit_scale": edit_scale,
                        "bg_path": page_info.get("bg_path"),
                        "bg_original_path": page_info.get("bg_original_path"),
                        "image": edit_img,
                        "text_boxes": page_info.get("text_boxes", []),
                        "layers": page_info.get("layers", []),
                    }
                )

        editor.current_page_index = min(
            data.get("current_page", 0),
            len(editor.pages) - 1 if editor.pages else 0,
        )

        if editor.pages:
            editor.load_current_page()
            editor.update_page_label()
            editor.update_thumbnails()
            editor.placeholder_label.place_forget()

        editor.update_status(f"已加载 {len(editor.pages)} 页项目 ?")
        editor.mark_saved()

    except Exception as e:
        messagebox.showerror("错误", f"加载失败: {e}")
