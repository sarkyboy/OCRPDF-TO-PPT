# 常见问题 FAQ

## 📋 目录

- [安装问题](#安装问题)
- [运行问题](#运行问题)
- [功能问题](#功能问题)
- [性能问题](#性能问题)
- [其他问题](#其他问题)

---

## 安装问题

### Q: 如何安装 PaddleOCR？

**A:** PaddleOCR 的安装取决于您的平台和是否需要 GPU 支持：

```bash
# CPU 版本（推荐，最稳定）
pip install paddlepaddle paddleocr

# GPU 版本（Windows，CUDA 11.x）
pip install paddlepaddle-gpu==2.6.2
pip install "paddleocr<3"

# 其他平台的 GPU 版本请参考：
# https://www.paddlepaddle.org.cn/install/quick
```

### Q: 安装时出现 "No module named 'tkinter'" 错误

**A:** Tkinter 通常随 Python 一起安装，但在某些 Linux 系统上需要单独安装：

```bash
# Ubuntu/Debian
sudo apt-get install python3-tk

# CentOS/RHEL
sudo yum install python3-tkinter

# macOS (使用 Homebrew)
brew install python-tk
```

### Q: PyMuPDF 安装失败

**A:** 尝试以下方法：

```bash
# 方法1：升级 pip
pip install --upgrade pip
pip install PyMuPDF

# 方法2：使用预编译版本
pip install PyMuPDF-binary

# 方法3：从清华镜像安装
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PyMuPDF
```

---

## 运行问题

### Q: 程序启动后立即崩溃

**A:** 检查以下几点：

1. **查看日志文件**
   ```bash
   cat logs/ppt_editor_error_*.log
   ```

2. **使用调试模式运行**
   ```bash
   python run_ppt_editor_improved.py --debug
   ```

3. **检查依赖是否完整**
   ```bash
   pip install -r requirements.txt --upgrade
   ```

### Q: OCR 功能不可用

**A:** 可能的原因和解决方法：

1. **PaddleOCR 未安装**
   ```bash
   pip install paddleocr
   ```

2. **模型正在下载**
   - 首次使用时 PaddleOCR 会自动下载模型（约 100MB）
   - 等待下载完成或手动下载模型

3. **GPU 驱动问题**（如果使用 GPU）
   - 检查 CUDA 和 cuDNN 是否正确安装
   - 尝试切换到 CPU 模式：修改配置文件中的 `ocr_device` 为 `"cpu"`

### Q: 程序运行缓慢

**A:** 性能优化建议：

1. **启用图片缓存**（v2.0 已默认启用）
   ```python
   # 确认缓存已启用
   self.image_cache = ImageCache(max_size=20)
   ```

2. **使用 GPU 加速 OCR**
   ```json
   {
     "ocr_device": "gpu"
   }
   ```

3. **减少自动保存频率**
   ```json
   {
     "autosave_interval": 600  // 改为10分钟
   }
   ```

4. **关闭不需要的功能**
   ```json
   {
     "ocr_autoload": false,  // 手动加载 OCR
     "autosave_enabled": false  // 手动保存
   }
   ```

---

## 功能问题

### Q: AI 图片替换不工作

**A:** 检查 API 配置：

1. **配置 API Key**
   ```json
   {
     "ai_image_api": {
       "api_type": "openai",
       "openai": {
         "api_key": "sk-your-actual-api-key-here",
         "api_host": "https://api.openai.com/v1"
       }
     }
   }
   ```

2. **测试 API 连接**
   - 查看日志中的 API 调用信息
   - 确认网络可以访问 API 地址
   - 检查 API Key 是否有效

3. **使用其他 API**
   ```json
   {
     "ai_image_api": {
       "api_type": "gemini",
       "gemini": {
         "api_key": "your-gemini-key",
         "api_host": "https://generativelanguage.googleapis.com"
       }
     }
   }
   ```

### Q: 背景去除功能不可用

**A:** 背景去除需要 IOPaint 服务：

1. **安装 IOPaint**
   ```bash
   pip install iopaint
   ```

2. **启动 IOPaint 服务**
   ```bash
   iopaint start --host 127.0.0.1 --port 8080
   ```

3. **配置 API 地址**
   ```json
   {
     "inpaint_api_url": "http://127.0.0.1:8080/api/v1/inpaint",
     "inpaint_enabled": true
   }
   ```

### Q: PDF 导入后图片模糊

**A:** PDF 导入分辨率设置：

1. **提高导出 DPI**（在 `features/project.py` 中修改）
   ```python
   # 找到 PDF 转换代码
   pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))  # 提高到 300 DPI
   ```

2. **使用原始 PDF 尺寸**
   - 避免缩放，保持原始分辨率

### Q: 导出的 PPT 中文显示乱码

**A:** 字体编码问题：

1. **确保使用支持中文的字体**
   - 微软雅黑、宋体、黑体等

2. **检查字体是否存在**
   ```python
   # 在导出代码中添加字体检查
   if not os.path.exists(font_path):
       font_path = "C:/Windows/Fonts/msyh.ttc"  # 使用系统字体
   ```

---

## 性能问题

### Q: 内存占用过高

**A:** 内存优化建议：

1. **检查图片缓存大小**
   ```python
   # 减少缓存大小
   self.image_cache = ImageCache(max_size=10)
   ```

2. **及时清理不用的页面**
   - 删除不需要的页面
   - 定期保存并重新打开项目

3. **减少图层数量**
   - 合并相似图层
   - 删除不可见的图层

### Q: 临时文件占用磁盘空间

**A:** v2.0 已自动清理临时文件。如果仍有问题：

1. **手动清理临时目录**
   ```bash
   # Windows
   rd /s /q temp_backgrounds temp_inpaint temp_cutout

   # Linux/Mac
   rm -rf temp_backgrounds temp_inpaint temp_cutout
   ```

2. **启用自动清理**（v2.0 默认启用）
   ```python
   # 使用新的资源管理器
   from ppt_editor_modular.utils import TempFileManager
   temp_mgr = TempFileManager()
   ```

### Q: OCR 批处理太慢

**A:** 使用线程池加速（v2.0 已支持）：

```python
# 在代码中使用线程池
from ppt_editor_modular.utils import ManagedThreadPool

with ManagedThreadPool(max_workers=4) as pool:
    futures = [pool.submit(ocr_page, page) for page in pages]
    results = [f.result() for f in futures]
```

---

## 其他问题

### Q: 如何查看详细的错误信息？

**A:** 查看日志文件：

```bash
# 查看所有日志
cat logs/ppt_editor_YYYYMMDD.log

# 只查看错误日志
cat logs/ppt_editor_error_YYYYMMDD.log

# 实时查看日志（Linux/Mac）
tail -f logs/ppt_editor_*.log
```

或使用调试模式：

```bash
python run_ppt_editor_improved.py --debug --log-level DEBUG
```

### Q: 配置文件在哪里？

**A:** 配置文件位置：

- 开发环境：项目根目录下的 `ppt_editor_config.json`
- 打包后：可执行文件同目录下的 `ppt_editor_config.json`

查看配置文件路径：

```python
from ppt_editor_modular.config import CONFIG_FILE
print(CONFIG_FILE)
```

### Q: 如何重置配置？

**A:** 删除配置文件，程序会自动创建默认配置：

```bash
# Windows
del ppt_editor_config.json

# Linux/Mac
rm ppt_editor_config.json
```

### Q: 支持哪些图片格式？

**A:** 支持的格式：

- 导入：JPG, JPEG, PNG, BMP, GIF, PDF
- 导出：PNG, JPG, PDF, PPTX

### Q: 可以在 Linux/Mac 上运行吗？

**A:** 是的，本项目支持跨平台：

- ✅ Windows 7/10/11
- ✅ Linux（Ubuntu, CentOS 等）
- ✅ macOS 10.14+

注意：
- Linux 需要安装 Tkinter：`sudo apt-get install python3-tk`
- macOS 可能需要使用 Python 3.8+ 的官方版本

### Q: 如何贡献代码？

**A:** 参考 [贡献指南](CONTRIBUTING.md)：

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 发起 Pull Request

### Q: 项目使用什么许可证？

**A:** MIT 许可证 - 可以自由使用、修改和分发。详见 [LICENSE](LICENSE) 文件。

---

## 🆘 仍然有问题？

如果上述答案没有解决您的问题：

1. **搜索 Issues**
   - https://github.com/Tansuo2021/OCRPDF-TO-PPT/issues

2. **创建新 Issue**
   - 提供详细的错误信息
   - 附上日志文件内容
   - 说明操作步骤

3. **参与讨论**
   - https://github.com/Tansuo2021/OCRPDF-TO-PPT/discussions

---

*FAQ 最后更新: 2025-12-15*
