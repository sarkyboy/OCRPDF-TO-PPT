"""
配置模块 - 配置文件加载和保存
"""

import os
import json
import sys
import logging
from typing import Dict, Any

# 配置日志
logger = logging.getLogger(__name__)


# 获取程序运行目录
def get_base_dir():
    if getattr(sys, 'frozen', False):
        # 打包后的exe运行目录
        return os.path.dirname(sys.executable)
    else:
        # 开发环境 - 返回当前包目录（与 editor_main.py 保持一致）
        return os.path.dirname(os.path.abspath(__file__))


# 配置文件路径
CONFIG_FILE = os.path.join(get_base_dir(), "ppt_editor_config.json")


def load_config() -> Dict[str, Any]:
    """
    加载配置文件

    Returns:
        配置字典，如果加载失败则返回默认配置
    """
    default_config = {
        "model_dir": os.path.join(get_base_dir(), ".paddlex", "official_models"),
        "download_dir": os.path.join(get_base_dir(), "models"),
        "ocr_device": "cpu",
        "ocr_autoload": True,
        "inpaint_api_url": "http://127.0.0.1:8080/api/v1/inpaint",
        "inpaint_enabled": True,
        "autosave_enabled": True,
        "autosave_interval": 300
    }

    if not os.path.exists(CONFIG_FILE):
        logger.info(f"配置文件不存在，使用默认配置: {CONFIG_FILE}")
        return default_config

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 验证配置格式
        if not isinstance(config, dict):
            logger.warning("配置文件格式错误，使用默认配置")
            return default_config

        # 合并默认配置
        for key in default_config:
            if key not in config:
                config[key] = default_config[key]

        logger.info("配置文件加载成功")
        return config

    except json.JSONDecodeError as e:
        logger.error(f"配置文件JSON解析失败: {e}，使用默认配置")
        return default_config
    except PermissionError as e:
        logger.error(f"无权限读取配置文件: {e}，使用默认配置")
        return default_config
    except Exception as e:
        logger.error(f"加载配置文件时发生未知错误: {e}，使用默认配置")
        return default_config


def save_config(config: Dict[str, Any]) -> bool:
    """
    保存配置到文件

    Args:
        config: 配置字典

    Returns:
        True表示保存成功，False表示失败
    """
    if not isinstance(config, dict):
        logger.error("配置必须是字典类型")
        return False

    try:
        # 确保目录存在
        config_dir = os.path.dirname(CONFIG_FILE)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)

        # 先写入临时文件，成功后再重命名（原子操作）
        temp_file = CONFIG_FILE + '.tmp'
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        # 重命名（在Windows上需要先删除目标文件）
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        os.rename(temp_file, CONFIG_FILE)

        logger.info("配置文件保存成功")
        return True

    except PermissionError as e:
        logger.error(f"无权限写入配置文件: {e}")
        return False
    except OSError as e:
        logger.error(f"保存配置文件时发生系统错误: {e}")
        return False
    except Exception as e:
        logger.error(f"保存配置文件时发生未知错误: {e}")
        return False
    finally:
        # 清理临时文件
        temp_file = CONFIG_FILE + '.tmp'
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


def validate_config(config: Dict[str, Any]) -> bool:
    """
    验证配置的有效性

    Args:
        config: 配置字典

    Returns:
        True表示配置有效，False表示无效
    """
    try:
        # 验证必需的键
        required_keys = ["ocr_device", "inpaint_api_url"]
        for key in required_keys:
            if key not in config:
                logger.warning(f"配置缺少必需的键: {key}")
                return False

        # 验证数值范围
        if "autosave_interval" in config:
            interval = config["autosave_interval"]
            if not isinstance(interval, (int, float)) or interval < 0:
                logger.warning(f"自动保存间隔无效: {interval}")
                return False

        # 验证OCR设备选项
        if config["ocr_device"] not in ["cpu", "gpu"]:
            logger.warning(f"OCR设备选项无效: {config['ocr_device']}")
            return False

        return True

    except Exception as e:
        logger.error(f"验证配置时发生错误: {e}")
        return False
