"""文件扫描器

使用 pathlib 递归扫描目录，生成 RenameJSON 结构。
"""

import json
import logging
from pathlib import Path

from trename.models import DirNode, FileNode, RenameJSON, RenameNode

logger = logging.getLogger(__name__)

# 默认排除的扩展名
DEFAULT_EXCLUDE_EXTS = {".json", ".txt", ".html", ".htm", ".md", ".log"}


class FileScanner:
    """文件扫描器 - 扫描目录生成 RenameJSON"""

    def __init__(
        self,
        ignore_hidden: bool = True,
        exclude_exts: set[str] | None = None,
    ):
        """初始化扫描器

        Args:
            ignore_hidden: 是否忽略隐藏文件/目录（以 . 开头）
            exclude_exts: 要排除的文件扩展名集合（如 {".json", ".txt"}）
        """
        self.ignore_hidden = ignore_hidden
        self.exclude_exts = exclude_exts if exclude_exts is not None else set()

    def scan(self, root_path: Path) -> RenameJSON:
        """扫描目录，返回 RenameJSON 结构

        Args:
            root_path: 要扫描的根目录路径

        Returns:
            RenameJSON 结构

        Raises:
            FileNotFoundError: 目录不存在
            NotADirectoryError: 路径不是目录
        """
        root_path = Path(root_path).resolve()

        if not root_path.exists():
            raise FileNotFoundError(f"目录不存在: {root_path}")

        if not root_path.is_dir():
            raise NotADirectoryError(f"路径不是目录: {root_path}")

        # 扫描根目录下的所有项目
        nodes = self._scan_children(root_path)
        return RenameJSON(root=nodes)

    def scan_as_single_dir(self, root_path: Path) -> RenameJSON:
        """将目录本身作为根节点扫描

        Args:
            root_path: 要扫描的目录路径

        Returns:
            RenameJSON 结构，root 包含单个 DirNode
        """
        root_path = Path(root_path).resolve()

        if not root_path.exists():
            raise FileNotFoundError(f"目录不存在: {root_path}")

        if not root_path.is_dir():
            raise NotADirectoryError(f"路径不是目录: {root_path}")

        dir_node = self._scan_dir(root_path)
        return RenameJSON(root=[dir_node])

    def _scan_children(self, dir_path: Path) -> list[RenameNode]:
        """扫描目录下的所有子项

        Args:
            dir_path: 目录路径

        Returns:
            子节点列表
        """
        nodes: list[RenameNode] = []

        try:
            items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            logger.warning(f"权限不足，跳过目录: {dir_path}")
            return nodes

        for item in items:
            # 跳过隐藏文件
            if self.ignore_hidden and item.name.startswith("."):
                continue

            try:
                if item.is_dir():
                    nodes.append(self._scan_dir(item))
                else:
                    # 检查扩展名排除
                    if item.suffix.lower() in self.exclude_exts:
                        continue
                    nodes.append(FileNode(src=item.name))
            except PermissionError:
                logger.warning(f"权限不足，跳过: {item}")
            except OSError as e:
                logger.warning(f"无法访问 {item}: {e}")

        return nodes

    def _scan_dir(self, dir_path: Path) -> DirNode:
        """扫描单个目录

        Args:
            dir_path: 目录路径

        Returns:
            DirNode 对象
        """
        children = self._scan_children(dir_path)
        return DirNode(src_dir=dir_path.name, children=children)

    def to_json(self, rename_json: RenameJSON, indent: int = 2) -> str:
        """将 RenameJSON 序列化为 JSON 字符串

        Args:
            rename_json: RenameJSON 对象
            indent: 缩进空格数

        Returns:
            JSON 字符串
        """
        return rename_json.model_dump_json(indent=indent, exclude_none=True)

    def to_compact_json(self, rename_json: RenameJSON) -> str:
        """将 RenameJSON 序列化为紧凑 JSON（文件节点单行）

        Args:
            rename_json: RenameJSON 对象

        Returns:
            紧凑格式的 JSON 字符串
        """
        return _compact_json(rename_json.model_dump())

    @staticmethod
    def from_json(json_str: str) -> RenameJSON:
        """从 JSON 字符串解析 RenameJSON

        Args:
            json_str: JSON 字符串

        Returns:
            RenameJSON 对象

        Raises:
            pydantic.ValidationError: JSON 格式或结构无效
        """
        return RenameJSON.model_validate_json(json_str)


def _compact_json(data: dict, indent: int = 0) -> str:
    """生成紧凑格式 JSON（文件节点单行，目录节点多行）"""
    lines = []
    ind = "  " * indent

    if "root" in data:
        lines.append('{')
        lines.append(f'{ind}  "root": [')
        for i, node in enumerate(data["root"]):
            node_str = _format_node(node, indent + 2)
            comma = "," if i < len(data["root"]) - 1 else ""
            lines.append(f"{node_str}{comma}")
        lines.append(f'{ind}  ]')
        lines.append('}')
    return "\n".join(lines)


def _format_node(node: dict, indent: int) -> str:
    """格式化单个节点"""
    ind = "  " * indent

    # 文件节点 - 单行
    if "src" in node:
        return f'{ind}{{"src": "{node["src"]}", "tgt": "{node.get("tgt", "")}"}}'

    # 目录节点 - 多行
    if "src_dir" in node:
        lines = [f'{ind}{{"src_dir": "{node["src_dir"]}", "tgt_dir": "{node.get("tgt_dir", "")}", "children": [']
        children = node.get("children", [])
        for i, child in enumerate(children):
            child_str = _format_node(child, indent + 1)
            comma = "," if i < len(children) - 1 else ""
            lines.append(f"{child_str}{comma}")
        lines.append(f"{ind}  ]")
        lines.append(f"{ind}}}")
        return "\n".join(lines)

    return json.dumps(node)


def count_lines(node: RenameNode) -> int:
    """计算节点序列化后的行数"""
    if isinstance(node, FileNode):
        return 1
    # DirNode: 开头 + children + 结尾
    return 3 + sum(count_lines(child) for child in node.children)


def split_json(
    rename_json: RenameJSON,
    max_lines: int = 100,
) -> list[RenameJSON]:
    """智能分段 JSON（保持文件夹完整）

    Args:
        rename_json: 原始 RenameJSON
        max_lines: 每段最大行数

    Returns:
        分段后的 RenameJSON 列表
    """
    segments: list[RenameJSON] = []
    current_nodes: list[RenameNode] = []
    current_lines = 2  # root 开头和结尾

    for node in rename_json.root:
        node_lines = count_lines(node)

        # 如果当前段加上这个节点超过限制，且当前段不为空
        if current_lines + node_lines > max_lines and current_nodes:
            segments.append(RenameJSON(root=current_nodes))
            current_nodes = []
            current_lines = 2

        current_nodes.append(node)
        current_lines += node_lines

    # 添加最后一段
    if current_nodes:
        segments.append(RenameJSON(root=current_nodes))

    return segments
