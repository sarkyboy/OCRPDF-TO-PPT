"""
测试所有模块导入是否正常
运行: python test_imports.py
"""

import sys
from pathlib import Path

def test_imports():
    """测试所有核心模块是否可以导入"""
    errors = []
    success = []

    modules_to_test = [
        "config",
        "constants",
        "logging_config",
        "textbox",
        "core.history",
        "core.page_manager",
        "core.ocr",
        "core.font_fit",
        "features.inpaint",
        "features.ai_replace",
        "features.export",
        "features.project",
        "ui.toolbar",
        "ui.canvas_area",
        "ui.property_panel",
        "ui.status_bar",
        "ui.thumbnail",
        "utils.resource_manager",
        "utils.thread_utils",
    ]

    print("🧪 开始测试模块导入...")
    print("=" * 60)

    for module_name in modules_to_test:
        try:
            __import__(module_name)
            success.append(module_name)
            print(f"✅ {module_name}")
        except Exception as e:
            errors.append((module_name, str(e)))
            print(f"❌ {module_name}: {e}")

    print("=" * 60)
    print(f"\n📊 测试结果:")
    print(f"   成功: {len(success)}/{len(modules_to_test)}")
    print(f"   失败: {len(errors)}/{len(modules_to_test)}")

    if errors:
        print("\n❌ 失败的模块:")
        for module, error in errors:
            print(f"   - {module}: {error}")
        return False
    else:
        print("\n✅ 所有模块导入成功！项目可以正常运行。")
        return True

if __name__ == "__main__":
    # 添加当前目录到 Python 路径
    this_dir = Path(__file__).parent
    sys.path.insert(0, str(this_dir))

    success = test_imports()
    sys.exit(0 if success else 1)
