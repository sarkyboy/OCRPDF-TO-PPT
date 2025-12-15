"""
涂抹擦除功能模块
"""

from __future__ import annotations

import base64
import os
import threading
from datetime import datetime
from io import BytesIO

import numpy as np
import requests
import tkinter as tk
from PIL import Image, ImageDraw, ImageFilter
from tkinter import messagebox

from ..config import get_base_dir
from ..constants import COLOR_RIBBON_BG


def toggle_inpaint_mode(editor):
    """切换涂抹模式"""
    if not editor.pages or not editor.original_image:
        messagebox.showwarning("提示", "请先导入图片")
        return

    editor.inpaint_mode = not editor.inpaint_mode

    if editor.inpaint_mode:
        editor.inpaint_mode_btn.config(text="退出涂抹", bg="#FF5722")

        editor.inpaint_tools_frame.pack(side=tk.LEFT, after=editor.inpaint_mode_btn)
        editor.brush_size_frame.pack(side=tk.LEFT, after=editor.inpaint_tools_frame)
        editor.inpaint_actions_frame.pack(side=tk.LEFT, after=editor.brush_size_frame)

        # 以当前“合成底图”为准：背景/图层都会参与，涂抹坐标与画布显示保持一致。
        base_image = None
        try:
            base_image = editor.get_current_page_composited_background()
        except Exception:
            base_image = None
        if base_image is None:
            base_image = editor.original_image

        if editor.inpaint_mask_layer is None or editor.inpaint_mask_layer.size != base_image.size:
            editor.inpaint_mask_layer = Image.new("L", base_image.size, 0)
            editor.inpaint_draw_layer = ImageDraw.Draw(editor.inpaint_mask_layer)
            editor.inpaint_strokes = []

        if editor.inpaint_tool == "brush":
            editor.canvas.config(cursor="dot")
        else:
            editor.canvas.config(cursor="tcross")

        editor.selected_box_index = -1
        editor.selected_boxes = []
        editor.refresh_canvas()

        editor.update_status("涂抹模式已激活 - 标记需要去除的区域")
        messagebox.showinfo(
            "涂抹模式",
            "已进入涂抹模式！\n\n"
            "笔刷工具 - 涂抹标记区域\n"
            "框选工具 - 拉框标记区域\n"
            "点击「生成背景」处理标记区域（结果将作为新图层叠加，不会替换原图）\n\n"
            "提示：可以与 OCR 检测结合使用\n"
            "先 OCR 检测文字，再手动补充遗漏区域",
        )
        return

    editor.inpaint_mode_btn.config(text="进入涂抹", bg="#FF6F00")

    editor.inpaint_tools_frame.pack_forget()
    editor.brush_size_frame.pack_forget()
    editor.inpaint_actions_frame.pack_forget()

    editor.canvas.config(cursor="")
    editor.canvas.delete("inpaint_visual")
    editor.canvas.delete("inpaint_temp")

    editor.update_status("已退出涂抹模式")


def switch_inpaint_tool(editor, tool):
    """切换涂抹工具"""
    editor.inpaint_tool = tool

    if tool == "brush":
        editor.brush_btn.config(relief=tk.SUNKEN, bg="#FFE0B2")
        editor.rect_btn.config(relief=tk.RAISED, bg=COLOR_RIBBON_BG)
        editor.canvas.config(cursor="dot")
        return

    editor.brush_btn.config(relief=tk.RAISED, bg=COLOR_RIBBON_BG)
    editor.rect_btn.config(relief=tk.SUNKEN, bg="#FFE0B2")
    editor.canvas.config(cursor="tcross")


def update_brush_size(editor, val):
    """更新笔刷大小"""
    editor.inpaint_brush_size = int(float(val))


def handle_inpaint_press(editor, x, y):
    """涂抹模式 - 按下事件"""
    if editor.inpaint_tool == "brush":
        r = editor.inpaint_brush_size // 2
        editor.inpaint_draw_layer.ellipse([x - r, y - r, x + r, y + r], fill=255, outline=255)
        editor.inpaint_last_pos = (x, y)
        draw_inpaint_visual_brush(editor, x, y, r)
        editor.inpaint_strokes.append({"type": "brush", "points": [(x, y)]})
        return

    editor.inpaint_rect_start = (x, y)


def handle_inpaint_drag(editor, x, y):
    """涂抹模式 - 拖拽事件"""
    if editor.inpaint_tool == "brush":
        r = editor.inpaint_brush_size // 2
        editor.inpaint_draw_layer.ellipse([x - r, y - r, x + r, y + r], fill=255, outline=255)

        if editor.inpaint_last_pos:
            editor.inpaint_draw_layer.line(
                [editor.inpaint_last_pos, (x, y)],
                fill=255,
                width=editor.inpaint_brush_size,
            )

        editor.inpaint_last_pos = (x, y)
        draw_inpaint_visual_brush(editor, x, y, r)
        if editor.inpaint_strokes and editor.inpaint_strokes[-1]["type"] == "brush":
            editor.inpaint_strokes[-1]["points"].append((x, y))
        return

    if editor.inpaint_rect_start:
        draw_inpaint_temp_rect(editor, x, y)


def handle_inpaint_release(editor, x, y):
    """涂抹模式 - 释放事件"""
    if editor.inpaint_tool == "brush":
        editor.inpaint_last_pos = None
        if editor.inpaint_strokes and editor.inpaint_strokes[-1]["type"] == "brush":
            editor.save_state(
                "inpaint_stroke",
                {
                    "stroke": editor.inpaint_strokes[-1],
                    "mask_state": editor.inpaint_strokes[:-1],
                },
            )
        return

    if not editor.inpaint_rect_start:
        return

    sx, sy = editor.inpaint_rect_start
    x1, y1 = min(sx, x), min(sy, y)
    x2, y2 = max(sx, x), max(sy, y)

    editor.inpaint_draw_layer.rectangle([x1, y1, x2, y2], fill=255, outline=255)
    draw_inpaint_visual_rect(editor, x1, y1, x2, y2)
    editor.canvas.delete("inpaint_temp")

    rect_stroke = {"type": "rect", "coords": (x1, y1, x2, y2)}
    editor.inpaint_strokes.append(rect_stroke)
    editor.save_state(
        "inpaint_stroke",
        {
            "stroke": rect_stroke,
            "mask_state": editor.inpaint_strokes[:-1],
        },
    )
    editor.inpaint_rect_start = None


def draw_inpaint_visual_brush(editor, x, y, radius):
    """绘制笔刷涂抹的视觉反馈"""
    canvas_x = x * editor.scale + getattr(editor, "canvas_offset_x", 0)
    canvas_y = y * editor.scale + getattr(editor, "canvas_offset_y", 0)
    canvas_r = radius * editor.scale

    editor.canvas.create_oval(
        canvas_x - canvas_r,
        canvas_y - canvas_r,
        canvas_x + canvas_r,
        canvas_y + canvas_r,
        fill="#ff0000",
        stipple="gray50",
        outline="",
        tags="inpaint_visual",
    )


def draw_inpaint_temp_rect(editor, x, y):
    """绘制临时矩形框选"""
    if not editor.inpaint_rect_start:
        return

    sx, sy = editor.inpaint_rect_start
    canvas_sx = sx * editor.scale + getattr(editor, "canvas_offset_x", 0)
    canvas_sy = sy * editor.scale + getattr(editor, "canvas_offset_y", 0)
    canvas_x = x * editor.scale + getattr(editor, "canvas_offset_x", 0)
    canvas_y = y * editor.scale + getattr(editor, "canvas_offset_y", 0)

    editor.canvas.delete("inpaint_temp")
    editor.canvas.create_rectangle(
        canvas_sx,
        canvas_sy,
        canvas_x,
        canvas_y,
        outline="red",
        width=2,
        tags="inpaint_temp",
    )


def draw_inpaint_visual_rect(editor, x1, y1, x2, y2):
    """绘制矩形框选的永久视觉反馈"""
    canvas_x1 = x1 * editor.scale + getattr(editor, "canvas_offset_x", 0)
    canvas_y1 = y1 * editor.scale + getattr(editor, "canvas_offset_y", 0)
    canvas_x2 = x2 * editor.scale + getattr(editor, "canvas_offset_x", 0)
    canvas_y2 = y2 * editor.scale + getattr(editor, "canvas_offset_y", 0)

    editor.canvas.create_rectangle(
        canvas_x1,
        canvas_y1,
        canvas_x2,
        canvas_y2,
        fill="#ff0000",
        stipple="gray25",
        outline="red",
        tags="inpaint_visual",
    )


def generate_bg_from_custom_mask(editor):
    """基于自定义涂抹蒙版生成修复结果（作为图层叠加，不替换原图/背景）"""
    if not editor.pages or not editor.original_image:
        messagebox.showwarning("提示", "请先导入图片")
        return

    if not editor.inpaint_mask_layer:
        messagebox.showwarning("提示", "请先涂抹标记需要去除的区域")
        return

    if not editor.inpaint_mask_layer.getbbox():
        messagebox.showwarning("提示", "当前没有涂抹内容\n\n请使用笔刷或框选工具标记需要去除的区域")
        return

    if not editor.config.get("inpaint_enabled", True):
        messagebox.showwarning("提示", "背景生成功能已禁用\n\n请在设置中启用")
        return

    page = editor.pages[editor.current_page_index]
    base_image = None
    try:
        base_image = editor.get_current_page_composited_background()
    except Exception:
        base_image = None
    if base_image is None:
        base_image = page.get("image") or editor.original_image
    mode_desc = "当前合成图（背景/图层叠加后）"

    result = messagebox.askyesno(
        "确认",
        f"即将基于{mode_desc}生成修复结果图层\n\n"
        f"底图：{mode_desc}\n"
        "涂抹区域：将被AI智能填充\n\n"
        "此操作需要调用IOPaint API服务\n"
        "处理时间约 5-30 秒\n\n"
        "是否继续？",
    )
    if not result:
        return

    # 支持撤销：图层快照（本页）
    editor.save_state("layers")
    editor.update_status(f"正在生成修复图层（基于{mode_desc}）...")

    def generate_bg():
        try:
            editor.root.after(
                0,
                lambda: editor.update_status(f"正在调用IOPaint API修复（{mode_desc}）..."),
            )
            result_img = call_inpaint_api(editor, base_image, editor.inpaint_mask_layer)

            if result_img:
                # 将结果转换为“只在蒙版区域有效”的 RGBA 图层（外部透明），避免直接替换底图。
                overlay = result_img.convert("RGBA")
                mask = editor.inpaint_mask_layer.convert("L")
                if mask.size != overlay.size:
                    mask = mask.resize(overlay.size, Image.Resampling.NEAREST)
                alpha = mask.filter(ImageFilter.GaussianBlur(3))
                overlay.putalpha(alpha)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                layer_name = f"IOPaint修复_{timestamp}"
                layer = editor.add_image_layer(page, overlay, name=layer_name, x=0, y=0, opacity=1.0, visible=True)

                editor.root.after(0, lambda: clear_inpaint_mask(editor, confirm=False))
                editor.root.after(0, editor.update_layer_listbox)
                editor.root.after(0, editor.scroll_to_layers)
                if layer and layer.get("id"):
                    editor.root.after(0, lambda lid=layer["id"]: editor.select_layer_by_id(lid))
                editor.root.after(0, editor.update_thumbnails)
                editor.root.after(0, editor.refresh_canvas)
                editor.root.after(0, editor.mark_unsaved)

                editor.root.after(0, lambda: editor.update_status(f"已生成修复图层：{layer_name}"))
                editor.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "成功",
                        "修复完成！\n\n"
                        "已作为新图层叠加（右侧“图层”可隐藏/删除/调透明度/调整顺序）\n"
                        "原图/背景不会被直接替换\n\n"
                        "提示：Ctrl+Z 可撤销本次图层变更",
                    ),
                )
            else:
                editor.root.after(0, lambda: editor.update_status("修复失败"))

        except Exception as e:
            import traceback

            error_msg = traceback.format_exc()
            print(f"背景生成失败:\n{error_msg}")
            editor.root.after(0, lambda: messagebox.showerror("错误", f"修复失败:\n{str(e)}"))
            editor.root.after(0, lambda: editor.update_status("修复失败"))

    threading.Thread(target=generate_bg, daemon=True).start()


def clear_inpaint_mask(editor, *, confirm: bool = True):
    """清空所有涂抹"""
    if not editor.inpaint_strokes:
        messagebox.showinfo("提示", "当前没有涂抹内容")
        return

    if confirm:
        result = messagebox.askyesno("确认", "确定要清空所有涂抹吗？")
        if not result:
            return

    editor.inpaint_mask_layer = Image.new("L", editor.original_image.size, 0)
    editor.inpaint_draw_layer = ImageDraw.Draw(editor.inpaint_mask_layer)
    editor.inpaint_strokes = []

    editor.canvas.delete("inpaint_visual")
    editor.canvas.delete("inpaint_temp")
    editor.update_status("已清空所有涂抹")


def rebuild_inpaint_mask(editor):
    """重建涂抹蒙版（用于撤销后）"""
    editor.inpaint_mask_layer = Image.new("L", editor.original_image.size, 0)
    editor.inpaint_draw_layer = ImageDraw.Draw(editor.inpaint_mask_layer)
    editor.canvas.delete("inpaint_visual")

    for stroke in editor.inpaint_strokes:
        if stroke["type"] == "brush":
            points = stroke["points"]
            r = editor.inpaint_brush_size // 2

            for i, (x, y) in enumerate(points):
                editor.inpaint_draw_layer.ellipse([x - r, y - r, x + r, y + r], fill=255, outline=255)
                if i > 0:
                    prev_x, prev_y = points[i - 1]
                    editor.inpaint_draw_layer.line(
                        [(prev_x, prev_y), (x, y)],
                        fill=255,
                        width=editor.inpaint_brush_size,
                    )
                draw_inpaint_visual_brush(editor, x, y, r)

        elif stroke["type"] == "rect":
            x1, y1, x2, y2 = stroke["coords"]
            editor.inpaint_draw_layer.rectangle([x1, y1, x2, y2], fill=255, outline=255)
            draw_inpaint_visual_rect(editor, x1, y1, x2, y2)


def call_inpaint_api(editor, image_pil, mask_pil, crop_padding=128):
    """
    调用IOPaint API进行图像修复

    Returns:
        PIL Image 或 None
    """
    api_url = editor.config.get("inpaint_api_url", "http://127.0.0.1:8080/api/v1/inpaint")
    try:
        mask_np = np.array(mask_pil)
        rows = np.any(mask_np, axis=1)
        cols = np.any(mask_np, axis=0)

        if not rows.any() or not cols.any():
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

        def to_b64(img):
            buffer = BytesIO()
            img.save(buffer, "PNG")
            return base64.b64encode(buffer.getvalue()).decode()

        payload = {
            "image": to_b64(crop_img),
            "mask": to_b64(crop_mask),
            "ldm_steps": 30,
            "hd_strategy": "Original",
            "sd_sampler": "UniPC",
        }

        response = requests.post(api_url, json=payload, timeout=120)

        if response.status_code == 200:
            res_crop = Image.open(BytesIO(response.content))
            final = image_pil.copy()

            blur_mask = crop_mask.filter(ImageFilter.GaussianBlur(3))
            orig_crop_area = final.crop(crop_box)
            blended = Image.composite(res_crop, orig_crop_area, blur_mask)
            final.paste(blended, (x1, y1))
            return final

        editor.root.after(
            0,
            lambda: messagebox.showerror(
                "API错误",
                f"IOPaint API返回错误: {response.status_code}\n{response.text[:200]}",
            ),
        )
        return None

    except requests.exceptions.ConnectionError:
        editor.root.after(
            0,
            lambda: messagebox.showerror(
                "连接错误",
                "无法连接到IOPaint API服务！\n\n"
                "请确保IOPaint服务正在运行：\n"
                f"API地址：{api_url}\n\n"
                "启动命令：\n"
                "iopaint start --host 127.0.0.1 --port 8080",
            ),
        )
        return None
    except Exception as e:
        import traceback

        error_msg = traceback.format_exc()
        print(f"IOPaint API调用失败:\n{error_msg}")
        editor.root.after(0, lambda: messagebox.showerror("错误", f"修复失败:\n{str(e)}"))
        return None


def create_mask_from_boxes(editor, image_size, text_boxes, padding=5):
    """根据文本框位置创建蒙版"""
    mask = Image.new("L", image_size, 0)
    draw = ImageDraw.Draw(mask)
    img_w, img_h = image_size

    for box in text_boxes:
        x1 = max(0, box.x - padding)
        y1 = max(0, box.y - padding)
        x2 = min(img_w, box.x + box.width + padding)
        y2 = min(img_h, box.y + box.height + padding)
        draw.rectangle([x1, y1, x2, y2], fill=255)

    return mask
