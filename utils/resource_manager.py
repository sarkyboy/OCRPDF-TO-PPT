"""
资源管理模块 - 提供资源清理和上下文管理器
"""

import os
import tempfile
import logging
from typing import Optional, List
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class TempFileManager:
    """临时文件管理器，确保临时文件被正确清理"""

    def __init__(self):
        self._temp_files: List[str] = []
        self._temp_dirs: List[str] = []

    def create_temp_file(
        self,
        suffix: str = "",
        prefix: str = "ppt_editor_",
        delete: bool = False
    ) -> str:
        """
        创建临时文件并跟踪

        Args:
            suffix: 文件后缀
            prefix: 文件前缀
            delete: 是否在创建时删除（False表示手动管理）

        Returns:
            临时文件路径
        """
        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix,
                prefix=prefix,
                delete=delete
            ) as f:
                temp_path = f.name

            self._temp_files.append(temp_path)
            logger.debug(f"创建临时文件: {temp_path}")
            return temp_path

        except Exception as e:
            logger.error(f"创建临时文件失败: {e}")
            raise

    def create_temp_dir(self, prefix: str = "ppt_editor_") -> str:
        """
        创建临时目录并跟踪

        Args:
            prefix: 目录前缀

        Returns:
            临时目录路径
        """
        try:
            temp_dir = tempfile.mkdtemp(prefix=prefix)
            self._temp_dirs.append(temp_dir)
            logger.debug(f"创建临时目录: {temp_dir}")
            return temp_dir

        except Exception as e:
            logger.error(f"创建临时目录失败: {e}")
            raise

    def cleanup_file(self, filepath: str) -> bool:
        """
        清理指定的临时文件

        Args:
            filepath: 文件路径

        Returns:
            True表示清理成功
        """
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                if filepath in self._temp_files:
                    self._temp_files.remove(filepath)
                logger.debug(f"清理临时文件: {filepath}")
                return True
            return False

        except Exception as e:
            logger.warning(f"清理临时文件失败 {filepath}: {e}")
            return False

    def cleanup_dir(self, dirpath: str) -> bool:
        """
        清理指定的临时目录

        Args:
            dirpath: 目录路径

        Returns:
            True表示清理成功
        """
        try:
            if os.path.exists(dirpath):
                import shutil
                shutil.rmtree(dirpath)
                if dirpath in self._temp_dirs:
                    self._temp_dirs.remove(dirpath)
                logger.debug(f"清理临时目录: {dirpath}")
                return True
            return False

        except Exception as e:
            logger.warning(f"清理临时目录失败 {dirpath}: {e}")
            return False

    def cleanup_all(self) -> None:
        """清理所有跟踪的临时文件和目录"""
        logger.info("开始清理所有临时文件...")

        # 清理文件
        for filepath in self._temp_files.copy():
            self.cleanup_file(filepath)

        # 清理目录
        for dirpath in self._temp_dirs.copy():
            self.cleanup_dir(dirpath)

        logger.info("临时文件清理完成")

    def __del__(self):
        """析构时自动清理"""
        self.cleanup_all()

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口，自动清理"""
        self.cleanup_all()
        return False


@contextmanager
def temp_file_context(suffix: str = "", prefix: str = "ppt_editor_"):
    """
    临时文件上下文管理器

    使用示例:
        with temp_file_context(suffix='.png') as temp_path:
            # 使用临时文件
            save_image(temp_path)
        # 文件自动清理

    Args:
        suffix: 文件后缀
        prefix: 文件前缀

    Yields:
        临时文件路径
    """
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            prefix=prefix,
            delete=False
        ) as f:
            temp_path = f.name

        logger.debug(f"创建临时文件: {temp_path}")
        yield temp_path

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug(f"清理临时文件: {temp_path}")
            except Exception as e:
                logger.warning(f"清理临时文件失败 {temp_path}: {e}")


@contextmanager
def temp_dir_context(prefix: str = "ppt_editor_"):
    """
    临时目录上下文管理器

    使用示例:
        with temp_dir_context() as temp_dir:
            # 使用临时目录
            save_files(temp_dir)
        # 目录自动清理

    Args:
        prefix: 目录前缀

    Yields:
        临时目录路径
    """
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=prefix)
        logger.debug(f"创建临时目录: {temp_dir}")
        yield temp_dir

    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                import shutil
                shutil.rmtree(temp_dir)
                logger.debug(f"清理临时目录: {temp_dir}")
            except Exception as e:
                logger.warning(f"清理临时目录失败 {temp_dir}: {e}")


class ImageCache:
    """图片缓存管理器（使用LRU策略）"""

    def __init__(self, max_size: int = 20):
        """
        初始化图片缓存

        Args:
            max_size: 最大缓存数量
        """
        from collections import OrderedDict
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size
        logger.info(f"初始化图片缓存，最大容量: {max_size}")

    def get(self, key: str):
        """
        获取缓存的图片

        Args:
            key: 缓存键（通常是文件路径）

        Returns:
            缓存的图片，如果不存在则返回None
        """
        if key in self._cache:
            # 移到末尾（最近使用）
            self._cache.move_to_end(key)
            logger.debug(f"命中缓存: {key}")
            return self._cache[key]
        return None

    def put(self, key: str, value) -> None:
        """
        放入图片到缓存

        Args:
            key: 缓存键
            value: 图片对象
        """
        if key in self._cache:
            # 更新并移到末尾
            self._cache.move_to_end(key)
        else:
            # 新增
            self._cache[key] = value
            logger.debug(f"加入缓存: {key}")

            # 检查容量
            if len(self._cache) > self._max_size:
                # 移除最旧的
                removed_key, _ = self._cache.popitem(last=False)
                logger.debug(f"缓存已满，移除: {removed_key}")

    def clear(self) -> None:
        """清空缓存"""
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"清空缓存，移除 {count} 个项目")

    def remove(self, key: str) -> bool:
        """
        移除指定的缓存项

        Args:
            key: 缓存键

        Returns:
            True表示移除成功
        """
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"移除缓存: {key}")
            return True
        return False

    def __len__(self) -> int:
        """返回缓存中的项目数量"""
        return len(self._cache)


def ensure_dir(path: str) -> bool:
    """
    确保目录存在，如果不存在则创建

    Args:
        path: 目录路径

    Returns:
        True表示目录存在或创建成功
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            logger.debug(f"创建目录: {path}")
        return True
    except Exception as e:
        logger.error(f"创建目录失败 {path}: {e}")
        return False


def safe_delete_file(filepath: str) -> bool:
    """
    安全删除文件

    Args:
        filepath: 文件路径

    Returns:
        True表示删除成功或文件不存在
    """
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.debug(f"删除文件: {filepath}")
        return True
    except Exception as e:
        logger.warning(f"删除文件失败 {filepath}: {e}")
        return False
