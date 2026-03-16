# utils.py
"""通用工具函数集合。"""

import io
from datetime import datetime
from PIL import Image


def image_to_bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    """将 PIL.Image 对象转换为字节串，供 NoneBot MessageSegment.image() 使用。

    Args:
        image: PIL.Image 对象。
        fmt:   保存格式，默认 PNG。

    Returns:
        图像的字节表示。
    """
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


def make_file_id(seed: int) -> str:
    """生成由时间戳和随机种子组成的唯一文件名（不含扩展名）。

    Args:
        seed: 生成图像时使用的随机种子。

    Returns:
        形如 ``1718000000_123456789`` 的字符串。
    """
    ts = int(datetime.now().timestamp())
    return f"{ts}_{seed}"
