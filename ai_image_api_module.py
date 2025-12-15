"""
AI图片生成API模块
支持OpenAI和Gemini格式的图片生成API
与 index.html 中的请求格式保持一致
"""

import logging
import requests
import base64
import re
from io import BytesIO
from PIL import Image
import json
import math

logger = logging.getLogger(__name__)


class AIImageAPIManager:
    """AI图片生成API管理器"""

    def __init__(self):
        self.config = {
            "api_type": "openai",  # openai 或 gemini
            "debug": False,
            "openai": {
                "api_key": "",
                "api_host": "https://api.openai.com/v1",
                "model": "gpt-4o",
                "size": "1024x1024",
                "aspect_ratio": "auto"
            },
            "gemini": {
                "api_key": "",
                "api_host": "https://generativelanguage.googleapis.com",
                "model": "gemini-2.0-flash-exp-image-generation",
                "image_size": "1K",
                "aspect_ratio": "auto"
            }
        }

    def load_config(self, config):
        """从配置加载AI API设置"""
        if "ai_image_api" in config:
            self.config.update(config["ai_image_api"])
        return self.config

    def save_config(self, config):
        """保存AI API设置到配置"""
        config["ai_image_api"] = self.config
        return config

    def generate_image(self, prompt, source_image=None, mask_image=None, progress_callback=None, overrides=None):
        """
        生成或编辑图片 (与HTML中的请求格式一致)

        参数:
            prompt: 提示词
            source_image: 源图片 (PIL Image, 可选 - 用于图生图)
            mask_image: 遮罩图片 (PIL Image, 可选)
            progress_callback: 进度回调函数
            overrides: 可选的按次覆盖参数（不落盘）
                - size: OpenAI size，如 "1024x1024"
                - image_size: Gemini imageSize，如 "1K"/"2K"/"4K"
                - aspect_ratio: 比例，如 "auto"/"1:1"/"16:9"

        返回:
            PIL Image 或 None
        """
        api_type = self.config.get("api_type", "openai")
        debug = bool((overrides or {}).get("debug", self.config.get("debug", False)))

        if progress_callback:
            progress_callback(f"使用 {api_type.upper()} API...")

        if api_type == "openai":
            return self._openai_chat_completions(
                prompt,
                source_image,
                mask_image,
                progress_callback,
                overrides=overrides,
                debug=debug,
            )
        elif api_type == "gemini":
            return self._gemini_generate_content(
                prompt,
                source_image,
                mask_image,
                progress_callback,
                overrides=overrides,
                debug=debug,
            )
        else:
            raise ValueError(f"不支持的API类型: {api_type}")

    def suggest_overrides(self, target_w: int, target_h: int) -> dict:
        """
        Suggest per-request overrides to avoid upscaling (which looks blurry).
        Merge with user overrides (user overrides win).
        """
        api_type = self.config.get("api_type", "openai")
        target_w = int(target_w or 0)
        target_h = int(target_h or 0)
        aspect_ratio = self._best_ratio_label(target_w, target_h)

        if api_type == "gemini":
            image_size = self._suggest_gemini_image_size(target_w, target_h)
            return {"image_size": image_size, "aspect_ratio": aspect_ratio}

        size = self._suggest_openai_size(target_w, target_h)
        return {"size": size, "aspect_ratio": aspect_ratio}

    @staticmethod
    def _best_ratio_label(width: int, height: int) -> str:
        if width <= 0 or height <= 0:
            return "auto"
        r = width / height
        candidates = {
            "1:1": 1.0,
            "16:9": 16 / 9,
            "9:16": 9 / 16,
            "4:3": 4 / 3,
            "3:4": 3 / 4,
        }
        return min(candidates.items(), key=lambda kv: abs(kv[1] - r))[0]

    @staticmethod
    def _suggest_gemini_image_size(width: int, height: int) -> str:
        m = max(int(width or 0), int(height or 0))
        if m > 2048:
            return "4K"
        if m > 1024:
            return "2K"
        return "1K"

    @staticmethod
    def _suggest_openai_size(width: int, height: int) -> str:
        m = max(int(width or 0), int(height or 0))
        if m > 1024:
            return "2048x2048"
        if m > 512:
            return "1024x1024"
        return "512x512"

    # 保持向后兼容
    def image_to_image(self, prompt, source_image, mask_image=None, progress_callback=None, overrides=None):
        """图片到图片生成 (向后兼容方法)"""
        return self.generate_image(prompt, source_image, mask_image, progress_callback, overrides=overrides)

    def _openai_chat_completions(self, prompt, source_image, mask_image, progress_callback, overrides=None, debug: bool = False):
        """
        OpenAI兼容格式 - 使用 /v1/chat/completions 端点
        与HTML中的请求格式一致
        """
        config = self.config.get("openai", {})
        api_key = config.get("api_key", "")
        api_host = config.get("api_host", "https://api.openai.com/v1").rstrip('/')
        model = config.get("model", "gpt-4o")
        overrides = overrides or {}
        size = overrides.get("size") or config.get("size", "1024x1024")
        aspect_ratio = overrides.get("aspect_ratio") or config.get("aspect_ratio", "auto")

        if not api_key:
            raise ValueError("请先配置OpenAI API Key")

        if progress_callback:
            progress_callback("准备请求...")

        # 构建消息内容
        content = [{"type": "text", "text": prompt}]

        # 如果有源图片，添加到消息中
        if source_image:
            source_b64 = self._image_to_base64(source_image, fmt="PNG")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{source_b64}"}
            })

        # 如果有遮罩图片，也添加
        if mask_image:
            mask_b64 = self._image_to_base64(mask_image, fmt="PNG")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{mask_b64}"}
            })

        # 构建请求体 (与HTML中的格式一致)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "size": size,
        }
        if aspect_ratio and aspect_ratio != "auto":
            payload["aspect_ratio"] = aspect_ratio

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        url = f"{api_host}/v1/chat/completions"

        if progress_callback:
            progress_callback("发送请求...")

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        if response.status_code != 200:
            try:
                error_msg = response.json().get("error", {}).get("message", response.text)
            except Exception:
                error_msg = response.text
            raise Exception(f"OpenAI API错误 ({response.status_code}): {error_msg}")

        data = response.json()

        if progress_callback:
            progress_callback("解析返回结果...")

        # 解析返回内容 (与HTML中的解析逻辑一致)
        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0].get("message", {}).get("content", "")

            # 1. 匹配 Markdown 格式的 Base64 图片: ![...](data:image/...)
            base64_match = re.search(r'!\[.*?\]\((data:image\/[^)]+)\)', content)
            if base64_match:
                if progress_callback:
                    progress_callback("解析到Base64图片...")
                data_url = base64_match.group(1)
                # 去掉前缀 "data:image/xxx;base64,"
                b64_data = data_url.split(',')[1] if ',' in data_url else data_url
                img_bytes = base64.b64decode(b64_data)
                return Image.open(BytesIO(img_bytes))

            # 2. 匹配 Markdown 格式的 URL 图片: ![...](https://...)
            url_match = re.search(r'!\[.*?\]\((https?:\/\/[^)]+)\)', content)
            if url_match:
                image_url = url_match.group(1)
                if progress_callback:
                    progress_callback(f"下载图片...")
                img_response = requests.get(image_url, timeout=60)
                return Image.open(BytesIO(img_response.content))

            # 3. 直接是 data:image 开头
            if content.startswith('data:image/'):
                b64_data = content.split(',')[1] if ',' in content else content
                img_bytes = base64.b64decode(b64_data)
                return Image.open(BytesIO(img_bytes))

        raise Exception("OpenAI API未返回图片数据")

    def _gemini_generate_content(self, prompt, source_image, mask_image, progress_callback, overrides=None, debug: bool = False):
        """
        Gemini原生格式 - 使用 generateContent 端点
        与HTML中的请求格式一致
        """
        config = self.config.get("gemini", {})
        api_key = config.get("api_key", "")
        api_host = config.get("api_host", "https://generativelanguage.googleapis.com").rstrip('/')
        model = config.get("model", "gemini-2.0-flash-exp-image-generation")
        overrides = overrides or {}
        image_size = overrides.get("image_size") or config.get("image_size", "1K")
        aspect_ratio = overrides.get("aspect_ratio") or config.get("aspect_ratio", "auto")

        if not api_key:
            raise ValueError("请先配置Gemini API Key")

        if progress_callback:
            progress_callback("准备请求...")

        # 构建 parts
        parts = [{"text": prompt}]

        # 如果有源图片，添加到 parts
        if source_image:
            source_b64 = self._image_to_base64(source_image, fmt="PNG")
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": source_b64
                }
            })

        # 如果有遮罩图片，也添加
        if mask_image:
            mask_b64 = self._image_to_base64(mask_image, fmt="PNG")
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": mask_b64
                }
            })

        # 构建请求体 (与HTML中的格式一致)
        generation_config = {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"imageSize": image_size},
        }
        if aspect_ratio and aspect_ratio != "auto":
            generation_config["imageConfig"]["aspectRatio"] = aspect_ratio

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config
        }

        headers = {
            "Content-Type": "application/json"
        }

        url = f"{api_host}/v1beta/models/{model}:generateContent?key={api_key}"

        if progress_callback:
            progress_callback("发送请求到Gemini...")

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        if response.status_code != 200:
            try:
                error_msg = response.json().get("error", {}).get("message", response.text)
            except Exception:
                error_msg = response.text
            raise Exception(f"Gemini API错误 ({response.status_code}): {error_msg}")

        result = response.json()

        if debug and logger.isEnabledFor(logging.DEBUG):
            debug_result = json.dumps(result, ensure_ascii=False, indent=2)
            if len(debug_result) > 3000:
                logger.debug("Gemini API 返回内容(截断前1500):\n%s", debug_result[:1500])
                logger.debug("Gemini API 返回内容(截断后1500):\n%s", debug_result[-1500:])
            else:
                logger.debug("Gemini API 返回内容:\n%s", debug_result)

        if progress_callback:
            progress_callback("解析返回结果...")

        # 解析响应获取图片 (与HTML中的解析逻辑一致)
        if "candidates" in result and len(result["candidates"]) > 0:
            candidate = result["candidates"][0]
            if debug:
                logger.debug("Gemini candidate keys: %s", list(candidate.keys()))

            if "content" in candidate and "parts" in candidate["content"]:
                parts = candidate["content"]["parts"]
                if debug:
                    logger.debug("Gemini parts count: %s", len(parts))

                for i, part in enumerate(parts):
                    if debug:
                        logger.debug("Gemini part[%s] keys: %s", i, list(part.keys()))

                    # 检查 inlineData (原生 Base64 返回)
                    if "inlineData" in part:
                        inline_data = part["inlineData"]
                        mime_type = inline_data.get("mimeType", "")
                        if debug:
                            logger.debug("Gemini inlineData mimeType: %s", mime_type)
                        if mime_type.startswith("image/"):
                            if progress_callback:
                                progress_callback("解析到Gemini图片...")
                            img_bytes = base64.b64decode(inline_data["data"])
                            return Image.open(BytesIO(img_bytes))

                    # 检查 text 中是否包含图片
                    if "text" in part:
                        text = part["text"]
                        if debug:
                            logger.debug("Gemini part[%s] text len=%s", i, len(text))
                            logger.debug("Gemini part[%s] text head200=%r", i, text[:200])

                        # 匹配多种 Markdown 格式
                        # 格式1: ![...](data:image/...)
                        match = re.search(r'!\[.*?\]\((data:image\/[^)]+)\)', text)
                        if match:
                            if debug:
                                logger.debug("Gemini matched markdown data:image")
                            data_url = match.group(1)
                            b64_data = data_url.split(',')[1] if ',' in data_url else data_url
                            img_bytes = base64.b64decode(b64_data)
                            return Image.open(BytesIO(img_bytes))

                        # 格式2: (data:image/...)
                        match = re.search(r'\((data:image\/[^;]+;base64,[^)]+)\)', text)
                        if match:
                            if debug:
                                logger.debug("Gemini matched parenthesized data:image")
                            data_url = match.group(1)
                            b64_data = data_url.split(',')[1]
                            img_bytes = base64.b64decode(b64_data)
                            return Image.open(BytesIO(img_bytes))

                        # 格式3: 直接 data:image 开头
                        if 'data:image/' in text:
                            if debug:
                                logger.debug("Gemini text contains data:image")
                            match = re.search(r'data:image\/[^;]+;base64,([A-Za-z0-9+/=]+)', text)
                            if match:
                                if debug:
                                    logger.debug("Gemini extracted base64 data")
                                b64_data = match.group(1)
                                img_bytes = base64.b64decode(b64_data)
                                return Image.open(BytesIO(img_bytes))
            else:
                if debug:
                    logger.debug("Gemini candidate lacks content.parts")
        else:
            if debug:
                logger.debug("Gemini response has no candidates")

        raise Exception("Gemini API未返回图片数据（可在 ai_image_api.debug=true 或 overrides['debug']=True 查看日志）")

    def _image_to_base64(self, img, *, fmt: str = "PNG", max_side: int = 1920, jpeg_quality: int = 95):
        """将 PIL Image 转换为 Base64 字符串（请求用）。"""
        if img is None:
            return ""

        # 控制请求体大小：过大的图片会导致请求缓慢/失败；清晰度主要靠 suggest_overrides() 避免上采样。
        try:
            w, h = img.size
            m = max(w, h)
            if max_side and m and m > max_side:
                scale = max_side / m
                new_w = max(1, int(math.ceil(w * scale)))
                new_h = max(1, int(math.ceil(h * scale)))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        except Exception:
            pass

        buffer = BytesIO()
        fmt = (fmt or "PNG").upper()
        if fmt == "PNG":
            if img.mode not in ("RGB", "RGBA", "L"):
                img = img.convert("RGBA")
            img.save(buffer, format="PNG", optimize=True)
        else:
            if img.mode == "RGBA":
                img = img.convert("RGB")
            img.save(buffer, format="JPEG", quality=int(jpeg_quality or 95), subsampling=0, optimize=True)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode()


def blend_images(base_image, overlay_image, mask=None, alpha=1.0):
    """
    混合两张图片

    参数:
        base_image: 底图 (PIL Image)
        overlay_image: 叠加图 (PIL Image)
        mask: 遮罩 (PIL Image, 可选)
        alpha: 透明度 (0-1)

    返回:
        混合后的 PIL Image
    """
    # 确保图片尺寸一致
    if overlay_image.size != base_image.size:
        overlay_image = overlay_image.resize(base_image.size, Image.Resampling.LANCZOS)

    # 确保是RGBA模式
    if base_image.mode != "RGBA":
        base_image = base_image.convert("RGBA")
    if overlay_image.mode != "RGBA":
        overlay_image = overlay_image.convert("RGBA")

    # 如果有遮罩，使用遮罩混合
    if mask:
        if mask.size != base_image.size:
            mask = mask.resize(base_image.size, Image.Resampling.LANCZOS)
        if mask.mode != "L":
            mask = mask.convert("L")

        # 使用遮罩作为alpha通道
        result = base_image.copy()
        result.paste(overlay_image, mask=mask)
        return result
    else:
        # 简单alpha混合
        return Image.blend(base_image, overlay_image, alpha)
