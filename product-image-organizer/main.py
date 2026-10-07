"""Desktop entry point. No network, account, analytics, or cloud dependencies."""
import sys
from pathlib import Path

from PySide6.QtGui import QIcon

from organizer.ui import MainWindow, create_application, info


def main():
    app = create_application()
    if len(sys.argv) == 3 and sys.argv[1] == "--verify-package":
        from organizer.package_check import verify_package
        return verify_package(Path(sys.argv[2]))
    assets = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"
    app.setWindowIcon(QIcon(str(assets / "app.ico")))
    window = MainWindow()

    def handle_exception(exc_type, value, traceback):
        from organizer.core import friendly_error
        info(window, "操作未完成", friendly_error(value))

    sys.excepthook = handle_exception
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
