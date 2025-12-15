"""
线程工具模块 - 提供线程安全和并发控制
"""

import threading
import logging
from typing import Any, Callable, Optional, List
from concurrent.futures import ThreadPoolExecutor, Future
from functools import wraps

logger = logging.getLogger(__name__)


class ThreadSafeCounter:
    """线程安全的计数器"""

    def __init__(self, initial_value: int = 0):
        """
        初始化计数器

        Args:
            initial_value: 初始值
        """
        self._value = initial_value
        self._lock = threading.Lock()

    def increment(self, delta: int = 1) -> int:
        """
        增加计数器

        Args:
            delta: 增量

        Returns:
            增加后的值
        """
        with self._lock:
            self._value += delta
            return self._value

    def decrement(self, delta: int = 1) -> int:
        """
        减少计数器

        Args:
            delta: 减量

        Returns:
            减少后的值
        """
        with self._lock:
            self._value -= delta
            return self._value

    def get(self) -> int:
        """获取当前值"""
        with self._lock:
            return self._value

    def set(self, value: int) -> None:
        """设置值"""
        with self._lock:
            self._value = value


class ThreadSafeCache:
    """线程安全的缓存"""

    def __init__(self):
        self._cache = {}
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        """获取缓存值"""
        with self._lock:
            return self._cache.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置缓存值"""
        with self._lock:
            self._cache[key] = value

    def delete(self, key: str) -> bool:
        """删除缓存值"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()

    def keys(self) -> List[str]:
        """获取所有键"""
        with self._lock:
            return list(self._cache.keys())


class ManagedThreadPool:
    """管理的线程池，支持任务追踪和优雅关闭"""

    def __init__(self, max_workers: int = 4, name: str = "default"):
        """
        初始化线程池

        Args:
            max_workers: 最大工作线程数
            name: 线程池名称
        """
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=f"PPTEditor-{name}"
        )
        self._futures: List[Future] = []
        self._lock = threading.Lock()
        self._name = name
        logger.info(f"创建线程池 '{name}'，工作线程数: {max_workers}")

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        """
        提交任务到线程池

        Args:
            fn: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            Future对象
        """
        with self._lock:
            future = self._pool.submit(fn, *args, **kwargs)
            self._futures.append(future)
            logger.debug(f"线程池 '{self._name}' 提交任务: {fn.__name__}")
            return future

    def submit_with_callback(
        self,
        fn: Callable,
        callback: Optional[Callable] = None,
        error_callback: Optional[Callable] = None,
        *args,
        **kwargs
    ) -> Future:
        """
        提交任务并设置回调

        Args:
            fn: 要执行的函数
            callback: 成功回调函数
            error_callback: 错误回调函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            Future对象
        """
        future = self.submit(fn, *args, **kwargs)

        def done_callback(f: Future):
            try:
                result = f.result()
                if callback:
                    callback(result)
            except Exception as e:
                logger.error(f"任务执行失败: {e}")
                if error_callback:
                    error_callback(e)

        future.add_done_callback(done_callback)
        return future

    def wait_all(self, timeout: Optional[float] = None) -> bool:
        """
        等待所有任务完成

        Args:
            timeout: 超时时间（秒）

        Returns:
            True表示所有任务完成
        """
        logger.info(f"等待线程池 '{self._name}' 中的所有任务完成...")
        from concurrent.futures import wait, FIRST_EXCEPTION

        with self._lock:
            futures = list(self._futures)

        if not futures:
            return True

        done, not_done = wait(futures, timeout=timeout, return_when=FIRST_EXCEPTION)

        if not_done:
            logger.warning(f"线程池 '{self._name}' 有 {len(not_done)} 个任务未完成")
            return False

        logger.info(f"线程池 '{self._name}' 所有任务完成")
        return True

    def cancel_all(self) -> int:
        """
        取消所有未完成的任务

        Returns:
            成功取消的任务数量
        """
        logger.info(f"取消线程池 '{self._name}' 中的所有任务...")
        with self._lock:
            futures = list(self._futures)

        cancelled_count = 0
        for future in futures:
            if future.cancel():
                cancelled_count += 1

        logger.info(f"线程池 '{self._name}' 取消了 {cancelled_count} 个任务")
        return cancelled_count

    def shutdown(self, wait: bool = True) -> None:
        """
        关闭线程池

        Args:
            wait: 是否等待所有任务完成
        """
        logger.info(f"关闭线程池 '{self._name}'...")
        self._pool.shutdown(wait=wait)
        with self._lock:
            self._futures.clear()
        logger.info(f"线程池 '{self._name}' 已关闭")

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口，自动关闭"""
        self.shutdown(wait=True)
        return False


def synchronized(lock: Optional[threading.Lock] = None):
    """
    同步装饰器，使函数线程安全

    使用示例:
        @synchronized()
        def my_function():
            # 线程安全的代码
            pass

    Args:
        lock: 锁对象，如果不提供则创建新锁
    """
    if lock is None:
        lock = threading.RLock()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)
        return wrapper
    return decorator


class ReadWriteLock:
    """读写锁，允许多个读取者或一个写入者"""

    def __init__(self):
        self._readers = 0
        self._writers = 0
        self._read_ready = threading.Condition(threading.RLock())
        self._write_ready = threading.Condition(threading.RLock())

    def acquire_read(self):
        """获取读锁"""
        with self._read_ready:
            while self._writers > 0:
                self._read_ready.wait()
            self._readers += 1

    def release_read(self):
        """释放读锁"""
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._write_ready.notify_all()

    def acquire_write(self):
        """获取写锁"""
        with self._write_ready:
            while self._writers > 0 or self._readers > 0:
                self._write_ready.wait()
            self._writers += 1

    def release_write(self):
        """释放写锁"""
        with self._write_ready:
            self._writers -= 1
            self._read_ready.notify_all()
            self._write_ready.notify_all()

    def read_lock(self):
        """读锁上下文管理器"""
        return _ReadLockContext(self)

    def write_lock(self):
        """写锁上下文管理器"""
        return _WriteLockContext(self)


class _ReadLockContext:
    """读锁上下文管理器"""

    def __init__(self, lock: ReadWriteLock):
        self._lock = lock

    def __enter__(self):
        self._lock.acquire_read()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release_read()
        return False


class _WriteLockContext:
    """写锁上下文管理器"""

    def __init__(self, lock: ReadWriteLock):
        self._lock = lock

    def __enter__(self):
        self._lock.acquire_write()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release_write()
        return False
