"""
OCR功能改进补丁 - 修复资源泄漏和错误处理

使用方法：在 ocr.py 中导入这些函数替换原有实现
"""

import os
import tempfile
import logging
from typing import Optional, Tuple
from contextlib import contextmanager

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@contextmanager
def create_temp_image_file(image_array: np.ndarray, suffix: str = ".jpg"):
    """
    安全地创建临时图片文件的上下文管理器

    Args:
        image_array: 图片数组
        suffix: 文件后缀

    Yields:
        临时文件路径
    """
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            temp_path = f.name

        success = cv2.imwrite(temp_path, image_array)
        if not success:
            raise IOError(f"Failed to write image to {temp_path}")

        logger.debug(f"Created temp image file: {temp_path}")
        yield temp_path

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug(f"Cleaned up temp file: {temp_path}")
            except Exception as e:
                logger.warning(f"Failed to remove temp file {temp_path}: {e}")


def safe_ocr_predict(ocr_model, image_path: str) -> Tuple[Optional[list], Optional[Exception]]:
    """
    安全地执行OCR预测，捕获所有异常

    Args:
        ocr_model: OCR模型对象
        image_path: 图片路径

    Returns:
        (结果列表, 错误对象) 元组
    """
    try:
        if not os.path.exists(image_path):
            return None, FileNotFoundError(f"Image file not found: {image_path}")

        result = ocr_model.predict(image_path)
        return result, None

    except FileNotFoundError as e:
        logger.error(f"OCR prediction failed - file not found: {e}")
        return None, e
    except RuntimeError as e:
        logger.error(f"OCR prediction failed - runtime error: {e}")
        return None, e
    except Exception as e:
        logger.error(f"OCR prediction failed - unexpected error: {e}")
        return None, e


def extract_text_from_ocr_result(result: list) -> Optional[str]:
    """
    从OCR结果中提取文本

    Args:
        result: OCR结果列表

    Returns:
        识别出的文本，如果没有结果则返回None
    """
    if not result or len(result) == 0:
        return None

    try:
        ocr_result = result[0]
        rec_texts = ocr_result.get("rec_texts", [])

        if rec_texts:
            text = "".join(rec_texts)
            if text.strip():
                return text
        return None

    except (KeyError, IndexError, AttributeError) as e:
        logger.warning(f"Failed to extract text from OCR result: {e}")
        return None


def crop_image_region(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
    expand_ratio_w: float = 0.1,
    expand_ratio_h: float = 0.3
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """
    裁剪图片区域，带扩展边界

    Args:
        image: 图片数组
        x: X坐标
        y: Y坐标
        width: 宽度
        height: 高度
        expand_ratio_w: 宽度扩展比例
        expand_ratio_h: 高度扩展比例

    Returns:
        (裁剪后的图片, (x1, y1, x2, y2)) 元组
    """
    img_h, img_w = image.shape[:2]

    expand_w = int(width * expand_ratio_w)
    expand_h = int(height * expand_ratio_h)

    x1 = max(0, x - expand_w)
    y1 = max(0, y - expand_h)
    x2 = min(img_w, x + width + expand_w)
    y2 = min(img_h, y + height + expand_h)

    cropped = image[y1:y2, x1:x2]

    return cropped, (x1, y1, x2, y2)
