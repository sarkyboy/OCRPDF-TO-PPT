"""
工具模块 - 提供通用工具类和辅助函数
"""

from .resource_manager import (
    TempFileManager,
    temp_file_context,
    temp_dir_context,
    ImageCache,
    ensure_dir,
    safe_delete_file
)

from .thread_utils import (
    ThreadSafeCounter,
    ThreadSafeCache,
    ManagedThreadPool,
    synchronized,
    ReadWriteLock
)

__all__ = [
    'TempFileManager',
    'temp_file_context',
    'temp_dir_context',
    'ImageCache',
    'ensure_dir',
    'safe_delete_file',
    'ThreadSafeCounter',
    'ThreadSafeCache',
    'ManagedThreadPool',
    'synchronized',
    'ReadWriteLock'
]
