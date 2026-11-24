# -*- coding: utf-8 -*-
"""python -m ulpp：不带参数（或只给 --lang）开图形界面，其余参数走命令行。

2.0 起**默认进新外壳**（``ui/shell.py``）；老界面退到 ``--v1``（``--classic`` 是别名），
``--v2`` 保留为等价别名，老脚本和快捷方式不会坏。
"""

import sys
from typing import Optional, Tuple

_OLD_UI_FLAGS = ("--v1", "--classic")
_ALL_UI_FLAGS = _OLD_UI_FLAGS + ("--v2",)


def _parse_gui_args(argv) -> Tuple[bool, Optional[str]]:
    """判断参数是否"只指定了语言"。是则返回 (True, lang)，否则 (False, None)。"""
    lang: Optional[str] = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--lang":
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                return False, None
            lang = argv[i + 1]
            i += 2
        elif arg.startswith("--lang="):
            lang = arg.split("=", 1)[1]
            i += 1
        else:
            return False, None
    return True, lang


def main() -> int:
    from .i18n import set_language

    argv = sys.argv[1:]
    want_old_ui = any(arg in _OLD_UI_FLAGS for arg in argv)
    rest = [arg for arg in argv if arg not in _ALL_UI_FLAGS]
    gui_only, lang = _parse_gui_args(rest)

    if want_old_ui:
        if not rest or gui_only:
            set_language(lang)
            from .gui import main as gui_main

            gui_main()
            return 0
        from .cli import main as cli_main

        return cli_main(rest)

    if not rest or gui_only:
        set_language(lang)
        from .ui.shell import main as shell_main

        return shell_main(lang)

    from .cli import main as cli_main

    return cli_main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
