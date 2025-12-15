"""
TextBox数据类 - 文本框数据模型
包含完整的输入验证和类型检查
"""

import copy
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class TextBox:
    """文本框数据类，包含位置、尺寸和格式信息"""

    # 有效的对齐方式
    VALID_ALIGNMENTS = {"left", "center", "right"}

    def __init__(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        text: str = "",
        font_size: int = 16,
        font_name: str = "微软雅黑",
        font_color: str = "#000000",
        bold: bool = False,
        italic: bool = False,
        align: str = "left"
    ):
        """
        初始化文本框

        Args:
            x: X坐标
            y: Y坐标
            width: 宽度
            height: 高度
            text: 文本内容
            font_size: 字体大小
            font_name: 字体名称
            font_color: 字体颜色
            bold: 是否粗体
            italic: 是否斜体
            align: 对齐方式

        Raises:
            ValueError: 如果参数值无效
        """
        # 验证坐标和尺寸
        if not isinstance(x, (int, float)):
            raise ValueError(f"x坐标必须是数字，得到: {type(x)}")
        if not isinstance(y, (int, float)):
            raise ValueError(f"y坐标必须是数字，得到: {type(y)}")
        if not isinstance(width, (int, float)) or width < 0:
            raise ValueError(f"宽度必须是非负数字，得到: {width}")
        if not isinstance(height, (int, float)) or height < 0:
            raise ValueError(f"高度必须是非负数字，得到: {height}")

        # 验证字体大小
        if not isinstance(font_size, (int, float)) or font_size <= 0:
            raise ValueError(f"字体大小必须是正数，得到: {font_size}")

        # 验证对齐方式
        if align not in self.VALID_ALIGNMENTS:
            logger.warning(f"无效的对齐方式: {align}，使用默认值 'left'")
            align = "left"

        # 验证颜色格式
        if not self._is_valid_color(font_color):
            logger.warning(f"无效的颜色格式: {font_color}，使用默认值 '#000000'")
            font_color = "#000000"

        self.x = float(x)
        self.y = float(y)
        self.width = float(width)
        self.height = float(height)
        self.text = str(text)
        self.font_size = int(font_size)
        self.font_name = str(font_name)
        self.font_color = str(font_color)
        self.bold = bool(bold)
        self.italic = bool(italic)
        self.align = str(align)

    @staticmethod
    def _is_valid_color(color: str) -> bool:
        """验证颜色格式是否有效（#RRGGBB或#RGB）"""
        if not isinstance(color, str):
            return False
        if not color.startswith('#'):
            return False
        color_part = color[1:]
        if len(color_part) not in (3, 6):
            return False
        try:
            int(color_part, 16)
            return True
        except ValueError:
            return False

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典

        Returns:
            包含所有属性的字典
        """
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "text": self.text,
            "font_size": self.font_size,
            "font_name": self.font_name,
            "font_color": self.font_color,
            "bold": self.bold,
            "italic": self.italic,
            "align": self.align
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional["TextBox"]:
        """
        从字典创建文本框

        Args:
            data: 包含文本框属性的字典

        Returns:
            TextBox实例，如果数据无效则返回None

        Raises:
            ValueError: 如果缺少必需的字段
        """
        if not isinstance(data, dict):
            logger.error(f"from_dict需要字典类型，得到: {type(data)}")
            return None

        # 检查必需字段
        required_fields = ["x", "y", "width", "height"]
        missing_fields = [f for f in required_fields if f not in data]
        if missing_fields:
            logger.error(f"缺少必需字段: {missing_fields}")
            raise ValueError(f"缺少必需字段: {missing_fields}")

        try:
            box = cls(
                x=data["x"],
                y=data["y"],
                width=data["width"],
                height=data["height"],
                text=data.get("text", ""),
                font_size=data.get("font_size", 16),
                font_name=data.get("font_name", "微软雅黑"),
                font_color=data.get("font_color", "#000000"),
                bold=data.get("bold", False),
                italic=data.get("italic", False),
                align=data.get("align", "left")
            )
            return box
        except (ValueError, TypeError) as e:
            logger.error(f"从字典创建TextBox失败: {e}")
            return None

    def copy(self) -> "TextBox":
        """
        创建文本框的深拷贝

        Returns:
            新的TextBox实例
        """
        return copy.deepcopy(self)

    def move(self, dx: float, dy: float) -> None:
        """
        移动文本框

        Args:
            dx: X方向移动距离
            dy: Y方向移动距离
        """
        self.x += dx
        self.y += dy

    def resize(self, new_width: float, new_height: float) -> None:
        """
        调整文本框大小

        Args:
            new_width: 新宽度
            new_height: 新高度

        Raises:
            ValueError: 如果尺寸无效
        """
        if new_width < 0 or new_height < 0:
            raise ValueError("尺寸不能为负数")
        self.width = new_width
        self.height = new_height

    def contains_point(self, px: float, py: float) -> bool:
        """
        检查点是否在文本框内

        Args:
            px: 点的X坐标
            py: 点的Y坐标

        Returns:
            True表示点在文本框内
        """
        return (self.x <= px <= self.x + self.width and
                self.y <= py <= self.y + self.height)

    def intersects(self, other: "TextBox") -> bool:
        """
        检查是否与另一个文本框相交

        Args:
            other: 另一个文本框

        Returns:
            True表示两个文本框相交
        """
        return not (
            self.x + self.width < other.x or
            other.x + other.width < self.x or
            self.y + self.height < other.y or
            other.y + other.height < self.y
        )

    def __repr__(self) -> str:
        """返回文本框的字符串表示"""
        return (f"TextBox(x={self.x}, y={self.y}, "
                f"width={self.width}, height={self.height}, "
                f"text='{self.text[:20]}...')")

    def __eq__(self, other: object) -> bool:
        """比较两个文本框是否相等"""
        if not isinstance(other, TextBox):
            return False
        return (self.x == other.x and self.y == other.y and
                self.width == other.width and self.height == other.height and
                self.text == other.text)
