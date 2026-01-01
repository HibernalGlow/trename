"""trename CLI 入口点"""

import sys
import io

from trename.cli import app


def setup_utf8_output():
    """强制设置 stdout/stderr 为 UTF-8 编码
    
    兼容老版 Windows PowerShell，避免中文输出乱码
    """
    if sys.platform == 'win32':
        # 强制使用 UTF-8 编码，errors='replace' 避免编码错误崩溃
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, 
                encoding='utf-8', 
                errors='replace',
                line_buffering=True
            )
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, 
                encoding='utf-8', 
                errors='replace',
                line_buffering=True
            )


def main():
    """CLI 主入口"""
    setup_utf8_output()
    app()


if __name__ == "__main__":
    main()
