# PPT编辑器重构指南

本文档提供完整的项目重构方案和实施步骤。

## 📁 新的项目结构

```
ppt_editor_modular/
├── __init__.py
├── __main__.py
├── config.py                    ✅ 已优化
├── logging_config.py            ✅ 新增
├── constants.py
├── textbox.py                   ✅ 已优化
│
├── utils/                       ✅ 新增
│   ├── __init__.py
│   ├── resource_manager.py      # 资源管理和缓存
│   └── thread_utils.py          # 线程安全工具
│
├── models/                      🆕 新增（数据模型层）
│   ├── __init__.py
│   ├── document.py              # 文档模型
│   ├── page.py                  # 页面模型
│   ├── layer.py                 # 图层模型
│   └── textbox.py               # 文本框模型（迁移）
│
├── services/                    🆕 新增（服务层）
│   ├── __init__.py
│   ├── ocr_service.py           # OCR服务
│   ├── ai_service.py            # AI API服务
│   ├── export_service.py        # 导出服务
│   └── image_service.py         # 图片处理服务
│
├── controllers/                 🆕 新增（控制器层）
│   ├── __init__.py
│   ├── document_controller.py   # 文档控制器
│   ├── page_controller.py       # 页面控制器
│   └── edit_controller.py       # 编辑控制器
│
├── ui/                          # UI组件
│   ├── __init__.py
│   ├── main_window.py           # 主窗口
│   ├── toolbar.py               # 工具栏
│   ├── canvas_widget.py         # 画布组件
│   ├── thumbnail_panel.py       # 缩略图面板
│   ├── property_panel.py        # 属性面板
│   └── status_bar.py            # 状态栏
│
├── core/                        # 核心功能
│   ├── __init__.py
│   ├── history.py               # 历史记录
│   ├── page_manager.py          # 页面管理
│   ├── ocr.py
│   ├── ocr_improvements.py      ✅ 新增
│   └── font_fit.py
│
└── features/                    # 功能模块
    ├── __init__.py
    ├── inpaint.py
    ├── ai_replace.py
    ├── export.py
    └── project.py
```

## 🎯 重构优先级

### 阶段1：基础设施（1-2周）✅ 完成

- [x] 统一日志系统
- [x] 配置管理优化
- [x] 资源管理工具
- [x] 线程安全工具
- [x] 输入验证增强

### 阶段2：数据模型层（1-2周）

- [ ] 创建文档模型
- [ ] 创建页面模型
- [ ] 创建图层模型
- [ ] 迁移TextBox到models

### 阶段3：服务层（2-3周）

- [ ] OCR服务重构
- [ ] AI服务重构
- [ ] 导出服务重构
- [ ] 图片服务创建

### 阶段4：控制器层（2-3周）

- [ ] 文档控制器
- [ ] 页面控制器
- [ ] 编辑控制器

### 阶段5：UI层重构（3-4周）

- [ ] 主窗口拆分
- [ ] 组件化各个面板
- [ ] 事件处理优化

## 🔧 关键改进点

### 1. 使用日志系统

```python
# 在任何模块开始处添加
from ..logging_config import setup_logging, get_logger

# 在主程序入口（editor_main.py 或 __main__.py）
setup_logging(log_level="INFO", log_to_file=True)

# 在各模块中
logger = get_logger(__name__)

# 使用日志
logger.info("信息日志")
logger.error("错误日志")
logger.debug("调试日志")
```

### 2. 使用资源管理器

```python
from ..utils import TempFileManager, temp_file_context, ImageCache

# 方式1：使用上下文管理器
with temp_file_context(suffix='.png') as temp_path:
    image.save(temp_path)
    process_image(temp_path)
# 文件自动清理

# 方式2：使用临时文件管理器
temp_mgr = TempFileManager()
try:
    temp_path = temp_mgr.create_temp_file(suffix='.png')
    image.save(temp_path)
finally:
    temp_mgr.cleanup_all()

# 方式3：使用图片缓存
cache = ImageCache(max_size=20)
img = cache.get('path/to/image.png')
if img is None:
    img = Image.open('path/to/image.png')
    cache.put('path/to/image.png', img)
```

### 3. 使用线程池

```python
from ..utils import ManagedThreadPool

# 创建线程池
with ManagedThreadPool(max_workers=4, name="image_processing") as pool:
    # 提交任务
    future1 = pool.submit(process_image, img1)
    future2 = pool.submit(process_image, img2)

    # 等待完成
    result1 = future1.result()
    result2 = future2.result()

# 线程池自动清理

# 或使用回调
pool.submit_with_callback(
    process_image,
    callback=lambda result: print(f"Success: {result}"),
    error_callback=lambda err: print(f"Error: {err}"),
    img
)
```

### 4. 线程安全

```python
from ..utils import ReadWriteLock, ThreadSafeCache, synchronized

class MyClass:
    def __init__(self):
        self.rw_lock = ReadWriteLock()
        self.data = []

    def read_data(self):
        with self.rw_lock.read_lock():
            return self.data.copy()

    def write_data(self, value):
        with self.rw_lock.write_lock():
            self.data.append(value)

# 或使用装饰器
@synchronized()
def thread_safe_function():
    # 这个函数是线程安全的
    pass
```

## 📝 迁移步骤示例

### 步骤1：创建文档模型

创建 `models/document.py`:

```python
from typing import List, Optional
from .page import Page
from ..utils import ReadWriteLock
import logging

logger = logging.getLogger(__name__)


class Document:
    """文档模型 - 管理多个页面"""

    def __init__(self):
        self._pages: List[Page] = []
        self._current_page_index: int = 0
        self._lock = ReadWriteLock()
        self._unsaved_changes = False

    def add_page(self, page: Page) -> int:
        """添加页面"""
        with self._lock.write_lock():
            self._pages.append(page)
            self._unsaved_changes = True
            logger.info(f"Added page, total: {len(self._pages)}")
            return len(self._pages) - 1

    def remove_page(self, index: int) -> bool:
        """移除页面"""
        with self._lock.write_lock():
            if 0 <= index < len(self._pages):
                del self._pages[index]
                self._unsaved_changes = True
                logger.info(f"Removed page {index}")
                return True
            return False

    def get_page(self, index: int) -> Optional[Page]:
        """获取页面"""
        with self._lock.read_lock():
            if 0 <= index < len(self._pages):
                return self._pages[index]
            return None

    @property
    def current_page(self) -> Optional[Page]:
        """当前页面"""
        return self.get_page(self._current_page_index)

    @property
    def page_count(self) -> int:
        """页面数量"""
        with self._lock.read_lock():
            return len(self._pages)
```

### 步骤2：创建页面模型

创建 `models/page.py`:

```python
from typing import List, Optional
from PIL import Image
from ..textbox import TextBox
import logging

logger = logging.getLogger(__name__)


class Layer:
    """图层模型"""
    def __init__(self, image: Image.Image, x: int = 0, y: int = 0,
                 opacity: float = 1.0, visible: bool = True, name: str = ""):
        self.image = image
        self.x = x
        self.y = y
        self.opacity = opacity
        self.visible = visible
        self.name = name or f"Layer_{id(self)}"


class Page:
    """页面模型 - 包含图片、文本框和图层"""

    def __init__(self, image: Image.Image, original_path: str = ""):
        self.image = image
        self.original_path = original_path
        self.text_boxes: List[TextBox] = []
        self.layers: List[Layer] = []
        self.background_path: Optional[str] = None

    def add_textbox(self, textbox: TextBox) -> None:
        """添加文本框"""
        self.text_boxes.append(textbox)
        logger.debug(f"Added textbox, total: {len(self.text_boxes)}")

    def remove_textbox(self, index: int) -> bool:
        """移除文本框"""
        if 0 <= index < len(self.text_boxes):
            del self.text_boxes[index]
            logger.debug(f"Removed textbox {index}")
            return True
        return False

    def add_layer(self, layer: Layer) -> None:
        """添加图层"""
        self.layers.append(layer)
        logger.debug(f"Added layer '{layer.name}'")

    def get_composited_image(self) -> Image.Image:
        """获取合成后的图片（背景+图层）"""
        result = self.image.copy()

        # 叠加背景
        if self.background_path:
            try:
                bg = Image.open(self.background_path)
                if bg.size == result.size:
                    result = bg.copy()
            except Exception as e:
                logger.warning(f"Failed to load background: {e}")

        # 叠加图层
        for layer in self.layers:
            if not layer.visible:
                continue
            try:
                # 应用透明度并合成
                if layer.image.mode == 'RGBA':
                    alpha = layer.image.split()[3]
                    # 调整透明度
                    if layer.opacity < 1.0:
                        alpha = alpha.point(lambda p: int(p * layer.opacity))
                    result.paste(layer.image, (layer.x, layer.y), alpha)
                else:
                    result.paste(layer.image, (layer.x, layer.y))
            except Exception as e:
                logger.error(f"Failed to composite layer '{layer.name}': {e}")

        return result
```

### 步骤3：创建服务层

创建 `services/ocr_service.py`:

```python
import logging
from typing import Optional, List, Tuple
from PIL import Image
import numpy as np

from ..core.ocr_improvements import (
    create_temp_image_file,
    safe_ocr_predict,
    extract_text_from_ocr_result,
    crop_image_region
)

logger = logging.getLogger(__name__)


class OCRService:
    """OCR服务 - 封装OCR相关功能"""

    def __init__(self, config: dict):
        self.config = config
        self._ocr_model = None
        self._lock = threading.Lock()

    def initialize(self) -> bool:
        """初始化OCR模型"""
        with self._lock:
            if self._ocr_model is not None:
                return True

            try:
                # 使用 core.ocr 的初始化逻辑
                # 这里需要重构 init_ocr 函数
                logger.info("Initializing OCR model...")
                # self._ocr_model = ...
                return True
            except Exception as e:
                logger.error(f"Failed to initialize OCR: {e}")
                return False

    def recognize_region(
        self,
        image: Image.Image,
        x: int, y: int,
        width: int, height: int
    ) -> Optional[str]:
        """识别图片指定区域的文字"""
        if self._ocr_model is None:
            logger.warning("OCR model not initialized")
            return None

        try:
            # 转换为OpenCV格式
            img_array = np.array(image)
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

            # 裁剪区域
            cropped, _ = crop_image_region(
                img_array, x, y, width, height
            )

            # 使用临时文件
            with create_temp_image_file(cropped) as temp_path:
                result, error = safe_ocr_predict(
                    self._ocr_model, temp_path
                )

                if error:
                    logger.error(f"OCR prediction failed: {error}")
                    return None

                text = extract_text_from_ocr_result(result)
                return text

        except Exception as e:
            logger.error(f"OCR recognition failed: {e}")
            return None

    def recognize_full_image(
        self, image: Image.Image
    ) -> List[Tuple[str, List[List[int]]]]:
        """识别整张图片的文字和位置"""
        # 实现全图OCR
        pass
```

## ⚠️ 重要注意事项

### 向后兼容性

重构时保持API兼容：

```python
# 旧代码
editor.text_boxes.append(box)

# 新代码内部使用新模型，但保持接口
@property
def text_boxes(self):
    return self.document.current_page.text_boxes if self.document.current_page else []

@text_boxes.setter
def text_boxes(self, value):
    if self.document.current_page:
        self.document.current_page.text_boxes = value
```

### 渐进式迁移

不要一次性重写所有代码：

1. 创建新的模型和服务
2. 在新功能中使用新架构
3. 逐步迁移旧功能
4. 保持两套代码并存一段时间
5. 充分测试后移除旧代码

### 测试

每个新模块都要添加单元测试：

```python
# tests/test_textbox.py
import pytest
from ppt_editor_modular.textbox import TextBox

def test_textbox_creation():
    box = TextBox(10, 20, 100, 50)
    assert box.x == 10
    assert box.y == 20
    assert box.width == 100
    assert box.height == 50

def test_textbox_invalid_width():
    with pytest.raises(ValueError):
        TextBox(0, 0, -10, 10)
```

## 🚀 立即可用的改进

以下改进可以立即应用到现有代码：

### 1. 在 editor_main.py 开头添加

```python
from .logging_config import setup_logging, get_logger
from .utils import ImageCache, ManagedThreadPool, ReadWriteLock

# 在 __init__ 方法开始
setup_logging(log_level="INFO")
self.logger = get_logger(__name__)

# 添加资源管理
self.image_cache = ImageCache(max_size=20)
self.thread_pool = ManagedThreadPool(max_workers=4, name="editor")
self.state_lock = ReadWriteLock()
```

### 2. 替换所有临时文件创建

```python
# 旧代码
temp_file = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
temp_path = temp_file.name
temp_file.close()
try:
    cv2.imwrite(temp_path, img)
    # 使用 temp_path
finally:
    os.remove(temp_path)

# 新代码
from .utils import temp_file_context
with temp_file_context(suffix='.jpg') as temp_path:
    cv2.imwrite(temp_path, img)
    # 使用 temp_path
# 自动清理
```

### 3. 保护共享状态访问

```python
# 旧代码
def load_current_page(self):
    page = self.pages[self.current_page_index]
    self.text_boxes = [TextBox.from_dict(d) for d in page.get("text_boxes", [])]

# 新代码
def load_current_page(self):
    with self.state_lock.read_lock():
        page = self.pages[self.current_page_index]
    with self.state_lock.write_lock():
        self.text_boxes = [TextBox.from_dict(d) for d in page.get("text_boxes", [])]
```

## 📊 性能优化建议

1. **图片缓存**: 使用 `ImageCache` 缓存常用图片
2. **线程池**: 使用 `ManagedThreadPool` 处理并发任务
3. **延迟加载**: 只在需要时加载图片
4. **异步渲染**: 将耗时的渲染操作移到后台线程

## 🔍 代码质量检查

使用以下工具检查代码质量：

```bash
# 安装工具
pip install pylint mypy black isort

# 代码格式化
black ppt_editor_modular/
isort ppt_editor_modular/

# 类型检查
mypy ppt_editor_modular/ --ignore-missing-imports

# 代码检查
pylint ppt_editor_modular/
```

## 📚 参考资源

- Python日志系统：https://docs.python.org/3/library/logging.html
- 线程安全：https://docs.python.org/3/library/threading.html
- 上下文管理器：https://docs.python.org/3/library/contextlib.html
- 类型注解：https://docs.python.org/3/library/typing.html
