"""撤销管理器

使用 SQLite 持久化存储撤销历史。
"""

import logging
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from trename.models import RenameOperation, UndoRecord, UndoResult

logger = logging.getLogger(__name__)

# 默认数据库路径
DEFAULT_DB_PATH = Path.home() / ".trename" / "undo.db"


class UndoManager:
    """撤销管理器 - 使用 SQLite 存储撤销记录"""

    def __init__(self, db_path: Path | None = None):
        """初始化撤销管理器

        Args:
            db_path: 数据库文件路径，默认为 ~/.trename/undo.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self._init_tables()

    def _init_tables(self) -> None:
        """创建数据库表"""
        cursor = self.conn.cursor()

        # 批次表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS undo_batches (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                description TEXT,
                undone INTEGER DEFAULT 0
            )
        """)

        # 操作表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS undo_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                original_path TEXT NOT NULL,
                new_path TEXT NOT NULL,
                seq_order INTEGER NOT NULL,
                FOREIGN KEY (batch_id) REFERENCES undo_batches(id)
            )
        """)

        # 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_operations_batch 
            ON undo_operations(batch_id)
        """)

        self.conn.commit()

    def record(
        self, operations: list[RenameOperation], description: str = ""
    ) -> str:
        """记录一批重命名操作

        Args:
            operations: 重命名操作列表
            description: 操作描述

        Returns:
            批次 ID
        """
        if not operations:
            return ""

        batch_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()

        cursor = self.conn.cursor()

        # 插入批次记录
        cursor.execute(
            "INSERT INTO undo_batches (id, timestamp, description) VALUES (?, ?, ?)",
            (batch_id, timestamp, description),
        )

        # 插入操作记录（按顺序）
        for seq, op in enumerate(operations):
            cursor.execute(
                """INSERT INTO undo_operations 
                   (batch_id, original_path, new_path, seq_order) 
                   VALUES (?, ?, ?, ?)""",
                (batch_id, str(op.original_path), str(op.new_path), seq),
            )

        self.conn.commit()
        logger.info(f"记录撤销批次 {batch_id}: {len(operations)} 个操作")
        return batch_id

    def undo(self, batch_id: str) -> UndoResult:
        """撤销指定批次的操作

        按逆序处理，确保目录重命名正确。

        Args:
            batch_id: 批次 ID

        Returns:
            撤销结果
        """
        cursor = self.conn.cursor()

        # 检查批次是否存在且未撤销
        cursor.execute(
            "SELECT undone FROM undo_batches WHERE id = ?", (batch_id,)
        )
        row = cursor.fetchone()

        if not row:
            return UndoResult(
                success_count=0,
                failed_count=0,
                failed_items=[(Path(), Path(), f"批次不存在: {batch_id}")],
            )

        if row[0]:
            return UndoResult(
                success_count=0,
                failed_count=0,
                failed_items=[(Path(), Path(), f"批次已撤销: {batch_id}")],
            )

        # 获取操作记录（逆序）
        cursor.execute(
            """SELECT original_path, new_path FROM undo_operations 
               WHERE batch_id = ? ORDER BY seq_order DESC""",
            (batch_id,),
        )
        operations = cursor.fetchall()

        success_count = 0
        failed_count = 0
        failed_items: list[tuple[Path, Path, str]] = []

        # 执行撤销（从新路径移回原路径）
        for original_path_str, new_path_str in operations:
            original_path = Path(original_path_str)
            new_path = Path(new_path_str)

            try:
                if new_path.exists():
                    shutil.move(str(new_path), str(original_path))
                    success_count += 1
                    logger.info(f"撤销: {new_path.name} -> {original_path.name}")
                else:
                    # 文件可能已被移动或删除
                    failed_count += 1
                    failed_items.append(
                        (original_path, new_path, f"文件不存在: {new_path}")
                    )
            except Exception as e:
                failed_count += 1
                failed_items.append((original_path, new_path, str(e)))
                logger.error(f"撤销失败 {new_path} -> {original_path}: {e}")

        # 标记批次为已撤销
        cursor.execute(
            "UPDATE undo_batches SET undone = 1 WHERE id = ?", (batch_id,)
        )
        self.conn.commit()

        return UndoResult(
            success_count=success_count,
            failed_count=failed_count,
            failed_items=failed_items,
        )

    def undo_latest(self) -> UndoResult:
        """撤销最近一次操作

        Returns:
            撤销结果
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT id FROM undo_batches 
               WHERE undone = 0 
               ORDER BY timestamp DESC LIMIT 1"""
        )
        row = cursor.fetchone()

        if not row:
            return UndoResult(
                success_count=0,
                failed_count=0,
                failed_items=[(Path(), Path(), "没有可撤销的操作")],
            )

        return self.undo(row[0])

    def get_history(self, limit: int = 10) -> list[UndoRecord]:
        """获取最近的操作历史

        Args:
            limit: 返回记录数量限制

        Returns:
            撤销记录列表
        """
        cursor = self.conn.cursor()

        # 获取批次
        cursor.execute(
            """SELECT id, timestamp, description, undone FROM undo_batches 
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )
        batches = cursor.fetchall()

        records: list[UndoRecord] = []

        for batch_id, timestamp_str, description, undone in batches:
            # 获取该批次的操作
            cursor.execute(
                """SELECT original_path, new_path FROM undo_operations 
                   WHERE batch_id = ? ORDER BY seq_order""",
                (batch_id,),
            )
            ops = [
                RenameOperation(original_path=Path(orig), new_path=Path(new))
                for orig, new in cursor.fetchall()
            ]

            records.append(
                UndoRecord(
                    id=batch_id,
                    timestamp=datetime.fromisoformat(timestamp_str),
                    operations=ops,
                    description=description or "",
                )
            )

        return records

    def clear_history(self, keep_recent: int = 0) -> int:
        """清理历史记录

        Args:
            keep_recent: 保留最近的记录数量

        Returns:
            删除的记录数量
        """
        cursor = self.conn.cursor()

        if keep_recent > 0:
            # 获取要保留的批次 ID
            cursor.execute(
                """SELECT id FROM undo_batches 
                   ORDER BY timestamp DESC LIMIT ?""",
                (keep_recent,),
            )
            keep_ids = [row[0] for row in cursor.fetchall()]

            if keep_ids:
                placeholders = ",".join("?" * len(keep_ids))
                cursor.execute(
                    f"DELETE FROM undo_operations WHERE batch_id NOT IN ({placeholders})",
                    keep_ids,
                )
                cursor.execute(
                    f"DELETE FROM undo_batches WHERE id NOT IN ({placeholders})",
                    keep_ids,
                )
        else:
            cursor.execute("DELETE FROM undo_operations")
            cursor.execute("DELETE FROM undo_batches")

        deleted = cursor.rowcount
        self.conn.commit()
        return deleted

    def close(self) -> None:
        """关闭数据库连接"""
        self.conn.close()

    def __enter__(self) -> "UndoManager":
        return self

    def __exit__(self, *args) -> None:
        self.close()
