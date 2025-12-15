"""
AI图片替换功能模块
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

import tkinter as tk
from PIL import Image, ImageDraw
from tkinter import messagebox

from ..config import get_base_dir
from ..constants import FONT_FAMILY


def toggle_ai_replace_mode(editor):
    """切换AI替换模式"""
    if not editor.pages:
        messagebox.showwarning("提示", "请先导入图片")
        return

    editor.save_current_page()
    editor.ai_replace_mode = not editor.ai_replace_mode

    if editor.ai_replace_mode:
        editor.ai_replace_mode_btn.config(text="退出AI替换", bg="#F50057")
        if editor.inpaint_mode:
            editor.toggle_inpaint_mode()
        editor.ai_replace_selection = None
        if editor.ai_replace_rect_id:
            editor.canvas.delete(editor.ai_replace_rect_id)
            editor.ai_replace_rect_id = None
        editor.update_status("AI替换模式已激活 - 框选要替换的区域")
        messagebox.showinfo(
            "AI替换模式",
            "已进入AI替换模式！\n\n"
            "?? 操作步骤：\n"
            "1. 用鼠标框选要替换/编辑的区域\n"
            "2. 输入提示词描述想要的效果\n"
            "3. 等待AI生成并自动融合\n\n"
            "?? 提示：\n"
            "- 可以在原图或背景图上框选\n"
            "- 支持多次编辑和迭代",
        )
        return

    editor.ai_replace_mode_btn.config(text="AI替换", bg="#E91E63")
    if editor.ai_replace_rect_id:
        editor.canvas.delete(editor.ai_replace_rect_id)
        editor.ai_replace_rect_id = None
    editor.ai_replace_selection = None
    editor.update_status("已退出AI替换模式")


def handle_ai_replace_press(editor, x, y):
    """AI替换模式 - 按下事件"""
    editor.ai_replace_rect_start = (x, y)


def handle_ai_replace_drag(editor, canvas_x, canvas_y):
    """AI替换模式 - 拖拽事件"""
    if not editor.ai_replace_rect_start:
        return
    if editor.ai_replace_rect_id:
        editor.canvas.delete(editor.ai_replace_rect_id)

    img_x, img_y = editor.ai_replace_rect_start
    canvas_x1 = img_x * editor.scale + getattr(editor, "canvas_offset_x", 0)
    canvas_y1 = img_y * editor.scale + getattr(editor, "canvas_offset_y", 0)

    editor.ai_replace_rect_id = editor.canvas.create_rectangle(
        canvas_x1,
        canvas_y1,
        canvas_x,
        canvas_y,
        outline="#E91E63",
        width=3,
        dash=(5, 5),
    )


def handle_ai_replace_release(editor, canvas_x, canvas_y):
    """AI替换模式 - 释放事件"""
    if not editor.ai_replace_rect_start:
        return

    img_x = (canvas_x - getattr(editor, "canvas_offset_x", 0)) / editor.scale
    img_y = (canvas_y - getattr(editor, "canvas_offset_y", 0)) / editor.scale

    x1, y1 = editor.ai_replace_rect_start
    x1, x2 = min(x1, img_x), max(x1, img_x)
    y1, y2 = min(y1, img_y), max(y1, img_y)

    if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
        messagebox.showwarning("提示", "选框太小，请重新框选")
        if editor.ai_replace_rect_id:
            editor.canvas.delete(editor.ai_replace_rect_id)
            editor.ai_replace_rect_id = None
        editor.ai_replace_rect_start = None
        return

    editor.ai_replace_selection = (int(x1), int(y1), int(x2), int(y2))
    editor.ai_replace_rect_start = None
    show_ai_replace_dialog(editor)


def show_ai_replace_dialog(editor):
    """显示AI替换操作对话框"""
    if not editor.ai_replace_selection:
        return

    x1, y1, x2, y2 = editor.ai_replace_selection

    dialog = tk.Toplevel(editor.root)
    dialog.title("AI图片替换/生成")
    dialog.geometry("500x350")
    dialog.transient(editor.root)
    dialog.grab_set()

    title_frame = tk.Frame(dialog, bg="#E91E63", height=50)
    title_frame.pack(fill=tk.X)
    title_frame.pack_propagate(False)

    tk.Label(
        title_frame,
        text="AI 图片替换/生成",
        bg="#E91E63",
        fg="white",
        font=(FONT_FAMILY, 14, "bold"),
    ).pack(pady=10)

    content_frame = tk.Frame(dialog, bg="white", padx=20, pady=20)
    content_frame.pack(fill=tk.BOTH, expand=True)

    info_text = f"已选中区域: {x2 - x1}×{y2 - y1} 像素"
    tk.Label(content_frame, text=info_text, bg="white", fg="#666", font=(FONT_FAMILY, 9)).pack(
        anchor=tk.W, pady=(0, 10)
    )

    tk.Label(content_frame, text="提示词:", bg="white", fg="#333", font=(FONT_FAMILY, 10, "bold")).pack(
        anchor=tk.W, pady=(10, 5)
    )

    prompt_frame = tk.Frame(content_frame, bg="white")
    prompt_frame.pack(fill=tk.BOTH, expand=True, pady=5)

    prompt_text = tk.Text(prompt_frame, height=5, font=(FONT_FAMILY, 9), relief=tk.SOLID, borderwidth=1)
    prompt_text.pack(fill=tk.BOTH, expand=True)

    api_type = editor.ai_api_manager.config.get("api_type", "openai")
    use_gemini_args_var = tk.BooleanVar(value=False)
    gemini_image_size_var = tk.StringVar(value=editor.ai_api_manager.config.get("gemini", {}).get("image_size", "1K"))
    gemini_aspect_ratio_var = tk.StringVar(value=editor._best_ratio_label(x2 - x1, y2 - y1))

    if api_type == "gemini":
        args_frame = tk.LabelFrame(
            content_frame,
            text="Gemini 参数（可选）",
            bg="white",
            fg="#333",
            font=(FONT_FAMILY, 9, "bold"),
            padx=10,
            pady=6,
        )
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

    tk.Label(content_frame, text="快速模板:", bg="white", fg="#666", font=(FONT_FAMILY, 9)).pack(
        anchor=tk.W, pady=(10, 5)
    )
    template_frame = tk.Frame(content_frame, bg="white")
    template_frame.pack(anchor=tk.W)

    def set_prompt(template):
        prompt_text.delete("1.0", tk.END)
        prompt_text.insert("1.0", template)

    templates = [
        ("换成苹果", "Replace with a red apple"),
        ("去除物体", "Remove this object and generate clean background"),
        ("油画风格", "Transform to oil painting style"),
        ("卡通风格", "Transform to cartoon style"),
    ]

    for i, (label, template) in enumerate(templates):
        btn = tk.Button(
            template_frame,
            text=label,
            command=lambda t=template: set_prompt(t),
            bg="#F5F5F5",
            relief=tk.FLAT,
            font=(FONT_FAMILY, 8),
        )
        btn.grid(row=i // 2, column=i % 2, padx=5, pady=2, sticky=tk.W)

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
        execute_ai_replace(editor, prompt, overrides=overrides)

    def on_cancel():
        if editor.ai_replace_rect_id:
            editor.canvas.delete(editor.ai_replace_rect_id)
            editor.ai_replace_rect_id = None
        editor.ai_replace_selection = None
        dialog.destroy()

    tk.Button(
        button_frame,
        text="生成/替换",
        command=on_generate,
        bg="#E91E63",
        fg="white",
        relief=tk.FLAT,
        font=(FONT_FAMILY, 10, "bold"),
        padx=30,
        pady=8,
    ).pack(side=tk.LEFT, padx=(20, 10))

    tk.Button(
        button_frame,
        text="取消",
        command=on_cancel,
        bg="#999",
        fg="white",
        relief=tk.FLAT,
        font=(FONT_FAMILY, 10),
        padx=30,
        pady=8,
    ).pack(side=tk.LEFT)


def execute_ai_replace(editor, prompt, overrides=None):
    """执行AI替换"""
    if not editor.ai_replace_selection:
        return

    x1, y1, x2, y2 = editor.ai_replace_selection
    current_page = editor.pages[editor.current_page_index]
    try:
        auto_overrides = editor.ai_api_manager.suggest_overrides(x2 - x1, y2 - y1)
        overrides = {**auto_overrides, **(overrides or {})}
    except Exception:
        overrides = overrides

    if current_page.get("bg_path") and os.path.exists(current_page["bg_path"]):
        base_image = Image.open(current_page["bg_path"])
    else:
        base_image = current_page["image"].copy()

    crop_box = (x1, y1, x2, y2)
    cropped_image = base_image.crop(crop_box)

    mask = Image.new("L", base_image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rectangle([x1, y1, x2, y2], fill=255)
    cropped_mask = mask.crop(crop_box)

    progress_dialog = tk.Toplevel(editor.root)
    progress_dialog.title("AI处理中")
    progress_dialog.geometry("400x150")
    progress_dialog.transient(editor.root)
    progress_dialog.grab_set()

    tk.Label(progress_dialog, text="AI正在处理图片...", font=(FONT_FAMILY, 11, "bold")).pack(pady=20)
    progress_label = tk.Label(progress_dialog, text="正在初始化...", font=(FONT_FAMILY, 9), fg="#666")
    progress_label.pack(pady=10)

    def update_progress(message):
        def _update():
            try:
                if progress_label.winfo_exists():
                    progress_label.config(text=message)
            except Exception:
                pass

        try:
            editor.root.after(0, _update)
        except Exception:
            pass

    def process_in_thread():
        try:
            result_image = editor.ai_api_manager.image_to_image(
                prompt,
                cropped_image,
                cropped_mask,
                update_progress,
                overrides=overrides,
            )

            if not result_image:
                raise Exception("AI API未返回结果")

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

            if result_image.size != cropped_image.size:
                result_image = editor._resize_cover_no_distort(result_image, cropped_image.size)

            layer_name = f"AI替换 {timestamp}"
            layer_img = result_image.convert("RGBA") if result_image.mode != "RGBA" else result_image
            editor.add_image_layer(
                current_page,
                layer_img,
                name=layer_name,
                x=x1,
                y=y1,
                opacity=1.0,
                visible=True,
            )
            try:
                editor.layers = current_page.get("layers", [])
            except Exception:
                pass

            editor.root.after(0, progress_dialog.destroy)
            editor.root.after(0, editor.update_layer_listbox)
            editor.root.after(0, editor.refresh_canvas)
            editor.root.after(0, editor.mark_unsaved)

            if editor.ai_replace_rect_id:
                editor.root.after(0, lambda: editor.canvas.delete(editor.ai_replace_rect_id))
                editor.ai_replace_rect_id = None
            editor.ai_replace_selection = None

            editor.root.after(
                0,
                lambda: messagebox.showinfo(
                    "成功",
                    "AI替换完成！\n\n"
                    "? 已作为图层叠加（右侧“图层”可隐藏/删除/调透明度）\n"
                    f"?? 原始返回已保存：{raw_path}\n\n"
                    "?? 可继续框选其他区域进行编辑",
                ),
            )
            editor.root.after(0, lambda: editor.update_status("AI替换完成"))

        except Exception as e:
            print(f"AI替换失败: {e}")
            import traceback

            traceback.print_exc()
            editor.root.after(0, progress_dialog.destroy)
            editor.root.after(
                0,
                lambda: messagebox.showerror(
                    "错误",
                    f"AI替换失败:\n{str(e)}\n\n"
                    "请检查:\n"
                    "1. API配置是否正确\n"
                    "2. API Key是否有效\n"
                    "3. 网络连接是否正常",
                ),
            )
            editor.root.after(0, lambda: editor.update_status("AI替换失败"))

    threading.Thread(target=process_in_thread, daemon=True).start()


def apply_ai_replace(editor, selection, prompt, overrides=None):
    """应用AI替换（提供给外部调用的快捷接口）"""
    editor.ai_replace_selection = selection
    return execute_ai_replace(editor, prompt, overrides=overrides)
