"""冲突检测器

检测重命名操作中的冲突：目标已存在、重复目标、非法字符等。
"""

import re
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

# Windows 文件名非法字符
ILLEGAL_CHARS = r'/\:*?"<>|'
ILLEGAL_CHARS_PATTERN = re.compile(r'[/\\:*?"<>|]')

# 字符替换映射（全角替换）
CHAR_REPLACEMENT_MAP = {
    '/': '／',   # 全角斜杠
    '\\': '＼',  # 全角反斜杠
    ':': '：',   # 全角冒号
    '*': '＊',   # 全角星号
    '?': '？',   # 全角问号
    '"': '＂',   # 全角双引号
    '<': '＜',   # 全角小于号
    '>': '＞',   # 全角大于号
    '|': '｜',   # 全角竖线
}


def sanitize_filename(name: str, is_dir: bool = False) -> tuple[str, list[str]]:
    """清理文件名中的非法字符
    
    Args:
        name: 原始文件名
        is_dir: 是否为目录名
        
    Returns:
        (清理后的文件名, 警告消息列表)
    """
    warnings: list[str] = []
    
    if not name:
        return name, warnings
    
    # 检测非法字符
    found_chars = ILLEGAL_CHARS_PATTERN.findall(name)
    if not found_chars:
        return name, warnings
    
    # 分离文件名和扩展名（仅对文件处理）
    if not is_dir and '.' in name:
        # 找到最后一个点的位置
        last_dot = name.rfind('.')
        base_name = name[:last_dot]
        ext = name[last_dot:]  # 包含点
        
        # 检查扩展名中是否有非法字符
        ext_illegal = ILLEGAL_CHARS_PATTERN.findall(ext)
        if ext_illegal:
            warnings.append(
                f"[ERROR] 扩展名 '{ext}' 包含非法字符 {ext_illegal}，"
                f"请检查文件名格式。扩展名不应包含: {ILLEGAL_CHARS}"
            )
            # 扩展名中的非法字符不自动替换，返回原名
            return name, warnings
    else:
        base_name = name
        ext = ""
    
    # 替换基础名中的非法字符
    sanitized_base = base_name
    replaced_chars: list[str] = []
    
    for char in found_chars:
        if char in base_name:
            replacement = CHAR_REPLACEMENT_MAP.get(char, '_')
            sanitized_base = sanitized_base.replace(char, replacement)
            replaced_chars.append(f"'{char}' -> '{replacement}'")
    
    if replaced_chars:
        warnings.append(
            f"[AUTO-FIX] 文件名包含非法字符，已自动替换: {', '.join(replaced_chars)}"
        )
    
    return sanitized_base + ext, warnings


def validate_extension_position(name: str) -> list[str]:
    """验证扩展名位置是否正确
    
    规则：禁止在扩展名后面加后缀，必须加在扩展名前面
    例如：
      - 错误: "file.txt_backup" (后缀在扩展名后)
      - 正确: "file_backup.txt" (后缀在扩展名前)
    
    Args:
        name: 文件名
        
    Returns:
        错误消息列表
    """
    errors: list[str] = []
    
    if not name or '.' not in name:
        return errors
    
    # 常见扩展名列表
    common_exts = {
        '.txt', '.json', '.xml', '.html', '.htm', '.css', '.js', '.ts',
        '.py', '.java', '.cpp', '.c', '.h', '.hpp', '.cs', '.go', '.rs',
        '.md', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.avif', '.svg',
        '.mp3', '.mp4', '.avi', '.mkv', '.mov', '.wav', '.flac',
        '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.exe', '.dll', '.so', '.dylib', '.bin',
        '.log', '.bak', '.tmp', '.cache',
    }
    
    # 找到所有点的位置
    parts = name.split('.')
    if len(parts) < 2:
        return errors
    
    # 检查是否有扩展名后跟非扩展名内容
    # 例如: "file.txt_backup" -> parts = ['file', 'txt_backup']
    for i, part in enumerate(parts[1:], 1):
        # 检查这个部分是否像 "ext_suffix" 格式
        if '_' in part or '-' in part:
            # 分离可能的扩展名和后缀
            potential_ext = '.' + part.split('_')[0].split('-')[0]
            if potential_ext.lower() in common_exts:
                errors.append(
                    f"[ERROR] 检测到扩展名后有后缀: '{name}'\n"
                    f"  问题: 扩展名 '{potential_ext}' 后面不应添加后缀\n"
                    f"  建议: 将后缀移到扩展名前面\n"
                    f"  示例: 'file{part.replace(potential_ext[1:], '')}{potential_ext}' 而不是 'file{potential_ext}{part.replace(potential_ext[1:], '')}'"
                )
    
    return errors


def validate_target_name(tgt: str, src: str, is_dir: bool = False) -> tuple[str, list[str]]:
    """验证并清理目标文件名
    
    执行以下检查和处理：
    1. 非法字符检测和自动替换
    2. 扩展名位置验证
    3. 保持原扩展名（对于文件）
    
    Args:
        tgt: 目标文件名
        src: 源文件名（用于获取原扩展名）
        is_dir: 是否为目录
        
    Returns:
        (处理后的目标名, 消息列表)
    """
    messages: list[str] = []
    
    if not tgt:
        return tgt, messages
    
    # 1. 清理非法字符
    sanitized, char_warnings = sanitize_filename(tgt, is_dir)
    messages.extend(char_warnings)
    
    # 如果有扩展名错误，直接返回
    if any('[ERROR]' in w for w in char_warnings):
        return tgt, messages
    
    # 2. 验证扩展名位置（仅对文件）
    if not is_dir:
        ext_errors = validate_extension_position(sanitized)
        messages.extend(ext_errors)
        
        # 3. 检查扩展名是否与源文件一致
        if '.' in src and '.' in sanitized:
            src_ext = src[src.rfind('.'):].lower()
            tgt_ext = sanitized[sanitized.rfind('.'):].lower()
            if src_ext != tgt_ext:
                messages.append(
                    f"[WARNING] 扩展名变更: '{src_ext}' -> '{tgt_ext}'，请确认是否正确"
                )
    
    return sanitized, messages


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
                # 验证目标文件名
                sanitized_tgt, messages = validate_target_name(node.tgt, node.src, is_dir=False)
                
                # 处理验证消息
                for msg in messages:
                    if '[ERROR]' in msg:
                        conflicts.append(
                            Conflict(
                                type=ConflictType.ILLEGAL_CHARS if '非法字符' in msg else ConflictType.INVALID_EXTENSION,
                                src_path=src_path,
                                tgt_path=parent_path / node.tgt,
                                message=msg,
                            )
                        )
                
                tgt_path = parent_path / sanitized_tgt
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
                # 验证目标目录名
                sanitized_tgt, messages = validate_target_name(node.tgt_dir, node.src_dir, is_dir=True)
                
                # 处理验证消息
                for msg in messages:
                    if '[ERROR]' in msg:
                        conflicts.append(
                            Conflict(
                                type=ConflictType.ILLEGAL_CHARS,
                                src_path=src_path,
                                tgt_path=parent_path / node.tgt_dir,
                                message=msg,
                            )
                        )
                
                tgt_path = parent_path / sanitized_tgt
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


def preprocess_rename_json(rename_json: RenameJSON) -> tuple[RenameJSON, list[str]]:
    """预处理 RenameJSON，自动清理非法字符
    
    在验证前调用此函数，可以自动修复可修复的问题。
    
    Args:
        rename_json: 原始 RenameJSON
        
    Returns:
        (处理后的 RenameJSON, 处理消息列表)
    """
    messages: list[str] = []
    
    def process_node(node: RenameNode) -> RenameNode:
        if isinstance(node, FileNode):
            if node.tgt:
                sanitized, node_msgs = sanitize_filename(node.tgt, is_dir=False)
                messages.extend(node_msgs)
                if sanitized != node.tgt:
                    return FileNode(src=node.src, tgt=sanitized)
            return node
            
        elif isinstance(node, DirNode):
            new_tgt_dir = node.tgt_dir
            if node.tgt_dir:
                sanitized, node_msgs = sanitize_filename(node.tgt_dir, is_dir=True)
                messages.extend(node_msgs)
                if sanitized != node.tgt_dir:
                    new_tgt_dir = sanitized
            
            new_children = [process_node(child) for child in node.children]
            return DirNode(
                src_dir=node.src_dir,
                tgt_dir=new_tgt_dir,
                children=new_children
            )
        
        return node
    
    new_root = [process_node(node) for node in rename_json.root]
    return RenameJSON(root=new_root), messages
