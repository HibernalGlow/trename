"""冲突检测器

检测重命名操作中的冲突：目标已存在、重复目标等。
"""

from collections import defaultdict
from pathlib import Path

from trename.models import (
    Conflict,
    ConflictType,
    DirNode,
    FileNode,
    RenameJSON,
    RenameNode,
)


class ConflictValidator:
    """冲突检测器"""

    def validate(self, rename_json: RenameJSON, base_path: Path) -> list[Conflict]:
        """检测所有冲突

        Args:
            rename_json: RenameJSON 结构
            base_path: 基础路径（文件系统中的实际路径）

        Returns:
            冲突列表
        """
        conflicts: list[Conflict] = []
        base_path = Path(base_path).resolve()

        # 收集所有目标路径用于检测重复
        target_paths: dict[Path, list[Path]] = defaultdict(list)

        # 递归检测
        for node in rename_json.root:
            self._validate_node(node, base_path, conflicts, target_paths)

        # 检测重复目标
        conflicts.extend(self._check_duplicate_targets(target_paths))

        return conflicts

    def _validate_node(
        self,
        node: RenameNode,
        parent_path: Path,
        conflicts: list[Conflict],
        target_paths: dict[Path, list[Path]],
    ) -> None:
        """递归验证节点

        Args:
            node: 当前节点
            parent_path: 父目录路径
            conflicts: 冲突列表（会被修改）
            target_paths: 目标路径映射（会被修改）
        """
        if isinstance(node, FileNode):
            src_path = parent_path / node.src
            if node.is_ready:
                tgt_path = parent_path / node.tgt
                # 检查目标是否已存在
                if self._check_target_exists(src_path, tgt_path):
                    conflicts.append(
                        Conflict(
                            type=ConflictType.TARGET_EXISTS,
                            src_path=src_path,
                            tgt_path=tgt_path,
                            message=f"目标文件已存在: {tgt_path}",
                        )
                    )
                # 记录目标路径
                target_paths[tgt_path].append(src_path)

        elif isinstance(node, DirNode):
            src_path = parent_path / node.src_dir
            current_path = src_path  # 用于子节点的路径计算

            if node.is_ready:
                tgt_path = parent_path / node.tgt_dir
                # 检查目标是否已存在
                if self._check_target_exists(src_path, tgt_path):
                    conflicts.append(
                        Conflict(
                            type=ConflictType.TARGET_EXISTS,
                            src_path=src_path,
                            tgt_path=tgt_path,
                            message=f"目标目录已存在: {tgt_path}",
                        )
                    )
                # 记录目标路径
                target_paths[tgt_path].append(src_path)

            # 递归处理子节点
            for child in node.children:
                self._validate_node(child, current_path, conflicts, target_paths)

    def _check_target_exists(self, src_path: Path, tgt_path: Path) -> bool:
        """检查目标路径是否已存在（且不是源路径本身）

        Args:
            src_path: 源路径
            tgt_path: 目标路径

        Returns:
            目标是否已存在
        """
        if src_path == tgt_path:
            return False
        return tgt_path.exists()

    def _check_duplicate_targets(
        self, target_paths: dict[Path, list[Path]]
    ) -> list[Conflict]:
        """检查重复目标

        Args:
            target_paths: 目标路径到源路径列表的映射

        Returns:
            重复目标冲突列表
        """
        conflicts: list[Conflict] = []

        for tgt_path, src_paths in target_paths.items():
            if len(src_paths) > 1:
                for src_path in src_paths:
                    conflicts.append(
                        Conflict(
                            type=ConflictType.DUPLICATE_TARGET,
                            src_path=src_path,
                            tgt_path=tgt_path,
                            message=f"多个源映射到同一目标: {tgt_path}",
                        )
                    )

        return conflicts

    def get_valid_operations(
        self, rename_json: RenameJSON, base_path: Path, smart_dedup: bool = True
    ) -> tuple[list[tuple[Path, Path]], list[Conflict]]:
        """获取有效的重命名操作和冲突

        Args:
            rename_json: RenameJSON 结构
            base_path: 基础路径
            smart_dedup: 智能去重，重复目标只保留第一个

        Returns:
            (有效操作列表, 冲突列表)
        """
        conflicts = self.validate(rename_json, base_path)
        
        # 智能去重：对于重复目标，只保留第一个，其他标记为跳过
        if smart_dedup:
            # 找出重复目标冲突
            dup_conflicts = [c for c in conflicts if c.type == ConflictType.DUPLICATE_TARGET]
            # 按目标路径分组
            dup_by_target: dict[Path, list[Conflict]] = defaultdict(list)
            for c in dup_conflicts:
                dup_by_target[c.tgt_path].append(c)
            
            # 对于每个重复目标，保留第一个源，其他移除
            skip_paths: set[tuple[Path, Path]] = set()
            kept_targets: set[Path] = set()
            
            for tgt_path, dup_list in dup_by_target.items():
                # 按源路径排序，保留第一个
                sorted_dups = sorted(dup_list, key=lambda c: str(c.src_path))
                # 第一个保留，其他跳过
                for i, c in enumerate(sorted_dups):
                    if i == 0:
                        kept_targets.add(tgt_path)
                    else:
                        skip_paths.add((c.src_path, c.tgt_path))
            
            # 从冲突列表中移除已处理的重复目标（保留的那个）
            conflicts = [
                c for c in conflicts 
                if not (c.type == ConflictType.DUPLICATE_TARGET and c.tgt_path in kept_targets and (c.src_path, c.tgt_path) not in skip_paths)
            ]
            # 更新跳过的冲突消息
            for i, c in enumerate(conflicts):
                if (c.src_path, c.tgt_path) in skip_paths:
                    conflicts[i] = Conflict(
                        type=c.type,
                        src_path=c.src_path,
                        tgt_path=c.tgt_path,
                        message=f"跳过重复: {c.src_path.name} (另一个同名源已处理)",
                    )
        
        conflict_paths = {(c.src_path, c.tgt_path) for c in conflicts}

        operations: list[tuple[Path, Path]] = []
        seen_targets: set[Path] = set()  # 已添加的目标路径
        base_path = Path(base_path).resolve()

        def collect_operations(node: RenameNode, parent_path: Path) -> None:
            if isinstance(node, FileNode):
                if node.is_ready:
                    src = parent_path / node.src
                    tgt = parent_path / node.tgt
                    # 跳过冲突和已处理的目标
                    if (src, tgt) not in conflict_paths and tgt not in seen_targets:
                        operations.append((src, tgt))
                        seen_targets.add(tgt)

            elif isinstance(node, DirNode):
                src_path = parent_path / node.src_dir
                # 先处理子节点
                for child in node.children:
                    collect_operations(child, src_path)
                # 再处理目录本身
                if node.is_ready:
                    tgt = parent_path / node.tgt_dir
                    if (src_path, tgt) not in conflict_paths and tgt not in seen_targets:
                        operations.append((src_path, tgt))
                        seen_targets.add(tgt)

        for node in rename_json.root:
            collect_operations(node, base_path)

        return operations, conflicts
