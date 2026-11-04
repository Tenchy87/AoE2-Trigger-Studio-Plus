from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import platform
import sys
import traceback


APP_NAME = "AoE2 Trigger Studio+"
APP_VERSION = "0.5.0"


class LoggerService:
    """Centralised application logging for Trigger Studio+."""

    LOG_FOLDER = (
        Path.home()
        / "Documents"
        / APP_NAME
        / "logs"
    )

    LOG_FILE = LOG_FOLDER / "error.log"

    @classmethod
    def ensure_log_folder(cls):
        """Create the user-writable log folder and return its path."""
        cls.LOG_FOLDER.mkdir(
            parents=True,
            exist_ok=True,
        )
        return cls.LOG_FOLDER

    @staticmethod
    def get_parser_version():
        """Return the installed or bundled parser version safely."""
        for package_name in (
            "AoE2ScenarioParser",
            "aoe2scenarioparser",
        ):
            try:
                return version(package_name)
            except PackageNotFoundError:
                continue
            except Exception:
                break

        return "Unknown"

    @classmethod
    def _write_text(cls, text):
        """Append text without allowing a logging failure to crash the app."""
        try:
            cls.ensure_log_folder()

            with cls.LOG_FILE.open(
                "a",
                encoding="utf-8",
            ) as log_file:
                log_file.write(text)

            return True
        except Exception:
            return False

    @classmethod
    def log_message(cls, message, context=None):
        timestamp = datetime.now().astimezone().isoformat(
            sep=" ",
            timespec="seconds",
        )

        prefix = f"[{timestamp}]"

        if context:
            prefix += f" [{context}]"

        cls._write_text(f"{prefix} {message}\n")

    @classmethod
    def log_exception(
        cls,
        error,
        scenario_path=None,
        context=None,
    ):
        """Write an exception, environment details, and full traceback."""
        timestamp = datetime.now().astimezone().isoformat(
            sep=" ",
            timespec="seconds",
        )

        frozen = bool(getattr(sys, "frozen", False))
        traceback_text = traceback.format_exc()

        if traceback_text.strip() == "NoneType: None":
            traceback_text = "No active traceback was available."

        lines = [
            "\n" + "=" * 80,
            f"{APP_NAME} ERROR",
            "=" * 80,
            f"Date: {timestamp}",
            f"Application Version: {APP_VERSION}",
            (
                "AoE2ScenarioParser Version: "
                f"{cls.get_parser_version()}"
            ),
            f"Python Version: {platform.python_version()}",
            f"Operating System: {platform.platform()}",
            f"Packaged Application: {frozen}",
        ]

        if context:
            lines.append(f"Context: {context}")

        if scenario_path:
            lines.append(f"Scenario: {scenario_path}")

        lines.extend(
            [
                f"Exception Type: {type(error).__name__}",
                f"Exception Message: {error}",
                "",
                "Traceback:",
                traceback_text.rstrip(),
                "=" * 80,
                "",
            ]
        )

        cls._write_text("\n".join(lines) + "\n")

    @classmethod
    def get_log_folder(cls):
        return cls.ensure_log_folder()

    @classmethod
    def get_log_file(cls):
        cls.ensure_log_folder()
        return cls.LOG_FILE
