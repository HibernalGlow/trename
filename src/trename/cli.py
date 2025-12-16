"""trename CLI

使用 typer 实现命令行界面。
"""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from trename.clipboard import ClipboardHandler
from trename.models import RenameJSON, count_pending, count_ready, count_total
from trename.renamer import FileRenamer
from trename.scanner import FileScanner
from trename.undo import UndoManager

app = typer.Typer(
    name="trename",
    help="文件批量重命名工具 - 支持扫描、重命名和撤销",
    no_args_is_help=True,
)
console = Console()


@app.command()
def scan(
    directories: Annotated[
        list[Path],
        typer.Argument(help="要扫描的目录路径（支持多个）"),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option("-o", "--output", help="输出到文件而非剪贴板"),
    ] = None,
    include_root: Annotated[
        bool,
        typer.Option("--include-root", help="将目录本身作为根节点"),
    ] = True,
    include_hidden: Annotated[
        bool,
        typer.Option("--hidden", help="包含隐藏文件"),
    ] = False,
    exclude: Annotated[
        Optional[str],
        typer.Option("-e", "--exclude", help="排除的扩展名，逗号分隔（如 .json,.txt）"),
    ] = ".json,.txt,.html,.htm,.md,.log",
    split: Annotated[
        int,
        typer.Option("-s", "--split", help="分段行数（0=不分段，默认1000）"),
    ] = 1000,
    compact: Annotated[
        bool,
        typer.Option("-c", "--compact", help="紧凑格式（文件单行）"),
    ] = False,
) -> None:
    """扫描目录生成 JSON 结构（支持多文件夹合并）"""
    from trename.scanner import split_json

    try:
        # 解析排除扩展名
        exclude_exts: set[str] = set()
        if exclude:
            exclude_exts = {
                ext.strip() if ext.strip().startswith(".") else f".{ext.strip()}"
                for ext in exclude.split(",")
                if ext.strip()
            }

        scanner = FileScanner(
            ignore_hidden=not include_hidden,
            exclude_exts=exclude_exts,
        )

        # 扫描所有目录并合并
        rename_json = RenameJSON(root=[])
        for directory in directories:
            if include_root:
                result = scanner.scan_as_single_dir(directory)
            else:
                result = scanner.scan(directory)
            rename_json.root.extend(result.root)
            console.print(f"  扫描: {directory} ({count_total(result)} 项)")

        # 分段处理
        if split > 0:
            segments = split_json(rename_json, max_lines=split)
            console.print(f"[cyan]分段数: {len(segments)}[/cyan]")

            for i, seg in enumerate(segments):
                if compact:
                    json_str = scanner.to_compact_json(seg)
                else:
                    json_str = scanner.to_json(seg)

                if output:
                    # 分段输出到多个文件
                    seg_path = output.with_stem(f"{output.stem}_{i+1}")
                    seg_path.write_text(json_str, encoding="utf-8")
                    console.print(f"[green]✓[/green] 第 {i+1} 段已保存到: {seg_path}")
                else:
                    # 分段复制到剪贴板（只复制第一段，提示用户）
                    if i == 0:
                        ClipboardHandler.copy(json_str)
                        console.print(f"[green]✓[/green] 第 1 段已复制到剪贴板")
                    console.print(f"  第 {i+1} 段: {count_total(seg)} 项")
        else:
            # 不分段
            if compact:
                json_str = scanner.to_compact_json(rename_json)
            else:
                json_str = scanner.to_json(rename_json)

            if output:
                output.write_text(json_str, encoding="utf-8")
                console.print(f"[green]✓[/green] JSON 已保存到: {output}")
            else:
                ClipboardHandler.copy(json_str)
                console.print("[green]✓[/green] JSON 已复制到剪贴板")

        # 显示统计
        total = count_total(rename_json)
        console.print(f"[green]总计: {total} 项[/green]")
        if exclude_exts:
            console.print(f"  排除扩展名: {', '.join(sorted(exclude_exts))}")

    except FileNotFoundError as e:
        console.print(f"[red]错误:[/red] {e}")
        raise typer.Exit(1)
    except NotADirectoryError as e:
        console.print(f"[red]错误:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def rename(
    input_file: Annotated[
        Optional[Path],
        typer.Option("-i", "--input", help="从文件读取 JSON 而非剪贴板"),
    ] = None,
    base_path: Annotated[
        Optional[Path],
        typer.Option("-b", "--base", help="基础路径（默认当前目录）"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="只模拟执行，不实际重命名"),
    ] = False,
) -> None:
    """根据 JSON 执行批量重命名"""
    try:
        # 读取 JSON
        if input_file:
            json_str = input_file.read_text(encoding="utf-8")
            console.print(f"从文件读取: {input_file}")
        else:
            json_str = ClipboardHandler.paste()
            console.print("从剪贴板读取")

        # 解析 JSON
        try:
            rename_json = RenameJSON.model_validate_json(json_str)
        except Exception as e:
            console.print(f"[red]JSON 解析错误:[/red] {e}")
            raise typer.Exit(1)

        # 统计
        total = count_total(rename_json)
        ready = count_ready(rename_json)
        pending = count_pending(rename_json)

        console.print(f"  总项目: {total}, 可重命名: {ready}, 待翻译: {pending}")

        if ready == 0:
            console.print("[yellow]没有可重命名的项目[/yellow]")
            return

        # 执行重命名
        base = base_path or Path.cwd()
        undo_manager = UndoManager()
        renamer = FileRenamer(undo_manager)

        if dry_run:
            console.print("[yellow]模拟执行模式[/yellow]")

        result = renamer.rename_batch(rename_json, base, dry_run=dry_run)

        # 显示结果
        console.print(f"\n[green]成功:[/green] {result.success_count}")
        console.print(f"[red]失败:[/red] {result.failed_count}")
        console.print(f"[yellow]跳过(冲突):[/yellow] {result.skipped_count}")

        if result.conflicts:
            console.print("\n[yellow]冲突详情:[/yellow]")
            for conflict in result.conflicts[:5]:  # 只显示前5个
                console.print(f"  • {conflict.message}")
            if len(result.conflicts) > 5:
                console.print(f"  ... 还有 {len(result.conflicts) - 5} 个冲突")

        if result.operation_id:
            console.print(f"\n撤销 ID: [cyan]{result.operation_id}[/cyan]")

    except Exception as e:
        console.print(f"[red]错误:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def undo(
    batch_id: Annotated[
        Optional[str],
        typer.Argument(help="要撤销的批次 ID（不指定则撤销最近一次）"),
    ] = None,
    list_history: Annotated[
        bool,
        typer.Option("-l", "--list", help="显示操作历史"),
    ] = False,
) -> None:
    """撤销重命名操作"""
    undo_manager = UndoManager()

    if list_history:
        # 显示历史
        history = undo_manager.get_history(limit=10)

        if not history:
            console.print("没有操作历史")
            return

        table = Table(title="操作历史")
        table.add_column("ID", style="cyan")
        table.add_column("时间")
        table.add_column("操作数")
        table.add_column("描述")

        for record in history:
            table.add_row(
                record.id,
                record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                str(len(record.operations)),
                record.description or "-",
            )

        console.print(table)
        return

    # 执行撤销
    if batch_id:
        result = undo_manager.undo(batch_id)
    else:
        result = undo_manager.undo_latest()

    console.print(f"[green]成功撤销:[/green] {result.success_count}")
    console.print(f"[red]失败:[/red] {result.failed_count}")

    if result.failed_items:
        console.print("\n[yellow]失败详情:[/yellow]")
        for orig, new, msg in result.failed_items[:5]:
            console.print(f"  • {msg}")


@app.command()
def ui() -> None:
    """启动 Streamlit 界面"""
    import subprocess
    import sys

    console.print("启动 Streamlit 界面...")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", 
         str(Path(__file__).parent / "app.py")],
        check=True,
    )


if __name__ == "__main__":
    app()
