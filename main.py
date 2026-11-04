import os
import sys


def configure_output_streams():
    """Provide valid output streams in PyInstaller windowed builds.

    PyInstaller's --windowed mode can set sys.stdout and sys.stderr to None.
    AoE2ScenarioParser writes progress information to these streams, so both
    streams must reference a writable object before the parser is imported.
    """

    if sys.stdout is None:
        sys.stdout = open(
            os.devnull,
            "w",
            encoding="utf-8",
        )

    if sys.stderr is None:
        sys.stderr = open(
            os.devnull,
            "w",
            encoding="utf-8",
        )


# This must run before importing MainWindow because MainWindow imports
# AoE2ScenarioParser through the scenario service and UI modules.
configure_output_streams()

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
