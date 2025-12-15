"""
改进的启动脚本 - 集成所有优化

用法：
  python run_ppt_editor_improved.py
  python run_ppt_editor_improved.py --debug
  python run_ppt_editor_improved.py --log-level DEBUG
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def setup_import_path():
    """设置导入路径"""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(this_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)


def main(argv: list[str] | None = None) -> int:
    """主函数"""
    parser = argparse.ArgumentParser(
        prog="run_ppt_editor_improved.py",
        description="PPT编辑器 - 优化版"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试模式（详细日志）"
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别"
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="不输出日志到文件"
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="冒烟测试模式（创建窗口后立即退出）"
    )
    args = parser.parse_args(argv)

    # 设置导入路径
    setup_import_path()

    # 导入日志配置
    from ppt_editor_modular.logging_config import setup_logging
    import logging

    # 确定日志级别
    log_level = args.log_level
    if log_level is None:
        log_level = "DEBUG" if args.debug else "INFO"

    # 配置日志
    setup_logging(
        log_level=log_level,
        log_to_file=not args.no_log_file,
        log_to_console=True
    )

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("PPT编辑器启动（优化版）")
    logger.info(f"Python版本: {sys.version}")
    logger.info(f"工作目录: {os.getcwd()}")
    logger.info(f"日志级别: {log_level}")
    logger.info("=" * 60)

    try:
        # 导入Tkinter
        import tkinter as tk
        logger.info("Tkinter导入成功")

        # 导入编辑器
        from ppt_editor_modular.editor_main import ModernPPTEditor
        logger.info("ModernPPTEditor导入成功")

        # 创建主窗口
        logger.info("创建主窗口...")
        root = tk.Tk()

        # 创建编辑器实例
        logger.info("初始化编辑器...")
        editor = ModernPPTEditor(root)

        # 冒烟测试模式
        if args.smoke:
            logger.info("冒烟测试模式：更新窗口后退出")
            root.update_idletasks()
            root.destroy()
            logger.info("冒烟测试完成")
            return 0

        # 正常运行
        logger.info("启动主循环...")
        root.mainloop()

        logger.info("程序正常退出")
        return 0

    except ImportError as e:
        logger.error(f"导入模块失败: {e}")
        logger.error("请检查依赖是否已安装：pip install -r requirements.txt")
        return 1

    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        return 1

    finally:
        logger.info("清理资源...")
        # 这里可以添加全局资源清理
        logger.info("资源清理完成")


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
