"""
OCR 功能模块 - 模型加载与识别

说明：
- 以 editor 实例作为第一个参数（等价于原先的 self）。
"""

from __future__ import annotations

import os
import tempfile
import threading
import warnings
import logging
from pathlib import Path

from tkinter import messagebox

import cv2
import numpy as np

from ..config import get_base_dir
from .font_fit import fit_font_size_pt

try:
    from paddleocr import PaddleOCR
except Exception:  # pragma: no cover
    PaddleOCR = None


_QUIET_READY = False


def _quiet_startup_once() -> None:
    global _QUIET_READY
    if _QUIET_READY:
        return
    _QUIET_READY = True

    warnings.filterwarnings("ignore", message=r".*`lang` and `ocr_version` will be ignored.*")
    warnings.filterwarnings("ignore", message=r"No ccache found\\..*")

    # Silence most Paddle C++ INFO/WARNING logs (keep ERROR+).
    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("FLAGS_minloglevel", "2")

    # Ensure `where ccache` doesn't print "无法找到文件" on Windows by providing a shim in PATH.
    if os.name == "nt":
        try:
            tools_dir = Path(__file__).resolve().parents[1] / "tools"
            tools_str = str(tools_dir)
            if tools_dir.is_dir():
                path = os.environ.get("PATH", "")
                if tools_str not in path.split(os.pathsep):
                    os.environ["PATH"] = tools_str + os.pathsep + path
        except Exception:
            pass

    # Reduce noisy Python logging from deps (e.g. paddlex "Creating model").
    try:
        logging.getLogger().setLevel(logging.WARNING)
        logging.getLogger("utils.cpp_extension").setLevel(logging.ERROR)
    except Exception:
        pass


def _post_status(editor, text: str) -> None:
    # init_ocr() 运行在后台线程；Tk UI 更新需要切回主线程。
    try:
        editor.root.after(0, lambda: editor.update_status(text))
    except Exception:
        pass


def _post_warning(editor, title: str, text: str) -> None:
    try:
        editor.root.after(0, lambda: messagebox.showwarning(title, text))
    except Exception:
        pass


def _gpu_available() -> bool:
    try:
        import paddle

        if not paddle.is_compiled_with_cuda():
            return False
        try:
            return paddle.device.cuda.device_count() > 0
        except Exception:
            return False
    except Exception:
        return False


def _paddleocr_major_version() -> int | None:
    try:
        import paddleocr as _paddleocr

        v = getattr(_paddleocr, "__version__", "")
        if not v:
            return None
        major_str = str(v).split(".", 1)[0]
        return int(major_str)
    except Exception:
        return None


class _PaddleOCRv2Compat:
    def __init__(self, impl):
        self._impl = impl

    def predict(self, img_path: str):
        """
        兼容 PaddleOCR 3.x 的 predict() 输出：
        返回 List[Dict]，包含 dt_polys / rec_texts。
        """
        result = self._impl.ocr(img_path, cls=False)
        dt_polys: list[list[list[float]]] = []
        rec_texts: list[str] = []

        if result:
            for item in result:
                try:
                    poly = item[0]
                    text = item[1][0]
                except Exception:
                    continue
                dt_polys.append(poly)
                rec_texts.append(text)

        return [{"dt_polys": dt_polys, "rec_texts": rec_texts}]

    def __getattr__(self, name: str):
        return getattr(self._impl, name)


def _warmup_predict(ocr_obj) -> Exception | None:
    """
    在 init 阶段跑一次最小推理，尽早暴露 GPU 动态库缺失（例如 cudnn64_8.dll）。
    """
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()

        blank = np.zeros((32, 32, 3), dtype=np.uint8)
        cv2.imwrite(tmp_path, blank)
        ocr_obj.predict(tmp_path)
        return None
    except Exception as e:
        return e
    finally:
        try:
            if "tmp_path" in locals() and tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _looks_like_missing_cuda_lib(err: Exception) -> bool:
    msg = str(err).lower()
    return (
        "cudnn" in msg
        or "cublas" in msg
        or "cufft" in msg
        or "curand" in msg
        or "dynamic library" in msg
        or "error code is 126" in msg
        or "preconditionnotmet" in msg
    )


def _try_create_ocr(params_list: list[dict]) -> tuple[object | None, Exception | None]:
    _quiet_startup_once()
    if PaddleOCR is None:
        return None, RuntimeError("未安装 paddleocr")

    last_error: Exception | None = None
    for params in params_list:
        try:
            return PaddleOCR(**params), None
        except Exception as e:
            last_error = e
            continue
    return None, last_error


def init_ocr(editor) -> None:
    """后台初始化OCR模型 - 优先使用配置的模型目录"""
    _post_status(editor, "正在加载OCR模型...")

    if PaddleOCR is None:
        _post_status(editor, "OCR加载失败: 未安装 paddleocr")
        return

    _quiet_startup_once()

    try:
        local_model_dir = editor.config.get("model_dir", os.path.join(get_base_dir(), ".paddlex", "official_models"))
        device_cfg = str(editor.config.get("ocr_device", "cpu")).lower()
        desired_device = "gpu" if device_cfg == "gpu" else "cpu"
        if desired_device == "gpu" and not _gpu_available():
            _post_status(editor, "检测到 Paddle GPU 不可用，已切换为 CPU（请检查 CUDA/驱动/安装版本）")
            desired_device = "cpu"
        device = desired_device

        # PaddleOCR 3.x 默认会启用文档预处理（旋转/矫正/行方向等），返回的 dt_polys 坐标往往对应预处理后的图像，
        # 在“原图叠框”的场景会出现明显偏移。这里默认关闭，以获得稳定的像素坐标。
        use_doc_orientation_classify = bool(editor.config.get("ocr_use_doc_orientation_classify", False))
        use_doc_unwarping = bool(editor.config.get("ocr_use_doc_unwarping", False))
        use_textline_orientation = bool(editor.config.get("ocr_use_textline_orientation", False))

        params_list: list[dict] = []
        paddleocr_major = _paddleocr_major_version()

        if paddleocr_major is None or paddleocr_major >= 3:
            det_model = os.path.join(local_model_dir, "PP-OCRv5_server_det")
            rec_model = os.path.join(local_model_dir, "PP-OCRv5_server_rec")
            # PaddleOCR v3+（paddleocr==3.x）使用 device=... 且模型参数名变更
            if os.path.exists(det_model) and os.path.exists(rec_model):
                params_list.append(
                    {
                        "text_detection_model_dir": det_model,
                        "text_recognition_model_dir": rec_model,
                        "device": device,
                        "use_doc_orientation_classify": use_doc_orientation_classify,
                        "use_doc_unwarping": use_doc_unwarping,
                        "use_textline_orientation": use_textline_orientation,
                    }
                )

            # 回退：让 PaddleOCR 自动下载/使用默认模型
            params_list.append(
                {
                    "lang": "ch",
                    "device": device,
                    "use_doc_orientation_classify": use_doc_orientation_classify,
                    "use_doc_unwarping": use_doc_unwarping,
                    "use_textline_orientation": use_textline_orientation,
                }
            )
        else:
            # PaddleOCR v2.x（常用于 Windows + paddlepaddle-gpu==2.6.2）
            # 这里不要复用 PaddleX/PP-OCRv5 的模型目录；PaddleOCR 2.x 会尝试在该目录下下载/解压 v4 模型，
            # 在部分环境可能触发推理初始化崩溃。让 PaddleOCR 使用其默认缓存目录（~/.paddleocr）更稳。
            params_list.append({"lang": "ch", "use_gpu": device == "gpu", "show_log": False})

        editor.ocr, err = _try_create_ocr(params_list)
        if editor.ocr is None:
            if err and "AnalysisConfig" in str(err) and "set_optimization_level" in str(err):
                _post_status(editor, "OCR初始化失败：PaddleOCR/Paddle 版本不兼容")
                _post_warning(
                    editor,
                    "OCR版本不兼容",
                    "检测到 PaddleOCR 3.x + Paddle 2.x 的不兼容组合。\n\n"
                    "如果你想用 GPU（Windows 常见情况是 paddlepaddle-gpu==2.6.2），建议安装：\n"
                    "  pip install \"paddleocr<3\"\n\n"
                    "或者改用 Paddle 3.x（对应的 GPU 包需按官方说明匹配平台/CUDA）。",
                )
            raise err or RuntimeError("OCR初始化失败")

        # 统一成“有 predict()”的接口，兼容 editor_main / core 里的调用方式
        if (paddleocr_major or 0) < 3:
            editor.ocr = _PaddleOCRv2Compat(editor.ocr)

        # GPU 场景提前做一次 warmup，避免用户点击“检测”时才发现缺少 cudnn 等动态库
        if device == "gpu":
            warmup_err = _warmup_predict(editor.ocr)
            if warmup_err is not None and _looks_like_missing_cuda_lib(warmup_err):
                _post_status(editor, "OCR(GPU) 推理依赖缺失，已回退到 CPU（请安装 CUDA/cuDNN 并配置 PATH）")
                _post_warning(
                    editor,
                    "OCR GPU 依赖缺失",
                    "检测到 PaddleOCR 在 GPU 推理时缺少 CUDA/cuDNN 动态库（例如 cudnn64_8.dll）。\n\n"
                    "解决方式（Windows）：\n"
                    "1) 安装与 paddlepaddle-gpu 匹配的 CUDA Toolkit 与 cuDNN\n"
                    "2) 将 cuDNN 的 bin 目录加入系统 PATH\n\n"
                    "临时方案：把配置里的 ocr_device 改成 cpu。",
                )
                if (paddleocr_major or 0) >= 3:
                    editor.ocr, _ = _try_create_ocr(
                        [
                            {
                                "lang": "ch",
                                "device": "cpu",
                                "use_doc_orientation_classify": use_doc_orientation_classify,
                                "use_doc_unwarping": use_doc_unwarping,
                                "use_textline_orientation": use_textline_orientation,
                            }
                        ]
                    )
                else:
                    editor.ocr, _ = _try_create_ocr([{"lang": "ch", "use_gpu": False, "show_log": False}])
                if editor.ocr is not None and (_paddleocr_major_version() or 0) < 3:
                    editor.ocr = _PaddleOCRv2Compat(editor.ocr)
                device = "cpu"

        device_name = "GPU" if device == "gpu" else "CPU"
        if (paddleocr_major or 0) >= 3:
            det_model = os.path.join(local_model_dir, "PP-OCRv5_server_det")
            rec_model = os.path.join(local_model_dir, "PP-OCRv5_server_rec")
            if os.path.exists(det_model) and os.path.exists(rec_model):
                _post_status(editor, f"OCR模型加载完成（本地模型，{device_name}）")
            else:
                _post_status(editor, f"OCR模型加载完成（{device_name}）")
        else:
            _post_status(editor, f"OCR模型加载完成（{device_name}）")

    except Exception:
        # 最后兜底：明确尝试 CPU（兼容 v3/v2）
        _post_status(editor, "OCR加载失败，尝试CPU模式...")
        fallback_major = _paddleocr_major_version() or 0
        if fallback_major >= 3:
            editor.ocr, err = _try_create_ocr(
                [
                    {
                        "lang": "ch",
                        "device": "cpu",
                        "use_doc_orientation_classify": bool(editor.config.get("ocr_use_doc_orientation_classify", False)),
                        "use_doc_unwarping": bool(editor.config.get("ocr_use_doc_unwarping", False)),
                        "use_textline_orientation": bool(editor.config.get("ocr_use_textline_orientation", False)),
                    }
                ]
            )
        else:
            editor.ocr, err = _try_create_ocr(
                [
                    {"lang": "ch", "device": "cpu"},
                    {"lang": "ch", "use_gpu": False, "show_log": False},
                ]
            )
        if editor.ocr is not None:
            if (_paddleocr_major_version() or 0) < 3:
                editor.ocr = _PaddleOCRv2Compat(editor.ocr)
            _post_status(editor, "OCR模型加载完成（CPU模式）")
            return

        _post_status(editor, f"OCR加载失败: {err}")
        import traceback

        traceback.print_exc()


def ocr_single_box(editor) -> None:
    """OCR识别单个选中的文本框"""
    if editor.selected_box_index < 0 or editor.selected_box_index >= len(editor.text_boxes):
        messagebox.showinfo("提示", "请先选中一个文本框")
        return

    if not editor.ocr:
        messagebox.showwarning("提示", "OCR模型正在加载中，请稍候...")
        return

    if not editor.original_img_path or not os.path.exists(editor.original_img_path):
        messagebox.showerror("错误", "找不到原始图片")
        return

    box = editor.text_boxes[editor.selected_box_index]
    editor.update_status(f"正在识别第 {editor.selected_box_index + 1} 个文本框...")

    def ocr_task():
        try:
            if editor.original_image is None:
                editor.root.after(0, lambda: messagebox.showerror("错误", "无法读取图片"))
                return

            img = np.array(editor.original_image)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            img_h, img_w = img.shape[:2]

            x, y, w, h = box.x, box.y, box.width, box.height
            expand_h, expand_w = int(h * 0.3), int(w * 0.1)

            crop_x = max(0, x - expand_w)
            crop_y = max(0, y - expand_h)
            crop_x2 = min(x + w + expand_w, img_w)
            crop_y2 = min(y + h + expand_h, img_h)

            cropped = img[crop_y:crop_y2, crop_x:crop_x2]

            temp_file = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            cv2.imwrite(temp_path, cropped)

            try:
                result = editor.ocr.predict(temp_path)
                os.remove(temp_path)

                if result and len(result) > 0:
                    ocr_result = result[0]
                    rec_texts = ocr_result.get("rec_texts", [])

                    if rec_texts:
                        recognized_text = "".join(rec_texts)

                        if recognized_text:
                            box.text = recognized_text

                            box.font_size = fit_font_size_pt(
                                box.text,
                                w,
                                h,
                                editor=editor,
                                font_name=getattr(box, "font_name", None),
                            )

                            editor.root.after(0, editor.refresh_canvas)
                            editor.root.after(0, editor.update_listbox)
                            editor.root.after(0, editor.update_property_panel)
                            editor.root.after(
                                0,
                                lambda: editor.update_status(f"识别成功: {recognized_text[:20]}..."),
                            )
                            editor.root.after(
                                0,
                                lambda: messagebox.showinfo(
                                    "识别成功",
                                    f"识别结果：\n\n{recognized_text}\n\n字号已自动调整为: {box.font_size}",
                                ),
                            )
                            return

                editor.root.after(0, lambda: editor.update_status("未识别到文字"))
                editor.root.after(0, lambda: messagebox.showwarning("识别结果", "未识别到文字"))

            except Exception as e:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
                editor.root.after(0, lambda: messagebox.showerror("错误", f"OCR识别出错:\n{str(e)}"))
                editor.root.after(0, lambda: editor.update_status("识别失败"))

        except Exception as e:
            import traceback

            traceback.print_exc()
            editor.root.after(0, lambda: messagebox.showerror("错误", f"识别出错:\n{str(e)}"))
            editor.root.after(0, lambda: editor.update_status("识别失败"))

    threading.Thread(target=ocr_task, daemon=True).start()


def ocr_all_boxes(editor) -> None:
    if not editor.text_boxes or not editor.ocr:
        return

    editor.update_status("正在识别...")

    def ocr_task():
        if editor.original_image is None:
            editor.root.after(0, lambda: editor.update_status("无法读取图片"))
            return

        img = np.array(editor.original_image)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        img_h, img_w = img.shape[:2]

        for box in editor.text_boxes:
            if box.text:
                continue

            x, y, w, h = box.x, box.y, box.width, box.height
            expand_h, expand_w = int(h * 0.3), int(w * 0.1)

            crop_x = max(0, x - expand_w)
            crop_y = max(0, y - expand_h)
            crop_x2 = min(x + w + expand_w, img_w)
            crop_y2 = min(y + h + expand_h, img_h)

            cropped = img[crop_y:crop_y2, crop_x:crop_x2]

            temp_file = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            cv2.imwrite(temp_path, cropped)

            try:
                result = editor.ocr.predict(temp_path)
                os.remove(temp_path)

                if result and len(result) > 0:
                    ocr_result = result[0]
                    rec_texts = ocr_result.get("rec_texts", [])
                    if rec_texts:
                        box.text = "".join(rec_texts)
                        if box.text:
                            box.font_size = fit_font_size_pt(
                                box.text,
                                w,
                                h,
                                editor=editor,
                                font_name=getattr(box, "font_name", None),
                            )
            except Exception:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

        editor.root.after(0, editor.refresh_canvas)
        editor.root.after(0, editor.update_listbox)
        editor.root.after(0, editor.update_property_panel)
        editor.root.after(0, lambda: editor.update_status("识别完成 ✓"))

    threading.Thread(target=ocr_task, daemon=True).start()
