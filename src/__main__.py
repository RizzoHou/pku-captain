"""Entry point: launch the PyQt6 application."""

from __future__ import annotations

import argparse
import sys

from PyQt6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.styles import apply_app_style


def main() -> int:
    parser = argparse.ArgumentParser(prog="pku-captain")
    parser.add_argument(
        "--online",
        action="store_true",
        help="Use DeepSeek and real-time tools. Default is offline GUI mode.",
    )
    parser.add_argument(
        "--rag",
        action="store_true",
        help="Enable RAG knowledge_search (online only; needs secrets/embedding_key.txt).",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    apply_app_style(app)
    window = MainWindow(offline=not args.online, enable_knowledge=args.rag)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
