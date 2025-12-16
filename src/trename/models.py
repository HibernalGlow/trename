"""trename 数据模型

使用 Pydantic 实现 JSON 验证和序列化。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Union

from pydantic import BaseModel, Field


class FileNode(BaseModel):
    """文件节点"""

    src: str  # 源文件名
    tgt: str = ""  # 目标文件名（空字符串表示待翻译）

    @property
    def is_pending(self) -> bool:
        """是否待翻译"""
        return self.tgt == ""

    @property
    def is_ready(self) -> bool:
        """是否可以重命名（tgt 非空且与 src 不同）"""
        return self.tgt != "" and self.src != self.tgt


class DirNode(BaseModel):
    """目录节点"""

    src_dir: str  # 源目录名
    tgt_dir: str = ""  # 目标目录名
    children: list[Annotated[Union[FileNode, "DirNode"], Field(discriminator=None)]] = (
        []
    )

    @property
    def is_pending(self) -> bool:
        """是否待翻译"""
        return self.tgt_dir == ""

    @property
    def is_ready(self) -> bool:
        """是否可以重命名"""
        return self.tgt_dir != "" and self.src_dir != self.tgt_dir


# 允许递归引用
DirNode.model_rebuild()

# 节点类型联合
RenameNode = FileNode | DirNode


class RenameJSON(BaseModel):
    """根节点 - Rename JSON 结构"""

    root: list[RenameNode] = []


# ============ 冲突和结果模型 ============


class ConflictType(str, Enum):
    """冲突类型"""

    TARGET_EXISTS = "target_exists"  # 目标路径已存在
    DUPLICATE_TARGET = "duplicate_target"  # 多个源映射到同一目标


@dataclass
class Conflict:
    """重命名冲突"""

    type: ConflictType
    src_path: Path
    tgt_path: Path
    message: str


@dataclass
class RenameOperation:
    """单次重命名操作"""

    original_path: Path
    new_path: Path


@dataclass
class UndoRecord:
    """撤销记录"""

    id: str
    timestamp: datetime
    operations: list[RenameOperation]
    description: str = ""


@dataclass
class RenameResult:
    """批量重命名结果"""

    success_count: int
    failed_count: int
    skipped_count: int
    conflicts: list[Conflict]
    operation_id: str  # 用于撤销


@dataclass
class UndoResult:
    """撤销操作结果"""

    success_count: int
    failed_count: int
    failed_items: list[tuple[Path, Path, str]]  # (original, new, error_msg)


# ============ 工具函数 ============


def count_pending(node: RenameNode | RenameJSON) -> int:
    """计算待翻译项目数量

    Args:
        node: RenameNode 或 RenameJSON 对象

    Returns:
        待翻译项目数量
    """
    if isinstance(node, RenameJSON):
        return sum(count_pending(child) for child in node.root)

    if isinstance(node, FileNode):
        return 1 if node.is_pending else 0

    # DirNode
    count = 1 if node.is_pending else 0
    for child in node.children:
        count += count_pending(child)
    return count


def count_total(node: RenameNode | RenameJSON) -> int:
    """计算总项目数量"""
    if isinstance(node, RenameJSON):
        return sum(count_total(child) for child in node.root)

    if isinstance(node, FileNode):
        return 1

    # DirNode
    count = 1
    for child in node.children:
        count += count_total(child)
    return count


def count_ready(node: RenameNode | RenameJSON) -> int:
    """计算可重命名项目数量"""
    if isinstance(node, RenameJSON):
        return sum(count_ready(child) for child in node.root)

    if isinstance(node, FileNode):
        return 1 if node.is_ready else 0

    # DirNode
    count = 1 if node.is_ready else 0
    for child in node.children:
        count += count_ready(child)
    return count
