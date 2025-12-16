"""文件重命名器

执行批量重命名操作，支持撤销。
"""

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from trename.models import (
    DirNode,
    FileNode,
    RenameJSON,
    RenameNode,
    RenameOperation,
    RenameResult,
)
from trename.validator import ConflictValidator

if TYPE_CHECKING:
    from trename.undo import UndoManager

logger = logging.getLogger(__name__)


class FileRenamer:
    """文件重命名器"""

    def __init__(self, undo_manager: "UndoManager | None" = None):
        """初始化重命名器

        Args:
            undo_manager: 撤销管理器（可选）
        """
        self.undo_manager = undo_manager
        self.validator = ConflictValidator()

    def rename_batch(
        self,
        rename_json: RenameJSON,
        base_path: Path,
        dry_run: bool = False,
    ) -> RenameResult:
        """批量重命名文件

        子项先于父目录处理，确保目录重命名时子项路径正确。

        Args:
            rename_json: RenameJSON 结构
            base_path: 基础路径
            dry_run: 是否只模拟执行

        Returns:
            重命名结果
        """
        base_path = Path(base_path).resolve()

        # 获取有效操作和冲突
        operations, conflicts = self.validator.get_valid_operations(
            rename_json, base_path
        )

        if dry_run:
            return RenameResult(
                success_count=len(operations),
                failed_count=0,
                skipped_count=len(conflicts),
                conflicts=conflicts,
                operation_id="",
            )

        # 执行重命名
        success_count = 0
        failed_count = 0
        executed_operations: list[RenameOperation] = []

        for src_path, tgt_path in operations:
            try:
                if self._rename_single(src_path, tgt_path):
                    success_count += 1
                    executed_operations.append(
                        RenameOperation(original_path=src_path, new_path=tgt_path)
                    )
                else:
                    failed_count += 1
            except Exception as e:
                logger.error(f"重命名失败 {src_path} -> {tgt_path}: {e}")
                failed_count += 1

        # 记录撤销
        operation_id = ""
        if self.undo_manager and executed_operations:
            operation_id = self.undo_manager.record(
                executed_operations,
                description=f"批量重命名 {len(executed_operations)} 个项目",
            )

        return RenameResult(
            success_count=success_count,
            failed_count=failed_count,
            skipped_count=len(conflicts),
            conflicts=conflicts,
            operation_id=operation_id,
        )

    def _rename_single(self, src: Path, tgt: Path) -> bool:
        """重命名单个文件/目录

        Args:
            src: 源路径
            tgt: 目标路径

        Returns:
            是否成功
        """
        if not src.exists():
            logger.warning(f"源文件不存在: {src}")
            return False

        if tgt.exists():
            logger.warning(f"目标已存在: {tgt}")
            return False

        try:
            shutil.move(str(src), str(tgt))
            logger.info(f"重命名: {src.name} -> {tgt.name}")
            return True
        except Exception as e:
            logger.error(f"重命名失败: {e}")
            return False

    def collect_operations(
        self, rename_json: RenameJSON, base_path: Path
    ) -> list[tuple[Path, Path]]:
        """收集所有重命名操作（子项优先）

        Args:
            rename_json: RenameJSON 结构
            base_path: 基础路径

        Returns:
            (源路径, 目标路径) 列表，子项在前
        """
        operations: list[tuple[Path, Path]] = []
        base_path = Path(base_path).resolve()

        def collect(node: RenameNode, parent_path: Path) -> None:
            if isinstance(node, FileNode):
                if node.is_ready:
                    operations.append((parent_path / node.src, parent_path / node.tgt))

            elif isinstance(node, DirNode):
                src_path = parent_path / node.src_dir
                # 先递归处理子节点
                for child in node.children:
                    collect(child, src_path)
                # 再处理目录本身
                if node.is_ready:
                    operations.append((src_path, parent_path / node.tgt_dir))

        for node in rename_json.root:
            collect(node, base_path)

        return operations
