"""剪贴板处理器

使用 pyperclip 实现跨平台剪贴板操作。
"""

import pyperclip


class ClipboardHandler:
    """剪贴板处理器"""

    @staticmethod
    def copy(text: str) -> None:
        """复制文本到剪贴板

        Args:
            text: 要复制的文本
        """
        pyperclip.copy(text)

    @staticmethod
    def paste() -> str:
        """从剪贴板读取文本

        Returns:
            剪贴板内容
        """
        return pyperclip.paste()

    @staticmethod
    def is_available() -> bool:
        """检查剪贴板是否可用

        Returns:
            剪贴板是否可用
        """
        try:
            pyperclip.paste()
            return True
        except pyperclip.PyperclipException:
            return False
