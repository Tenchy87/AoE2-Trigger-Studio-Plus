import gc
import os
from pathlib import Path
import tempfile

from AoE2ScenarioParser.exceptions.asp_exceptions import (
    UnsupportedAttributeError,
)
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import (
    AoE2DEScenario,
)

from services.logger_service import LoggerService


class ScenarioService:
    def __init__(self):
        self.scenario = None
        self.current_file = None
        self.modified = False

    def load_scenario(self, file_path):
        resolved_path = Path(file_path).resolve()

        LoggerService.log_message(
            f"Loading scenario: {resolved_path}",
            context="load_scenario",
        )

        # Release the scenario currently held by Trigger Studio+ before
        # asking AoE2ScenarioParser to load a different scenario version.
        self.scenario = None
        self.current_file = None
        self.modified = False

        gc.collect()

        LoggerService.log_message(
            (
                "Released previous scenario and forced "
                "garbage collection."
            ),
            context="load_scenario",
        )

        try:
            # Load into a local variable so a failed parser load does not
            # assign a partially constructed scenario to the service.
            new_scenario = AoE2DEScenario.from_file(
                str(resolved_path)
            )

        except UnsupportedAttributeError as error:
            error_message = str(error)

            if "execute_on_load" in error_message:
                LoggerService.log_message(
                    (
                        "Detected the AoE2ScenarioParser 0.9.4 "
                        "cross-version execute_on_load issue while "
                        f"loading: {resolved_path}"
                    ),
                    context="load_scenario",
                )

                raise RuntimeError(
                    "This scenario triggered a known "
                    "AoE2ScenarioParser 0.9.4 cross-version "
                    "compatibility issue.\n\n"
                    "This can happen after opening scenarios with "
                    "different scenario versions in the same "
                    "Trigger Studio+ session.\n\n"
                    "Workaround:\n"
                    "Close Trigger Studio+, reopen it, and open this "
                    "scenario first."
                ) from error

            raise

        self.scenario = new_scenario
        self.current_file = str(resolved_path)
        self.modified = False

        LoggerService.log_message(
            f"Load succeeded: {resolved_path}",
            context="load_scenario",
        )

        return self.scenario

    def save_scenario(self):
        """Safely save changes back to the current scenario file.

        AoE2ScenarioParser intentionally rejects direct writes over the
        scenario file used as its source. The updated scenario is therefore
        written to a temporary file in the same folder. The original file is
        replaced only after the temporary output exists and is non-empty.
        """
        if self.scenario is None:
            return False

        if not self.current_file:
            return False

        target_path = Path(self.current_file).resolve()
        target_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = None

        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target_path.stem}_",
                suffix=".aoe2scenario",
                dir=str(target_path.parent),
            )
            os.close(file_descriptor)

            temporary_path = Path(temporary_name)

            # The parser expects to create the output file itself.
            temporary_path.unlink(missing_ok=True)

            self.scenario.write_to_file(
                str(temporary_path)
            )

            if not temporary_path.exists():
                raise RuntimeError(
                    "The temporary scenario file was not created."
                )

            if temporary_path.stat().st_size == 0:
                raise RuntimeError(
                    "The temporary scenario file is empty."
                )

            # The temporary file is beside the target, allowing an atomic
            # replacement on the same filesystem.
            os.replace(
                temporary_path,
                target_path,
            )

            # Reload the saved file so its parser source reference matches
            # the file used by future Ctrl+S operations.
            self.scenario = AoE2DEScenario.from_file(
                str(target_path)
            )
            self.current_file = str(target_path)
            self.modified = False

            return True

        finally:
            if (
                temporary_path is not None
                and temporary_path.exists()
            ):
                temporary_path.unlink(missing_ok=True)

    def save_scenario_as(self, file_path):
        """Save to a new path, or safely overwrite the current source path."""
        if self.scenario is None:
            return False

        target_path = Path(file_path).resolve()

        if target_path.suffix.lower() != ".aoe2scenario":
            target_path = target_path.with_suffix(
                ".aoe2scenario"
            )

        current_path = None

        if self.current_file:
            current_path = Path(self.current_file).resolve()

        if (
            current_path is not None
            and target_path == current_path
        ):
            return self.save_scenario()

        target_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.scenario.write_to_file(
            str(target_path)
        )

        # Reload the new output so subsequent Ctrl+S operations use the
        # safe current-file workflow.
        self.scenario = AoE2DEScenario.from_file(
            str(target_path)
        )
        self.current_file = str(target_path)
        self.modified = False

        return True

    def mark_modified(self):
        self.modified = True

    def is_modified(self):
        return self.modified

    def get_trigger_count(self):
        if self.scenario is None:
            return 0

        return len(
            self.scenario.trigger_manager.triggers
        )

    def get_trigger_names(self):
        if self.scenario is None:
            return []

        return [
            trigger.name
            for trigger in self.scenario.trigger_manager.triggers
        ]

    def get_unit_count(self):
        if self.scenario is None:
            return 0

        return len(
            self.scenario.unit_manager.get_all_units()
        )
