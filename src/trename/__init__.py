"""trename - 文件批量重命名工具

支持扫描文件树生成 JSON、与 AI 翻译服务协作、批量重命名和撤销操作。
"""

__version__ = "0.1.0"

# 导出验证相关函数
from trename.validator import (
    sanitize_filename,
    validate_extension_position,
    validate_target_name,
    preprocess_rename_json,
    ILLEGAL_CHARS,
    CHAR_REPLACEMENT_MAP,
)

__all__ = [
    "sanitize_filename",
    "validate_extension_position", 
    "validate_target_name",
    "preprocess_rename_json",
    "ILLEGAL_CHARS",
    "CHAR_REPLACEMENT_MAP",
]
