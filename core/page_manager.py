"""
页面/缩略图/画布缩放相关逻辑

说明：
- 以 editor 实例作为第一个参数（等价于原先的 self）。
- 这里抽出了与页面切换、缩略图、背景状态、画布缩放相关的实现。
"""

from __future__ import annotations

import os

import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk

from ..constants import COLOR_GREEN
from ..textbox import TextBox


def update_bg_status(editor) -> None:
    """更新背景状态显示"""
    if editor.clean_bg_path:
        bg_name = os.path.basename(editor.clean_bg_path)
        if len(bg_name) > 25:
            bg_name = bg_name[:22] + "..."
        editor.bg_status_label.config(text=f"已设置: {bg_name}", fg=COLOR_GREEN)
    else:
        editor.bg_status_label.config(text="未设置背景", fg="#999")


def save_current_page(editor) -> None:
    """保存当前页数据"""
    if not editor.pages or editor.current_page_index >= len(editor.pages):
        return
    page = editor.pages[editor.current_page_index]
    page["text_boxes"] = [box.to_dict() for box in editor.text_boxes]
    page["bg_path"] = editor.clean_bg_path
    page["layers"] = getattr(editor, "layers", page.get("layers", []))


def load_current_page(editor) -> None:
    """加载当前页数据"""
    if not editor.pages or editor.current_page_index >= len(editor.pages):
        return

    page = editor.pages[editor.current_page_index]
    editor.original_img_path = page["original_path"]
    editor.original_image = page["image"]
    editor.clean_bg_path = page.get("bg_path")
    editor.text_boxes = [TextBox.from_dict(d) for d in page.get("text_boxes", [])]
    editor.layers = page.setdefault("layers", [])
    editor.selected_box_index = -1
    editor.selected_boxes = []

    editor.fit_image_to_canvas()
    editor.update_listbox()
    if hasattr(editor, "update_layer_listbox"):
        editor.update_layer_listbox()
    editor.update_status_info()
    editor.update_bg_status()


def prev_page(editor) -> None:
    """上一页"""
    if not editor.pages or editor.current_page_index <= 0:
        return
    editor.save_current_page()
    editor.current_page_index -= 1
    editor.load_current_page()
    editor.update_page_label()
    editor.highlight_current_thumbnail()


def next_page(editor) -> None:
    """下一页"""
    if not editor.pages or editor.current_page_index >= len(editor.pages) - 1:
        return
    editor.save_current_page()
    editor.current_page_index += 1
    editor.load_current_page()
    editor.update_page_label()
    editor.highlight_current_thumbnail()


def update_page_label(editor) -> None:
    """更新页码"""
    if editor.pages:
        page_text = f"{editor.current_page_index + 1}/{len(editor.pages)}"
        editor.page_label.config(text=page_text)
        editor.title_page_label.config(text=f"第 {page_text} 页")
    else:
        editor.page_label.config(text="0/0")
        editor.title_page_label.config(text="第 0/0 页")


def update_status_info(editor) -> None:
    """更新状态栏信息"""
    if editor.pages and editor.original_image:
        w, h = editor.original_image.size
        boxes = len(editor.text_boxes)
        editor.status_info.config(
            text=f"尺寸: {w}×{h} | 文本框: {boxes} | 缩放: {int(editor.scale*100)}%"
        )
        editor.zoom_label.config(text=f"{int(editor.scale*100)}%")


def update_thumbnails(editor) -> None:
    """更新缩略图"""
    for widget in editor.thumbnail_frame.winfo_children():
        widget.destroy()
    editor.thumbnail_images = []

    for idx, page in enumerate(editor.pages):
        frame = tk.Frame(editor.thumbnail_frame, bg="#ffffff", cursor="hand2", relief=tk.GROOVE, bd=1)
        frame.pack(fill=tk.X, padx=5, pady=3)

        # 缩略图以“合成底图”为准（背景/图层都会体现），更接近 PS/PPT 的预览体验
        try:
            img = editor.get_page_composited_background(page) or page["image"].copy()
        except Exception:
            img = page["image"].copy()
        img.thumbnail((110, 70), Image.Resampling.LANCZOS)
        tk_img = ImageTk.PhotoImage(img)
        editor.thumbnail_images.append(tk_img)

        label = tk.Label(frame, image=tk_img, bg="#ffffff")
        label.pack(padx=2, pady=2)

        has_bg = "✓" if page.get("bg_path") else ""
        has_layers = "层" if page.get("layers") else ""
        page_num = tk.Label(
            frame,
            text=f"第 {idx + 1} 页 {has_bg}{has_layers}",
            bg="#ffffff",
            fg="#666666" if (not has_bg and not has_layers) else COLOR_GREEN,
            font=("微软雅黑", 8),
        )
        page_num.pack()

        frame.bind("<Button-1>", lambda e, i=idx: editor.go_to_page(i))
        label.bind("<Button-1>", lambda e, i=idx: editor.go_to_page(i))
        page_num.bind("<Button-1>", lambda e, i=idx: editor.go_to_page(i))

        frame.bind("<Button-3>", lambda e, i=idx: editor.show_thumbnail_menu(e, i))
        label.bind("<Button-3>", lambda e, i=idx: editor.show_thumbnail_menu(e, i))
        page_num.bind("<Button-3>", lambda e, i=idx: editor.show_thumbnail_menu(e, i))

    editor.highlight_current_thumbnail()


def show_thumbnail_menu(editor, event, page_index: int) -> None:
    """显示缩略图右键菜单"""
    menu = tk.Menu(editor.root, tearoff=0)
    menu.add_command(
        label=f"设置第 {page_index + 1} 页背景", command=lambda: editor.set_page_background(page_index)
    )
    menu.add_command(
        label=f"清除第 {page_index + 1} 页背景", command=lambda: editor.clear_page_background(page_index)
    )
    menu.add_separator()
    menu.add_command(label=f"删除第 {page_index + 1} 页", command=lambda: editor.delete_page(page_index))
    menu.post(event.x_root, event.y_root)


def set_page_background(editor, page_index: int) -> None:
    """为指定页设置背景图"""
    if page_index < 0 or page_index >= len(editor.pages):
        return

    file_path = filedialog.askopenfilename(
        title=f"选择第 {page_index + 1} 页的背景图", filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp")]
    )
    if not file_path:
        return

    page = editor.pages[page_index]
    edit_size = page["image"].size

    resized_bg_path = editor._resize_bg_to_match(file_path, edit_size)
    page["bg_path"] = resized_bg_path

    if page_index == editor.current_page_index:
        editor.clean_bg_path = resized_bg_path
        editor.update_bg_status()
        editor.refresh_canvas()

    editor.update_thumbnails()
    editor.update_status(f"第 {page_index + 1} 页背景已设置")


def clear_page_background(editor, page_index: int) -> None:
    """清除指定页的背景图"""
    if page_index < 0 or page_index >= len(editor.pages):
        return

    editor.pages[page_index]["bg_path"] = None

    if page_index == editor.current_page_index:
        editor.clean_bg_path = None
        editor.update_bg_status()
        editor.refresh_canvas()

    editor.update_thumbnails()
    editor.update_status(f"第 {page_index + 1} 页背景已清除")


def delete_page(editor, page_index: int) -> None:
    """删除指定页"""
    if page_index < 0 or page_index >= len(editor.pages):
        return

    if len(editor.pages) <= 1:
        messagebox.showwarning("提示", "至少保留一页")
        return

    result = messagebox.askyesno("确认", f"确定删除第 {page_index + 1} 页？")
    if not result:
        return

    del editor.pages[page_index]

    if editor.current_page_index >= len(editor.pages):
        editor.current_page_index = len(editor.pages) - 1
    elif editor.current_page_index > page_index:
        editor.current_page_index -= 1

    editor.load_current_page()
    editor.update_page_label()
    editor.update_thumbnails()
    editor.update_status(f"已删除页面，剩余 {len(editor.pages)} 页")


def highlight_current_thumbnail(editor) -> None:
    """高亮当前页缩略图"""
    for idx, widget in enumerate(editor.thumbnail_frame.winfo_children()):
        if idx == editor.current_page_index:
            widget.config(bg="#bbdefb", relief=tk.SOLID, bd=2)
            for child in widget.winfo_children():
                child.config(bg="#bbdefb")
        else:
            widget.config(bg="#ffffff", relief=tk.GROOVE, bd=1)
            for child in widget.winfo_children():
                child.config(bg="#ffffff")


def go_to_page(editor, index: int) -> None:
    """跳转到指定页"""
    if 0 <= index < len(editor.pages):
        editor.save_current_page()
        editor.current_page_index = index
        editor.load_current_page()
        editor.update_page_label()
        editor.highlight_current_thumbnail()


def fit_image_to_canvas(editor) -> None:
    """自适应显示图片"""
    if not editor.original_image:
        return

    canvas_w = editor.canvas.winfo_width()
    canvas_h = editor.canvas.winfo_height()

    if canvas_w < 10 or canvas_h < 10:
        editor.root.after(100, editor.fit_image_to_canvas)
        return

    img_w, img_h = editor.original_image.size
    scale_w = (canvas_w - 40) / img_w
    scale_h = (canvas_h - 40) / img_h
    editor.scale = min(scale_w, scale_h, 1.0)

    editor.refresh_canvas()


def on_canvas_resize(editor, event) -> None:
    """画布大小改变"""
    if editor.original_image:
        editor.fit_image_to_canvas()


def on_canvas_zoom(editor, event) -> None:
    """Ctrl+滚轮缩放"""
    if not editor.original_image:
        return

    # 获取鼠标位置作为缩放中心（保留原逻辑）
    _ = editor.canvas.canvasx(event.x)
    _ = editor.canvas.canvasy(event.y)

    factor = 1.1 if event.delta > 0 else 0.9

    new_scale = editor.scale * factor
    new_scale = max(0.1, min(new_scale, 3.0))

    if new_scale != editor.scale:
        editor.scale = new_scale
        editor.refresh_canvas()
        editor.update_status(f"缩放: {int(editor.scale * 100)}%")


def on_canvas_scroll(editor, event) -> None:
    """普通滚轮滚动"""
    editor.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


def zoom_to_100(editor) -> None:
    """缩放到100%"""
    if not editor.original_image:
        return
    editor.scale = 1.0
    editor.refresh_canvas()
    editor.update_status("缩放: 100%")
