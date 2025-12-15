"""
日志配置模块 - 统一的日志管理
"""

import logging
import os
import sys
from datetime import datetime
from typing import Optional

from .config import get_base_dir


def setup_logging(
    log_level: str = "INFO",
    log_to_file: bool = True,
    log_to_console: bool = True,
    log_dir: Optional[str] = None
) -> None:
    """
    配置应用程序的日志系统

    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: 是否输出到文件
        log_to_console: 是否输出到控制台
        log_dir: 日志文件目录（默认为程序目录下的logs文件夹）
    """
    # 转换日志级别
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # 创建根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # 清除已有的处理器
    root_logger.handlers.clear()

    # 日志格式
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # 控制台处理器
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(simple_formatter)
        root_logger.addHandler(console_handler)

    # 文件处理器
    if log_to_file:
        if log_dir is None:
            log_dir = os.path.join(get_base_dir(), "logs")

        # 创建日志目录
        os.makedirs(log_dir, exist_ok=True)

        # 按日期命名日志文件
        log_filename = f"ppt_editor_{datetime.now().strftime('%Y%m%d')}.log"
        log_filepath = os.path.join(log_dir, log_filename)

        try:
            file_handler = logging.FileHandler(
                log_filepath,
                encoding='utf-8',
                mode='a'
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(detailed_formatter)
            root_logger.addHandler(file_handler)

            # 添加错误日志文件（只记录ERROR及以上级别）
            error_log_filename = f"ppt_editor_error_{datetime.now().strftime('%Y%m%d')}.log"
            error_log_filepath = os.path.join(log_dir, error_log_filename)

            error_file_handler = logging.FileHandler(
                error_log_filepath,
                encoding='utf-8',
                mode='a'
            )
            error_file_handler.setLevel(logging.ERROR)
            error_file_handler.setFormatter(detailed_formatter)
            root_logger.addHandler(error_file_handler)

        except (PermissionError, OSError) as e:
            # 如果无法创建日志文件，只输出到控制台
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(logging.WARNING)
            console_handler.setFormatter(simple_formatter)
            root_logger.addHandler(console_handler)
            logging.warning(f"无法创建日志文件: {e}，仅输出到控制台")

    # 设置第三方库的日志级别
    logging.getLogger('PIL').setLevel(logging.WARNING)
    logging.getLogger('ppocr').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)

    # 记录启动信息
    logging.info("=" * 60)
    logging.info("PPT编辑器启动")
    logging.info(f"日志级别: {log_level}")
    logging.info(f"日志目录: {log_dir if log_to_file else '不记录文件'}")
    logging.info("=" * 60)


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志记录器

    Args:
        name: 日志记录器名称（通常使用 __name__）

    Returns:
        日志记录器实例
    """
    return logging.getLogger(name)


class LoggerMixin:
    """
    日志记录器混入类，为类添加日志功能

    使用方法:
        class MyClass(LoggerMixin):
            def some_method(self):
                self.logger.info("日志消息")
    """

    @property
    def logger(self) -> logging.Logger:
        """获取当前类的日志记录器"""
        if not hasattr(self, '_logger'):
            self._logger = logging.getLogger(
                f"{self.__class__.__module__}.{self.__class__.__name__}"
            )
        return self._logger
