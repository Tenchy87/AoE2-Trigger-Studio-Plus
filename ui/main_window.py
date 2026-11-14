import sys

from pathlib import Path

from PySide6.QtCore import (
    QEventLoop,
    QObject,
    QProcess,
    QThread,
    QTimer,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QKeySequence,
    QPixmap,
)

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QPlainTextEdit,
    QLineEdit,
    QInputDialog,
    QMenu,
    QMessageBox,
    QTabWidget,
    QComboBox,
    QDoubleSpinBox,
    QDockWidget,
    QGroupBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QSpinBox,
    QSplitter,
    QCheckBox,
    QStackedWidget,
)

from AoE2ScenarioParser.datasets.conditions import ConditionId
from AoE2ScenarioParser.datasets.effects import EffectId
from AoE2ScenarioParser.datasets.players import PlayerId, ColorId
from AoE2ScenarioParser.datasets.techs import TechInfo
from AoE2ScenarioParser.datasets.trigger_lists import (
    Attribute,
    DifficultyLevel,
    DiplomacyState,
)
from AoE2ScenarioParser.datasets.object_support import (
    StartingAge,
    Civilization,
)
# AOKTS_DIPLOMACY_STATE_V21
# AOKTS_DIPLOMACY_STATE_GAIA_V21_1
# AOKTS_DISPLAY_TIMER_TRIGGERED_V22
# AOKTS_DISPLAY_TIMER_GAME_UI_V22_1
# AOKTS_HERO_POWER_CAST_V23
# AOKTS_LOCAL_TECH_RESEARCHED_V24
# AOKTS_MULTIPLAYER_AI_SIGNAL_V25
# AOKTS_HERO_POWER_CAST_GAIA_V23_1_FIXED
# AOKTS_DIFFICULTY_LEVEL_V20
from AoE2ScenarioParser.datasets.units import UnitInfo

from services.logger_service import LoggerService
from services.minimap_renderer import MinimapRenderer
from services.scenario_service import ScenarioService
from services.undo_manager import UndoManager
from services.commands.rename_trigger_command import RenameTriggerCommand
from services.commands.edit_scenario_message_command import EditScenarioMessageCommand
from services.commands.reorder_trigger_command import ReorderTriggerCommand
from services.commands.edit_logic_object_command import EditLogicObjectCommand
from services.commands.add_condition_command import AddConditionCommand
from services.commands.change_condition_type_command import ChangeConditionTypeCommand
from services.commands.delete_logic_object_command import DeleteLogicObjectCommand
from services.commands.move_logic_object_command import MoveLogicObjectCommand
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario
# AOKTS_COMPARE_DEVELOPER_MODE_PATCH_V2
from PySide6.QtGui import QShortcut
from ui.scenario_compare_tab import ScenarioCompareTab


class BusyOperationWorker(QObject):
    completed = Signal(object)
    failed = Signal(object)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self):
        try:
            result = self.operation()
        except Exception as error:
            self.failed.emit(error)
            return

        self.completed.emit(result)


class BusyOverlay(QDialog):
    SPINNER_FRAMES = ("|", "/", "-", "\\")

    def __init__(self, parent, title, message):
        super().__init__(parent)

        self.setWindowFlags(
            Qt.Dialog
            | Qt.FramelessWindowHint
            | Qt.CustomizeWindowHint
        )
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(outer_layout)

        self.overlay_frame = QFrame()
        self.overlay_frame.setObjectName("busyOverlayFrame")
        self.overlay_frame.setStyleSheet(
            "QFrame#busyOverlayFrame {"
            "background-color: rgba(25, 29, 36, 238);"
            "border: 1px solid rgba(145, 155, 170, 180);"
            "border-radius: 14px;"
            "}"
            "QLabel { color: #f2f4f7; }"
        )
        outer_layout.addWidget(self.overlay_frame)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(34, 28, 34, 28)
        content_layout.setSpacing(14)
        self.overlay_frame.setLayout(content_layout)

        title_label = QLabel(title)
        title_font = title_label.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(title_label)

        self.spinner_label = QLabel(self.SPINNER_FRAMES[0])
        spinner_font = self.spinner_label.font()
        spinner_font.setPointSize(30)
        spinner_font.setBold(True)
        self.spinner_label.setFont(spinner_font)
        self.spinner_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(self.spinner_label)

        message_label = QLabel(message)
        message_label.setAlignment(Qt.AlignCenter)
        message_label.setWordWrap(True)
        content_layout.addWidget(message_label)

        self.setFixedSize(430, 230)
        self._spinner_index = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(110)
        self._spinner_timer.timeout.connect(self.advance_spinner)

    def showEvent(self, event):
        super().showEvent(event)
        self.centre_on_parent()
        self._spinner_timer.start()

    def closeEvent(self, event):
        self._spinner_timer.stop()
        super().closeEvent(event)

    def centre_on_parent(self):
        parent = self.parentWidget()
        if parent is None:
            return

        parent_centre = parent.frameGeometry().center()
        geometry = self.frameGeometry()
        geometry.moveCenter(parent_centre)
        self.move(geometry.topLeft())

    def advance_spinner(self):
        self._spinner_index = (
            self._spinner_index + 1
        ) % len(self.SPINNER_FRAMES)
        self.spinner_label.setText(
            self.SPINNER_FRAMES[self._spinner_index]
        )


class ConditionPickerDialog(QDialog):
    CONDITION_TIMER = "timer"
    CONDITION_OWN_OBJECTS = "own_objects"
    CONDITION_OWN_FEWER_OBJECTS = "own_fewer_objects"
    CONDITION_OBJECTS_IN_AREA = "objects_in_area"
    CONDITION_ACCUMULATE_ATTRIBUTE = "accumulate_attribute"
    CONDITION_AI_SIGNAL = "ai_signal"
    CONDITION_AND = "and"
    CONDITION_OR = "or"
    CONDITION_DECISION_TRIGGERED = "decision_triggered"
    CONDITION_DIFFICULTY_LEVEL = "difficulty_level"
    CONDITION_DIPLOMACY_STATE = "diplomacy_state"
    CONDITION_DISPLAY_TIMER_TRIGGERED = "display_timer_triggered"
    CONDITION_HERO_POWER_CAST = "hero_power_cast"
    CONDITION_LOCAL_TECH_RESEARCHED = "local_tech_researched"
    CONDITION_MULTIPLAYER_AI_SIGNAL = "multiplayer_ai_signal"
    CONDITION_RESEARCH_TECHNOLOGY = "research_technology"
    CONDITION_DESTROY_OBJECT = "destroy_object"
    CONDITION_BRING_OBJECT_TO_AREA = "bring_object_to_area"
    CONDITION_BRING_OBJECT_TO_OBJECT = "bring_object_to_object"
    CONDITION_BUILDING_IS_TRADING = "building_is_trading"
    CONDITION_CAPTURE_OBJECT = "capture_object"
    CONDITION_CHANCE = "chance"
    CONDITION_COMPARE_VARIABLES = "compare_variables"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Add Condition")
        self.setMinimumWidth(540)

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        type_layout = QFormLayout()
        main_layout.addLayout(type_layout)

        self.condition_type_combo = QComboBox()
        condition_entries = [
            ("Accumulate Attribute", self.CONDITION_ACCUMULATE_ATTRIBUTE),
            ("AI Signal", self.CONDITION_AI_SIGNAL),
            ("Bring Object To Area", self.CONDITION_BRING_OBJECT_TO_AREA),
            ("Bring Object To Object", self.CONDITION_BRING_OBJECT_TO_OBJECT),
            ("Building Is Trading", self.CONDITION_BUILDING_IS_TRADING),
            ("Capture Object", self.CONDITION_CAPTURE_OBJECT),
            ("Chance", self.CONDITION_CHANCE),
            ("Compare Variables", self.CONDITION_COMPARE_VARIABLES),
            ("Condition Joiner", self.CONDITION_AND),
            ("Condition Separator", self.CONDITION_OR),
            ("Decision Triggered", self.CONDITION_DECISION_TRIGGERED),
            ("Difficulty Level", self.CONDITION_DIFFICULTY_LEVEL),
            ("Diplomacy State", self.CONDITION_DIPLOMACY_STATE),
            ("Display Timer Triggered", self.CONDITION_DISPLAY_TIMER_TRIGGERED),
            ("Destroy Object", self.CONDITION_DESTROY_OBJECT),
            ("Hero Power Cast", self.CONDITION_HERO_POWER_CAST),
            ("Local Tech Researched", self.CONDITION_LOCAL_TECH_RESEARCHED),
            ("Multiplayer AI Signal", self.CONDITION_MULTIPLAYER_AI_SIGNAL),
            ("Objects In Area", self.CONDITION_OBJECTS_IN_AREA),
            ("Own Fewer Objects", self.CONDITION_OWN_FEWER_OBJECTS),
            ("Own Objects", self.CONDITION_OWN_OBJECTS),
            ("Research Technology", self.CONDITION_RESEARCH_TECHNOLOGY),
            ("Timer", self.CONDITION_TIMER),
        ]
        for label, condition_type in condition_entries:
            self.condition_type_combo.addItem(label, condition_type)

        type_layout.addRow(
            "Condition type:",
            self.condition_type_combo,
        )

        self.condition_settings = QStackedWidget()
        main_layout.addWidget(self.condition_settings)

        self.timer_page = self.create_timer_page()
        self.own_objects_page = self.create_own_objects_page()
        self.own_fewer_objects_page = (
            self.create_own_fewer_objects_page()
        )
        self.objects_in_area_page = (
            self.create_objects_in_area_page()
        )
        self.accumulate_attribute_page = self.create_accumulate_attribute_page()
        self.ai_signal_page = self.create_ai_signal_page()
        self.multiplayer_ai_signal_page = (
            self.create_multiplayer_ai_signal_page()
        )
        self.and_page = self.create_and_page()
        self.or_page = self.create_or_page()
        self.decision_triggered_page = self.create_decision_triggered_page()
        self.difficulty_level_page = self.create_difficulty_level_page()
        self.diplomacy_state_page = self.create_diplomacy_state_page()
        self.display_timer_triggered_page = self.create_display_timer_triggered_page()
        self.research_technology_page = (
            self.create_research_technology_page()
        )
        self.destroy_object_page = self.create_destroy_object_page()
        self.hero_power_cast_page = self.create_hero_power_cast_page()
        self.local_tech_researched_page = self.create_local_tech_researched_page()
        self.bring_object_to_area_page = (
            self.create_bring_object_to_area_page()
        )
        self.bring_object_to_object_page = (
            self.create_bring_object_to_object_page()
        )
        self.building_is_trading_page = (
            self.create_building_is_trading_page()
        )
        self.capture_object_page = self.create_capture_object_page()
        self.chance_page = self.create_chance_page()
        self.compare_variables_page = self.create_compare_variables_page()

        self.condition_settings.addWidget(self.accumulate_attribute_page)
        self.condition_settings.addWidget(self.ai_signal_page)
        self.condition_settings.addWidget(self.bring_object_to_area_page)
        self.condition_settings.addWidget(self.bring_object_to_object_page)
        self.condition_settings.addWidget(self.building_is_trading_page)
        self.condition_settings.addWidget(self.capture_object_page)
        self.condition_settings.addWidget(self.chance_page)
        self.condition_settings.addWidget(self.compare_variables_page)
        self.condition_settings.addWidget(self.and_page)
        self.condition_settings.addWidget(self.or_page)
        self.condition_settings.addWidget(self.decision_triggered_page)
        self.condition_settings.addWidget(self.difficulty_level_page)
        self.condition_settings.addWidget(self.diplomacy_state_page)
        self.condition_settings.addWidget(self.display_timer_triggered_page)
        self.condition_settings.addWidget(self.destroy_object_page)
        self.condition_settings.addWidget(self.hero_power_cast_page)
        self.condition_settings.addWidget(self.local_tech_researched_page)
        self.condition_settings.addWidget(self.multiplayer_ai_signal_page)
        self.condition_settings.addWidget(self.objects_in_area_page)
        self.condition_settings.addWidget(self.own_fewer_objects_page)
        self.condition_settings.addWidget(self.own_objects_page)
        self.condition_settings.addWidget(self.research_technology_page)
        self.condition_settings.addWidget(self.timer_page)

        self.dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.dialog_buttons.button(
            QDialogButtonBox.Ok
        ).setText("Add Condition")
        main_layout.addWidget(self.dialog_buttons)

        self.dialog_buttons.accepted.connect(
            self.validate_and_accept
        )
        self.dialog_buttons.rejected.connect(self.reject)
        self.condition_type_combo.currentIndexChanged.connect(
            self.condition_settings.setCurrentIndex
        )

    def create_ai_signal_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.ai_signal_value = QSpinBox()
        self.ai_signal_value.setRange(-1, 2147483647)
        self.ai_signal_value.setValue(0)
        self.ai_signal_inverted = QCheckBox("Invert this condition")
        layout.addRow("AI Signal:", self.ai_signal_value)
        layout.addRow("", self.ai_signal_inverted)
        return page

    def create_multiplayer_ai_signal_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.multiplayer_ai_signal_value = QComboBox()
        for signal_value in range(256):
            self.multiplayer_ai_signal_value.addItem(
                f"AI Signal {signal_value}", signal_value
            )
        self.multiplayer_ai_signal_value.setCurrentIndex(0)
        self.multiplayer_ai_signal_inverted = QCheckBox(
            "Invert this condition"
        )
        layout.addRow(
            "AI Signal:", self.multiplayer_ai_signal_value
        )
        layout.addRow("", self.multiplayer_ai_signal_inverted)
        help_label = QLabel(
            "Checks whether the specified multiplayer AI signal has been "
            "received."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    def create_timer_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.timer_seconds = QSpinBox()
        self.timer_seconds.setRange(0, 2147483647)
        self.timer_seconds.setValue(60)
        self.timer_seconds.setSuffix(" seconds")
        layout.addRow("Timer duration:", self.timer_seconds)

        self.timer_inverted = QCheckBox(
            "Invert this condition"
        )
        layout.addRow("", self.timer_inverted)

        help_label = QLabel(
            "The condition becomes true after the selected "
            "number of seconds. Inverting reverses the result."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)

        return page

    def create_own_objects_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.own_objects_player = self.create_player_combo()
        self.own_objects_unit = self.create_unit_combo()
        self.own_objects_quantity = self.create_quantity_spinbox()
        self.own_objects_inverted = QCheckBox(
            "Invert this condition"
        )

        layout.addRow("Player:", self.own_objects_player)
        layout.addRow("Object:", self.own_objects_unit)
        layout.addRow("Quantity:", self.own_objects_quantity)
        layout.addRow("", self.own_objects_inverted)

        help_label = QLabel(
            "The condition becomes true when the selected player "
            "owns at least the specified quantity of the object."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)

        return page

    def create_own_fewer_objects_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.own_fewer_objects_player = self.create_player_combo()
        self.own_fewer_objects_unit = self.create_unit_combo()
        self.own_fewer_objects_quantity = (
            self.create_quantity_spinbox()
        )
        self.own_fewer_objects_inverted = QCheckBox(
            "Invert this condition"
        )

        layout.addRow(
            "Player:",
            self.own_fewer_objects_player,
        )
        layout.addRow(
            "Object:",
            self.own_fewer_objects_unit,
        )
        layout.addRow(
            "Quantity:",
            self.own_fewer_objects_quantity,
        )
        layout.addRow("", self.own_fewer_objects_inverted)

        help_label = QLabel(
            "The condition becomes true when the selected player "
            "owns fewer than the specified quantity of the object."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)

        return page

    def create_hero_power_cast_page(self):
        """Create controls for Hero Power Cast (player only; no inversion)."""
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.hero_power_cast_source_player = self.create_player_combo()
        self.hero_power_cast_source_player.insertItem(0, "Gaia", 0)
        layout.addRow("Player:", self.hero_power_cast_source_player)
        return page

    def create_local_tech_researched_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.local_tech_player = self.create_player_combo()
        self.local_tech_player.insertItem(0, "Gaia", 0)
        self.local_tech_technology = QComboBox()
        for label, value in (
            ("Defensive Town Center", 1197),
            ("Economic Town Center", 1195),
            ("Military Town Center", 1196),
            ("Fortified Outpost", 1270),
            ("Defensive Emplacement", 1323),
            ("Offensive Emplacement", 1324),
        ):
            self.local_tech_technology.addItem(label, value)
        self.local_tech_technology.setCurrentIndex(4)
        self.local_tech_object = self.create_object_instance_spinbox()
        self.local_tech_quantity = QSpinBox()
        self.local_tech_quantity.setRange(-1, 2147483647)
        self.local_tech_quantity.setValue(-1)
        self.local_tech_x1 = self.create_coordinate_spinbox()
        self.local_tech_y1 = self.create_coordinate_spinbox()
        self.local_tech_x2 = self.create_coordinate_spinbox()
        self.local_tech_y2 = self.create_coordinate_spinbox()
        for control in (self.local_tech_x1, self.local_tech_y1,
                        self.local_tech_x2, self.local_tech_y2):
            control.setValue(-1)
        self.local_tech_inverted = QCheckBox("Invert this condition")
        layout.addRow("Player:", self.local_tech_player)
        layout.addRow("Local Technology:", self.local_tech_technology)
        layout.addRow("Object instance ID:", self.local_tech_object)
        layout.addRow("Quantity:", self.local_tech_quantity)
        layout.addRow("Area X1:", self.local_tech_x1)
        layout.addRow("Area Y1:", self.local_tech_y1)
        layout.addRow("Area X2:", self.local_tech_x2)
        layout.addRow("Area Y2:", self.local_tech_y2)
        layout.addRow("", self.local_tech_inverted)
        return page

    def create_objects_in_area_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.objects_in_area_player = self.create_player_combo()
        self.objects_in_area_unit = self.create_unit_combo()
        self.objects_in_area_quantity = self.create_quantity_spinbox()
        self.objects_in_area_x1 = self.create_coordinate_spinbox()
        self.objects_in_area_y1 = self.create_coordinate_spinbox()
        self.objects_in_area_x2 = self.create_coordinate_spinbox()
        self.objects_in_area_y2 = self.create_coordinate_spinbox()
        self.objects_in_area_inverted = QCheckBox(
            "Invert this condition"
        )

        self.objects_in_area_x2.setValue(10)
        self.objects_in_area_y2.setValue(10)

        layout.addRow("Player:", self.objects_in_area_player)
        layout.addRow("Object:", self.objects_in_area_unit)
        layout.addRow("Quantity:", self.objects_in_area_quantity)
        layout.addRow("Area X1:", self.objects_in_area_x1)
        layout.addRow("Area Y1:", self.objects_in_area_y1)
        layout.addRow("Area X2:", self.objects_in_area_x2)
        layout.addRow("Area Y2:", self.objects_in_area_y2)
        layout.addRow("", self.objects_in_area_inverted)

        help_label = QLabel(
            "The condition becomes true when the area contains at "
            "least the specified quantity of the selected object. "
            "Coordinate corners are normalised automatically."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)

        return page

    @staticmethod
    def create_resource_attribute_combo():
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)

        for attribute in Attribute:
            display_name = attribute.name.replace("_", " ").title()
            combo.addItem(
                f"{display_name} (ID: {attribute.value})",
                attribute.value,
            )

        completer = QCompleter(combo.model(), combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        combo.setCompleter(completer)
        return combo

    def create_accumulate_attribute_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.accumulate_attribute_player = self.create_player_combo()
        self.accumulate_attribute_resource = self.create_resource_attribute_combo()
        self.accumulate_attribute_quantity = QSpinBox()
        self.accumulate_attribute_quantity.setRange(0, 2147483647)
        self.accumulate_attribute_quantity.setValue(500)
        self.accumulate_attribute_inverted = QCheckBox("Invert this condition")
        layout.addRow("Player:", self.accumulate_attribute_player)
        layout.addRow("Resource:", self.accumulate_attribute_resource)
        layout.addRow("Amount:", self.accumulate_attribute_quantity)
        layout.addRow("", self.accumulate_attribute_inverted)
        return page

    @staticmethod
    def create_technology_combo():
        combo = QComboBox()
        technology_entries = []

        for attribute_name in dir(TechInfo):
            if attribute_name.startswith("_"):
                continue

            try:
                technology_definition = getattr(
                    TechInfo,
                    attribute_name,
                )
                technology_id = technology_definition.ID
            except (AttributeError, TypeError):
                continue

            display_name = attribute_name.replace("_", " ").title()
            technology_entries.append(
                (display_name, technology_id)
            )

        technology_entries.sort(
            key=lambda entry: (entry[0].lower(), entry[1])
        )

        for display_name, technology_id in technology_entries:
            combo.addItem(
                f"{display_name} (ID: {technology_id})",
                technology_id,
            )

        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        completer = QCompleter(combo.model(), combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        combo.setCompleter(completer)
        return combo

    def create_research_technology_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.research_technology_player = self.create_player_combo()
        self.research_technology_technology = (
            self.create_technology_combo()
        )
        self.research_technology_inverted = QCheckBox(
            "Invert this condition"
        )

        layout.addRow("Player:", self.research_technology_player)
        layout.addRow(
            "Technology:",
            self.research_technology_technology,
        )
        layout.addRow("", self.research_technology_inverted)

        help_label = QLabel(
            "The condition becomes true when the selected player has "
            "researched the selected technology."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    @staticmethod
    def create_object_instance_spinbox():
        spinbox = QSpinBox()
        spinbox.setRange(0, 2147483647)
        spinbox.setValue(0)
        spinbox.setToolTip(
            "The scenario object instance ID used by the trigger condition."
        )
        return spinbox

    def create_difficulty_level_page(self):
        """Create Difficulty Level controls using parser-backed values."""
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.difficulty_level_value = QComboBox()
        for label, value in (
            ("Easiest", DifficultyLevel.EASIEST.value),
            ("Standard", DifficultyLevel.STANDARD.value),
            ("Moderate", DifficultyLevel.MODERATE.value),
            ("Hard", DifficultyLevel.HARD.value),
            ("Hardest", DifficultyLevel.HARDEST.value),
            ("Extreme", DifficultyLevel.EXTREME.value),
        ):
            self.difficulty_level_value.addItem(label, value)
        self.difficulty_level_inverted = QCheckBox("Invert this condition")
        layout.addRow("Difficulty:", self.difficulty_level_value)
        layout.addRow("", self.difficulty_level_inverted)
        return page

    def create_diplomacy_state_page(self):
        """Create directional Diplomacy State controls."""
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.diplomacy_state_source_player = self.create_player_combo()
        self.diplomacy_state_target_player = self.create_player_combo()
        self.diplomacy_state_source_player.insertItem(0, "Gaia", 0)
        self.diplomacy_state_target_player.insertItem(0, "Gaia", 0)
        self.diplomacy_state_value = QComboBox()
        for label, value in (
            ("Ally", DiplomacyState.ALLY.value),
            ("Neutral", DiplomacyState.NEUTRAL.value),
            ("Enemy", DiplomacyState.ENEMY.value),
        ):
            self.diplomacy_state_value.addItem(label, value)
        self.diplomacy_state_inverted = QCheckBox("Invert this condition")
        layout.addRow("Source Player:", self.diplomacy_state_source_player)
        layout.addRow("Target Player:", self.diplomacy_state_target_player)
        layout.addRow("Diplomacy State:", self.diplomacy_state_value)
        layout.addRow("", self.diplomacy_state_inverted)
        return page

    def create_display_timer_triggered_page(self):
        """Create controls for the Display Timer Triggered condition."""
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.display_timer_triggered_timer_id = QComboBox()
        for timer_id in range(10):
            self.display_timer_triggered_timer_id.addItem(
                f"Timer {timer_id}", timer_id
            )
        self.display_timer_triggered_inverted = QCheckBox("Invert this condition")
        layout.addRow("Timer:", self.display_timer_triggered_timer_id)
        layout.addRow("", self.display_timer_triggered_inverted)
        return page

    def create_destroy_object_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.destroy_object_unit_object = (
            self.create_object_instance_spinbox()
        )
        self.destroy_object_inverted = QCheckBox(
            "Invert this condition"
        )

        layout.addRow(
            "Object instance ID:",
            self.destroy_object_unit_object,
        )
        layout.addRow("", self.destroy_object_inverted)

        help_label = QLabel(
            "The condition becomes true when the placed scenario object "
            "with this instance ID has been destroyed or removed."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    def create_bring_object_to_area_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.bring_object_to_area_unit_object = (
            self.create_object_instance_spinbox()
        )
        self.bring_object_to_area_x1 = self.create_coordinate_spinbox()
        self.bring_object_to_area_y1 = self.create_coordinate_spinbox()
        self.bring_object_to_area_x2 = self.create_coordinate_spinbox()
        self.bring_object_to_area_y2 = self.create_coordinate_spinbox()
        self.bring_object_to_area_inverted = QCheckBox(
            "Invert this condition"
        )

        layout.addRow(
            "Object instance ID:",
            self.bring_object_to_area_unit_object,
        )
        layout.addRow("Area X1:", self.bring_object_to_area_x1)
        layout.addRow("Area Y1:", self.bring_object_to_area_y1)
        layout.addRow("Area X2:", self.bring_object_to_area_x2)
        layout.addRow("Area Y2:", self.bring_object_to_area_y2)
        layout.addRow("", self.bring_object_to_area_inverted)

        help_label = QLabel(
            "The condition becomes true when the placed scenario object "
            "with this instance ID enters the destination area."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    def create_bring_object_to_object_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.bring_object_to_object_unit_object = (
            self.create_object_instance_spinbox()
        )
        self.bring_object_to_object_next_object = (
            self.create_object_instance_spinbox()
        )
        self.bring_object_to_object_inverted = QCheckBox(
            "Invert this condition"
        )

        layout.addRow(
            "Object instance ID:",
            self.bring_object_to_object_unit_object,
        )
        layout.addRow(
            "Target object instance ID:",
            self.bring_object_to_object_next_object,
        )
        layout.addRow("", self.bring_object_to_object_inverted)

        help_label = QLabel(
            "The condition becomes true when the first placed scenario "
            "object reaches the target scenario object."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    def create_building_is_trading_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.building_is_trading_unit_object = (
            self.create_object_instance_spinbox()
        )
        self.building_is_trading_inverted = QCheckBox(
            "Invert this condition"
        )
        layout.addRow(
            "Building instance ID:",
            self.building_is_trading_unit_object,
        )
        layout.addRow("", self.building_is_trading_inverted)

        help_label = QLabel(
            "The condition becomes true while the selected building "
            "is participating in trade."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    def create_capture_object_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.capture_object_unit_object = (
            self.create_object_instance_spinbox()
        )
        self.capture_object_source_player = self.create_player_combo()
        self.capture_object_inverted = QCheckBox("Invert this condition")

        layout.addRow(
            "Object instance ID:",
            self.capture_object_unit_object,
        )
        layout.addRow("Player:", self.capture_object_source_player)
        layout.addRow("", self.capture_object_inverted)

        help_label = QLabel(
            "The condition becomes true when the selected player captures "
            "the specified scenario object."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    def create_chance_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.chance_quantity = QSpinBox()
        self.chance_quantity.setRange(0, 100)
        self.chance_quantity.setValue(50)
        self.chance_quantity.setSuffix(" %")
        layout.addRow("Chance:", self.chance_quantity)
        help_label = QLabel(
            "Percentage chance that this condition evaluates as true."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    @staticmethod
    def create_comparison_combo():
        combo = QComboBox()
        combo.addItem("Equal (=)", 0)
        combo.addItem("Less than (<)", 1)
        combo.addItem("Greater than (>)", 2)
        combo.addItem("Less than or equal (<=)", 3)
        combo.addItem("Greater than or equal (>=)", 4)
        return combo

    def create_compare_variables_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        self.compare_variables_variable = QSpinBox()
        self.compare_variables_variable.setRange(0, 2147483647)
        self.compare_variables_comparison = self.create_comparison_combo()
        self.compare_variables_variable2 = QSpinBox()
        self.compare_variables_variable2.setRange(0, 2147483647)
        self.compare_variables_inverted = QCheckBox("Invert this condition")
        layout.addRow("Variable 1 ID:", self.compare_variables_variable)
        layout.addRow("Comparison:", self.compare_variables_comparison)
        layout.addRow("Variable 2 ID:", self.compare_variables_variable2)
        layout.addRow("", self.compare_variables_inverted)
        help_label = QLabel("Compares the current values of two scenario variables.")
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    def create_and_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        help_label = QLabel(
            "Condition Joiner creates the game's AND joiner. No values are required."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    def create_or_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)
        help_label = QLabel(
            "Condition Separator creates the game's OR separator. "
            "No values are required."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    @staticmethod
    def create_decision_option_combo():
        combo = QComboBox()
        combo.addItem("Any", -1)
        combo.addItem("Option 1", 1)
        combo.addItem("Option 2", 2)
        return combo

    def create_decision_triggered_page(self):
        page = QWidget()
        layout = QFormLayout()
        page.setLayout(layout)

        self.decision_triggered_id = QSpinBox()
        self.decision_triggered_id.setRange(0, 2147483647)
        self.decision_triggered_option = self.create_decision_option_combo()
        self.decision_triggered_inverted = QCheckBox(
            "Invert this condition"
        )

        layout.addRow("Decision ID:", self.decision_triggered_id)
        layout.addRow("Decision Option:", self.decision_triggered_option)
        layout.addRow("", self.decision_triggered_inverted)

        help_label = QLabel(
            "The condition becomes true when the selected decision and "
            "option have been triggered."
        )
        help_label.setWordWrap(True)
        layout.addRow("", help_label)
        return page

    @staticmethod
    def create_player_combo():
        combo = QComboBox()

        for player_number in range(1, 9):
            combo.addItem(
                f"Player {player_number}",
                player_number,
            )

        return combo

    @staticmethod
    def create_quantity_spinbox():
        spinbox = QSpinBox()
        spinbox.setRange(1, 2147483647)
        spinbox.setValue(1)
        return spinbox

    @staticmethod
    def create_coordinate_spinbox():
        spinbox = QSpinBox()
        spinbox.setRange(0, 500)
        spinbox.setValue(0)
        return spinbox

    @staticmethod
    def create_unit_combo():
        combo = QComboBox()
        unit_entries = []

        for attribute_name in dir(UnitInfo):
            if attribute_name.startswith("_"):
                continue

            try:
                unit_definition = getattr(
                    UnitInfo,
                    attribute_name,
                )
                unit_id = unit_definition.ID
            except (AttributeError, TypeError):
                continue

            display_name = attribute_name.replace(
                "_",
                " ",
            ).title()
            unit_entries.append(
                (display_name, unit_id)
            )

        unit_entries.sort(
            key=lambda entry: entry[0].lower()
        )

        for display_name, unit_id in unit_entries:
            combo.addItem(
                f"{display_name} (ID: {unit_id})",
                unit_id,
            )

        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)

        completer = QCompleter(combo.model(), combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        combo.setCompleter(completer)

        return combo

    def selected_condition_type(self):
        return self.condition_type_combo.currentData()

    def selected_object_combo(self):
        condition_type = self.selected_condition_type()

        if condition_type == self.CONDITION_OWN_OBJECTS:
            return self.own_objects_unit

        if condition_type == self.CONDITION_OWN_FEWER_OBJECTS:
            return self.own_fewer_objects_unit

        if condition_type == self.CONDITION_OBJECTS_IN_AREA:
            return self.objects_in_area_unit

        return None

    def validate_and_accept(self):
        object_combo = self.selected_object_combo()

        if (
            object_combo is not None
            and object_combo.currentData() is None
        ):
            QMessageBox.warning(
                self,
                "Invalid Object Selection",
                "Select an object from the dropdown list.",
            )
            return

        self.accept()

    def condition_data(self):
        condition_type = self.selected_condition_type()

        if condition_type == self.CONDITION_AI_SIGNAL:
            return {
                "type": self.CONDITION_AI_SIGNAL,
                "label": "AI Signal",
                "condition_id": 12,
                "kwargs": {
                    "ai_signal": self.ai_signal_value.value(),
                    "inverted": int(self.ai_signal_inverted.isChecked()),
                },
            }

        if condition_type == self.CONDITION_MULTIPLAYER_AI_SIGNAL:
            return {
                "type": condition_type,
                "label": "Multiplayer AI Signal",
                "condition_id": ConditionId.AI_SIGNAL_MULTIPLAYER,
                "kwargs": {
                    "ai_signal": self.multiplayer_ai_signal_value.currentData(),
                    "inverted": int(
                        self.multiplayer_ai_signal_inverted.isChecked()
                    ),
                },
            }
        if condition_type == self.CONDITION_TIMER:
            return {
                "type": condition_type,
                "label": "Timer",
                "condition_id": ConditionId.TIMER,
                "kwargs": {
                    "timer": self.timer_seconds.value(),
                    "inverted": int(
                        self.timer_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_OWN_OBJECTS:
            return {
                "type": condition_type,
                "label": "Own Objects",
                "condition_id": ConditionId.OWN_OBJECTS,
                "kwargs": {
                    "source_player": (
                        self.own_objects_player.currentData()
                    ),
                    "object_list": (
                        self.own_objects_unit.currentData()
                    ),
                    "quantity": (
                        self.own_objects_quantity.value()
                    ),
                    "inverted": int(
                        self.own_objects_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_OWN_FEWER_OBJECTS:
            return {
                "type": condition_type,
                "label": "Own Fewer Objects",
                "condition_id": ConditionId.OWN_FEWER_OBJECTS,
                "kwargs": {
                    "source_player": (
                        self.own_fewer_objects_player.currentData()
                    ),
                    "object_list": (
                        self.own_fewer_objects_unit.currentData()
                    ),
                    "quantity": (
                        self.own_fewer_objects_quantity.value()
                    ),
                    "inverted": int(
                        self.own_fewer_objects_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_OBJECTS_IN_AREA:
            x1 = self.objects_in_area_x1.value()
            y1 = self.objects_in_area_y1.value()
            x2 = self.objects_in_area_x2.value()
            y2 = self.objects_in_area_y2.value()

            return {
                "type": condition_type,
                "label": "Objects In Area",
                "condition_id": ConditionId.OBJECTS_IN_AREA,
                "kwargs": {
                    "source_player": (
                        self.objects_in_area_player.currentData()
                    ),
                    "object_list": (
                        self.objects_in_area_unit.currentData()
                    ),
                    "quantity": (
                        self.objects_in_area_quantity.value()
                    ),
                    "area_x1": min(x1, x2),
                    "area_y1": min(y1, y2),
                    "area_x2": max(x1, x2),
                    "area_y2": max(y1, y2),
                    "inverted": int(
                        self.objects_in_area_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_ACCUMULATE_ATTRIBUTE:
            return {
                "type": condition_type,
                "label": "Accumulate Attribute",
                "condition_id": ConditionId.ACCUMULATE_ATTRIBUTE,
                "kwargs": {
                    "source_player": self.accumulate_attribute_player.currentData(),
                    "attribute": self.accumulate_attribute_resource.currentData(),
                    "quantity": self.accumulate_attribute_quantity.value(),
                    "inverted": int(self.accumulate_attribute_inverted.isChecked()),
                },
            }

        if condition_type == self.CONDITION_RESEARCH_TECHNOLOGY:
            return {
                "type": condition_type,
                "label": "Research Technology",
                "condition_id": ConditionId.RESEARCH_TECHNOLOGY,
                "kwargs": {
                    "source_player": (
                        self.research_technology_player.currentData()
                    ),
                    "technology": (
                        self.research_technology_technology.currentData()
                    ),
                    "inverted": int(
                        self.research_technology_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_DIFFICULTY_LEVEL:
            return {
                "type": condition_type,
                "label": "Difficulty Level",
                "condition_id": ConditionId.DIFFICULTY_LEVEL,
                "kwargs": {
                    "quantity": self.difficulty_level_value.currentData(),
                    "inverted": int(
                        self.difficulty_level_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_DIPLOMACY_STATE:
            return {
                "type": condition_type,
                "label": "Diplomacy State",
                "condition_id": ConditionId.DIPLOMACY_STATE,
                "kwargs": {
                    "quantity": self.diplomacy_state_value.currentData(),
                    "source_player": self.diplomacy_state_source_player.currentData(),
                    "target_player": self.diplomacy_state_target_player.currentData(),
                    "inverted": int(self.diplomacy_state_inverted.isChecked()),
                },
            }

        if condition_type == self.CONDITION_DISPLAY_TIMER_TRIGGERED:
            return {
                "type": condition_type,
                "label": "Display Timer Triggered",
                "condition_id": ConditionId.DISPLAY_TIMER_TRIGGERED,
                "kwargs": {
                    "timer_id": self.display_timer_triggered_timer_id.currentData(),
                    "inverted": int(self.display_timer_triggered_inverted.isChecked()),
                },
            }

        if condition_type == self.CONDITION_DESTROY_OBJECT:
            return {
                "type": condition_type,
                "label": "Destroy Object",
                "condition_id": ConditionId.DESTROY_OBJECT,
                "kwargs": {
                    "unit_object": (
                        self.destroy_object_unit_object.value()
                    ),
                    "inverted": int(
                        self.destroy_object_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_HERO_POWER_CAST:
            return {
                "type": condition_type,
                "label": "Hero Power Cast",
                "condition_id": ConditionId.HERO_POWER_CAST,
                "kwargs": {
                    "source_player": self.hero_power_cast_source_player.currentData(),
                },
            }

        if condition_type == self.CONDITION_LOCAL_TECH_RESEARCHED:
            return {
                "type": condition_type,
                "label": "Local Tech Researched",
                "condition_id": ConditionId.LOCAL_TECH_RESEARCHED,
                "kwargs": {
                    "local_technology": self.local_tech_technology.currentData(),
                    "source_player": self.local_tech_player.currentData(),
                    "unit_object": self.local_tech_object.value(),
                    "area_x1": self.local_tech_x1.value(),
                    "area_y1": self.local_tech_y1.value(),
                    "area_x2": self.local_tech_x2.value(),
                    "area_y2": self.local_tech_y2.value(),
                    "quantity": self.local_tech_quantity.value(),
                    "inverted": int(self.local_tech_inverted.isChecked()),
                },
            }

        if condition_type == self.CONDITION_BRING_OBJECT_TO_AREA:
            x1 = self.bring_object_to_area_x1.value()
            y1 = self.bring_object_to_area_y1.value()
            x2 = self.bring_object_to_area_x2.value()
            y2 = self.bring_object_to_area_y2.value()
            return {
                "type": condition_type,
                "label": "Bring Object To Area",
                "condition_id": ConditionId.BRING_OBJECT_TO_AREA,
                "kwargs": {
                    "unit_object": (
                        self.bring_object_to_area_unit_object.value()
                    ),
                    "area_x1": min(x1, x2),
                    "area_y1": min(y1, y2),
                    "area_x2": max(x1, x2),
                    "area_y2": max(y1, y2),
                    "inverted": int(
                        self.bring_object_to_area_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_BRING_OBJECT_TO_OBJECT:
            return {
                "type": condition_type,
                "label": "Bring Object To Object",
                "condition_id": ConditionId.BRING_OBJECT_TO_OBJECT,
                "kwargs": {
                    "unit_object": (
                        self.bring_object_to_object_unit_object.value()
                    ),
                    "next_object": (
                        self.bring_object_to_object_next_object.value()
                    ),
                    "inverted": int(
                        self.bring_object_to_object_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_BUILDING_IS_TRADING:
            return {
                "type": condition_type,
                "label": "Building Is Trading",
                "condition_id": ConditionId.BUILDING_IS_TRADING,
                "kwargs": {
                    "unit_object": (
                        self.building_is_trading_unit_object.value()
                    ),
                    "inverted": int(
                        self.building_is_trading_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_CAPTURE_OBJECT:
            return {
                "type": condition_type,
                "label": "Capture Object",
                "condition_id": ConditionId.CAPTURE_OBJECT,
                "kwargs": {
                    "unit_object": self.capture_object_unit_object.value(),
                    "source_player": (
                        self.capture_object_source_player.currentData()
                    ),
                    "inverted": int(
                        self.capture_object_inverted.isChecked()
                    ),
                },
            }

        if condition_type == self.CONDITION_CHANCE:
            return {
                "type": condition_type,
                "label": "Chance",
                "condition_id": ConditionId.CHANCE,
                "kwargs": {"quantity": self.chance_quantity.value()},
            }

        if condition_type == self.CONDITION_COMPARE_VARIABLES:
            return {
                "type": condition_type,
                "label": "Compare Variables",
                "condition_id": ConditionId.COMPARE_VARIABLES,
                "kwargs": {
                    "variable": self.compare_variables_variable.value(),
                    "comparison": self.compare_variables_comparison.currentData(),
                    "variable2": self.compare_variables_variable2.value(),
                    "inverted": int(self.compare_variables_inverted.isChecked()),
                },
            }

        if condition_type == self.CONDITION_AND:
            return {
                "type": condition_type,
                "label": "Condition Joiner",
                "condition_id": ConditionId.AND,
                "kwargs": {},
            }

        if condition_type == self.CONDITION_OR:
            return {
                "type": condition_type,
                "label": "Condition Separator",
                "condition_id": ConditionId.OR,
                "kwargs": {},
            }

        if condition_type == self.CONDITION_DECISION_TRIGGERED:
            return {
                "type": condition_type,
                "label": "Decision Triggered",
                "condition_id": ConditionId.DECISION_TRIGGERED,
                "kwargs": {
                    "decision_id": self.decision_triggered_id.value(),
                    "decision_option": (
                        self.decision_triggered_option.currentData()
                    ),
                    "inverted": int(
                        self.decision_triggered_inverted.isChecked()
                    ),
                },
            }

        return None


class EffectPickerDialog(QDialog):
    def __init__(self, triggers, source_trigger, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Add Effect")
        self.setMinimumWidth(500)

        self.target_triggers = [
            trigger
            for trigger in triggers
            if trigger is not source_trigger
        ]

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        type_layout = QFormLayout()
        main_layout.addLayout(type_layout)

        self.effect_type_combo = QComboBox()
        self.effect_type_combo.addItem(
            "Activate Trigger",
            "activate_trigger",
        )
        self.effect_type_combo.addItem(
            "Deactivate Trigger",
            "deactivate_trigger",
        )
        self.effect_type_combo.addItem(
            "Research Technology",
            "research_technology",
        )
        self.effect_type_combo.addItem("Change Ownership", "change_ownership")
        self.effect_type_combo.addItem("Tribute", "tribute")
        type_layout.addRow(
            "Effect type:",
            self.effect_type_combo,
        )

        self.effect_settings = QStackedWidget()
        main_layout.addWidget(self.effect_settings)

        self.trigger_target_page = QWidget()
        target_layout = QFormLayout()
        self.trigger_target_page.setLayout(target_layout)

        self.target_trigger_combo = QComboBox()

        for trigger in self.target_triggers:
            self.target_trigger_combo.addItem(
                f"{trigger.name} (ID: {trigger.trigger_id})",
                trigger.trigger_id,
            )

        target_layout.addRow(
            "Target trigger:",
            self.target_trigger_combo,
        )

        self.effect_help_label = QLabel()
        self.update_effect_help()
        self.effect_help_label.setWordWrap(True)
        target_layout.addRow("", self.effect_help_label)

        self.effect_settings.addWidget(
            self.trigger_target_page
        )

        self.research_technology_effect_page = QWidget()
        research_effect_layout = QFormLayout()
        self.research_technology_effect_page.setLayout(
            research_effect_layout
        )
        self.research_effect_player = (
            ConditionPickerDialog.create_player_combo()
        )
        self.research_effect_technology = (
            ConditionPickerDialog.create_technology_combo()
        )
        research_effect_layout.addRow(
            "Player:",
            self.research_effect_player,
        )
        research_effect_layout.addRow(
            "Technology:",
            self.research_effect_technology,
        )
        research_effect_help = QLabel(
            "Researches the selected technology for the selected player."
        )
        research_effect_help.setWordWrap(True)
        research_effect_layout.addRow("", research_effect_help)
        self.effect_settings.addWidget(
            self.research_technology_effect_page
        )
        self.change_ownership_effect_page = QWidget()
        ownership_layout = QFormLayout()
        self.change_ownership_effect_page.setLayout(ownership_layout)
        self.change_ownership_source_player = ConditionPickerDialog.create_player_combo()
        self.change_ownership_target_player = ConditionPickerDialog.create_player_combo()
        self.change_ownership_object_ids = QLineEdit()
        self.change_ownership_object_ids.setPlaceholderText("Example: 12, 15, 27")
        ownership_layout.addRow("Source Player:", self.change_ownership_source_player)
        ownership_layout.addRow("Target Player:", self.change_ownership_target_player)
        ownership_layout.addRow("Object instance IDs:", self.change_ownership_object_ids)
        self.effect_settings.addWidget(self.change_ownership_effect_page)

        self.tribute_effect_page = QWidget()
        tribute_layout = QFormLayout()
        self.tribute_effect_page.setLayout(tribute_layout)
        self.tribute_source_player = ConditionPickerDialog.create_player_combo()
        self.tribute_target_player = ConditionPickerDialog.create_player_combo()
        self.tribute_resource = (
            ConditionPickerDialog.create_resource_attribute_combo()
        )
        self.tribute_quantity = QSpinBox()
        self.tribute_quantity.setRange(0, 2147483647)
        self.tribute_quantity.setValue(500)
        tribute_layout.addRow("Source Player:", self.tribute_source_player)
        tribute_layout.addRow("Target Player:", self.tribute_target_player)
        tribute_layout.addRow("Resource:", self.tribute_resource)
        tribute_layout.addRow("Amount:", self.tribute_quantity)
        self.effect_settings.addWidget(self.tribute_effect_page)

        self.dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.dialog_buttons.button(
            QDialogButtonBox.Ok
        ).setText("Add Effect")
        main_layout.addWidget(self.dialog_buttons)

        self.dialog_buttons.accepted.connect(self.accept)
        self.dialog_buttons.rejected.connect(self.reject)
        self.effect_type_combo.currentIndexChanged.connect(
            self.update_effect_help
        )

        if not self.target_triggers:
            self.target_trigger_combo.addItem(
                "No target triggers available",
                None,
            )
            self.target_trigger_combo.setEnabled(False)
            self.dialog_buttons.button(
                QDialogButtonBox.Ok
            ).setEnabled(False)

    @staticmethod
    def parse_object_instance_ids(text):
        values = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            value = int(part)
            if value < 0:
                raise ValueError("Object IDs cannot be negative")
            if value not in values:
                values.append(value)
        return values

    def update_effect_help(self):
        effect_type = self.effect_type_combo.currentData()

        if effect_type == "research_technology":
            self.effect_settings.setCurrentWidget(self.research_technology_effect_page)
            return
        if effect_type == "change_ownership":
            self.effect_settings.setCurrentWidget(self.change_ownership_effect_page)
            return
        if effect_type == "tribute":
            self.effect_settings.setCurrentWidget(self.tribute_effect_page)
            return

        self.effect_settings.setCurrentWidget(
            self.trigger_target_page
        )
        if effect_type == "deactivate_trigger":
            self.effect_help_label.setText(
                "When the selected trigger runs, this effect "
                "deactivates the target trigger."
            )
        else:
            self.effect_help_label.setText(
                "When the selected trigger runs, this effect "
                "activates the target trigger."
            )

    def effect_data(self):
        effect_type = self.effect_type_combo.currentData()

        if effect_type in (
            "activate_trigger",
            "deactivate_trigger",
        ):
            trigger_id = self.target_trigger_combo.currentData()

            if trigger_id is None:
                return None

            return {
                "type": effect_type,
                "trigger_id": trigger_id,
                "target_name": self.target_trigger_combo.currentText(),
            }

        if effect_type == "research_technology":
            technology = self.research_effect_technology.currentData()
            player = self.research_effect_player.currentData()
            if technology is None or player is None:
                return None
            return {
                "type": effect_type,
                "source_player": player,
                "technology": technology,
                "target_name": (
                    self.research_effect_technology.currentText()
                ),
            }

        if effect_type == "change_ownership":
            try:
                object_ids = self.parse_object_instance_ids(
                    self.change_ownership_object_ids.text()
                )
            except ValueError:
                return None
            if not object_ids:
                return None
            return {
                "type": effect_type,
                "source_player": self.change_ownership_source_player.currentData(),
                "target_player": self.change_ownership_target_player.currentData(),
                "selected_object_ids": object_ids,
                "target_name": "Change Ownership",
            }

        if effect_type == "tribute":
            return {
                "type": effect_type,
                "source_player": self.tribute_source_player.currentData(),
                "target_player": self.tribute_target_player.currentData(),
                "tribute_list": self.tribute_resource.currentData(),
                "quantity": self.tribute_quantity.value(),
                "target_name": "Tribute",
            }

        return None


class NewScenarioDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("New Scenario")
        self.setMinimumWidth(650)

        layout = QVBoxLayout()
        self.setLayout(layout)

        form = QFormLayout()
        layout.addLayout(form)

        self.name_edit = QLineEdit("New Scenario")
        self.name_edit.selectAll()
        form.addRow("Scenario Name:", self.name_edit)

        location_widget = QWidget()
        location_layout = QHBoxLayout()
        location_layout.setContentsMargins(0, 0, 0, 0)
        location_widget.setLayout(location_layout)

        self.location_edit = QLineEdit()
        self.location_edit.setText(
            str(self.detect_default_scenario_folder())
        )

        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(
            self.browse_location
        )

        location_layout.addWidget(self.location_edit, 1)
        location_layout.addWidget(self.browse_button)
        form.addRow("Save Location:", location_widget)

        help_label = QLabel(
            "The Age of Empires II: Definitive Edition scenario "
            "folder is detected automatically when possible. "
            "Use Browse to select a different folder."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.file_preview_label = QLabel()
        self.file_preview_label.setWordWrap(True)
        layout.addWidget(self.file_preview_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Ok).setText("Create")
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_edit.textChanged.connect(
            self.update_file_preview
        )
        self.location_edit.textChanged.connect(
            self.update_file_preview
        )
        self.update_file_preview()

    @staticmethod
    def detect_default_scenario_folder():
        aoe_folder = (
            Path.home()
            / "Games"
            / "Age of Empires 2 DE"
        )

        if not aoe_folder.exists():
            return Path.home()

        candidates = []

        for scenario_folder in aoe_folder.glob(
            "*/resources/_common/scenario"
        ):
            if not scenario_folder.is_dir():
                continue

            account_folder_name = (
                scenario_folder.parent.parent.parent.name
            )

            if not account_folder_name.isdigit():
                continue

            account_id = int(account_folder_name)

            # The folder named 0 is not the active Steam account
            # scenario directory used by the game.
            if account_id == 0:
                continue

            # SteamID64 account folders normally contain 17 digits
            # and commonly begin with 765611. Prefer such folders.
            is_steam_id_64 = (
                len(account_folder_name) == 17
                and account_folder_name.startswith("765611")
            )

            candidates.append(
                (
                    is_steam_id_64,
                    account_id,
                    scenario_folder,
                )
            )

        if candidates:
            candidates.sort(
                key=lambda item: (item[0], item[1]),
                reverse=True,
            )
            return candidates[0][2]

        return Path.home()

    def browse_location(self):
        starting_folder = self.location_edit.text().strip()

        if not starting_folder:
            starting_folder = str(Path.home())

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Scenario Folder",
            starting_folder,
        )

        if folder:
            self.location_edit.setText(folder)

    def update_file_preview(self):
        name = self.name_edit.text().strip() or "New Scenario"
        folder_text = self.location_edit.text().strip()

        if folder_text:
            file_path = (
                Path(folder_text)
                / f"{name}.aoe2scenario"
            )
            self.file_preview_label.setText(
                f"Scenario file: {file_path}"
            )
        else:
            self.file_preview_label.setText(
                "Scenario file: Select a save location"
            )

    def validate_and_accept(self):
        name = self.scenario_name()
        folder = self.scenario_folder()

        if not name:
            QMessageBox.warning(
                self,
                "Invalid Name",
                "Please enter a scenario name.",
            )
            return

        invalid_characters = set('<>:"/\\|?*')

        if any(character in invalid_characters for character in name):
            QMessageBox.warning(
                self,
                "Invalid Name",
                (
                    "The scenario name contains a character that "
                    "cannot be used in a Windows filename.\n\n"
                    'Do not use: < > : " / \\ | ? *'
                ),
            )
            return

        if name.endswith(" ") or name.endswith("."):
            QMessageBox.warning(
                self,
                "Invalid Name",
                "The scenario name cannot end with a space or full stop.",
            )
            return

        if not folder:
            QMessageBox.warning(
                self,
                "Invalid Location",
                "Please select a folder for the scenario.",
            )
            return

        folder_path = Path(folder)

        if not folder_path.exists() or not folder_path.is_dir():
            QMessageBox.warning(
                self,
                "Invalid Location",
                "The selected scenario folder does not exist.",
            )
            return

        self.accept()

    def scenario_name(self):
        return self.name_edit.text().strip()

    def scenario_folder(self):
        return self.location_edit.text().strip()

    def scenario_file_path(self):
        return (
            Path(self.scenario_folder())
            / f"{self.scenario_name()}.aoe2scenario"
        )


class TriggerListWidget(QListWidget):
    drop_detected = Signal(int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragged_trigger_id = None
        self._source_row = -1

        self.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(
            QAbstractItemView.InternalMove
        )

    def startDrag(self, supported_actions):
        item = self.currentItem()

        if item is None:
            return

        self._dragged_trigger_id = item.data(Qt.UserRole)
        self._source_row = self.currentRow()
        super().startDrag(supported_actions)

    def dropEvent(self, event):
        dragged_trigger_id = self._dragged_trigger_id
        source_row = self._source_row

        super().dropEvent(event)

        self._dragged_trigger_id = None
        self._source_row = -1

        if dragged_trigger_id is None or source_row < 0:
            return

        target_row = next(
            (
                index
                for index in range(self.count())
                if self.item(index).data(Qt.UserRole)
                == dragged_trigger_id
            ),
            -1,
        )

        if target_row < 0 or target_row == source_row:
            return

        self.drop_detected.emit(
            dragged_trigger_id,
            source_row,
            target_row,
        )


class MinimapLabel(QLabel):
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        LoggerService.log_message(
            "Application started.",
            context="Startup",
        )

        self.setWindowTitle("AoE2 Trigger Studio+")
        self.resize(1200, 800)

        self.scenario_service = ScenarioService()
        self.undo_manager = UndoManager()
        self.trigger_names = []
        self.copied_trigger_id = None
        self.copied_trigger_name = None
        self.copied_trigger_object = None
        # AOKTS_COMPARE_DEVELOPER_MODE_PATCH_V2
        self.developer_mode = False
        self.compare_tab = None
        self.developer_shortcut = QShortcut(
            QKeySequence("Ctrl+Alt+H"), self
        )
        self.developer_shortcut.activated.connect(
            self.toggle_developer_mode
        )
        self.cut_trigger_object = None
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        self.status_label = QLabel("No scenario loaded")

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.create_triggers_tab()
        self.create_messages_tab()
        self.create_players_tab()
        self.create_units_tab()
        self.create_minimap_dock()


        self.create_menus()

        self.location_label = QLabel(
            "Location: Not yet saved"
        )
        self.location_label.setMinimumWidth(420)
        self.location_label.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )
        self.statusBar().addWidget(
            self.status_label,
            1,
        )
        self.statusBar().addPermanentWidget(
            self.location_label,
            1,
        )

        self.update_ui_enabled_state()
        self.update_location_display()
        self.clear_minimap()

    def run_busy_operation(
        self,
        title,
        message,
        operation,
    ):
        overlay = BusyOverlay(self, title, message)
        event_loop = QEventLoop(self)
        thread = QThread(self)
        worker = BusyOperationWorker(operation)
        worker.moveToThread(thread)

        outcome = {
            "result": None,
            "error": None,
        }

        def operation_completed(result):
            outcome["result"] = result
            thread.quit()

        def operation_failed(error):
            outcome["error"] = error
            thread.quit()

        worker.completed.connect(operation_completed)
        worker.failed.connect(operation_failed)
        thread.started.connect(worker.run)
        thread.finished.connect(event_loop.quit)
        thread.finished.connect(worker.deleteLater)

        overlay.show()
        overlay.raise_()
        QApplication.processEvents()

        thread.start()
        event_loop.exec()
        thread.wait()

        overlay.close()
        overlay.deleteLater()
        thread.deleteLater()
        QApplication.processEvents()

        if outcome["error"] is not None:
            raise outcome["error"]

        return outcome["result"]

    # AOKTS_COMPARE_DEVELOPER_MODE_PATCH_V2
    def load_scenario_for_compare(self, path):
        resolved_path = Path(path).expanduser().resolve()
        return AoE2DEScenario.from_file(str(resolved_path))

    def toggle_developer_mode(self):
        self.developer_mode = not self.developer_mode
        if self.developer_mode:
            if self.compare_tab is None:
                self.compare_tab = ScenarioCompareTab(
                    self.load_scenario_for_compare, self
                )
            compare_index = self.tabs.indexOf(self.compare_tab)
            if compare_index < 0:
                compare_index = self.tabs.addTab(
                    self.compare_tab, "Compare"
                )
            self.tabs.setCurrentIndex(compare_index)
            QMessageBox.information(
                self,
                "Developer Mode Unlocked",
                "Developer Mode has been unlocked.\n\n"
                "Advanced developer tools are now available.",
            )
            self.statusBar().showMessage(
                "Developer Mode enabled", 3000
            )
            return
        if self.compare_tab is not None:
            compare_index = self.tabs.indexOf(self.compare_tab)
            if compare_index >= 0:
                self.tabs.removeTab(compare_index)
        self.statusBar().showMessage(
            "Developer Mode disabled", 3000
        )

    def create_menus(self):
        file_menu = self.menuBar().addMenu("File")

        self.new_scenario_action = QAction("New Scenario...", self)
        self.new_scenario_action.setShortcut(QKeySequence.New)
        self.new_scenario_action.triggered.connect(self.new_scenario)
        file_menu.addAction(self.new_scenario_action)

        self.open_action = QAction(
            "Open Scenario",
            self,
        )
        self.open_action.setShortcut(
            QKeySequence.Open
        )
        self.open_action.setStatusTip(
            "Open an AoE2 scenario"
        )
        self.open_action.triggered.connect(
            self.open_scenario
        )
        file_menu.addAction(self.open_action)

        self.save_action = QAction(
            "Save",
            self,
        )
        self.save_action.setShortcut(
            QKeySequence.Save
        )
        self.save_action.setStatusTip(
            "Save changes to the current scenario file"
        )
        self.save_action.triggered.connect(
            self.save_scenario
        )
        file_menu.addAction(self.save_action)

        self.save_as_action = QAction(
            "Save As",
            self,
        )
        self.save_as_action.setShortcut(
            QKeySequence("Ctrl+Shift+S")
        )
        self.save_as_action.setStatusTip(
            "Save the scenario to a new file"
        )
        self.save_as_action.triggered.connect(
            self.save_scenario_as
        )
        file_menu.addAction(self.save_as_action)

        self.export_triggers_action = QAction(
            "Export Triggers to Text...",
            self,
        )
        self.export_triggers_action.setStatusTip(
            "Export all triggers as a human-readable text file"
        )
        self.export_triggers_action.triggered.connect(
            self.export_triggers_to_text
        )
        file_menu.addAction(self.export_triggers_action)

        file_menu.addSeparator()

        self.exit_action = QAction(
            "Exit",
            self,
        )
        self.exit_action.setShortcut(
            QKeySequence("Alt+F4")
        )
        self.exit_action.setStatusTip(
            "Close AoE2 Trigger Studio+"
        )
        self.exit_action.triggered.connect(
            self.close
        )
        file_menu.addAction(self.exit_action)

        edit_menu = self.menuBar().addMenu("Edit")

        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.undo_last_action)
        edit_menu.addAction(self.undo_action)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcut(QKeySequence.Redo)
        self.redo_action.triggered.connect(self.redo_last_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()

        self.new_trigger_action = QAction(
            "New Trigger",
            self,
        )
        self.new_trigger_action.setShortcut(
            QKeySequence("Ctrl+Shift+N")
        )
        self.new_trigger_action.setStatusTip(
            "Create a new empty trigger"
        )
        self.new_trigger_action.triggered.connect(
            self.create_new_trigger
        )
        edit_menu.addAction(self.new_trigger_action)

        self.rename_trigger_action = QAction(
            "Rename Trigger",
            self,
        )
        self.rename_trigger_action.setShortcut(
            QKeySequence("F2")
        )
        self.rename_trigger_action.setStatusTip(
            "Rename the selected trigger"
        )
        self.rename_trigger_action.triggered.connect(
            self.rename_trigger
        )
        edit_menu.addAction(self.rename_trigger_action)
        self.blank_all_trigger_names_action = QAction(
            "Blank All Trigger Names", self
        )
        self.blank_all_trigger_names_action.setStatusTip(
            "Remove the names from every trigger in the scenario"
        )
        self.blank_all_trigger_names_action.triggered.connect(
            self.blank_all_trigger_names
        )
        edit_menu.addAction(self.blank_all_trigger_names_action)
        self.delete_trigger_action = QAction(
            "Delete Trigger",
            self,
        )
        self.delete_trigger_action.setShortcut(
            QKeySequence("Delete")
        )
        self.delete_trigger_action.setStatusTip(
            "Delete the selected trigger"
        )
        self.delete_trigger_action.triggered.connect(
            self.delete_trigger
        )
        edit_menu.addAction(self.delete_trigger_action)

        self.move_trigger_up_action = QAction(
            "Move Trigger Up",
            self,
        )
        self.move_trigger_up_action.setShortcut(
            QKeySequence("Alt+Up")
        )
        self.move_trigger_up_action.setStatusTip(
            "Move the selected trigger one position earlier"
        )
        self.move_trigger_up_action.triggered.connect(
            self.move_trigger_up
        )
        edit_menu.addAction(self.move_trigger_up_action)

        self.move_trigger_down_action = QAction(
            "Move Trigger Down",
            self,
        )
        self.move_trigger_down_action.setShortcut(
            QKeySequence("Alt+Down")
        )
        self.move_trigger_down_action.setStatusTip(
            "Move the selected trigger one position later"
        )
        self.move_trigger_down_action.triggered.connect(
            self.move_trigger_down
        )
        edit_menu.addAction(self.move_trigger_down_action)
        edit_menu.addSeparator()

        self.cut_trigger_action = QAction("Cut Trigger", self)

        self.cut_trigger_action.setShortcut(QKeySequence.Cut)

        self.cut_trigger_action.setStatusTip(

            "Cut the selected trigger for pasting after another trigger"

        )

        self.cut_trigger_action.triggered.connect(self.aokts_cut_trigger)

        edit_menu.addAction(self.cut_trigger_action)

        self.paste_trigger_action = QAction("Paste Trigger", self)

        self.paste_trigger_action.setShortcut(QKeySequence.Paste)

        self.paste_trigger_action.setStatusTip(

            "Move the cut trigger after the currently selected trigger"

        )

        self.paste_trigger_action.triggered.connect(self.aokts_paste_trigger)

        self.paste_trigger_action.setEnabled(False)

        edit_menu.addAction(self.paste_trigger_action)

        self.copy_trigger_action = QAction(
            "Copy Trigger",
            self,
        )
        self.copy_trigger_action.setShortcut(
            QKeySequence.Copy
        )
        self.copy_trigger_action.setStatusTip(
            "Copy the selected trigger"
        )
        self.copy_trigger_action.triggered.connect(
            self.aokts_copy_trigger
        )
        edit_menu.addAction(self.copy_trigger_action)
        self.copy_all_players_action = QAction("Copy All Players", self)
        self.copy_all_players_action.setStatusTip(
            "Copy the selected trigger for Players 1 to 8"
        )
        self.copy_all_players_action.triggered.connect(self.copy_all_players)
        edit_menu.addAction(self.copy_all_players_action)
        self.randomize_trigger_order_action = QAction("Randomize Trigger Order", self)
        self.randomize_trigger_order_action.setStatusTip(
            "Randomize the order of every trigger in the loaded scenario"
        )
        self.randomize_trigger_order_action.triggered.connect(
            self.randomize_trigger_order
        )
        edit_menu.addSeparator()
        edit_menu.addAction(self.randomize_trigger_order_action)
        view_menu = self.menuBar().addMenu("View")
        self.minimap_toggle_action = (
            self.minimap_dock.toggleViewAction()
        )
        self.minimap_toggle_action.setText(
            "Scenario Minimap"
        )
        self.minimap_toggle_action.setStatusTip(
            "Show or hide the Scenario Minimap window"
        )
        view_menu.addAction(self.minimap_toggle_action)

        help_menu = self.menuBar().addMenu("Help")

        self.open_log_folder_action = QAction(
            "Open Log Folder",
            self,
        )
        self.open_log_folder_action.setStatusTip(
            "Open the Trigger Studio+ diagnostic log folder"
        )
        self.open_log_folder_action.triggered.connect(
            self.open_log_folder
        )
        help_menu.addAction(self.open_log_folder_action)
        help_menu.addSeparator()

        self.about_action = QAction(
            "About",
            self,
        )
        self.about_action.setStatusTip(
            "About AoE2 Trigger Studio+"
        )
        self.about_action.triggered.connect(
            self.show_about_dialog
        )
        help_menu.addAction(self.about_action)

    def open_log_folder(self):
        log_folder = LoggerService.get_log_folder()
        opened = QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(log_folder))
        )

        if not opened:
            QMessageBox.warning(
                self,
                "Open Log Folder Failed",
                f"The log folder could not be opened.\n\n{log_folder}",
            )

    def show_about_dialog(self):
        QMessageBox.about(
            self,
            "About AoE2 Trigger Studio+",
            (
                "AoE2 Trigger Studio+\n\n"
                "A desktop utility for Age of Empires II: "
                "Definitive Edition scenario editing.\n\n"
                "Current features include:\n"
                "- Trigger browsing and search\n"
                "- Trigger duplication\n"
                "- Trigger-tree copying\n"
                "- Copy and paste triggers\n"
                "- Coordinate-based unit placement\n"
                "- Open, Save and Save As\n\n"
                "Built with Python, PySide6 and "
                "AoE2ScenarioParser 0.9.4.\n\n"
                "Project owner: Tenchy"
            ),
        )

    def create_minimap_dock(self):
        self.minimap_dock = QDockWidget(
            "Scenario Minimap",
            self,
        )
        self.minimap_dock.setObjectName(
            "ScenarioMinimapDock"
        )
        self.minimap_dock.setAllowedAreas(
            Qt.LeftDockWidgetArea
            | Qt.RightDockWidgetArea
            | Qt.BottomDockWidgetArea
        )
        self.minimap_dock.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )

        minimap_container = QWidget()
        minimap_layout = QVBoxLayout()
        minimap_container.setLayout(minimap_layout)

        self.minimap_label = MinimapLabel(
            "Open a scenario to display its minimap."
        )
        self.minimap_label.setAlignment(Qt.AlignCenter)
        self.minimap_label.setMinimumSize(320, 240)
        self.minimap_label.setStyleSheet(
            "QLabel { "
            "background-color: #20242b; "
            "color: #d6d6d6; "
            "border: 1px solid #555b66; "
            "padding: 6px; "
            "}"
        )
        self.minimap_label.resized.connect(
            self.refresh_minimap_display
        )
        minimap_layout.addWidget(
            self.minimap_label,
            stretch=1,
        )

        self.minimap_status_label = QLabel(
            "Terrain preview not loaded"
        )
        self.minimap_status_label.setAlignment(Qt.AlignCenter)
        minimap_layout.addWidget(self.minimap_status_label)

        self.minimap_dock.setWidget(minimap_container)
        self.minimap_dock.setMinimumSize(360, 320)
        self.minimap_dock.resize(520, 520)

        self.addDockWidget(
            Qt.RightDockWidgetArea,
            self.minimap_dock,
        )
        self.minimap_dock.setFloating(True)
        self.minimap_dock.show()
        self.minimap_dock.visibilityChanged.connect(
            self.handle_minimap_visibility_changed
        )

    def handle_minimap_visibility_changed(self, visible):
        if visible:
            self.refresh_minimap_display()

    def create_triggers_tab(self):
        self.triggers_tab = QWidget()
        self.tabs.addTab(self.triggers_tab, "Triggers")

        tab_layout = QVBoxLayout()
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(10)
        self.triggers_tab.setLayout(tab_layout)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search triggers...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumHeight(34)
        tab_layout.addWidget(self.search_box)

        self.trigger_workspace_splitter = QSplitter(
            Qt.Horizontal
        )
        self.trigger_workspace_splitter.setChildrenCollapsible(False)
        self.trigger_workspace_splitter.setHandleWidth(2)
        self.trigger_workspace_splitter.setStyleSheet(
            "QSplitter::handle { background-color: transparent; }"
            "QSplitter::handle:hover { background-color: transparent; }"
        )
        tab_layout.addWidget(
            self.trigger_workspace_splitter,
            stretch=1,
        )

        trigger_column = QWidget()
        trigger_list_layout = QVBoxLayout()
        trigger_list_layout.setContentsMargins(0, 0, 0, 0)
        trigger_list_layout.setSpacing(10)
        trigger_column.setLayout(trigger_list_layout)
        self.trigger_workspace_splitter.addWidget(trigger_column)

        self.triggers_group = QGroupBox("Triggers")
        triggers_group_layout = QVBoxLayout()
        triggers_group_layout.setContentsMargins(10, 12, 10, 10)
        triggers_group_layout.setSpacing(8)
        self.triggers_group.setLayout(triggers_group_layout)

        self.trigger_list = TriggerListWidget(self)
        self.trigger_list.setContextMenuPolicy(
            Qt.CustomContextMenu
        )
        triggers_group_layout.addWidget(
            self.trigger_list,
            stretch=1,
        )
        trigger_list_layout.addWidget(
            self.triggers_group,
            stretch=1,
        )

        self.panel_move_trigger_up_button = QPushButton(
            "Move Up"
        )
        self.panel_move_trigger_down_button = QPushButton(
            "Move Down"
        )

        self.panel_move_trigger_up_button.setToolTip(
            "Move the selected trigger one position earlier (Alt+Up)"
        )
        self.panel_move_trigger_down_button.setToolTip(
            "Move the selected trigger one position later (Alt+Down)"
        )

        logic_column = QWidget()
        logic_column_layout = QVBoxLayout()
        logic_column_layout.setContentsMargins(0, 0, 0, 0)
        logic_column_layout.setSpacing(10)
        logic_column.setLayout(logic_column_layout)
        self.trigger_workspace_splitter.addWidget(logic_column)

        self.trigger_logic_group = QGroupBox("Trigger Logic")
        trigger_logic_layout = QVBoxLayout()
        trigger_logic_layout.setContentsMargins(10, 12, 10, 10)
        trigger_logic_layout.setSpacing(8)
        self.trigger_logic_group.setLayout(trigger_logic_layout)

        self.trigger_logic_list = QListWidget()
        self.trigger_logic_list.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        self.trigger_logic_list.setAlternatingRowColors(True)
        self.trigger_logic_list.setToolTip(
            "Select an item to inspect it. Double-click to edit it."
        )
        self.trigger_logic_list.setContextMenuPolicy(
            Qt.CustomContextMenu
        )
        trigger_logic_layout.addWidget(self.trigger_logic_list)
        logic_column_layout.addWidget(
            self.trigger_logic_group,
            stretch=1,
        )

        logic_actions_row = QHBoxLayout()
        logic_actions_row.setSpacing(8)
        self.panel_add_condition_button = QPushButton(
            "Add Condition"
        )
        self.panel_add_effect_button = QPushButton(
            "Add Effect"
        )
        self.panel_delete_logic_button = QPushButton("Delete")
        self.panel_move_logic_up_button = QPushButton("Move Up")
        self.panel_move_logic_down_button = QPushButton("Move Down")
        for button in (
            self.panel_delete_logic_button,
            self.panel_move_logic_up_button,
            self.panel_move_logic_down_button,
        ):
            button.setEnabled(False)
        logic_actions_row.addWidget(self.panel_add_condition_button)
        logic_actions_row.addWidget(self.panel_add_effect_button)
        logic_actions_row.addWidget(self.panel_delete_logic_button)
        logic_actions_row.addWidget(self.panel_move_logic_up_button)
        logic_actions_row.addWidget(self.panel_move_logic_down_button)
        logic_column_layout.addLayout(logic_actions_row)

        editor_column = QWidget()
        details_and_operations_layout = QVBoxLayout()
        details_and_operations_layout.setContentsMargins(0, 0, 0, 0)
        details_and_operations_layout.setSpacing(10)
        editor_column.setLayout(details_and_operations_layout)
        self.trigger_workspace_splitter.addWidget(editor_column)
        self.trigger_workspace_splitter.setStretchFactor(0, 2)
        self.trigger_workspace_splitter.setStretchFactor(1, 3)
        self.trigger_workspace_splitter.setStretchFactor(2, 4)
        self.trigger_workspace_splitter.setSizes([280, 390, 530])

        self.logic_editor_group = QGroupBox("Item Editor")
        logic_editor_layout = QVBoxLayout()
        logic_editor_layout.setContentsMargins(12, 14, 12, 12)
        logic_editor_layout.setSpacing(10)
        self.logic_editor_group.setLayout(logic_editor_layout)

        self.logic_editor_stack = QStackedWidget()
        logic_editor_layout.addWidget(self.logic_editor_stack)

        self.logic_summary_page = QWidget()
        logic_summary_layout = QVBoxLayout()
        logic_summary_layout.setContentsMargins(0, 0, 0, 0)
        self.logic_summary_page.setLayout(logic_summary_layout)

        # Retained as an internal compatibility widget for existing refresh
        # paths. The Item Editor deliberately remains visually empty until a
        # supported condition or effect is opened for editing.
        self.trigger_details = QTextEdit()
        self.trigger_details.setReadOnly(True)
        self.trigger_details.clear()
        self.trigger_details.hide()
        logic_summary_layout.addWidget(self.trigger_details)
        self.logic_editor_stack.addWidget(self.logic_summary_page)

        self.timer_editor_page = QWidget()
        timer_editor_layout = QFormLayout()
        timer_editor_layout.setContentsMargins(14, 14, 14, 14)
        timer_editor_layout.setHorizontalSpacing(14)
        timer_editor_layout.setVerticalSpacing(12)
        self.timer_editor_page.setLayout(timer_editor_layout)
        self.edit_timer_seconds = QSpinBox()
        self.edit_timer_seconds.setRange(0, 2147483647)
        self.edit_timer_seconds.setSuffix(" seconds")
        self.edit_timer_inverted = QCheckBox("Invert this condition")
        timer_editor_layout.addRow(
            "Timer duration:",
            self.edit_timer_seconds,
        )
        timer_editor_layout.addRow("", self.edit_timer_inverted)
        self.timer_apply_button = QPushButton("Apply Changes")
        self.timer_cancel_button = QPushButton("Cancel")
        timer_button_row = QHBoxLayout()
        timer_button_row.addWidget(self.timer_apply_button)
        timer_button_row.addWidget(self.timer_cancel_button)
        timer_editor_layout.addRow("", timer_button_row)
        self.logic_editor_stack.addWidget(self.timer_editor_page)

        self.and_editor_page = QWidget()
        and_editor_layout = QFormLayout()
        and_editor_layout.setContentsMargins(14, 14, 14, 14)
        and_editor_layout.setHorizontalSpacing(14)
        and_editor_layout.setVerticalSpacing(12)
        self.and_editor_page.setLayout(and_editor_layout)
        and_editor_help = QLabel(
            "Condition Joiner creates the game's AND joiner. There are no values to edit."
        )
        and_editor_help.setWordWrap(True)
        and_editor_layout.addRow("", and_editor_help)
        self.and_close_button = QPushButton("Close")
        self.and_close_button.clicked.connect(self.cancel_logic_edit)
        and_editor_layout.addRow("", self.and_close_button)
        self.logic_editor_stack.addWidget(self.and_editor_page)

        self.or_editor_page = QWidget()
        or_editor_layout = QFormLayout()
        or_editor_layout.setContentsMargins(14, 14, 14, 14)
        or_editor_layout.setHorizontalSpacing(14)
        or_editor_layout.setVerticalSpacing(12)
        self.or_editor_page.setLayout(or_editor_layout)
        or_editor_help = QLabel(
            "Condition Separator uses the game's OR separator. "
            "There are no values to edit."
        )
        or_editor_help.setWordWrap(True)
        or_editor_layout.addRow("", or_editor_help)
        self.or_close_button = QPushButton("Close")
        self.or_close_button.clicked.connect(self.cancel_logic_edit)
        or_editor_layout.addRow("", self.or_close_button)
        self.logic_editor_stack.addWidget(self.or_editor_page)

        self.ai_signal_editor_page = QWidget()
        ai_signal_editor_layout = QFormLayout()
        ai_signal_editor_layout.setContentsMargins(14, 14, 14, 14)
        ai_signal_editor_layout.setHorizontalSpacing(14)
        ai_signal_editor_layout.setVerticalSpacing(12)
        self.ai_signal_editor_page.setLayout(ai_signal_editor_layout)
        self.edit_ai_signal_value = QSpinBox()
        self.edit_ai_signal_value.setRange(-1, 2147483647)
        self.edit_ai_signal_inverted = QCheckBox("Invert this condition")
        ai_signal_editor_layout.addRow("AI Signal:", self.edit_ai_signal_value)
        ai_signal_editor_layout.addRow("", self.edit_ai_signal_inverted)
        self.ai_signal_apply_button = QPushButton("Apply Changes")
        self.ai_signal_cancel_button = QPushButton("Cancel")
        ai_signal_button_row = QHBoxLayout()
        ai_signal_button_row.addWidget(self.ai_signal_apply_button)
        ai_signal_button_row.addWidget(self.ai_signal_cancel_button)
        ai_signal_editor_layout.addRow("", ai_signal_button_row)
        self.ai_signal_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.ai_signal_cancel_button.clicked.connect(self.cancel_logic_edit)
        self.logic_editor_stack.addWidget(self.ai_signal_editor_page)
        self.multiplayer_ai_signal_editor_page = QWidget()
        multiplayer_ai_signal_layout = QFormLayout()
        multiplayer_ai_signal_layout.setContentsMargins(14, 14, 14, 14)
        multiplayer_ai_signal_layout.setHorizontalSpacing(14)
        multiplayer_ai_signal_layout.setVerticalSpacing(12)
        self.multiplayer_ai_signal_editor_page.setLayout(
            multiplayer_ai_signal_layout
        )
        self.edit_multiplayer_ai_signal_value = QComboBox()
        for signal_value in range(256):
            self.edit_multiplayer_ai_signal_value.addItem(
                f"AI Signal {signal_value}", signal_value
            )
        self.edit_multiplayer_ai_signal_inverted = QCheckBox(
            "Invert this condition"
        )
        multiplayer_ai_signal_layout.addRow(
            "AI Signal:", self.edit_multiplayer_ai_signal_value
        )
        multiplayer_ai_signal_layout.addRow(
            "", self.edit_multiplayer_ai_signal_inverted
        )
        self.multiplayer_ai_signal_apply_button = QPushButton(
            "Apply Changes"
        )
        self.multiplayer_ai_signal_cancel_button = QPushButton("Cancel")
        multiplayer_ai_signal_buttons = QHBoxLayout()
        multiplayer_ai_signal_buttons.addWidget(
            self.multiplayer_ai_signal_apply_button
        )
        multiplayer_ai_signal_buttons.addWidget(
            self.multiplayer_ai_signal_cancel_button
        )
        multiplayer_ai_signal_layout.addRow(
            "", multiplayer_ai_signal_buttons
        )
        self.multiplayer_ai_signal_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.multiplayer_ai_signal_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.logic_editor_stack.addWidget(
            self.multiplayer_ai_signal_editor_page
        )

        self.own_objects_editor_page = QWidget()
        own_objects_layout = QFormLayout()
        own_objects_layout.setContentsMargins(14, 14, 14, 14)
        own_objects_layout.setHorizontalSpacing(14)
        own_objects_layout.setVerticalSpacing(12)
        self.own_objects_editor_page.setLayout(own_objects_layout)
        self.edit_own_objects_player = (
            ConditionPickerDialog.create_player_combo()
        )
        self.edit_own_objects_unit = (
            ConditionPickerDialog.create_unit_combo()
        )
        self.edit_own_objects_quantity = (
            ConditionPickerDialog.create_quantity_spinbox()
        )
        self.edit_own_objects_inverted = QCheckBox(
            "Invert this condition"
        )
        own_objects_layout.addRow(
            "Player:",
            self.edit_own_objects_player,
        )
        own_objects_layout.addRow(
            "Object:",
            self.edit_own_objects_unit,
        )
        own_objects_layout.addRow(
            "Quantity:",
            self.edit_own_objects_quantity,
        )
        own_objects_layout.addRow(
            "",
            self.edit_own_objects_inverted,
        )
        self.own_objects_apply_button = QPushButton("Apply Changes")
        self.own_objects_cancel_button = QPushButton("Cancel")
        own_objects_button_row = QHBoxLayout()
        own_objects_button_row.addWidget(self.own_objects_apply_button)
        own_objects_button_row.addWidget(self.own_objects_cancel_button)
        own_objects_layout.addRow("", own_objects_button_row)
        self.logic_editor_stack.addWidget(
            self.own_objects_editor_page
        )

        self.own_fewer_editor_page = QWidget()
        own_fewer_layout = QFormLayout()
        own_fewer_layout.setContentsMargins(14, 14, 14, 14)
        own_fewer_layout.setHorizontalSpacing(14)
        own_fewer_layout.setVerticalSpacing(12)
        self.own_fewer_editor_page.setLayout(own_fewer_layout)
        self.edit_own_fewer_player = (
            ConditionPickerDialog.create_player_combo()
        )
        self.edit_own_fewer_unit = (
            ConditionPickerDialog.create_unit_combo()
        )
        self.edit_own_fewer_quantity = (
            ConditionPickerDialog.create_quantity_spinbox()
        )
        self.edit_own_fewer_inverted = QCheckBox(
            "Invert this condition"
        )
        own_fewer_layout.addRow(
            "Player:",
            self.edit_own_fewer_player,
        )
        own_fewer_layout.addRow(
            "Object:",
            self.edit_own_fewer_unit,
        )
        own_fewer_layout.addRow(
            "Quantity:",
            self.edit_own_fewer_quantity,
        )
        own_fewer_layout.addRow("", self.edit_own_fewer_inverted)
        self.own_fewer_apply_button = QPushButton("Apply Changes")
        self.own_fewer_cancel_button = QPushButton("Cancel")
        own_fewer_button_row = QHBoxLayout()
        own_fewer_button_row.addWidget(self.own_fewer_apply_button)
        own_fewer_button_row.addWidget(self.own_fewer_cancel_button)
        own_fewer_layout.addRow("", own_fewer_button_row)
        self.logic_editor_stack.addWidget(self.own_fewer_editor_page)

        self.objects_area_editor_page = QWidget()
        objects_area_layout = QFormLayout()
        objects_area_layout.setContentsMargins(14, 14, 14, 14)
        objects_area_layout.setHorizontalSpacing(14)
        objects_area_layout.setVerticalSpacing(12)
        self.objects_area_editor_page.setLayout(objects_area_layout)
        self.edit_objects_area_player = (
            ConditionPickerDialog.create_player_combo()
        )
        self.edit_objects_area_unit = (
            ConditionPickerDialog.create_unit_combo()
        )
        self.edit_objects_area_quantity = (
            ConditionPickerDialog.create_quantity_spinbox()
        )
        self.edit_objects_area_x1 = (
            ConditionPickerDialog.create_coordinate_spinbox()
        )
        self.edit_objects_area_y1 = (
            ConditionPickerDialog.create_coordinate_spinbox()
        )
        self.edit_objects_area_x2 = (
            ConditionPickerDialog.create_coordinate_spinbox()
        )
        self.edit_objects_area_y2 = (
            ConditionPickerDialog.create_coordinate_spinbox()
        )
        self.edit_objects_area_inverted = QCheckBox(
            "Invert this condition"
        )
        objects_area_layout.addRow(
            "Player:",
            self.edit_objects_area_player,
        )
        objects_area_layout.addRow(
            "Object:",
            self.edit_objects_area_unit,
        )
        objects_area_layout.addRow(
            "Quantity:",
            self.edit_objects_area_quantity,
        )
        objects_area_layout.addRow("Area X1:", self.edit_objects_area_x1)
        objects_area_layout.addRow("Area Y1:", self.edit_objects_area_y1)
        objects_area_layout.addRow("Area X2:", self.edit_objects_area_x2)
        objects_area_layout.addRow("Area Y2:", self.edit_objects_area_y2)
        objects_area_layout.addRow("", self.edit_objects_area_inverted)
        self.objects_area_apply_button = QPushButton("Apply Changes")
        self.objects_area_cancel_button = QPushButton("Cancel")
        objects_area_button_row = QHBoxLayout()
        objects_area_button_row.addWidget(self.objects_area_apply_button)
        objects_area_button_row.addWidget(self.objects_area_cancel_button)
        objects_area_layout.addRow("", objects_area_button_row)
        self.logic_editor_stack.addWidget(
            self.objects_area_editor_page
        )

        self.accumulate_attribute_editor_page = QWidget()
        accumulate_attribute_layout = QFormLayout()
        accumulate_attribute_layout.setContentsMargins(14, 14, 14, 14)
        accumulate_attribute_layout.setHorizontalSpacing(14)
        accumulate_attribute_layout.setVerticalSpacing(12)
        self.accumulate_attribute_editor_page.setLayout(accumulate_attribute_layout)
        self.edit_accumulate_attribute_player = ConditionPickerDialog.create_player_combo()
        self.edit_accumulate_attribute_resource = ConditionPickerDialog.create_resource_attribute_combo()
        self.edit_accumulate_attribute_quantity = QSpinBox()
        self.edit_accumulate_attribute_quantity.setRange(0, 2147483647)
        self.edit_accumulate_attribute_inverted = QCheckBox("Invert this condition")
        accumulate_attribute_layout.addRow("Player:", self.edit_accumulate_attribute_player)
        accumulate_attribute_layout.addRow("Resource:", self.edit_accumulate_attribute_resource)
        accumulate_attribute_layout.addRow("Amount:", self.edit_accumulate_attribute_quantity)
        accumulate_attribute_layout.addRow("", self.edit_accumulate_attribute_inverted)
        self.accumulate_attribute_apply_button = QPushButton("Apply Changes")
        self.accumulate_attribute_cancel_button = QPushButton("Cancel")
        accumulate_attribute_button_row = QHBoxLayout()
        accumulate_attribute_button_row.addWidget(self.accumulate_attribute_apply_button)
        accumulate_attribute_button_row.addWidget(self.accumulate_attribute_cancel_button)
        accumulate_attribute_layout.addRow("", accumulate_attribute_button_row)
        self.logic_editor_stack.addWidget(self.accumulate_attribute_editor_page)

        self.research_technology_editor_page = QWidget()
        research_technology_layout = QFormLayout()
        research_technology_layout.setContentsMargins(14, 14, 14, 14)
        research_technology_layout.setHorizontalSpacing(14)
        research_technology_layout.setVerticalSpacing(12)
        self.research_technology_editor_page.setLayout(
            research_technology_layout
        )

        self.edit_research_technology_player = (
            ConditionPickerDialog.create_player_combo()
        )
        self.edit_research_technology_technology = (
            ConditionPickerDialog.create_technology_combo()
        )
        self.edit_research_technology_inverted = QCheckBox(
            "Invert this condition"
        )

        research_technology_layout.addRow(
            "Player:",
            self.edit_research_technology_player,
        )
        research_technology_layout.addRow(
            "Technology:",
            self.edit_research_technology_technology,
        )
        research_technology_layout.addRow(
            "",
            self.edit_research_technology_inverted,
        )

        self.research_technology_apply_button = QPushButton(
            "Apply Changes"
        )
        self.research_technology_cancel_button = QPushButton("Cancel")
        research_technology_button_row = QHBoxLayout()
        research_technology_button_row.addWidget(
            self.research_technology_apply_button
        )
        research_technology_button_row.addWidget(
            self.research_technology_cancel_button
        )
        research_technology_layout.addRow(
            "",
            research_technology_button_row,
        )
        self.logic_editor_stack.addWidget(
            self.research_technology_editor_page
        )

        self.building_is_trading_editor_page = QWidget()
        building_is_trading_layout = QFormLayout()
        building_is_trading_layout.setContentsMargins(14, 14, 14, 14)
        building_is_trading_layout.setHorizontalSpacing(14)
        building_is_trading_layout.setVerticalSpacing(12)
        self.building_is_trading_editor_page.setLayout(
            building_is_trading_layout
        )

        self.edit_building_is_trading_unit_object = (
            ConditionPickerDialog.create_object_instance_spinbox()
        )
        self.edit_building_is_trading_inverted = QCheckBox(
            "Invert this condition"
        )
        building_is_trading_layout.addRow(
            "Building instance ID:",
            self.edit_building_is_trading_unit_object,
        )
        building_is_trading_layout.addRow(
            "", self.edit_building_is_trading_inverted
        )

        self.building_is_trading_apply_button = QPushButton(
            "Apply Changes"
        )
        self.building_is_trading_cancel_button = QPushButton("Cancel")
        building_is_trading_button_row = QHBoxLayout()
        building_is_trading_button_row.addWidget(
            self.building_is_trading_apply_button
        )
        building_is_trading_button_row.addWidget(
            self.building_is_trading_cancel_button
        )
        building_is_trading_layout.addRow(
            "", building_is_trading_button_row
        )
        self.building_is_trading_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.building_is_trading_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.logic_editor_stack.addWidget(
            self.building_is_trading_editor_page
        )

        self.capture_object_editor_page = QWidget()
        capture_object_layout = QFormLayout()
        capture_object_layout.setContentsMargins(14, 14, 14, 14)
        capture_object_layout.setHorizontalSpacing(14)
        capture_object_layout.setVerticalSpacing(12)
        self.capture_object_editor_page.setLayout(capture_object_layout)

        self.edit_capture_object_unit_object = (
            ConditionPickerDialog.create_object_instance_spinbox()
        )
        self.edit_capture_object_source_player = (
            ConditionPickerDialog.create_player_combo()
        )
        self.edit_capture_object_inverted = QCheckBox(
            "Invert this condition"
        )
        capture_object_layout.addRow(
            "Object instance ID:",
            self.edit_capture_object_unit_object,
        )
        capture_object_layout.addRow(
            "Player:", self.edit_capture_object_source_player
        )
        capture_object_layout.addRow(
            "", self.edit_capture_object_inverted
        )

        self.capture_object_apply_button = QPushButton("Apply Changes")
        self.capture_object_cancel_button = QPushButton("Cancel")
        capture_object_button_row = QHBoxLayout()
        capture_object_button_row.addWidget(
            self.capture_object_apply_button
        )
        capture_object_button_row.addWidget(
            self.capture_object_cancel_button
        )
        capture_object_layout.addRow("", capture_object_button_row)
        self.capture_object_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.capture_object_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.logic_editor_stack.addWidget(self.capture_object_editor_page)

        self.chance_editor_page = QWidget()
        chance_editor_layout = QFormLayout()
        chance_editor_layout.setContentsMargins(14, 14, 14, 14)
        chance_editor_layout.setHorizontalSpacing(14)
        chance_editor_layout.setVerticalSpacing(12)
        self.chance_editor_page.setLayout(chance_editor_layout)
        self.edit_chance_quantity = QSpinBox()
        self.edit_chance_quantity.setRange(0, 100)
        self.edit_chance_quantity.setSuffix(" %")
        chance_editor_layout.addRow("Chance:", self.edit_chance_quantity)
        self.chance_apply_button = QPushButton("Apply Changes")
        self.chance_cancel_button = QPushButton("Cancel")
        chance_button_row = QHBoxLayout()
        chance_button_row.addWidget(self.chance_apply_button)
        chance_button_row.addWidget(self.chance_cancel_button)
        chance_editor_layout.addRow("", chance_button_row)
        self.chance_apply_button.clicked.connect(self.apply_wave_1_condition_edit)
        self.chance_cancel_button.clicked.connect(self.cancel_logic_edit)
        self.logic_editor_stack.addWidget(self.chance_editor_page)

        self.compare_variables_editor_page = QWidget()
        compare_variables_layout = QFormLayout()
        compare_variables_layout.setContentsMargins(14, 14, 14, 14)
        compare_variables_layout.setHorizontalSpacing(14)
        compare_variables_layout.setVerticalSpacing(12)
        self.compare_variables_editor_page.setLayout(compare_variables_layout)
        self.edit_compare_variables_variable = QSpinBox()
        self.edit_compare_variables_variable.setRange(0, 2147483647)
        self.edit_compare_variables_comparison = ConditionPickerDialog.create_comparison_combo()
        self.edit_compare_variables_variable2 = QSpinBox()
        self.edit_compare_variables_variable2.setRange(0, 2147483647)
        self.edit_compare_variables_inverted = QCheckBox("Invert this condition")
        compare_variables_layout.addRow("Variable 1 ID:", self.edit_compare_variables_variable)
        compare_variables_layout.addRow("Comparison:", self.edit_compare_variables_comparison)
        compare_variables_layout.addRow("Variable 2 ID:", self.edit_compare_variables_variable2)
        compare_variables_layout.addRow("", self.edit_compare_variables_inverted)
        self.compare_variables_apply_button = QPushButton("Apply Changes")
        self.compare_variables_cancel_button = QPushButton("Cancel")
        compare_variables_button_row = QHBoxLayout()
        compare_variables_button_row.addWidget(self.compare_variables_apply_button)
        compare_variables_button_row.addWidget(self.compare_variables_cancel_button)
        compare_variables_layout.addRow("", compare_variables_button_row)
        self.compare_variables_apply_button.clicked.connect(self.apply_wave_1_condition_edit)
        self.compare_variables_cancel_button.clicked.connect(self.cancel_logic_edit)
        self.logic_editor_stack.addWidget(self.compare_variables_editor_page)

        self.decision_triggered_editor_page = QWidget()
        decision_triggered_layout = QFormLayout()
        decision_triggered_layout.setContentsMargins(14, 14, 14, 14)
        decision_triggered_layout.setHorizontalSpacing(14)
        decision_triggered_layout.setVerticalSpacing(12)
        self.decision_triggered_editor_page.setLayout(
            decision_triggered_layout
        )

        self.edit_decision_triggered_id = QSpinBox()
        self.edit_decision_triggered_id.setRange(0, 2147483647)
        self.edit_decision_triggered_option = (
            ConditionPickerDialog.create_decision_option_combo()
        )
        self.edit_decision_triggered_inverted = QCheckBox(
            "Invert this condition"
        )
        decision_triggered_layout.addRow(
            "Decision ID:", self.edit_decision_triggered_id
        )
        decision_triggered_layout.addRow(
            "Decision Option:", self.edit_decision_triggered_option
        )
        decision_triggered_layout.addRow(
            "", self.edit_decision_triggered_inverted
        )

        self.decision_triggered_apply_button = QPushButton(
            "Apply Changes"
        )
        self.decision_triggered_cancel_button = QPushButton("Cancel")
        decision_triggered_button_row = QHBoxLayout()
        decision_triggered_button_row.addWidget(
            self.decision_triggered_apply_button
        )
        decision_triggered_button_row.addWidget(
            self.decision_triggered_cancel_button
        )
        decision_triggered_layout.addRow(
            "", decision_triggered_button_row
        )
        self.decision_triggered_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.decision_triggered_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.logic_editor_stack.addWidget(
            self.decision_triggered_editor_page
        )

        # AOKTS_DIFFICULTY_LEVEL_V20
        self.difficulty_level_editor_page = QWidget()
        difficulty_level_layout = QFormLayout()
        difficulty_level_layout.setContentsMargins(14, 14, 14, 14)
        difficulty_level_layout.setHorizontalSpacing(14)
        difficulty_level_layout.setVerticalSpacing(12)
        self.difficulty_level_editor_page.setLayout(difficulty_level_layout)

        self.edit_difficulty_level_value = QComboBox()
        for label, value in (
            ("Easiest", DifficultyLevel.EASIEST.value),
            ("Standard", DifficultyLevel.STANDARD.value),
            ("Moderate", DifficultyLevel.MODERATE.value),
            ("Hard", DifficultyLevel.HARD.value),
            ("Hardest", DifficultyLevel.HARDEST.value),
            ("Extreme", DifficultyLevel.EXTREME.value),
        ):
            self.edit_difficulty_level_value.addItem(label, value)
        self.edit_difficulty_level_inverted = QCheckBox(
            "Invert this condition"
        )
        difficulty_level_layout.addRow(
            "Difficulty:", self.edit_difficulty_level_value
        )
        difficulty_level_layout.addRow(
            "", self.edit_difficulty_level_inverted
        )
        self.difficulty_level_apply_button = QPushButton("Apply Changes")
        self.difficulty_level_cancel_button = QPushButton("Cancel")
        difficulty_level_buttons = QHBoxLayout()
        difficulty_level_buttons.addWidget(
            self.difficulty_level_apply_button
        )
        difficulty_level_buttons.addWidget(
            self.difficulty_level_cancel_button
        )
        difficulty_level_layout.addRow("", difficulty_level_buttons)
        self.difficulty_level_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.difficulty_level_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.logic_editor_stack.addWidget(
            self.difficulty_level_editor_page
        )

        # AOKTS_DIPLOMACY_STATE_V21
        self.diplomacy_state_editor_page = QWidget()
        diplomacy_state_layout = QFormLayout()
        diplomacy_state_layout.setContentsMargins(14, 14, 14, 14)
        diplomacy_state_layout.setHorizontalSpacing(14)
        diplomacy_state_layout.setVerticalSpacing(12)
        self.diplomacy_state_editor_page.setLayout(diplomacy_state_layout)
        self.edit_diplomacy_state_source_player = ConditionPickerDialog.create_player_combo()
        self.edit_diplomacy_state_target_player = ConditionPickerDialog.create_player_combo()
        self.edit_diplomacy_state_source_player.insertItem(0, "Gaia", 0)
        self.edit_diplomacy_state_target_player.insertItem(0, "Gaia", 0)
        self.edit_diplomacy_state_value = QComboBox()
        for label, value in (
            ("Ally", DiplomacyState.ALLY.value),
            ("Neutral", DiplomacyState.NEUTRAL.value),
            ("Enemy", DiplomacyState.ENEMY.value),
        ):
            self.edit_diplomacy_state_value.addItem(label, value)
        self.edit_diplomacy_state_inverted = QCheckBox("Invert this condition")
        diplomacy_state_layout.addRow("Source Player:", self.edit_diplomacy_state_source_player)
        diplomacy_state_layout.addRow("Target Player:", self.edit_diplomacy_state_target_player)
        diplomacy_state_layout.addRow("Diplomacy State:", self.edit_diplomacy_state_value)
        diplomacy_state_layout.addRow("", self.edit_diplomacy_state_inverted)
        self.diplomacy_state_apply_button = QPushButton("Apply Changes")
        self.diplomacy_state_cancel_button = QPushButton("Cancel")
        diplomacy_state_buttons = QHBoxLayout()
        diplomacy_state_buttons.addWidget(self.diplomacy_state_apply_button)
        diplomacy_state_buttons.addWidget(self.diplomacy_state_cancel_button)
        diplomacy_state_layout.addRow("", diplomacy_state_buttons)
        self.diplomacy_state_apply_button.clicked.connect(self.apply_wave_1_condition_edit)
        self.diplomacy_state_cancel_button.clicked.connect(self.cancel_logic_edit)
        self.logic_editor_stack.addWidget(self.diplomacy_state_editor_page)

        # AOKTS_DISPLAY_TIMER_TRIGGERED_V22
        self.display_timer_triggered_editor_page = QWidget()
        display_timer_triggered_layout = QFormLayout()
        display_timer_triggered_layout.setContentsMargins(14, 14, 14, 14)
        display_timer_triggered_layout.setHorizontalSpacing(14)
        display_timer_triggered_layout.setVerticalSpacing(12)
        self.display_timer_triggered_editor_page.setLayout(display_timer_triggered_layout)
        self.edit_display_timer_triggered_timer_id = QComboBox()
        for timer_id in range(10):
            self.edit_display_timer_triggered_timer_id.addItem(
                f"Timer {timer_id}", timer_id
            )
        self.edit_display_timer_triggered_inverted = QCheckBox("Invert this condition")
        display_timer_triggered_layout.addRow(
            "Timer:", self.edit_display_timer_triggered_timer_id
        )
        display_timer_triggered_layout.addRow("", self.edit_display_timer_triggered_inverted)
        self.display_timer_triggered_apply_button = QPushButton("Apply Changes")
        self.display_timer_triggered_cancel_button = QPushButton("Cancel")
        display_timer_triggered_buttons = QHBoxLayout()
        display_timer_triggered_buttons.addWidget(self.display_timer_triggered_apply_button)
        display_timer_triggered_buttons.addWidget(self.display_timer_triggered_cancel_button)
        display_timer_triggered_layout.addRow("", display_timer_triggered_buttons)
        self.display_timer_triggered_apply_button.clicked.connect(self.apply_wave_1_condition_edit)
        self.display_timer_triggered_cancel_button.clicked.connect(self.cancel_logic_edit)
        self.logic_editor_stack.addWidget(self.display_timer_triggered_editor_page)

        self.destroy_object_editor_page = QWidget()
        destroy_object_layout = QFormLayout()
        destroy_object_layout.setContentsMargins(14, 14, 14, 14)
        destroy_object_layout.setHorizontalSpacing(14)
        destroy_object_layout.setVerticalSpacing(12)
        self.destroy_object_editor_page.setLayout(
            destroy_object_layout
        )

        self.edit_destroy_object_unit_object = (
            ConditionPickerDialog.create_object_instance_spinbox()
        )
        self.edit_destroy_object_inverted = QCheckBox(
            "Invert this condition"
        )
        destroy_object_layout.addRow(
            "Object instance ID:",
            self.edit_destroy_object_unit_object,
        )
        destroy_object_layout.addRow(
            "",
            self.edit_destroy_object_inverted,
        )

        self.destroy_object_apply_button = QPushButton(
            "Apply Changes"
        )
        self.destroy_object_cancel_button = QPushButton("Cancel")
        destroy_object_button_row = QHBoxLayout()
        destroy_object_button_row.addWidget(
            self.destroy_object_apply_button
        )
        destroy_object_button_row.addWidget(
            self.destroy_object_cancel_button
        )
        destroy_object_layout.addRow("", destroy_object_button_row)
        self.logic_editor_stack.addWidget(
            self.destroy_object_editor_page
        )

        # AOKTS_HERO_POWER_CAST_V23
        self.hero_power_cast_editor_page = QWidget()
        hero_power_cast_layout = QFormLayout()
        hero_power_cast_layout.setContentsMargins(14, 14, 14, 14)
        hero_power_cast_layout.setHorizontalSpacing(14)
        hero_power_cast_layout.setVerticalSpacing(12)
        self.hero_power_cast_editor_page.setLayout(hero_power_cast_layout)
        self.edit_hero_power_cast_source_player = (
            ConditionPickerDialog.create_player_combo()
        )
        self.edit_hero_power_cast_source_player.insertItem(0, "Gaia", 0)
        hero_power_cast_layout.addRow(
            "Player:", self.edit_hero_power_cast_source_player
        )
        self.hero_power_cast_apply_button = QPushButton("Apply Changes")
        self.hero_power_cast_cancel_button = QPushButton("Cancel")
        hero_power_cast_buttons = QHBoxLayout()
        hero_power_cast_buttons.addWidget(self.hero_power_cast_apply_button)
        hero_power_cast_buttons.addWidget(self.hero_power_cast_cancel_button)
        hero_power_cast_layout.addRow("", hero_power_cast_buttons)
        self.hero_power_cast_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.hero_power_cast_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.logic_editor_stack.addWidget(self.hero_power_cast_editor_page)

        self.local_tech_editor_page = QWidget()
        local_layout = QFormLayout()
        local_layout.setContentsMargins(14, 14, 14, 14)
        self.local_tech_editor_page.setLayout(local_layout)
        self.edit_local_tech_player = ConditionPickerDialog.create_player_combo()
        self.edit_local_tech_player.insertItem(0, "Gaia", 0)
        self.edit_local_tech_technology = QComboBox()
        for label, value in (
            ("Defensive Town Center", 1197),
            ("Economic Town Center", 1195),
            ("Military Town Center", 1196),
            ("Fortified Outpost", 1270),
            ("Defensive Emplacement", 1323),
            ("Offensive Emplacement", 1324),
        ):
            self.edit_local_tech_technology.addItem(label, value)
        self.edit_local_tech_object = ConditionPickerDialog.create_object_instance_spinbox()
        self.edit_local_tech_quantity = QSpinBox()
        self.edit_local_tech_quantity.setRange(-1, 2147483647)
        self.edit_local_tech_x1 = ConditionPickerDialog.create_coordinate_spinbox()
        self.edit_local_tech_y1 = ConditionPickerDialog.create_coordinate_spinbox()
        self.edit_local_tech_x2 = ConditionPickerDialog.create_coordinate_spinbox()
        self.edit_local_tech_y2 = ConditionPickerDialog.create_coordinate_spinbox()
        self.edit_local_tech_inverted = QCheckBox("Invert this condition")
        local_layout.addRow("Player:", self.edit_local_tech_player)
        local_layout.addRow("Local Technology:", self.edit_local_tech_technology)
        local_layout.addRow("Object instance ID:", self.edit_local_tech_object)
        local_layout.addRow("Quantity:", self.edit_local_tech_quantity)
        local_layout.addRow("Area X1:", self.edit_local_tech_x1)
        local_layout.addRow("Area Y1:", self.edit_local_tech_y1)
        local_layout.addRow("Area X2:", self.edit_local_tech_x2)
        local_layout.addRow("Area Y2:", self.edit_local_tech_y2)
        local_layout.addRow("", self.edit_local_tech_inverted)
        self.local_tech_apply_button = QPushButton("Apply Changes")
        self.local_tech_cancel_button = QPushButton("Cancel")
        local_buttons = QHBoxLayout()
        local_buttons.addWidget(self.local_tech_apply_button)
        local_buttons.addWidget(self.local_tech_cancel_button)
        local_layout.addRow("", local_buttons)
        self.local_tech_apply_button.clicked.connect(self.apply_wave_1_condition_edit)
        self.local_tech_cancel_button.clicked.connect(self.cancel_logic_edit)
        self.logic_editor_stack.addWidget(self.local_tech_editor_page)

        self.bring_object_to_object_editor_page = QWidget()
        bring_object_to_object_layout = QFormLayout()
        bring_object_to_object_layout.setContentsMargins(14, 14, 14, 14)
        bring_object_to_object_layout.setHorizontalSpacing(14)
        bring_object_to_object_layout.setVerticalSpacing(12)
        self.bring_object_to_object_editor_page.setLayout(
            bring_object_to_object_layout
        )

        self.edit_bring_object_to_object_unit_object = (
            ConditionPickerDialog.create_object_instance_spinbox()
        )
        self.edit_bring_object_to_object_next_object = (
            ConditionPickerDialog.create_object_instance_spinbox()
        )
        self.edit_bring_object_to_object_inverted = QCheckBox(
            "Invert this condition"
        )
        bring_object_to_object_layout.addRow(
            "Object instance ID:",
            self.edit_bring_object_to_object_unit_object,
        )
        bring_object_to_object_layout.addRow(
            "Target object instance ID:",
            self.edit_bring_object_to_object_next_object,
        )
        bring_object_to_object_layout.addRow(
            "", self.edit_bring_object_to_object_inverted
        )

        self.bring_object_to_object_apply_button = QPushButton(
            "Apply Changes"
        )
        self.bring_object_to_object_cancel_button = QPushButton("Cancel")
        bring_object_to_object_button_row = QHBoxLayout()
        bring_object_to_object_button_row.addWidget(
            self.bring_object_to_object_apply_button
        )
        bring_object_to_object_button_row.addWidget(
            self.bring_object_to_object_cancel_button
        )
        bring_object_to_object_layout.addRow(
            "", bring_object_to_object_button_row
        )
        self.bring_object_to_object_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.bring_object_to_object_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.logic_editor_stack.addWidget(
            self.bring_object_to_object_editor_page
        )

        self.bring_object_to_area_editor_page = QWidget()
        bring_object_to_area_layout = QFormLayout()
        bring_object_to_area_layout.setContentsMargins(14, 14, 14, 14)
        bring_object_to_area_layout.setHorizontalSpacing(14)
        bring_object_to_area_layout.setVerticalSpacing(12)
        self.bring_object_to_area_editor_page.setLayout(
            bring_object_to_area_layout
        )

        self.edit_bring_object_to_area_unit_object = (
            ConditionPickerDialog.create_object_instance_spinbox()
        )
        self.edit_bring_object_to_area_x1 = (
            ConditionPickerDialog.create_coordinate_spinbox()
        )
        self.edit_bring_object_to_area_y1 = (
            ConditionPickerDialog.create_coordinate_spinbox()
        )
        self.edit_bring_object_to_area_x2 = (
            ConditionPickerDialog.create_coordinate_spinbox()
        )
        self.edit_bring_object_to_area_y2 = (
            ConditionPickerDialog.create_coordinate_spinbox()
        )
        self.edit_bring_object_to_area_inverted = QCheckBox(
            "Invert this condition"
        )

        bring_object_to_area_layout.addRow(
            "Object instance ID:",
            self.edit_bring_object_to_area_unit_object,
        )
        bring_object_to_area_layout.addRow(
            "Area X1:", self.edit_bring_object_to_area_x1
        )
        bring_object_to_area_layout.addRow(
            "Area Y1:", self.edit_bring_object_to_area_y1
        )
        bring_object_to_area_layout.addRow(
            "Area X2:", self.edit_bring_object_to_area_x2
        )
        bring_object_to_area_layout.addRow(
            "Area Y2:", self.edit_bring_object_to_area_y2
        )
        bring_object_to_area_layout.addRow(
            "", self.edit_bring_object_to_area_inverted
        )

        self.bring_object_to_area_apply_button = QPushButton(
            "Apply Changes"
        )
        self.bring_object_to_area_cancel_button = QPushButton("Cancel")
        bring_object_to_area_button_row = QHBoxLayout()
        bring_object_to_area_button_row.addWidget(
            self.bring_object_to_area_apply_button
        )
        bring_object_to_area_button_row.addWidget(
            self.bring_object_to_area_cancel_button
        )
        bring_object_to_area_layout.addRow(
            "", bring_object_to_area_button_row
        )
        self.logic_editor_stack.addWidget(
            self.bring_object_to_area_editor_page
        )

        self.trigger_effect_editor_page = QWidget()
        trigger_effect_layout = QFormLayout()
        trigger_effect_layout.setContentsMargins(14, 14, 14, 14)
        trigger_effect_layout.setHorizontalSpacing(14)
        trigger_effect_layout.setVerticalSpacing(12)
        self.trigger_effect_editor_page.setLayout(
            trigger_effect_layout
        )

        self.edit_trigger_effect_type_label = QLabel()
        trigger_effect_layout.addRow(
            "Effect:",
            self.edit_trigger_effect_type_label,
        )

        self.edit_trigger_effect_target = QComboBox()
        self.edit_trigger_effect_target.setEditable(True)
        self.edit_trigger_effect_target.setInsertPolicy(
            QComboBox.NoInsert
        )
        trigger_effect_layout.addRow(
            "Target Trigger:",
            self.edit_trigger_effect_target,
        )

        self.trigger_effect_apply_button = QPushButton(
            "Apply Changes"
        )
        self.trigger_effect_cancel_button = QPushButton("Cancel")
        trigger_effect_button_row = QHBoxLayout()
        trigger_effect_button_row.addWidget(
            self.trigger_effect_apply_button
        )
        trigger_effect_button_row.addWidget(
            self.trigger_effect_cancel_button
        )
        trigger_effect_layout.addRow(
            "",
            trigger_effect_button_row,
        )
        self.logic_editor_stack.addWidget(
            self.trigger_effect_editor_page
        )

        self.research_technology_effect_editor_page = QWidget()
        research_effect_editor_layout = QFormLayout()
        research_effect_editor_layout.setContentsMargins(14, 14, 14, 14)
        research_effect_editor_layout.setHorizontalSpacing(14)
        research_effect_editor_layout.setVerticalSpacing(12)
        self.research_technology_effect_editor_page.setLayout(
            research_effect_editor_layout
        )
        self.edit_research_effect_player = (
            ConditionPickerDialog.create_player_combo()
        )
        self.edit_research_effect_technology = (
            ConditionPickerDialog.create_technology_combo()
        )
        research_effect_editor_layout.addRow(
            "Player:",
            self.edit_research_effect_player,
        )
        research_effect_editor_layout.addRow(
            "Technology:",
            self.edit_research_effect_technology,
        )
        self.research_effect_apply_button = QPushButton(
            "Apply Changes"
        )
        self.research_effect_cancel_button = QPushButton("Cancel")
        research_effect_editor_buttons = QHBoxLayout()
        research_effect_editor_buttons.addWidget(
            self.research_effect_apply_button
        )
        research_effect_editor_buttons.addWidget(
            self.research_effect_cancel_button
        )
        research_effect_editor_layout.addRow(
            "",
            research_effect_editor_buttons,
        )
        self.logic_editor_stack.addWidget(
            self.research_technology_effect_editor_page
        )
        self.change_ownership_effect_editor_page = QWidget()
        ownership_edit_layout = QFormLayout()
        self.change_ownership_effect_editor_page.setLayout(ownership_edit_layout)
        self.edit_change_ownership_source_player = ConditionPickerDialog.create_player_combo()
        self.edit_change_ownership_target_player = ConditionPickerDialog.create_player_combo()
        self.edit_change_ownership_object_ids = QLineEdit()
        ownership_edit_layout.addRow("Source Player:", self.edit_change_ownership_source_player)
        ownership_edit_layout.addRow("Target Player:", self.edit_change_ownership_target_player)
        ownership_edit_layout.addRow("Object instance IDs:", self.edit_change_ownership_object_ids)
        self.change_ownership_apply_button = QPushButton("Apply Changes")
        self.change_ownership_cancel_button = QPushButton("Cancel")
        ownership_buttons = QHBoxLayout()
        ownership_buttons.addWidget(self.change_ownership_apply_button)
        ownership_buttons.addWidget(self.change_ownership_cancel_button)
        ownership_edit_layout.addRow("", ownership_buttons)
        self.logic_editor_stack.addWidget(self.change_ownership_effect_editor_page)

        self.tribute_effect_editor_page = QWidget()
        tribute_edit_layout = QFormLayout()
        self.tribute_effect_editor_page.setLayout(tribute_edit_layout)
        self.edit_tribute_source_player = ConditionPickerDialog.create_player_combo()
        self.edit_tribute_target_player = ConditionPickerDialog.create_player_combo()
        self.edit_tribute_resource = (
            ConditionPickerDialog.create_resource_attribute_combo()
        )
        self.edit_tribute_quantity = QSpinBox()
        self.edit_tribute_quantity.setRange(0, 2147483647)
        tribute_edit_layout.addRow("Source Player:", self.edit_tribute_source_player)
        tribute_edit_layout.addRow("Target Player:", self.edit_tribute_target_player)
        tribute_edit_layout.addRow("Resource:", self.edit_tribute_resource)
        tribute_edit_layout.addRow("Amount:", self.edit_tribute_quantity)
        self.tribute_apply_button = QPushButton("Apply Changes")
        self.tribute_cancel_button = QPushButton("Cancel")
        tribute_buttons = QHBoxLayout()
        tribute_buttons.addWidget(self.tribute_apply_button)
        tribute_buttons.addWidget(self.tribute_cancel_button)
        tribute_edit_layout.addRow("", tribute_buttons)
        self.logic_editor_stack.addWidget(self.tribute_effect_editor_page)

        self.current_edit_logic_object = None
        self.current_edit_trigger = None
        self.current_edit_kind = None
        self.current_edit_display_index = None

        self.timer_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.own_objects_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.own_fewer_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.objects_area_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.accumulate_attribute_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.research_technology_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.destroy_object_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.bring_object_to_area_apply_button.clicked.connect(
            self.apply_wave_1_condition_edit
        )
        self.timer_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.own_objects_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.own_fewer_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.objects_area_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.accumulate_attribute_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.research_technology_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.destroy_object_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.bring_object_to_area_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.trigger_effect_apply_button.clicked.connect(
            self.apply_trigger_effect_edit
        )
        self.trigger_effect_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.research_effect_apply_button.clicked.connect(
            self.apply_research_technology_effect_edit
        )
        self.research_effect_cancel_button.clicked.connect(
            self.cancel_logic_edit
        )
        self.change_ownership_apply_button.clicked.connect(
            self.apply_change_ownership_effect_edit
        )
        self.change_ownership_cancel_button.clicked.connect(self.cancel_logic_edit)
        self.tribute_apply_button.clicked.connect(self.apply_tribute_effect_edit)
        self.tribute_cancel_button.clicked.connect(self.cancel_logic_edit)
        details_and_operations_layout.addWidget(
            self.logic_editor_group,
            stretch=1,
        )

        self.trigger_operations_group = QGroupBox(
            "Trigger Operations"
        )
        trigger_list_layout.addWidget(
            self.trigger_operations_group
        )

        operations_layout = QVBoxLayout()
        operations_layout.setContentsMargins(10, 12, 10, 10)
        operations_layout.setSpacing(8)
        self.trigger_operations_group.setLayout(operations_layout)

        operations_row_one = QHBoxLayout()
        operations_row_one.setSpacing(8)
        operations_row_two = QHBoxLayout()
        operations_row_two.setSpacing(8)
        operations_row_three = QHBoxLayout()
        operations_row_three.setSpacing(8)
        operations_layout.addLayout(operations_row_one)
        operations_layout.addLayout(operations_row_two)
        operations_layout.addLayout(operations_row_three)

        self.panel_new_trigger_button = QPushButton("New Trigger")
        self.panel_copy_trigger_button = QPushButton("Copy Trigger")
        self.panel_copy_tree_button = QPushButton("Copy Trigger Tree")
        self.panel_delete_trigger_button = QPushButton("Delete Trigger")

        self.panel_copy_trigger_button.setToolTip(
            "Copy the selected trigger"
        )

        operations_row_one.addWidget(self.panel_new_trigger_button)
        operations_row_one.addWidget(self.panel_move_trigger_up_button)
        operations_row_two.addWidget(self.panel_copy_trigger_button)
        operations_row_two.addWidget(self.panel_move_trigger_down_button)
        operations_row_three.addWidget(self.panel_copy_tree_button)
        operations_row_three.addWidget(self.panel_delete_trigger_button)

        workspace_buttons = (
            self.panel_new_trigger_button,
            self.panel_copy_trigger_button,
            self.panel_copy_tree_button,
            self.panel_delete_trigger_button,
            self.panel_move_trigger_up_button,
            self.panel_move_trigger_down_button,
            self.panel_add_condition_button,
            self.panel_add_effect_button,
            self.timer_apply_button,
            self.timer_cancel_button,
            self.own_objects_apply_button,
            self.own_objects_cancel_button,
            self.own_fewer_apply_button,
            self.own_fewer_cancel_button,
            self.objects_area_apply_button,
            self.objects_area_cancel_button,
            self.accumulate_attribute_apply_button,
            self.accumulate_attribute_cancel_button,
            self.research_technology_apply_button,
            self.research_technology_cancel_button,
            self.difficulty_level_apply_button,
            self.difficulty_level_cancel_button,
            self.diplomacy_state_apply_button,
            self.diplomacy_state_cancel_button,
            self.display_timer_triggered_apply_button,
            self.display_timer_triggered_cancel_button,
            self.destroy_object_apply_button,
            self.destroy_object_cancel_button,
            self.hero_power_cast_apply_button,
            self.hero_power_cast_cancel_button,
            self.local_tech_apply_button,
            self.local_tech_cancel_button,
            self.bring_object_to_area_apply_button,
            self.bring_object_to_area_cancel_button,
            self.bring_object_to_object_apply_button,
            self.bring_object_to_object_cancel_button,
            self.building_is_trading_apply_button,
            self.building_is_trading_cancel_button,
            self.capture_object_apply_button,
            self.capture_object_cancel_button,
            self.chance_apply_button,
            self.chance_cancel_button,
            self.compare_variables_apply_button,
            self.compare_variables_cancel_button,
            self.trigger_effect_apply_button,
            self.trigger_effect_cancel_button,
            self.research_effect_apply_button,
            self.research_effect_cancel_button,
        )
        for button in workspace_buttons:
            button.setMinimumHeight(34)
            button.setSizePolicy(
                button.sizePolicy().horizontalPolicy(),
                button.sizePolicy().verticalPolicy(),
            )

        self.search_box.textChanged.connect(self.filter_triggers)
        self.trigger_list.currentRowChanged.connect(
            self.show_trigger_details
        )
        self.trigger_list.drop_detected.connect(
            self.log_trigger_drop
        )
        self.trigger_logic_list.currentItemChanged.connect(
            self.show_logic_item_summary
        )
        self.trigger_logic_list.itemDoubleClicked.connect(
            self.edit_logic_item
        )
        self.trigger_logic_list.customContextMenuRequested.connect(
            self.show_logic_context_menu
        )
        self.panel_delete_logic_button.clicked.connect(
            self.delete_selected_logic_item
        )
        self.panel_move_logic_up_button.clicked.connect(
            self.move_selected_condition_up
        )
        self.panel_move_logic_down_button.clicked.connect(
            self.move_selected_condition_down
        )

        self.panel_new_trigger_button.clicked.connect(
            self.create_new_trigger
        )
        self.trigger_list.customContextMenuRequested.connect(
            self.show_trigger_context_menu
        )
        self.panel_delete_trigger_button.clicked.connect(
            self.delete_trigger
        )
        self.panel_move_trigger_up_button.clicked.connect(
            self.move_trigger_up
        )
        self.panel_move_trigger_down_button.clicked.connect(
            self.move_trigger_down
        )
        self.panel_copy_tree_button.clicked.connect(
            self.copy_trigger_tree
        )
        self.panel_copy_trigger_button.clicked.connect(
            self.aokts_copy_trigger
        )
        self.panel_add_condition_button.clicked.connect(
            self.add_condition
        )
        self.panel_add_effect_button.clicked.connect(
            self.add_effect
        )

    # AOKTS_MESSAGES_WORKSPACE_V1
    MESSAGE_FIELDS = (
        ("Scenario Instructions", "instructions", "instructions_string_table_id"),
        ("Hints", "hints", "hints_string_table_id"),
        ("Victory", "victory", "victory_string_table_id"),
        ("Loss", "loss", "loss_string_table_id"),
        ("History", "history", "history_string_table_id"),
        ("Scout", "scouts", "scouts_string_table_id"),
    )

    @staticmethod
    def scenario_message_to_editor(value):
        return (value or "").replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def editor_message_to_scenario(value):
        normalised = value.replace("\r\n", "\n").replace("\r", "\n")
        return normalised.replace("\n", "\r")

    def create_messages_tab(self):
        self.messages_tab = QWidget()
        self.tabs.addTab(self.messages_tab, "Messages")
        layout = QVBoxLayout(self.messages_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        heading = QLabel("Scenario Messages")
        heading_font = heading.font()
        heading_font.setPointSize(heading_font.pointSize() + 2)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        layout.addWidget(heading)

        help_label = QLabel(
            "Edit the scenario instructions, hints, victory, loss, history "
            "and scout messages. String Table IDs are preserved."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        selector = QHBoxLayout()
        selector.addWidget(QLabel("Message:"))
        self.message_type_combo = QComboBox()
        for label, field_name, string_table_field in self.MESSAGE_FIELDS:
            self.message_type_combo.addItem(label, (field_name, string_table_field))
        selector.addWidget(self.message_type_combo, 1)
        selector.addWidget(QLabel("String Table ID:"))
        self.message_string_table_id = QLineEdit()
        self.message_string_table_id.setReadOnly(True)
        self.message_string_table_id.setMaximumWidth(180)
        selector.addWidget(self.message_string_table_id)
        layout.addLayout(selector)

        self.scenario_message_editor = QPlainTextEdit()
        self.scenario_message_editor.setPlaceholderText(
            "Open a scenario to edit its messages."
        )
        layout.addWidget(self.scenario_message_editor, 1)

        buttons = QHBoxLayout()
        self.centre_message_button = QPushButton("Centre Text")
        self.centre_message_button.setToolTip(
            "Centre the current line, or every selected non-empty line, "
            "for the AoE2 Game Settings message panel."
        )
        buttons.addWidget(self.centre_message_button)
        buttons.addStretch(1)
        live_save_label = QLabel(
            "Message text is saved with the scenario automatically."
        )
        live_save_label.setStyleSheet("color: #666;")
        buttons.addWidget(live_save_label)
        layout.addLayout(buttons)

        self._loading_scenario_message = False
        self.message_type_combo.currentIndexChanged.connect(
            self.load_selected_scenario_message
        )
        self.centre_message_button.clicked.connect(
            self.centre_selected_message_text
        )
        self.scenario_message_editor.textChanged.connect(
            self.sync_scenario_message_from_editor
        )
        self.set_messages_workspace_enabled(False)

    def set_messages_workspace_enabled(self, enabled):
        self.message_type_combo.setEnabled(enabled)
        self.scenario_message_editor.setEnabled(enabled)
        self.centre_message_button.setEnabled(enabled)
        if not enabled:
            self._loading_scenario_message = True
            try:
                self.scenario_message_editor.clear()
                self.message_string_table_id.clear()
            finally:
                self._loading_scenario_message = False

    def load_selected_scenario_message(self):
        scenario = self.scenario_service.scenario
        if scenario is None:
            self.set_messages_workspace_enabled(False)
            return
        data = self.message_type_combo.currentData()
        if not data:
            return
        field_name, string_table_field = data
        manager = scenario.message_manager
        self.set_messages_workspace_enabled(True)
        self._loading_scenario_message = True
        try:
            self.scenario_message_editor.setPlainText(
                self.scenario_message_to_editor(
                    getattr(manager, field_name, "")
                )
            )
            self.message_string_table_id.setText(
                str(getattr(manager, string_table_field, ""))
            )
        finally:
            self._loading_scenario_message = False

    def sync_scenario_message_from_editor(self):
        if self._loading_scenario_message:
            return
        scenario = self.scenario_service.scenario
        if scenario is None:
            return
        data = self.message_type_combo.currentData()
        if not data:
            return
        field_name, _string_table_field = data
        manager = scenario.message_manager
        new_value = self.editor_message_to_scenario(
            self.scenario_message_editor.toPlainText()
        )
        if getattr(manager, field_name, "") == new_value:
            return
        setattr(manager, field_name, new_value)
        self.scenario_service.mark_modified()
        self.update_status()

    # AOKTS_MESSAGES_CENTRE_TEXT_V6
    # AOKTS_MESSAGES_LIVE_EDIT_V1
    # Empirically calibrated against the AoE2 DE Game Settings parchment.
    # The renderer wrapped an unpadded digit ruler at about 61 digit widths.
    # Scroll centre and wrap safety are intentionally separate constraints.
    AOE2_MESSAGE_LINE_UNITS = 61.0
    AOE2_MESSAGE_SAFE_UNITS = 58.0
    AOE2_MESSAGE_SCROLL_CENTRE_UNITS = 21.0
    AOE2_MESSAGE_SPACE_UNITS = 0.40

    @staticmethod
    def aoe2_message_character_width(character):
        if character == " ":
            return MainWindow.AOE2_MESSAGE_SPACE_UNITS
        if character in "ilI|!.,:;'`":
            return 0.44
        if character in "MW@%&":
            return 1.35
        if character in "mw":
            return 1.18
        if character in "JLT1()[]{}ftjr":
            return 0.72
        if character in "=+-_":
            return 0.76
        if character.isdigit():
            return 0.86
        if character.isupper():
            return 1.00
        if character.islower():
            return 0.81
        return 0.90

    @classmethod
    def aoe2_message_text_width(cls, text):
        return sum(cls.aoe2_message_character_width(ch) for ch in text)

    @classmethod
    def centre_aoe2_message_line_details(cls, line):
        content = line.lstrip(" ")
        if not content:
            return line, False, False

        text_width = cls.aoe2_message_text_width(content)
        if text_width >= cls.AOE2_MESSAGE_SAFE_UNITS:
            return content, True, False

        # Stage 1: target the fixed horizontal centre of the parchment.
        desired_left = max(
            0.0,
            cls.AOE2_MESSAGE_SCROLL_CENTRE_UNITS - (text_width / 2.0),
        )

        # Stage 2: cap only if that placement would approach AoE2's wrap edge.
        max_safe_left = max(0.0, cls.AOE2_MESSAGE_SAFE_UNITS - text_width)
        actual_left = min(desired_left, max_safe_left)
        spaces = max(0, round(actual_left / cls.AOE2_MESSAGE_SPACE_UNITS))

        # In-game calibration: mixed/lowercase headings render slightly left
        # of uppercase-only headings at the same estimated midpoint. Add one
        # AoE2 leading space while preserving the calibrated global centre.
        has_lowercase = any(character.islower() for character in content)
        has_digit = any(character.isdigit() for character in content)
        if has_lowercase:
            spaces += 1
        if has_lowercase and has_digit:
            spaces += 1

        # Rounding may add a fraction of a unit; trim until safely inside.
        while spaces > 0 and (
            spaces * cls.AOE2_MESSAGE_SPACE_UNITS + text_width
            > cls.AOE2_MESSAGE_SAFE_UNITS
        ):
            spaces -= 1

        centred = (" " * spaces) + content
        was_capped = actual_left + 1e-9 < desired_left
        return centred, False, was_capped

    @classmethod
    def centre_aoe2_message_line(cls, line):
        centred, _too_wide, _was_capped = (
            cls.centre_aoe2_message_line_details(line)
        )
        return centred

    def centre_selected_message_text(self):
        editor = self.scenario_message_editor
        cursor = editor.textCursor()
        text = editor.toPlainText()
        lines = text.split("\n")
        selection_start = cursor.selectionStart()
        selection_end = cursor.selectionEnd()
        start_line = text.count("\n", 0, selection_start)
        if cursor.hasSelection():
            adjusted_end = max(selection_start, selection_end - 1)
            end_line = text.count("\n", 0, adjusted_end)
        else:
            end_line = start_line
        if not lines or start_line >= len(lines):
            return
        end_line = min(end_line, len(lines) - 1)
        changed = False
        too_wide_count = 0
        capped_count = 0
        for index in range(start_line, end_line + 1):
            centred, too_wide, was_capped = (
                self.centre_aoe2_message_line_details(lines[index])
            )
            too_wide_count += int(too_wide)
            capped_count += int(was_capped)
            if centred != lines[index]:
                lines[index] = centred
                changed = True
        if not changed:
            self.statusBar().showMessage("Selected text is already centred.", 3000)
            return
        editor.setPlainText("\n".join(lines))
        new_cursor = editor.textCursor()
        line_start = sum(len(line) + 1 for line in lines[:start_line])
        if start_line == end_line:
            new_cursor.setPosition(line_start + len(lines[start_line]))
        else:
            line_end = sum(len(line) + 1 for line in lines[:end_line]) + len(lines[end_line])
            new_cursor.setPosition(line_start)
            new_cursor.setPosition(line_end, new_cursor.KeepAnchor)
        editor.setTextCursor(new_cursor)
        editor.setFocus()
        if too_wide_count:
            message = (
                f"{too_wide_count} selected line(s) are too wide to centre "
                "safely and were left unpadded."
            )
        elif capped_count:
            message = (
                "Centred selected text with wrap-safe padding. "
                "The centred text will be included when the scenario is saved."
            )
        else:
            message = (
                "Centred selected message text. "
                "The centred text will be included when the scenario is saved."
            )
        self.statusBar().showMessage(message, 7000)

    def refresh_messages_workspace(self):
        self.load_selected_scenario_message()


    # AOKTS_PLAYERS_TAB_V1
    PLAYER_STARTING_AGES = (
        ("Dark Age", StartingAge.DARK_AGE),
        ("Feudal Age", StartingAge.FEUDAL_AGE),
        ("Castle Age", StartingAge.CASTLE_AGE),
        ("Imperial Age", StartingAge.IMPERIAL_AGE),
        ("Post-Imperial Age", StartingAge.POST_IMPERIAL_AGE),
    )
    PLAYER_COLORS = (
        ("Blue", ColorId.BLUE),
        ("Red", ColorId.RED),
        ("Green", ColorId.GREEN),
        ("Yellow", ColorId.YELLOW),
        ("Aqua", ColorId.AQUA),
        ("Purple", ColorId.PURPLE),
        ("Gray", ColorId.GRAY),
        ("Orange", ColorId.ORANGE),
    )

    def create_players_tab(self):
        self.players_tab = QWidget()
        self.tabs.addTab(self.players_tab, "Players")
        layout = QVBoxLayout(self.players_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        self._loading_player_fields = False

        selector_group = QGroupBox("Player Selection")
        selector_layout = QFormLayout(selector_group)
        self.player_selector_combo = QComboBox()
        self.player_selector_combo.addItem("Gaia", 0)
        for player_number in range(1, 9):
            self.player_selector_combo.addItem(
                f"Player {player_number}", player_number
            )
        self.number_of_players_combo = QComboBox()
        for count in range(1, 9):
            label = f"{count} Player" if count == 1 else f"{count} Players"
            self.number_of_players_combo.addItem(label, count)
        selector_layout.addRow("Player:", self.player_selector_combo)
        selector_layout.addRow(
            "Number of Players:", self.number_of_players_combo
        )
        layout.addWidget(selector_group)

        general_group = QGroupBox("General")
        general_layout = QFormLayout(general_group)
        self.player_starting_age_combo = QComboBox()
        for label, value in self.PLAYER_STARTING_AGES:
            self.player_starting_age_combo.addItem(label, value)
        self.player_color_combo = QComboBox()
        for label, value in self.PLAYER_COLORS:
            self.player_color_combo.addItem(label, value)
        self.player_civilization_combo = QComboBox()
        self.player_architecture_combo = QComboBox()
        general_layout.addRow("Starting Age:", self.player_starting_age_combo)
        general_layout.addRow("Color:", self.player_color_combo)
        general_layout.addRow(
            "Civilization:", self.player_civilization_combo
        )
        general_layout.addRow(
            "Architecture:", self.player_architecture_combo
        )
        self.player_lock_civ_check = QCheckBox("Lock Civ")
        lock_row = QHBoxLayout()
        lock_row.addWidget(self.player_lock_civ_check)
        lock_row.addStretch(1)
        general_layout.addRow("", lock_row)
        layout.addWidget(general_group)

        resources_group = QGroupBox("Starting Resources")
        resources_layout = QFormLayout(resources_group)
        self.player_food_spin = QSpinBox()
        self.player_wood_spin = QSpinBox()
        self.player_stone_spin = QSpinBox()
        self.player_gold_spin = QSpinBox()
        for control in (
            self.player_food_spin,
            self.player_wood_spin,
            self.player_stone_spin,
            self.player_gold_spin,
        ):
            control.setRange(0, 2147483647)
        resources_layout.addRow("Food:", self.player_food_spin)
        resources_layout.addRow("Wood:", self.player_wood_spin)
        resources_layout.addRow("Stone:", self.player_stone_spin)
        resources_layout.addRow("Gold:", self.player_gold_spin)
        layout.addWidget(resources_group)

        details_group = QGroupBox("Player Properties")
        details_layout = QFormLayout(details_group)
        self.player_population_cap_spin = QSpinBox()
        self.player_population_cap_spin.setRange(0, 500)
        self.player_base_priority_spin = QSpinBox()
        self.player_base_priority_spin.setRange(-2147483648, 2147483647)
        self.player_tribe_name_edit = QLineEdit()
        details_layout.addRow(
            "Population Limit:", self.player_population_cap_spin
        )
        details_layout.addRow(
            "Base Priority:", self.player_base_priority_spin
        )
        details_layout.addRow("Tribe Name:", self.player_tribe_name_edit)
        layout.addWidget(details_group)
        layout.addStretch(1)

        self.player_selector_combo.currentIndexChanged.connect(
            self.load_selected_player
        )
        self.number_of_players_combo.currentIndexChanged.connect(
            self.update_number_of_players
        )
        self.player_starting_age_combo.currentIndexChanged.connect(
            self.update_selected_player
        )
        self.player_color_combo.currentIndexChanged.connect(
            self.update_selected_player
        )
        self.player_civilization_combo.currentIndexChanged.connect(
            self.update_selected_player
        )
        self.player_architecture_combo.currentIndexChanged.connect(
            self.update_selected_player
        )
        for control in (
            self.player_food_spin,
            self.player_wood_spin,
            self.player_stone_spin,
            self.player_gold_spin,
            self.player_population_cap_spin,
            self.player_base_priority_spin,
        ):
            control.valueChanged.connect(self.update_selected_player)
        self.player_lock_civ_check.stateChanged.connect(
            self.update_selected_player
        )
        self.player_tribe_name_edit.editingFinished.connect(
            self.update_selected_player
        )
        self.players_tab.setEnabled(False)

    def selected_player_object(self):
        scenario = self.scenario_service.scenario
        if scenario is None:
            return None
        player_number = self.player_selector_combo.currentData()
        players = getattr(scenario.player_manager, "players", None)
        if isinstance(players, dict):
            return players.get(player_number)
        private_players = getattr(scenario.player_manager, "_players", None)
        if isinstance(private_players, dict):
            return private_players.get(player_number)
        if isinstance(players, (list, tuple)):
            if 0 <= player_number < len(players):
                return players[player_number]
        return None

    def populate_player_civilization_combos(self, player):
        civilization_values = sorted(
            (
                civilization
                for civilization in Civilization
                if civilization is not Civilization.GAIA
            ),
            key=lambda civilization: (
                civilization.name.replace("_", " ").casefold()
            ),
        )
        self.player_civilization_combo.clear()
        self.player_architecture_combo.clear()
        for civilization in civilization_values:
            name = civilization.name.replace("_", " ").title()
            self.player_civilization_combo.addItem(name, civilization)
            self.player_architecture_combo.addItem(name, civilization)

    def refresh_players_tab(self):
        scenario = self.scenario_service.scenario
        self.players_tab.setEnabled(scenario is not None)
        if scenario is None:
            return
        self._loading_player_fields = True
        try:
            active_players = scenario.player_manager.active_players
            self.set_combo_data(
                self.number_of_players_combo, active_players
            )
            player = self.selected_player_object()
            if player is not None:
                self.populate_player_civilization_combos(player)
        finally:
            self._loading_player_fields = False
        self.update_available_player_choices()
        self.load_selected_player()

    def load_selected_player(self):
        if self._loading_player_fields:
            return
        player = self.selected_player_object()
        if player is None:
            return
        self._loading_player_fields = True
        try:
            self.populate_player_civilization_combos(player)
            self.set_combo_data(
                self.player_starting_age_combo, player.starting_age
            )
            self.set_combo_data(self.player_color_combo, player.color)
            self.set_combo_data(
                self.player_civilization_combo, player.civilization
            )
            self.set_combo_data(
                self.player_architecture_combo, player.architecture_set
            )
            self.player_food_spin.setValue(int(player.food or 0))
            self.player_wood_spin.setValue(int(player.wood or 0))
            self.player_stone_spin.setValue(int(player.stone or 0))
            self.player_gold_spin.setValue(int(player.gold or 0))
            self.player_population_cap_spin.setValue(
                int(player.population_cap or 0)
            )
            self.player_base_priority_spin.setValue(
                int(player.base_priority or 0)
            )
            self.player_tribe_name_edit.setText(player.tribe_name or "")
            self.player_lock_civ_check.setChecked(bool(player.lock_civ))
        finally:
            self._loading_player_fields = False

    def update_available_player_choices(self):
        scenario = self.scenario_service.scenario
        if scenario is None:
            return
        active_players = int(scenario.player_manager.active_players)
        current_player = self.player_selector_combo.currentData()
        self._loading_player_fields = True
        try:
            self.player_selector_combo.clear()
            self.player_selector_combo.addItem("Gaia", 0)
            for player_number in range(1, active_players + 1):
                self.player_selector_combo.addItem(
                    f"Player {player_number}", player_number
                )
            if current_player is None or current_player > active_players:
                current_player = active_players
            self.set_combo_data(self.player_selector_combo, current_player)
        finally:
            self._loading_player_fields = False

    def update_number_of_players(self):
        if self._loading_player_fields:
            return
        scenario = self.scenario_service.scenario
        if scenario is None:
            return
        value = self.number_of_players_combo.currentData()
        if scenario.player_manager.active_players == value:
            return
        scenario.player_manager.active_players = value
        self.update_available_player_choices()
        self.load_selected_player()
        self.scenario_service.mark_modified()
        self.update_status()

    def update_selected_player(self, *_args):
        if self._loading_player_fields:
            return
        player = self.selected_player_object()
        if player is None:
            return
        values = {
            "starting_age": self.player_starting_age_combo.currentData(),
            "color": self.player_color_combo.currentData(),
            "civilization": self.player_civilization_combo.currentData(),
            "architecture_set": self.player_architecture_combo.currentData(),
            "food": self.player_food_spin.value(),
            "wood": self.player_wood_spin.value(),
            "stone": self.player_stone_spin.value(),
            "gold": self.player_gold_spin.value(),
            "population_cap": self.player_population_cap_spin.value(),
            "base_priority": self.player_base_priority_spin.value(),
            "tribe_name": self.player_tribe_name_edit.text(),
            "lock_civ": self.player_lock_civ_check.isChecked(),
        }
        if all(getattr(player, name) == value for name, value in values.items()):
            return
        for name, value in values.items():
            setattr(player, name, value)
        self.scenario_service.mark_modified()
        self.update_status()

    def create_units_tab(self):
        self.units_tab = QWidget()
        self.tabs.addTab(self.units_tab, "Units")

        tab_layout = QVBoxLayout()
        self.units_tab.setLayout(tab_layout)

        instructions_label = QLabel(
            "Add a unit to the loaded scenario using exact X and Y coordinates."
        )
        tab_layout.addWidget(instructions_label)

        self.unit_placement_group = QGroupBox(
            "Coordinate-Based Unit Placement"
        )
        tab_layout.addWidget(self.unit_placement_group)

        placement_layout = QFormLayout()
        self.unit_placement_group.setLayout(
            placement_layout
        )

        self.player_combo = QComboBox()
        self.player_combo.addItem("Player 1", PlayerId.ONE)
        self.player_combo.addItem("Player 2", PlayerId.TWO)
        self.player_combo.addItem("Player 3", PlayerId.THREE)
        self.player_combo.addItem("Player 4", PlayerId.FOUR)
        self.player_combo.addItem("Player 5", PlayerId.FIVE)
        self.player_combo.addItem("Player 6", PlayerId.SIX)
        self.player_combo.addItem("Player 7", PlayerId.SEVEN)
        self.player_combo.addItem("Player 8", PlayerId.EIGHT)
        placement_layout.addRow("Player:", self.player_combo)

        self.unit_combo = QComboBox()
        self.unit_combo.setEditable(True)
        self.unit_combo.setInsertPolicy(QComboBox.NoInsert)
        self.populate_unit_combo()

        unit_completer = QCompleter(self.unit_combo.model(), self.unit_combo)
        unit_completer.setCaseSensitivity(Qt.CaseInsensitive)
        unit_completer.setFilterMode(Qt.MatchContains)
        unit_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.unit_combo.setCompleter(unit_completer)

        placement_layout.addRow("Unit:", self.unit_combo)

        self.x_coordinate = QDoubleSpinBox()
        self.x_coordinate.setRange(0.0, 500.0)
        self.x_coordinate.setDecimals(1)
        self.x_coordinate.setSingleStep(0.5)
        self.x_coordinate.setValue(10.0)
        placement_layout.addRow("X coordinate:", self.x_coordinate)

        self.y_coordinate = QDoubleSpinBox()
        self.y_coordinate.setRange(0.0, 500.0)
        self.y_coordinate.setDecimals(1)
        self.y_coordinate.setSingleStep(0.5)
        self.y_coordinate.setValue(10.0)
        placement_layout.addRow("Y coordinate:", self.y_coordinate)

        self.add_unit_button = QPushButton("Add Unit")
        placement_layout.addRow("", self.add_unit_button)

        self.unit_result_label = QLabel("No unit has been added.")
        tab_layout.addWidget(self.unit_result_label)
        tab_layout.addStretch()

        self.add_unit_button.clicked.connect(self.add_unit)

    def populate_unit_combo(self):
        unit_entries = []

        for attribute_name in dir(UnitInfo):
            if attribute_name.startswith("_"):
                continue

            try:
                unit_definition = getattr(UnitInfo, attribute_name)
                unit_id = unit_definition.ID
            except (AttributeError, TypeError):
                continue

            display_name = attribute_name.replace("_", " ").title()
            unit_entries.append((display_name, unit_id))

        unit_entries.sort(key=lambda entry: entry[0].lower())

        self.unit_combo.clear()

        for display_name, unit_id in unit_entries:
            self.unit_combo.addItem(
                f"{display_name} (ID: {unit_id})",
                unit_id,
            )

        militia_index = self.unit_combo.findData(UnitInfo.MILITIA.ID)

        if militia_index >= 0:
            self.unit_combo.setCurrentIndex(militia_index)

    def update_ui_enabled_state(self):
        scenario_loaded = (
            self.scenario_service.scenario is not None
        )

        # Top-level buttons. Open Scenario remains enabled.

        # File menu actions. Open and Exit remain enabled.
        self.save_action.setEnabled(scenario_loaded)
        self.save_as_action.setEnabled(scenario_loaded)
        self.export_triggers_action.setEnabled(scenario_loaded)
        self.set_messages_workspace_enabled(scenario_loaded)

        # Edit menu actions.
        self.update_undo_redo_actions()
        self.new_trigger_action.setEnabled(scenario_loaded)
        self.rename_trigger_action.setEnabled(scenario_loaded)
        self.blank_all_trigger_names_action.setEnabled(scenario_loaded)
        self.delete_trigger_action.setEnabled(scenario_loaded)
        self.move_trigger_up_action.setEnabled(scenario_loaded)
        self.move_trigger_down_action.setEnabled(scenario_loaded)
        self.cut_trigger_action.setEnabled(scenario_loaded)
        self.copy_trigger_action.setEnabled(scenario_loaded)
        self.randomize_trigger_order_action.setEnabled(scenario_loaded)
        self.copy_all_players_action.setEnabled(scenario_loaded)
        self.update_copy_trigger_ui()

        # Trigger workspace.
        self.search_box.setEnabled(scenario_loaded)
        self.triggers_group.setEnabled(scenario_loaded)
        self.trigger_list.setEnabled(scenario_loaded)
        self.trigger_logic_group.setEnabled(scenario_loaded)
        self.logic_editor_group.setEnabled(scenario_loaded)
        self.trigger_details.setEnabled(scenario_loaded)
        self.trigger_operations_group.setEnabled(
            scenario_loaded
        )

        # Players workspace.
        self.players_tab.setEnabled(scenario_loaded)

        # Coordinate-based unit placement workspace.
        self.unit_placement_group.setEnabled(
            scenario_loaded
        )
        self.unit_result_label.setEnabled(
            scenario_loaded
        )
        self.tabs.setTabEnabled(1, scenario_loaded)
        self.tabs.setTabEnabled(2, scenario_loaded)

    def update_undo_redo_actions(self):
        if not hasattr(self, "undo_action"):
            return

        can_undo = self.undo_manager.can_undo()
        can_redo = self.undo_manager.can_redo()

        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)

        undo_text = self.undo_manager.undo_text()
        redo_text = self.undo_manager.redo_text()

        self.undo_action.setText(
            f"Undo {undo_text}" if undo_text else "Undo"
        )
        self.redo_action.setText(
            f"Redo {redo_text}" if redo_text else "Redo"
        )

    def select_trigger_object(self, selected_trigger):
        if selected_trigger is None:
            return False

        scenario = self.scenario_service.scenario
        if scenario is None:
            return False

        for row, trigger in enumerate(
            scenario.trigger_manager.triggers
        ):
            if trigger is selected_trigger:
                if row < self.trigger_list.count():
                    self.trigger_list.setCurrentRow(row)
                    self.trigger_list.scrollToItem(
                        self.trigger_list.currentItem(),
                        QAbstractItemView.PositionAtCenter,
                    )
                    return True
                break

        return self.select_trigger_by_id(
            selected_trigger.trigger_id
        )

    def finish_history_action(self, command, action_label):
        if command is None:
            self.update_undo_redo_actions()
            return

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        selected_trigger = getattr(command, "selected_trigger", None)
        if selected_trigger is not None:
            self.select_trigger_object(selected_trigger)
        if isinstance(command, EditScenarioMessageCommand):
            self.refresh_messages_workspace()

        selected_logic_object = getattr(
            command,
            "selected_logic_object",
            None,
        )
        if selected_logic_object is not None:
            self.select_logic_object(selected_logic_object)

        self.update_undo_redo_actions()

        LoggerService.log_message(
            f"{action_label}: {command.description}",
            context="undo_redo",
        )
        self.statusBar().showMessage(
            f"{action_label}: {command.description}",
            5000,
        )

    def undo_last_action(self):
        try:
            command = self.undo_manager.undo()
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="undo",
            )
            QMessageBox.critical(
                self,
                "Undo Failed",
                "The last action could not be undone. See the error log.",
            )
            return

        self.finish_history_action(command, "Undid")

    def redo_last_action(self):
        try:
            command = self.undo_manager.redo()
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="redo",
            )
            QMessageBox.critical(
                self,
                "Redo Failed",
                "The last action could not be redone. See the error log.",
            )
            return

        self.finish_history_action(command, "Redid")

    def clear_minimap(self, message=None):
        self.minimap_pixmap = None
        self.minimap_label.clear()
        self.minimap_label.setText(
            message or "Open a scenario to display its minimap."
        )
        self.minimap_status_label.setText(
            "Terrain preview not loaded"
        )

    def update_minimap(self):
        scenario = self.scenario_service.scenario

        if scenario is None:
            self.clear_minimap()
            return

        try:
            image = MinimapRenderer.render(scenario)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="update_minimap",
            )
            self.clear_minimap(
                "The minimap could not be rendered.\n"
                "See the error log for details."
            )
            return

        self.minimap_pixmap = QPixmap.fromImage(image)
        self.refresh_minimap_display()
        self.minimap_status_label.setText(
            f"Map size: {image.width()} x {image.height()} tiles"
        )

        LoggerService.log_message(
            (
                "Rendered minimap: "
                f"{image.width()} x {image.height()} tiles"
            ),
            context="update_minimap",
        )

    def refresh_minimap_display(self):
        if not getattr(self, "minimap_pixmap", None):
            return

        scaled_pixmap = self.minimap_pixmap.scaled(
            self.minimap_label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
        )
        self.minimap_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_minimap_display()

    def update_location_display(self):
        current_file = self.scenario_service.current_file

        if not current_file:
            self.location_label.setText(
                "Location: Not yet saved"
            )
            self.location_label.setToolTip(
                "This scenario has not yet been saved to a file."
            )
            return

        full_path = str(current_file)
        display_path = full_path

        if len(display_path) > 120:
            display_path = "..." + display_path[-117:]

        self.location_label.setText(
            f"Location: {display_path}"
        )
        self.location_label.setToolTip(full_path)

    def update_status(self):
        if self.scenario_service.scenario is None:
            self.status_label.setText("No scenario loaded")
            return

        trigger_count = len(self.trigger_names)
        unit_count = self.scenario_service.get_unit_count()

        status_text = (
            f"Loaded: {trigger_count} triggers"
            f"   |   {unit_count} units"
        )

        if self.scenario_service.is_modified():
            status_text += "   * UNSAVED CHANGES"

        self.status_label.setText(status_text)

    def refresh_trigger_ui(self):
        self.refresh_trigger_list()
        self.update_status()
        self.update_ui_enabled_state()

    def refresh_scenario_information(self, select_name=None):
        self.trigger_names = self.scenario_service.get_trigger_names()
        self.refresh_trigger_list()

        if select_name:
            self.select_trigger_by_name(select_name)

        self.update_status()
        self.update_minimap()
        self.refresh_messages_workspace()
        self.refresh_players_tab()

    def new_scenario(self):
        if self.scenario_service.is_modified():
            result = QMessageBox.question(
                self,
                "Unsaved Changes",
                (
                    "The current scenario has unsaved changes.\n\n"
                    "Do you want to save before creating a new scenario?"
                ),
                (
                    QMessageBox.Yes
                    | QMessageBox.No
                    | QMessageBox.Cancel
                ),
                QMessageBox.Yes,
            )

            if result == QMessageBox.Yes:
                if not self.save_scenario():
                    return
            elif result == QMessageBox.Cancel:
                return

        dialog = NewScenarioDialog(self)

        if dialog.exec() != QDialog.Accepted:
            return

        scenario_name = dialog.scenario_name()
        scenario_path = dialog.scenario_file_path()

        if scenario_path.exists():
            overwrite_result = QMessageBox.question(
                self,
                "Scenario Already Exists",
                (
                    "A scenario with this name already exists at:\n\n"
                    f"{scenario_path}\n\n"
                    "Do you want to overwrite it?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if overwrite_result != QMessageBox.Yes:
                return

        try:
            scenario = AoE2DEScenario.from_default()
            self.scenario_service.scenario = scenario
            self.scenario_service.current_file = None
            self.scenario_service.modified = False

            saved = self.scenario_service.save_scenario_as(
                str(scenario_path)
            )

            if not saved:
                raise RuntimeError(
                    "The scenario service did not report a successful save."
                )

        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=str(scenario_path),
                context="new_scenario",
            )
            QMessageBox.critical(
                self,
                "Scenario Creation Failed",
                (
                    "The scenario could not be created.\n\n"
                    f"{error}"
                ),
            )
            self.update_ui_enabled_state()
            self.update_location_display()
            return

        self.undo_manager.clear()
        self.update_undo_redo_actions()
        self.copied_trigger_id = None
        self.copied_trigger_name = None
        self.copied_trigger_object = None
        self.search_box.clear()
        self.trigger_details.setText(
            ""
        )
        self.unit_result_label.setText(
            "No unit has been added."
        )

        self.refresh_scenario_information()
        self.update_ui_enabled_state()
        self.update_location_display()
        self.setWindowTitle(
            f"AoE2 Trigger Studio+ - {scenario_name}"
        )
        self.statusBar().showMessage(
            f"Created scenario: {scenario_path}",
            7000,
        )
        LoggerService.log_message(
            f"Created scenario: {scenario_path}",
            context="new_scenario",
        )

    def restart_application(self):
        LoggerService.log_message(
            "Application restart requested.",
            context="restart_application",
        )

        executable = sys.executable
        working_directory = str(
            Path(sys.argv[0]).resolve().parent
        )

        if getattr(sys, "frozen", False):
            arguments = list(sys.argv[1:])
        else:
            script_path = str(
                Path(sys.argv[0]).resolve()
            )
            arguments = [script_path, *sys.argv[1:]]

        try:
            started = QProcess.startDetached(
                executable,
                arguments,
                working_directory,
            )

            if not started:
                raise RuntimeError(
                    "The replacement application process did not start."
                )

            QApplication.quit()

        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="restart_application",
            )
            QMessageBox.critical(
                self,
                "Restart Failed",
                (
                    "Trigger Studio+ could not restart automatically.\n\n"
                    "Please close and reopen the application manually.\n\n"
                    "See the error log for more information."
                ),
            )

    def open_scenario(self):
        if self.scenario_service.is_modified():
            result = QMessageBox.question(
                self,
                "Unsaved Changes",
                (
                    "The current scenario has unsaved changes.\n\n"
                    "Do you want to save before opening another scenario?"
                ),
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )

            if result == QMessageBox.Yes:
                if not self.save_scenario():
                    return
            elif result == QMessageBox.Cancel:
                return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Scenario",
            "",
            "AoE2 Scenarios (*.aoe2scenario)",
        )

        if not file_path:
            return

        scenario_file = Path(file_path)

        if not scenario_file.exists():
            LoggerService.log_message(
                f"Open failed - file not found: {file_path}",
                context="open_scenario",
            )

            QMessageBox.warning(
                self,
                "Open Scenario",
                (
                    f"{file_path}\n\n"
                    "The file does not exist. "
                    "Check the path and try again."
                ),
            )
            return

        if not scenario_file.is_file():
            LoggerService.log_message(
                f"Open failed - path is not a file: {file_path}",
                context="open_scenario",
            )

            QMessageBox.warning(
                self,
                "Open Scenario",
                (
                    f"{file_path}\n\n"
                    "The selected path is not a file."
                ),
            )
            return

        try:
            self.run_busy_operation(
                "Opening Scenario",
                (
                    "Reading and parsing scenario data.\n"
                    "Please wait..."
                ),
                lambda: self.scenario_service.load_scenario(file_path),
            )
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=file_path,
                context="open_scenario",
            )

            error_text = str(error)

            if (
                "execute_on_load" in error_text
                or "cross-version compatibility issue" in error_text
            ):
                compatibility_dialog = QMessageBox(self)
                compatibility_dialog.setIcon(QMessageBox.Critical)
                compatibility_dialog.setWindowTitle(
                    "Known Parser Compatibility Issue"
                )
                compatibility_dialog.setText(
                    "This scenario triggered a known "
                    "AoE2ScenarioParser 0.9.4 cross-version "
                    "compatibility issue."
                )
                compatibility_dialog.setInformativeText(
                    "This can happen after opening scenarios with "
                    "different scenario versions in the same "
                    "Trigger Studio+ session.\n\n"
                    "Restart Trigger Studio+, then open the affected "
                    "scenario first."
                )

                restart_button = compatibility_dialog.addButton(
                    "Restart Application",
                    QMessageBox.AcceptRole,
                )
                compatibility_dialog.addButton(
                    "Keep Current Scenario",
                    QMessageBox.RejectRole,
                )
                compatibility_dialog.setDefaultButton(
                    restart_button
                )
                compatibility_dialog.exec()

                if compatibility_dialog.clickedButton() is restart_button:
                    self.restart_application()
            else:
                QMessageBox.critical(
                    self,
                    "Open Failed",
                    (
                        "The scenario could not be opened.\n\n"
                        "Please see the error log for more information."
                    ),
                )

            self.update_ui_enabled_state()
            return

        self.undo_manager.clear()
        self.update_undo_redo_actions()
        self.copied_trigger_id = None
        self.copied_trigger_name = None
        self.copied_trigger_object = None
        self.search_box.clear()
        self.trigger_details.setText(
            ""
        )
        self.unit_result_label.setText(
            "No unit has been added."
        )

        self.refresh_scenario_information()
        self.update_ui_enabled_state()
        self.update_location_display()

        LoggerService.log_message(
            f"Opened scenario: {file_path}",
            context="open_scenario",
        )

        self.statusBar().showMessage(
            f"Opened scenario: {file_path}",
            5000,
        )

    def save_scenario(self):
        if self.scenario_service.scenario is None:
            LoggerService.log_message(
                "Save failed - no scenario loaded.",
                context="save_scenario",
            )

            QMessageBox.warning(
                self,
                "No Scenario Loaded",
                "Please load a scenario first.",
            )
            return False

        current_file = self.scenario_service.current_file

        if not current_file:
            LoggerService.log_message(
                "Save redirected to Save As because no file is assigned.",
                context="save_scenario",
            )
            return self.save_scenario_as()

        try:
            saved = self.run_busy_operation(
                "Saving Scenario",
                (
                    "Writing scenario data safely.\n"
                    "Please wait..."
                ),
                self.scenario_service.save_scenario,
            )
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=current_file,
                context="save_scenario",
            )

            QMessageBox.critical(
                self,
                "Save Failed",
                (
                    "The scenario could not be saved.\n\n"
                    "Please see the error log for more information."
                ),
            )
            return False

        if not saved:
            LoggerService.log_message(
                f"Save failed - scenario service returned False: {current_file}",
                context="save_scenario",
            )

            QMessageBox.critical(
                self,
                "Save Failed",
                "The scenario could not be saved.",
            )
            return False

        self.update_status()
        self.update_location_display()

        LoggerService.log_message(
            f"Saved scenario: {current_file}",
            context="save_scenario",
        )

        self.statusBar().showMessage(
            f"Scenario saved: {current_file}",
            5000,
        )
        return True

    def save_scenario_as(self):
        if self.scenario_service.scenario is None:
            LoggerService.log_message(
                "Save As failed - no scenario loaded.",
                context="save_scenario_as",
            )

            QMessageBox.warning(
                self,
                "No Scenario Loaded",
                "Please load a scenario first.",
            )
            return False

        suggested_path = self.scenario_service.current_file or ""

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Scenario As",
            suggested_path,
            "AoE2 Scenarios (*.aoe2scenario)",
        )

        if not file_path:
            return False

        if not file_path.lower().endswith(".aoe2scenario"):
            file_path += ".aoe2scenario"

        try:
            saved = self.run_busy_operation(
                "Saving Scenario",
                (
                    "Writing scenario data safely.\n"
                    "Please wait..."
                ),
                lambda: self.scenario_service.save_scenario_as(
                    file_path
                ),
            )
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=file_path,
                context="save_scenario_as",
            )

            QMessageBox.critical(
                self,
                "Save Failed",
                (
                    "The scenario could not be saved.\n\n"
                    "Please see the error log for more information."
                ),
            )
            return False

        if not saved:
            LoggerService.log_message(
                f"Save As failed - scenario service returned False: {file_path}",
                context="save_scenario_as",
            )

            QMessageBox.critical(
                self,
                "Save Failed",
                "The scenario could not be saved.",
            )
            return False

        self.update_status()
        self.update_location_display()

        LoggerService.log_message(
            f"Saved scenario as: {file_path}",
            context="save_scenario_as",
        )

        QMessageBox.information(
            self,
            "Scenario Saved",
            f"Scenario saved successfully:\n\n{file_path}",
        )
        return True

    @staticmethod
    def _friendly_enum_name(value, enum_type, fallback):
        try:
            return enum_type(value).name.replace("_", " ").title()
        except Exception:
            return fallback

    @staticmethod
    def _unit_name_lookup():
        lookup = {}
        for attribute_name in dir(UnitInfo):
            if attribute_name.startswith("_"):
                continue
            try:
                unit = getattr(UnitInfo, attribute_name)
                unit_id = unit.ID
            except (AttributeError, TypeError):
                continue
            lookup.setdefault(
                unit_id,
                attribute_name.replace("_", " ").title(),
            )
        return lookup

    def _condition_export_lines(self, condition, unit_names):
        condition_type = getattr(condition, "condition_type", -1)
        title = self._friendly_enum_name(
            condition_type,
            ConditionId,
            f"Condition Type {condition_type}",
        )
        if condition_type == ConditionId.AI_SIGNAL_MULTIPLAYER.value:
            title = "Multiplayer AI Signal"
        lines = [title]

        ai_signal = getattr(condition, "ai_signal", -1)
        if ai_signal != -1:
            lines.append(f"AI Signal: {ai_signal}")


        if condition_type == ConditionId.DIPLOMACY_STATE.value:
            diplomacy_names = {
                DiplomacyState.ALLY.value: "Ally",
                DiplomacyState.NEUTRAL.value: "Neutral",
                DiplomacyState.ENEMY.value: "Enemy",
            }
            diplomacy_value = getattr(condition, "quantity", None)
            lines.append(
                "Diplomacy State: "
                + diplomacy_names.get(diplomacy_value, str(diplomacy_value))
            )
            source_player = getattr(condition, "source_player", -1)
            target_player = getattr(condition, "target_player", -1)
            source_label = "Gaia" if source_player == 0 else f"Player {source_player}"
            target_label = "Gaia" if target_player == 0 else f"Player {target_player}"
            lines.append(f"Direction: {source_label} -> {target_label}")


        if condition_type == ConditionId.DISPLAY_TIMER_TRIGGERED.value:
            timer_id = getattr(condition, "timer_id", -1)
            if timer_id != -1:
                lines.append(f"Timer: Timer {timer_id}")

        if condition_type == ConditionId.HERO_POWER_CAST.value:
            source_player = getattr(condition, "source_player", -1)
            if source_player >= 0:
                source_label = "Gaia" if source_player == 0 else f"Player {source_player}"
                lines.append(f"Player: {source_label}")

        if condition_type == ConditionId.LOCAL_TECH_RESEARCHED.value:
            tech_names = {1197: "Defensive Town Center", 1195: "Economic Town Center",
                          1196: "Military Town Center", 1270: "Fortified Outpost",
                          1323: "Defensive Emplacement", 1324: "Offensive Emplacement"}
            player = getattr(condition, "source_player", -1)
            local_technology = getattr(condition, "local_technology", -1)
            lines.append(
                "Local Technology: "
                + tech_names.get(local_technology, f"Local Tech {local_technology}")
            )
            if player >= 0:
                player_label = "Gaia" if player == 0 else f"Player {player}"
                lines.append(f"Player: {player_label}")
            quantity = getattr(condition, "quantity", -1)
            if quantity != -1:
                lines.append(f"Quantity: {quantity}")

        if condition_type == ConditionId.DIFFICULTY_LEVEL.value:
            difficulty_value = getattr(condition, "quantity", None)
            difficulty_names = {
                DifficultyLevel.EASIEST.value: "Easiest",
                DifficultyLevel.STANDARD.value: "Standard",
                DifficultyLevel.MODERATE.value: "Moderate",
                DifficultyLevel.HARD.value: "Hard",
                DifficultyLevel.HARDEST.value: "Hardest",
                DifficultyLevel.EXTREME.value: "Extreme",
            }
            lines.append(
                "Difficulty: "
                + difficulty_names.get(
                    difficulty_value,
                    str(difficulty_value),
                )
            )

        timer = getattr(condition, "timer", -1)
        if timer != -1:
            lines.append(f"Duration: {timer} seconds")

        source_player = getattr(condition, "source_player", -1)
        if source_player != -1:
            lines.append(f"Player: Player {source_player}")

        target_player = getattr(condition, "target_player", -1)
        if target_player != -1 and target_player != source_player:
            lines.append(f"Target Player: Player {target_player}")

        quantity = getattr(condition, "quantity", -1)
        if quantity != -1:
            lines.append(f"Quantity: {quantity}")

        object_list = getattr(condition, "object_list", -1)
        if object_list != -1:
            object_name = unit_names.get(object_list, "Unknown Object")
            lines.append(f"Object: {object_name} (ID: {object_list})")
        unit_object = getattr(condition, "unit_object", -1)
        if unit_object != -1:
            lines.append(f"Object Instance ID: {unit_object}")

        next_object = getattr(condition, "next_object", -1)
        if next_object != -1:
            lines.append(f"Target Object Instance ID: {next_object}")

        coordinates = tuple(
            getattr(condition, field_name, -1)
            for field_name in ("area_x1", "area_y1", "area_x2", "area_y2")
        )
        if all(value != -1 for value in coordinates):
            x1, y1, x2, y2 = coordinates
            lines.append(f"Area: ({x1}, {y1}) to ({x2}, {y2})")

        technology = getattr(condition, "technology", -1)
        if technology != -1:
            lines.append(f"Technology ID: {technology}")

        attribute = getattr(condition, "attribute", -1)
        if attribute != -1:
            lines.append(f"Attribute ID: {attribute}")

        variable = getattr(condition, "variable", -1)
        if variable != -1:
            lines.append(f"Variable ID: {variable}")

        if getattr(condition, "inverted", 0):
            lines.append("Inverted: Yes")

        return lines

    @staticmethod
    def _effect_export_title(effect):
        text = str(effect).strip()
        if text and not text.startswith("<"):
            return text
        effect_type = getattr(effect, "effect_type", -1)
        return f"Effect Type {effect_type}"

    def _effect_export_lines(
        self,
        effect,
        trigger_names_by_id,
        unit_names,
    ):
        lines = [self._effect_export_title(effect)]

        trigger_id = getattr(effect, "trigger_id", -1)
        if trigger_id != -1:
            target_name = trigger_names_by_id.get(
                trigger_id,
                "Unknown Trigger",
            )
            lines.append(f"Target Trigger: [{trigger_id}] {target_name}")

        source_player = getattr(effect, "source_player", -1)
        if source_player != -1:
            lines.append(f"Source Player: Player {source_player}")

        target_player = getattr(effect, "target_player", -1)
        if target_player != -1:
            lines.append(f"Target Player: Player {target_player}")

        object_list = getattr(effect, "object_list", -1)
        if object_list != -1:
            object_name = unit_names.get(object_list, "Unknown Object")
            lines.append(f"Object: {object_name} (ID: {object_list})")

        quantity = getattr(effect, "quantity", -1)
        if quantity != -1:
            lines.append(f"Quantity: {quantity}")

        location_x = getattr(effect, "location_x", -1)
        location_y = getattr(effect, "location_y", -1)
        if location_x != -1 and location_y != -1:
            lines.append(f"Location: ({location_x}, {location_y})")

        message = getattr(effect, "message", "")
        if message:
            lines.append(f"Message: {message}")

        technology = getattr(effect, "technology", -1)
        if technology != -1:
            lines.append(f"Technology ID: {technology}")

        tribute_list = getattr(effect, "tribute_list", -1)
        if tribute_list != -1:
            try:
                tribute_name = (
                    Attribute(tribute_list).name.replace("_", " ").title()
                )
            except (ValueError, TypeError):
                tribute_name = f"Attribute {tribute_list}"
            lines.append(
                f"Tribute Resource: {tribute_name} (ID: {tribute_list})"
            )

        selected_object_ids = getattr(effect, "selected_object_ids", []) or []
        if selected_object_ids:
            lines.append("Object Instance IDs: " + ", ".join(map(str, selected_object_ids)))
        return lines

    def build_trigger_text_export(self):
        scenario = self.scenario_service.scenario
        if scenario is None:
            return ""

        triggers = list(scenario.trigger_manager.triggers)
        current_file = self.scenario_service.current_file
        scenario_name = (
            Path(current_file).stem
            if current_file
            else (getattr(scenario, "name", "") or "Unsaved Scenario")
        )
        unit_names = self._unit_name_lookup()
        trigger_names_by_id = {
            trigger.trigger_id: (trigger.name or "Unnamed Trigger")
            for trigger in triggers
        }

        separator = "=" * 72
        subsection = "-" * 72
        lines = [
            separator,
            f"SCENARIO: {scenario_name}",
            separator,
            "",
            f"Trigger Count: {len(triggers)}",
            "",
        ]

        for position, trigger in enumerate(triggers, start=1):
            trigger_name = (trigger.name or "").strip() or "Unnamed Trigger"
            lines.extend(
                [
                    separator,
                    f"TRIGGER {position}: [{trigger.trigger_id}] {trigger_name}",
                    separator,
                    "",
                    "Enabled: " + (
                        "Yes" if bool(getattr(trigger, "enabled", True)) else "No"
                    ),
                    "Looping: " + (
                        "Yes" if bool(getattr(trigger, "looping", False)) else "No"
                    ),
                    "",
                    f"Conditions ({len(trigger.conditions)})",
                    subsection,
                ]
            )

            if not trigger.conditions:
                lines.append("None")
            else:
                for index, condition in enumerate(trigger.conditions, start=1):
                    condition_lines = self._condition_export_lines(
                        condition,
                        unit_names,
                    )
                    lines.append(f"{index}. {condition_lines[0]}")
                    lines.extend(
                        f"   {line}" for line in condition_lines[1:]
                    )
                    lines.append("")

            lines.extend(
                [
                    "",
                    f"Effects ({len(trigger.effects)})",
                    subsection,
                ]
            )

            if not trigger.effects:
                lines.append("None")
            else:
                for index, effect in enumerate(trigger.effects, start=1):
                    effect_lines = self._effect_export_lines(
                        effect,
                        trigger_names_by_id,
                        unit_names,
                    )
                    lines.append(f"{index}. {effect_lines[0]}")
                    lines.extend(
                        f"   {line}" for line in effect_lines[1:]
                    )
                    lines.append("")

            lines.extend(["", ""])

        return "\n".join(lines).rstrip() + "\n"

    def export_triggers_to_text(self):
        if self.scenario_service.scenario is None:
            QMessageBox.warning(
                self,
                "No Scenario Loaded",
                "Please load a scenario before exporting triggers.",
            )
            return False

        current_file = self.scenario_service.current_file
        scenario_name = Path(current_file).stem if current_file else "scenario"
        suggested_path = (
            str(
                Path(current_file).with_name(
                    f"{scenario_name}_triggers.txt"
                )
            )
            if current_file
            else f"{scenario_name}_triggers.txt"
        )

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Triggers to Text",
            suggested_path,
            "Text Files (*.txt)",
        )
        if not file_path:
            return False
        if not file_path.lower().endswith(".txt"):
            file_path += ".txt"

        try:
            Path(file_path).write_text(
                self.build_trigger_text_export(),
                encoding="utf-8",
            )
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="export_triggers_to_text",
            )
            QMessageBox.critical(
                self,
                "Export Failed",
                f"The trigger text file could not be created.\n\n{error}",
            )
            return False

        LoggerService.log_message(
            f"Exported triggers to text: {file_path}",
            context="export_triggers_to_text",
        )
        self.statusBar().showMessage(
            f"Exported triggers: {file_path}",
            7000,
        )
        QMessageBox.information(
            self,
            "Triggers Exported",
            f"Trigger documentation was exported successfully:\n\n{file_path}",
        )
        return True

    def closeEvent(self, event):
        if not self.scenario_service.is_modified():
            event.accept()
            return

        result = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved changes.\n\nDo you want to save before closing?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )

        if result == QMessageBox.Yes:
            if self.save_scenario():
                event.accept()
            else:
                event.ignore()
        elif result == QMessageBox.No:
            event.accept()
        else:
            event.ignore()

    def add_unit(self):
        scenario = self.scenario_service.scenario

        if scenario is None:
            QMessageBox.warning(
                self,
                "No Scenario Loaded",
                "Please load a scenario before adding a unit.",
            )
            return

        player = self.player_combo.currentData()
        player_name = self.player_combo.currentText()
        unit_id = self.unit_combo.currentData()
        unit_name = self.unit_combo.currentText()

        if unit_id is None:
            QMessageBox.warning(
                self,
                "Invalid Unit Selection",
                "Please select a unit from the dropdown list.",
            )
            return

        x_value = self.x_coordinate.value()
        y_value = self.y_coordinate.value()

        original_count = self.scenario_service.get_unit_count()

        try:
            scenario.unit_manager.add_unit(
                player=player,
                unit_const=unit_id,
                x=x_value,
                y=y_value,
            )
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="add_unit",
            )
            QMessageBox.critical(
                self,
                "Unit Placement Failed",
                f"The unit could not be added.\n\n{error}",
            )
            return

        new_count = self.scenario_service.get_unit_count()

        if new_count != original_count + 1:
            QMessageBox.critical(
                self,
                "Unit Placement Validation Failed",
                (
                    "The unit count did not increase by exactly one.\n\n"
                    "The scenario has not been saved."
                ),
            )
            self.scenario_service.mark_modified()
            self.update_status()
            return

        self.scenario_service.mark_modified()
        self.update_status()

        result_text = (
            f"Added {unit_name} for {player_name} "
            f"at X={x_value:.1f}, Y={y_value:.1f}."
        )
        self.unit_result_label.setText(result_text)

        QMessageBox.information(
            self,
            "Unit Added",
            (
                f"{unit_name} was added successfully.\n\n"
                f"Player: {player_name}\n"
                f"X: {x_value:.1f}\n"
                f"Y: {y_value:.1f}\n\n"
                "Use Save As to write the changes to a scenario file."
            ),
        )

    def create_new_trigger(self):
        scenario = self.scenario_service.scenario

        if scenario is None:
            QMessageBox.warning(
                self,
                "No Scenario Loaded",
                "Please load a scenario first.",
            )
            return

        trigger_name, ok = QInputDialog.getText(
            self,
            "New Trigger",
            "Trigger Name:",
            text="New Trigger",
        )

        if not ok:
            return

        trigger_name = trigger_name.strip()

        if not trigger_name:
            QMessageBox.warning(
                self,
                "Invalid Trigger Name",
                "The trigger name cannot be empty.",
            )
            return

        if not self.confirm_trigger_name(trigger_name):
            return

        original_count = len(
            scenario.trigger_manager.triggers
        )

        try:
            scenario.trigger_manager.add_trigger(trigger_name)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="create_new_trigger",
            )
            QMessageBox.critical(
                self,
                "New Trigger Failed",
                f"The trigger could not be created.\n\n{error}",
            )
            return

        new_count = len(
            scenario.trigger_manager.triggers
        )

        if new_count != original_count + 1:
            QMessageBox.critical(
                self,
                "New Trigger Validation Failed",
                (
                    "The trigger count did not increase by exactly one.\n\n"
                    "Review the scenario before saving."
                ),
            )
            self.scenario_service.mark_modified()
            self.refresh_scenario_information()
            return

        self.scenario_service.mark_modified()
        self.refresh_scenario_information(select_name=trigger_name)
        self.statusBar().showMessage(
            f"Created trigger: {trigger_name}",
            5000,
        )

    def add_condition(self):
        trigger = self.get_selected_trigger()

        if trigger is None:
            return

        dialog = ConditionPickerDialog(self)

        if dialog.exec() != QDialog.Accepted:
            return

        condition_data = dialog.condition_data()

        if condition_data is None:
            QMessageBox.warning(
                self,
                "Unsupported Condition",
                "The selected condition type is not supported yet.",
            )
            return

        condition_type = condition_data["type"]
        condition_label = condition_data["label"]
        condition_id = condition_data["condition_id"]
        condition_kwargs = condition_data["kwargs"]

        command = AddConditionCommand(
            trigger,
            condition_type,
            condition_id,
            condition_kwargs,
            condition_label,
        )

        try:
            recorded_command = self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="add_condition",
            )
            QMessageBox.critical(
                self,
                "Add Condition Failed",
                f"The condition could not be added.\n\n{error}",
            )
            return

        if recorded_command is None or not self.undo_manager.can_undo():
            LoggerService.log_message(
                "Add Condition command was not recorded in Undo history.",
                context="add_condition",
            )
            QMessageBox.critical(
                self,
                "Undo History Error",
                (
                    "The condition was added, but the action was not "
                    "recorded in Undo history."
                ),
            )
            return

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.select_logic_object(command.condition)
        self.update_undo_redo_actions()

        LoggerService.log_message(
            (
                f"Added {condition_label} condition to "
                f"trigger [{trigger.trigger_id}] "
                f"{trigger.name or 'Unnamed Trigger'}: "
                f"{condition_kwargs}; "
                f"undo_available={self.undo_manager.can_undo()}"
            ),
            context="add_condition",
        )

        self.statusBar().showMessage(
            (
                f"Added {condition_label} condition to "
                f"{trigger.name or 'Unnamed Trigger'}."
            ),
            5000,
        )

    def add_effect(self):
        source_trigger = self.get_selected_trigger()

        if source_trigger is None:
            return

        scenario = self.scenario_service.scenario

        dialog = EffectPickerDialog(
            scenario.trigger_manager.triggers,
            source_trigger,
            self,
        )

        if dialog.exec() != QDialog.Accepted:
            return

        effect_data = dialog.effect_data()

        if effect_data is None:
            QMessageBox.warning(
                self,
                "Invalid Effect Settings",
                "Select a valid target trigger before adding the effect.",
            )
            return

        effect_type = effect_data["type"]

        try:
            if effect_type == "activate_trigger":
                source_trigger.new_effect.activate_trigger(
                    trigger_id=effect_data["trigger_id"]
                )
            elif effect_type == "deactivate_trigger":
                source_trigger.new_effect.deactivate_trigger(
                    trigger_id=effect_data["trigger_id"]
                )
            elif effect_type == "research_technology":
                source_trigger._add_effect(
                    EffectId.RESEARCH_TECHNOLOGY,
                    source_player=effect_data["source_player"],
                    technology=effect_data["technology"],
                )
            elif effect_type == "change_ownership":
                source_trigger._add_effect(
                    EffectId.CHANGE_OWNERSHIP,
                    source_player=effect_data["source_player"],
                    target_player=effect_data["target_player"],
                    selected_object_ids=effect_data["selected_object_ids"],
                )
            elif effect_type == "tribute":
                source_trigger._add_effect(
                    EffectId.TRIBUTE,
                    source_player=effect_data["source_player"],
                    target_player=effect_data["target_player"],
                    tribute_list=effect_data["tribute_list"],
                    quantity=effect_data["quantity"],
                )
            else:
                raise ValueError(
                    f"Unsupported effect type: {effect_type}"
                )
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="add_effect",
            )
            QMessageBox.critical(
                self,
                "Add Effect Failed",
                f"The effect could not be added.\n\n{error}",
            )
            return

        self.scenario_service.mark_modified()
        self.update_status()
        self.show_trigger_details(self.trigger_list.currentRow())

        effect_labels = {
            "activate_trigger": "Activate Trigger",
            "deactivate_trigger": "Deactivate Trigger",
            "research_technology": "Research Technology",
            "change_ownership": "Change Ownership",
            "tribute": "Tribute",
        }
        effect_label = effect_labels[effect_type]

        self.statusBar().showMessage(
            (
                f"Added {effect_label} effect to "
                f"{source_trigger.name}: "
                f"{effect_data['target_name']}"
            ),
            5000,
        )

    def aokts_cut_trigger(self):

        scenario = self.scenario_service.scenario

        selected_trigger = self.get_selected_trigger()

        if scenario is None or selected_trigger is None:

            return

        self.cut_trigger_object = selected_trigger

        display_name = selected_trigger.name or "Unnamed Trigger"

        self.paste_trigger_action.setEnabled(True)

        self.statusBar().showMessage(

            f"Cut trigger: {display_name}. Select destination and Paste (Ctrl+V).",

            7000,

        )

    

    def aokts_paste_trigger(self):

        scenario = self.scenario_service.scenario

        destination = self.get_selected_trigger()

        source = self.cut_trigger_object

        if scenario is None or source is None or destination is None:

            return

        manager = scenario.trigger_manager

        current = list(manager.triggers)

        if source not in current:

            self.cut_trigger_object = None

            self.paste_trigger_action.setEnabled(False)

            QMessageBox.warning(self, "Paste Trigger", "The cut trigger is no longer in the loaded scenario.")

            return

        if destination is source:

            self.statusBar().showMessage("Choose a different destination trigger before pasting.", 4000)

            return

        reordered = list(current)

        reordered.remove(source)

        destination_index = reordered.index(destination) + 1

        reordered.insert(destination_index, source)

        try:

            manager.reorder_triggers([trigger.trigger_id for trigger in reordered])

        except Exception as error:

            LoggerService.log_exception(error, scenario_path=self.scenario_service.current_file, context="paste_cut_trigger")

            QMessageBox.critical(self, "Paste Trigger Failed", f"The cut trigger could not be moved.\n\n{error}")

            return

        self.cut_trigger_object = None

        self.paste_trigger_action.setEnabled(False)

        self.scenario_service.mark_modified()

        self.refresh_scenario_information()

        self.select_trigger_object(source)

        LoggerService.log_message(f"Moved trigger {source.trigger_id} using Cut/Paste.", context="paste_cut_trigger")

        self.statusBar().showMessage(f"Pasted trigger [{source.trigger_id}] {source.name or 'Unnamed Trigger'}.", 5000)

    

    def update_copy_trigger_ui(self):
        if not hasattr(self, "copy_trigger_action"):
            return

        has_clipboard = self.copied_trigger_object is not None

        if has_clipboard:
            copied_name = (
                self.copied_trigger_name
                or "Unnamed Trigger"
            )
            tooltip = (
                f"Create a copy of '{copied_name}' after the "
                "currently selected trigger"
            )
        else:
            tooltip = "Copy the selected trigger"

        self.copy_trigger_action.setStatusTip(tooltip)

        if hasattr(self, "panel_copy_trigger_button"):
            self.panel_copy_trigger_button.setToolTip(tooltip)

    def aokts_copy_trigger(self):
        scenario = self.scenario_service.scenario

        if scenario is None:
            QMessageBox.warning(
                self,
                "No Scenario Loaded",
                "Please load a scenario first.",
            )
            return

        selected_trigger = self.get_selected_trigger()

        if selected_trigger is None:
            return

        if self.copied_trigger_object is None:
            self.copied_trigger_object = selected_trigger
            self.copied_trigger_id = selected_trigger.trigger_id
            self.copied_trigger_name = selected_trigger.name
            self.update_copy_trigger_ui()

            display_name = (
                selected_trigger.name
                or "Unnamed Trigger"
            )
            self.statusBar().showMessage(
                f"Copied trigger: {display_name}",
                5000,
            )
            return

        trigger_manager = scenario.trigger_manager
        current_triggers = list(trigger_manager.triggers)

        if self.copied_trigger_object not in current_triggers:
            self.copied_trigger_object = None
            self.copied_trigger_id = None
            self.copied_trigger_name = None
            self.update_copy_trigger_ui()
            QMessageBox.warning(
                self,
                "Copied Trigger Not Found",
                (
                    "The copied trigger is no longer available in the "
                    "loaded scenario. Select it and press Copy again."
                ),
            )
            return

        source_trigger = self.copied_trigger_object
        base_source_name = (
            self.copied_trigger_name
            or source_trigger.name
            or "Unnamed Trigger"
        )
        base_name = f"{base_source_name} - COPY"
        existing_names = {
            trigger.name
            for trigger in current_triggers
        }

        new_name = base_name
        copy_number = 2
        while new_name in existing_names:
            new_name = f"{base_name} {copy_number}"
            copy_number += 1

        target_index = current_triggers.index(selected_trigger) + 1
        original_count = len(current_triggers)

        try:
            copied_trigger = trigger_manager.copy_trigger(
                source_trigger.trigger_id
            )
            copied_trigger.name = new_name

            reordered_objects = list(trigger_manager.triggers)
            reordered_objects.remove(copied_trigger)
            reordered_objects.insert(target_index, copied_trigger)
            new_id_order = [
                trigger.trigger_id
                for trigger in reordered_objects
            ]
            trigger_manager.reorder_triggers(new_id_order)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="aokts_copy_trigger",
            )
            QMessageBox.critical(
                self,
                "Copy Trigger Failed",
                f"The trigger could not be copied.\n\n{error}",
            )
            return

        if len(trigger_manager.triggers) != original_count + 1:
            QMessageBox.critical(
                self,
                "Copy Validation Failed",
                (
                    "The trigger count did not increase by exactly one.\n\n"
                    "Review the scenario before saving."
                ),
            )
            self.scenario_service.mark_modified()
            self.refresh_trigger_ui()
            return

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(copied_trigger)
        self.update_copy_trigger_ui()

        LoggerService.log_message(
            (
                f"Copied trigger '{base_source_name}' to '{new_name}' "
                f"at position {target_index + 1}."
            ),
            context="aokts_copy_trigger",
        )
        self.statusBar().showMessage(
            f"Created trigger copy: {new_name}",
            5000,
        )

    def get_selected_trigger(self):
        selected_item = self.trigger_list.currentItem()

        if selected_item is None:
            QMessageBox.warning(
                self,
                "No Trigger Selected",
                "Please select a trigger first.",
            )
            return None

        scenario = self.scenario_service.scenario

        if scenario is None:
            QMessageBox.warning(
                self,
                "No Scenario Loaded",
                "Please load a scenario first.",
            )
            return None

        trigger_id = selected_item.data(Qt.UserRole)

        if trigger_id is None:
            QMessageBox.warning(
                self,
                "Trigger ID Missing",
                "The selected trigger does not contain a trigger ID.",
            )
            return None

        for trigger in scenario.trigger_manager.triggers:
            if trigger.trigger_id == trigger_id:
                return trigger

        QMessageBox.warning(
            self,
            "Trigger Not Found",
            (
                "The selected trigger could not be found.\n\n"
                f"Trigger ID: {trigger_id}"
            ),
        )
        return None

    def show_trigger_context_menu(self, position):
        item = self.trigger_list.itemAt(position)

        if item is None:
            return

        self.trigger_list.setCurrentItem(item)

        menu = QMenu(self.trigger_list)

        rename_action = menu.addAction("Rename Trigger")
        rename_action.setShortcut(QKeySequence("F2"))

        menu.addSeparator()

        cut_action = menu.addAction("Cut Trigger")

        paste_action = menu.addAction("Paste Trigger")

        paste_action.setEnabled(self.cut_trigger_object is not None)

        copy_action = menu.addAction("Copy Trigger")
        copy_tree_action = menu.addAction("Copy Trigger Tree")
        copy_all_players_action = menu.addAction("Copy All Players")
        delete_action = menu.addAction("Delete Trigger")

        menu.addSeparator()

        move_up_action = menu.addAction("Move Up")
        move_up_action.setShortcut(QKeySequence("Alt+Up"))
        move_down_action = menu.addAction("Move Down")
        move_down_action.setShortcut(QKeySequence("Alt+Down"))

        selected_action = menu.exec(
            self.trigger_list.viewport().mapToGlobal(position)
        )

        if selected_action is rename_action:
            self.rename_trigger()
        elif selected_action is cut_action:
            self.aokts_cut_trigger()
        elif selected_action is paste_action:
            self.aokts_paste_trigger()
        elif selected_action is copy_action:
            self.aokts_copy_trigger()
        elif selected_action is copy_tree_action:
            self.copy_trigger_tree()
        elif selected_action is copy_all_players_action:
            self.copy_all_players()
        elif selected_action is delete_action:
            self.delete_trigger()
        elif selected_action is move_up_action:
            self.move_trigger_up()
        elif selected_action is move_down_action:
            self.move_trigger_down()

    def blank_all_trigger_names(self):

        scenario = self.scenario_service.scenario

        if scenario is None:

            return

    

        named_triggers = [

            trigger for trigger in scenario.trigger_manager.triggers

            if (trigger.name or "").strip()

        ]

        if not named_triggers:

            QMessageBox.information(

                self, "Blank All Trigger Names",

                "All trigger names are already blank.",

            )

            return

    

        result = QMessageBox.question(

            self,

            "Blank All Trigger Names",

            (

                f"Blank the names of {len(named_triggers)} trigger(s)?\n\n"

                "Conditions, effects, trigger order and trigger references "

                "will not be changed.\n\nThis action cannot be undone."

            ),

            QMessageBox.Yes | QMessageBox.No,

            QMessageBox.No,

        )

        if result != QMessageBox.Yes:

            return

    

        try:

            for trigger in named_triggers:

                trigger.name = ""

        except Exception as error:

            LoggerService.log_exception(

                error,

                scenario_path=self.scenario_service.current_file,

                context="blank_all_trigger_names",

            )

            QMessageBox.critical(

                self, "Blank Trigger Names Failed",

                "The trigger names could not be blanked.\n\nPlease see the error log for more information.",

            )

            return

    

        self.scenario_service.mark_modified()

        self.refresh_scenario_information()

        LoggerService.log_message(

            f"Blanked {len(named_triggers)} trigger name(s).",

            context="blank_all_trigger_names",

        )

        self.statusBar().showMessage(

            f"Blanked {len(named_triggers)} trigger name(s).", 5000

        )

    

    def _player_fields(self, logic_object):

    

        """Return writable Player 1-8 fields exposed by a parser object."""

    

        fields = []

    

        for name in dir(logic_object):

    

            lowered = name.lower()

    

            if "player" not in lowered or name.startswith("_"):

    

                continue

    

            try:

    

                value = getattr(logic_object, name)

    

            except Exception:

    

                continue

    

            if isinstance(value, bool) or not isinstance(value, int):

    

                continue

    

            if 1 <= value <= 8:

    

                fields.append((name, value))

    

        return fields

    

    

    

    def _detect_trigger_source_player(self, trigger):

    

        players = set()

    

        for logic_object in list(trigger.conditions) + list(trigger.effects):

    

            players.update(value for _, value in self._player_fields(logic_object))

    

        if len(players) == 1:

    

            return next(iter(players))

    

        return None

    

    

    

    def _replace_trigger_player(self, trigger, source_player, target_player):

    

        changed = 0

    

        for logic_object in list(trigger.conditions) + list(trigger.effects):

    

            for field_name, value in self._player_fields(logic_object):

    

                if value == source_player:

    

                    setattr(logic_object, field_name, target_player)

    

                    changed += 1

    

        return changed

    

    

    

    def copy_all_players(self):

    

        source_trigger = self.get_selected_trigger()

    

        scenario = self.scenario_service.scenario

    

        if source_trigger is None or scenario is None:

    

            return

    

    

    

        source_player = self._detect_trigger_source_player(source_trigger)

    

        if source_player is None:

    

            QMessageBox.warning(

    

                self,

    

                "Copy All Players",

    

                (

    

                    "The selected trigger does not contain exactly one "

    

                    "detectable Player 1-8 reference.\n\n"

    

                    "No triggers were created. This prevents unrelated "

    

                    "source and target players from being changed."

    

                ),

    

            )

    

            return

    

    

    

        display_name = (source_trigger.name or "").strip() or "Unnamed Trigger"

    

        result = QMessageBox.question(

    

            self,

    

            "Copy All Players",

    

            (

    

                f"Use '{display_name}' as the Player {source_player} template?\n\n"

    

                "Seven new triggers will be created for the other players. "

    

                "Only Player 1-8 fields matching the detected template player "

    

                "will be replaced.\n\nThis action cannot be undone."

    

            ),

    

            QMessageBox.Yes | QMessageBox.No,

    

            QMessageBox.No,

    

        )

    

        if result != QMessageBox.Yes:

    

            return

    

    

    

        manager = scenario.trigger_manager

    

        original_order = list(manager.triggers)

    

        source_index = original_order.index(source_trigger)

    

        created = []

    

        try:

    

            # Rename the template consistently, then create the other seven.

    

            base_name = (source_trigger.name or "").strip() or "Unnamed Trigger"

    

            source_trigger.name = f"{base_name} - P{source_player}"

    

            by_player = {source_player: source_trigger}

    

            for player in range(1, 9):

    

                if player == source_player:

    

                    continue

    

                copied = manager.copy_trigger(source_trigger.trigger_id)

    

                copied.name = f"{base_name} - P{player}"

    

                self._replace_trigger_player(copied, source_player, player)

    

                created.append(copied)

    

                by_player[player] = copied

    

            current = list(manager.triggers)

    

            block = [by_player[player] for player in range(1, 9)]

    

            remaining = [trigger for trigger in current if trigger not in block]

    

            reordered = remaining[:source_index] + block + remaining[source_index:]

    

            manager.reorder_triggers([trigger.trigger_id for trigger in reordered])

    

        except Exception as error:

    

            LoggerService.log_exception(

    

                error,

    

                scenario_path=self.scenario_service.current_file,

    

                context="copy_all_players",

    

            )

    

            QMessageBox.critical(

    

                self, "Copy All Players Failed",

    

                f"The player copies could not be completed.\n\n{error}",

    

            )

    

            return

    

        self.scenario_service.mark_modified()

    

        self.refresh_scenario_information()

    

        self.select_trigger_object(source_trigger)

    

        LoggerService.log_message(

    

            f"Created Player 1-8 trigger set from trigger {source_trigger.trigger_id}.",

    

            context="copy_all_players",

    

        )

    

        self.statusBar().showMessage(

    

            f"Created seven player copies from Player {source_player} template.", 5000

    

        )

    

    

    

    def rename_trigger(self):
        trigger = self.get_selected_trigger()

        if trigger is None:
            return

        trigger_id = trigger.trigger_id
        old_name = (trigger.name or "").strip()

        new_name, ok = QInputDialog.getText(
            self,
            "Rename Trigger",
            "New Trigger Name:",
            text=old_name,
        )

        if not ok:
            return

        new_name = new_name.strip()

        if not new_name:
            QMessageBox.warning(
                self,
                "Invalid Trigger Name",
                "The trigger name cannot be empty.",
            )
            return

        if new_name == old_name:
            return

        if not self.confirm_trigger_name(new_name):
            return

        command = RenameTriggerCommand(
            trigger,
            old_name,
            new_name,
        )

        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="rename_trigger",
            )
            QMessageBox.critical(
                self,
                "Rename Failed",
                (
                    "The trigger could not be renamed.\n\n"
                    "Please see the error log for more information."
                ),
            )
            return

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.update_undo_redo_actions()

        LoggerService.log_message(
            (
                f"Renamed trigger {trigger_id}: "
                f"'{old_name or 'Unnamed Trigger'}' -> '{new_name}'"
            ),
            context="rename_trigger",
        )

        self.statusBar().showMessage(
            f"Renamed trigger [{trigger_id}] to {new_name}",
            5000,
        )

    def delete_trigger(self):
        trigger = self.get_selected_trigger()

        if trigger is None:
            return

        scenario = self.scenario_service.scenario
        trigger_id = trigger.trigger_id
        trigger_name = (trigger.name or "").strip()
        display_name = trigger_name or "Unnamed Trigger"
        selected_row = self.trigger_list.currentRow()

        result = QMessageBox.question(
            self,
            "Delete Trigger",
            (
                "Are you sure you want to delete:\n\n"
                f"[{trigger_id}] {display_name}\n\n"
                "This action cannot be undone."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if result != QMessageBox.Yes:
            return

        try:
            scenario.trigger_manager.remove_trigger(trigger_id)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="delete_trigger",
            )
            QMessageBox.critical(
                self,
                "Delete Failed",
                (
                    "The trigger could not be deleted.\n\n"
                    "Please see the error log for more information."
                ),
            )
            return

        self.scenario_service.mark_modified()
        self.refresh_scenario_information()

        if self.trigger_list.count() > 0:
            next_row = min(
                selected_row,
                self.trigger_list.count() - 1,
            )
            self.trigger_list.setCurrentRow(next_row)
        else:
            self.trigger_details.setText(
                ""
            )

        LoggerService.log_message(
            f"Deleted trigger [{trigger_id}] {display_name}",
            context="delete_trigger",
        )

        self.statusBar().showMessage(
            f"Deleted trigger [{trigger_id}] {display_name}",
            5000,
        )

    def log_trigger_drop(
        self,
        trigger_id,
        source_row,
        target_row,
    ):
        scenario = self.scenario_service.scenario

        if scenario is None:
            self.refresh_trigger_list()
            return

        if self.search_box.text().strip():
            self.refresh_trigger_list()
            self.select_trigger_by_id(trigger_id)
            QMessageBox.information(
                self,
                "Clear Trigger Search",
                (
                    "Drag-and-drop reordering is unavailable while the "
                    "trigger list is filtered. Clear the search and try again."
                ),
            )
            return

        trigger_manager = scenario.trigger_manager
        moved_trigger = next(
            (
                trigger
                for trigger in trigger_manager.triggers
                if trigger.trigger_id == trigger_id
            ),
            None,
        )

        if moved_trigger is None:
            self.refresh_trigger_list()
            QMessageBox.warning(
                self,
                "Trigger Not Found",
                "The dragged trigger could not be found in the scenario.",
            )
            return

        new_id_order = [
            self.trigger_list.item(index).data(Qt.UserRole)
            for index in range(self.trigger_list.count())
        ]

        old_trigger_order = list(
            trigger_manager.triggers
        )
        parser_id_order = [
            trigger.trigger_id
            for trigger in old_trigger_order
        ]

        if len(new_id_order) != len(parser_id_order):
            self.refresh_trigger_list()
            self.select_trigger_by_id(trigger_id)
            QMessageBox.warning(
                self,
                "Trigger Reorder Cancelled",
                (
                    "The visible trigger list does not contain every trigger. "
                    "Clear the search and try again."
                ),
            )
            return

        LoggerService.log_message(
            (
                f"Applying trigger drag: trigger ID {trigger_id}, "
                f"row {source_row} -> {target_row}, "
                f"count={len(new_id_order)}, "
                f"first10={new_id_order[:10]}."
            ),
            context="drag_drop_reorder",
        )

        trigger_by_id = {
            trigger.trigger_id: trigger
            for trigger in old_trigger_order
        }
        new_trigger_order = [
            trigger_by_id[trigger_id_value]
            for trigger_id_value in new_id_order
        ]
        command = ReorderTriggerCommand(
            trigger_manager,
            old_trigger_order,
            new_trigger_order,
            moved_trigger,
            description="Drag Trigger",
        )

        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="drag_drop_reorder",
            )
            self.refresh_trigger_list()
            self.select_trigger_by_id(trigger_id)
            QMessageBox.critical(
                self,
                "Trigger Reorder Failed",
                (
                    "The trigger order could not be changed.\n\n"
                    "The previous parser order has been restored in the list.\n\n"
                    "Please see the error log for more information."
                ),
            )
            return

        moved_trigger_id = moved_trigger.trigger_id
        moved_trigger_row = next(
            (
                index
                for index, trigger in enumerate(
                    trigger_manager.triggers
                )
                if trigger is moved_trigger
            ),
            target_row,
        )

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.update_undo_redo_actions()

        if 0 <= moved_trigger_row < self.trigger_list.count():
            self.trigger_list.setCurrentRow(moved_trigger_row)
            self.trigger_list.scrollToItem(
                self.trigger_list.currentItem(),
                QAbstractItemView.PositionAtCenter,
            )
        else:
            self.select_trigger_by_id(moved_trigger_id)

        LoggerService.log_message(
            (
                f"Applied trigger drag successfully: original ID "
                f"{trigger_id}, current ID {moved_trigger_id}, "
                f"row {source_row} -> {moved_trigger_row}."
            ),
            context="drag_drop_reorder",
        )

        self.statusBar().showMessage(
            (
                f"Moved trigger to position {moved_trigger_row + 1}. "
                "Save the scenario to persist the new order."
            ),
            7000,
        )

    def move_trigger_up(self):
        self.move_selected_trigger(-1)

    def move_trigger_down(self):
        self.move_selected_trigger(1)

    def move_selected_trigger(self, direction):
        trigger = self.get_selected_trigger()

        if trigger is None:
            return

        scenario = self.scenario_service.scenario
        trigger_manager = scenario.trigger_manager
        triggers = trigger_manager.triggers
        original_trigger_id = trigger.trigger_id

        current_index = next(
            (
                index
                for index, current_trigger in enumerate(triggers)
                if current_trigger.trigger_id == original_trigger_id
            ),
            None,
        )

        if current_index is None:
            QMessageBox.warning(
                self,
                "Trigger Not Found",
                "The selected trigger could not be located in the trigger order.",
            )
            return

        modifiers = QApplication.keyboardModifiers()

        move_amount = 1

        if modifiers & Qt.ControlModifier:
            move_amount = 10
        elif modifiers & Qt.ShiftModifier:
            move_amount = 5

        target_index = current_index + (direction * move_amount)

        if target_index < 0:
            target_index = 0

        if target_index >= len(triggers):
            target_index = len(triggers) - 1

        if target_index == current_index:
            return

        if target_index < 0:
            self.statusBar().showMessage(
                "The selected trigger is already first.",
                4000,
            )
            return

        if target_index >= len(triggers):
            self.statusBar().showMessage(
                "The selected trigger is already last.",
                4000,
            )
            return

        new_id_order = [
            current_trigger.trigger_id
            for current_trigger in triggers
        ]
        new_id_order[current_index], new_id_order[target_index] = (
            new_id_order[target_index],
            new_id_order[current_index],
        )

        action_name = (
            "move_trigger_up"
            if direction < 0
            else "move_trigger_down"
        )
        direction_label = "up" if direction < 0 else "down"

        old_trigger_order = list(triggers)
        trigger_by_id = {
            current_trigger.trigger_id: current_trigger
            for current_trigger in old_trigger_order
        }
        new_trigger_order = [
            trigger_by_id[trigger_id_value]
            for trigger_id_value in new_id_order
        ]
        command = ReorderTriggerCommand(
            trigger_manager,
            old_trigger_order,
            new_trigger_order,
            trigger,
            description=(
                f"Move Trigger {direction_label.title()}"
            ),
        )

        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context=action_name,
            )
            QMessageBox.critical(
                self,
                "Move Trigger Failed",
                (
                    "The trigger could not be moved.\n\n"
                    "Please see the error log for more information."
                ),
            )
            return

        moved_trigger_id = trigger.trigger_id

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.update_undo_redo_actions()

        selected = self.select_trigger_by_id(moved_trigger_id)

        if (
            not selected
            and not self.search_box.text().strip()
            and 0 <= target_index < self.trigger_list.count()
        ):
            self.trigger_list.setCurrentRow(target_index)

        LoggerService.log_message(
            (
                f"Moved trigger [{original_trigger_id}] {direction_label}: "
                f"index {current_index} -> {target_index}; current trigger ID: {moved_trigger_id}"
            ),
            context=action_name,
        )

        self.statusBar().showMessage(
            (
                f"Moved trigger [{moved_trigger_id}] {direction_label} "
                f"to position {target_index + 1}."
            ),
            5000,
        )

    def randomize_trigger_order(self):

        scenario = self.scenario_service.scenario

        if scenario is None:

            return

        manager = scenario.trigger_manager

        triggers = list(manager.triggers)

        if len(triggers) < 2:

            QMessageBox.information(

                self, "Randomize Trigger Order",

                "At least two triggers are required to randomize the order.",

            )

            return

        result = QMessageBox.question(

            self,

            "Randomize Trigger Order",

            (

                f"Randomize all {len(triggers)} triggers?\n\n"

                "Trigger IDs, names, conditions, effects and trigger references will not be changed. "

                "Only the trigger order will change.\n\n"

                "This is intended for final map distribution/obfuscation."

            ),

            QMessageBox.Yes | QMessageBox.No,

            QMessageBox.No,

        )

        if result != QMessageBox.Yes:

            return

        import random

        original_ids = [trigger.trigger_id for trigger in triggers]

        randomized = list(triggers)

        rng = random.SystemRandom()

        # Avoid the very unlikely no-op shuffle so clicking Randomize always changes order.

        for _ in range(10):

            rng.shuffle(randomized)

            if [trigger.trigger_id for trigger in randomized] != original_ids:

                break

        try:

            manager.reorder_triggers([trigger.trigger_id for trigger in randomized])

        except Exception as error:

            LoggerService.log_exception(

                error,

                scenario_path=self.scenario_service.current_file,

                context="randomize_trigger_order",

            )

            QMessageBox.critical(

                self, "Randomize Trigger Order Failed",

                f"The trigger order could not be randomized.\n\n{error}",

            )

            return

        self.scenario_service.mark_modified()

        self.refresh_scenario_information()

        LoggerService.log_message(

            f"Randomized the order of {len(triggers)} triggers.",

            context="randomize_trigger_order",

        )

        self.statusBar().showMessage(

            f"Randomized the order of {len(triggers)} triggers.", 5000

        )

    

    def confirm_trigger_name(self, new_name):
        scenario = self.scenario_service.scenario

        existing_names = [
            trigger.name
            for trigger in scenario.trigger_manager.triggers
        ]

        if new_name not in existing_names:
            return True

        result = QMessageBox.question(
            self,
            "Trigger Name Already Exists",
            (
                "A trigger with that name already exists.\n\n"
                "Do you still want to use this name?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        return result == QMessageBox.Yes

    def duplicate_trigger(self):
        trigger_to_copy = self.get_selected_trigger()

        if trigger_to_copy is None:
            return

        selected_name = trigger_to_copy.name

        new_name, ok = QInputDialog.getText(
            self,
            "Duplicate Trigger",
            "New Trigger Name:",
            text=f"{selected_name} - COPY",
        )

        if not ok:
            return

        new_name = new_name.strip()

        if not new_name:
            QMessageBox.warning(
                self,
                "Invalid Trigger Name",
                "The new trigger name cannot be empty.",
            )
            return

        if not self.confirm_trigger_name(new_name):
            return

        scenario = self.scenario_service.scenario
        original_count = len(scenario.trigger_manager.triggers)

        try:
            copied_trigger = scenario.trigger_manager.copy_trigger(
                trigger_to_copy.trigger_id
            )
            copied_trigger.name = new_name
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="duplicate_trigger",
            )
            QMessageBox.critical(
                self,
                "Duplication Failed",
                f"The trigger could not be duplicated.\n\n{error}",
            )
            return

        new_count = len(scenario.trigger_manager.triggers)

        if new_count != original_count + 1:
            QMessageBox.critical(
                self,
                "Duplication Validation Failed",
                (
                    "The trigger count did not increase by exactly one.\n\n"
                    "The scenario has not been saved."
                ),
            )
            self.scenario_service.mark_modified()
            self.refresh_scenario_information()
            return

        self.scenario_service.mark_modified()
        self.refresh_scenario_information(select_name=new_name)

        QMessageBox.information(
            self,
            "Trigger Duplicated",
            f'Trigger "{new_name}" created.',
        )

    def copy_trigger_tree(self):
        source_trigger = self.get_selected_trigger()

        if source_trigger is None:
            return

        selected_name = source_trigger.name

        new_name, ok = QInputDialog.getText(
            self,
            "Copy Trigger Tree",
            "New Root Trigger Name:",
            text=f"{selected_name} - TREE COPY",
        )

        if not ok:
            return

        new_name = new_name.strip()

        if not new_name:
            QMessageBox.warning(
                self,
                "Invalid Trigger Name",
                "The copied root trigger name cannot be empty.",
            )
            return

        if not self.confirm_trigger_name(new_name):
            return

        scenario = self.scenario_service.scenario
        original_count = len(scenario.trigger_manager.triggers)

        try:
            copied_triggers = scenario.trigger_manager.copy_trigger_tree(
                source_trigger.trigger_id
            )
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="copy_trigger_tree",
            )
            QMessageBox.critical(
                self,
                "Tree Copy Failed",
                f"The trigger tree could not be copied.\n\n{error}",
            )
            return

        if not copied_triggers:
            QMessageBox.warning(
                self,
                "Tree Copy Failed",
                "No triggers were copied.",
            )
            return

        copied_root = copied_triggers[0]
        copied_root.name = new_name

        new_count = len(scenario.trigger_manager.triggers)
        expected_additions = len(copied_triggers)
        actual_additions = new_count - original_count

        self.scenario_service.mark_modified()
        self.refresh_scenario_information(select_name=new_name)

        if actual_additions != expected_additions:
            QMessageBox.warning(
                self,
                "Tree Copy Validation Warning",
                (
                    "The trigger tree was copied, but the reported number "
                    "of additions differed.\n\n"
                    f"Parser returned: {expected_additions}\n"
                    f"Trigger count increased by: {actual_additions}\n\n"
                    "Review the copied triggers before saving."
                ),
            )
            return

        copied_names_text = "\n".join(
            f"- {trigger.name}"
            for trigger in copied_triggers
        )

        QMessageBox.information(
            self,
            "Trigger Tree Copied",
            (
                f"Copied {len(copied_triggers)} trigger(s).\n\n"
                f"New root trigger:\n{new_name}\n\n"
                f"Copied triggers:\n{copied_names_text}"
            ),
        )

    def format_trigger_display_name(self, trigger):
        trigger_name = (trigger.name or "").strip()

        if trigger_name:
            return f"[{trigger.trigger_id}] {trigger_name}"

        return f"[{trigger.trigger_id}] Unnamed Trigger"

    def refresh_trigger_list(self):
        self.trigger_list.clear()

        scenario = self.scenario_service.scenario

        if scenario is None:
            return

        search_text = self.search_box.text().strip().lower()

        for trigger in scenario.trigger_manager.triggers:
            display_name = self.format_trigger_display_name(trigger)

            searchable_text = (
                f"{display_name} "
                f"{trigger.name or ''} "
                f"{trigger.trigger_id}"
            ).lower()

            if search_text and search_text not in searchable_text:
                continue

            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, trigger.trigger_id)
            self.trigger_list.addItem(item)

    def filter_triggers(self):
        self.refresh_trigger_list()
        self.clear_logic_list()
        self.trigger_logic_group.setTitle("Trigger Logic")
        self.logic_editor_group.setTitle("Item Editor")
        self.trigger_details.setText(
            ""
        )

    def select_trigger_by_id(self, trigger_id):
        for index in range(self.trigger_list.count()):
            item = self.trigger_list.item(index)

            if item.data(Qt.UserRole) == trigger_id:
                self.trigger_list.setCurrentItem(item)
                return True

        return False

    def select_trigger_by_name(self, trigger_name):
        scenario = self.scenario_service.scenario

        if scenario is None:
            return False

        for trigger in scenario.trigger_manager.triggers:
            if trigger.name == trigger_name:
                return self.select_trigger_by_id(trigger.trigger_id)

        return False

    def clear_logic_list(self):
        self.trigger_logic_list.clear()
        for attribute_name in (
            "panel_delete_logic_button",
            "panel_move_logic_up_button",
            "panel_move_logic_down_button",
        ):
            button = getattr(self, attribute_name, None)
            if button is not None:
                button.setEnabled(False)

    @staticmethod
    def logic_object_fields(logic_object):
        field_lines = []

        for field_name in sorted(vars(logic_object)):
            if field_name.startswith("_"):
                continue

            try:
                value = getattr(logic_object, field_name)
            except Exception:
                continue

            if callable(value):
                continue

            field_lines.append(
                f"{field_name}: {value}"
            )

        return field_lines

    @staticmethod
    def format_condition_item(condition, display_index):
        condition_type = getattr(
            condition,
            "condition_type",
            "?",
        )

        try:
            condition_name = ConditionId(condition_type).name
            condition_name = condition_name.replace("_", " ").title()
        except Exception:
            condition_name = f"Condition Type {condition_type}"

        if condition_type == ConditionId.AND.value:
            condition_name = "Condition Joiner"
        elif condition_type == ConditionId.OR.value:
            condition_name = "Condition Separator"
        elif condition_type == ConditionId.AI_SIGNAL_MULTIPLAYER.value:
            condition_name = "Multiplayer AI Signal"

        details = []

        if condition_type == ConditionId.AND.value:
            details.append("AND")
        elif condition_type == ConditionId.OR.value:
            details.append("OR")


        if condition_type == ConditionId.DECISION_TRIGGERED.value:
            decision_id = getattr(condition, "decision_id", -1)
            decision_option = getattr(condition, "decision_option", -1)
            if decision_id >= 0:
                details.append(f"Decision {decision_id}")
            if decision_option >= 0:
                details.append(f"Option {decision_option}")

        ai_signal = getattr(condition, "ai_signal", -1)
        if ai_signal >= 0:
            details.append(f"signal {ai_signal}")

        next_object = getattr(condition, "next_object", -1)
        if next_object >= 0:
            details.append(f"target object {next_object}")

        if condition_type == ConditionId.BUILDING_IS_TRADING.value:
            unit_object = getattr(condition, "unit_object", -1)
            if unit_object >= 0:
                details.append(f"building {unit_object}")

        if condition_type == ConditionId.CAPTURE_OBJECT.value:
            unit_object = getattr(condition, "unit_object", -1)
            source_player = getattr(condition, "source_player", -1)
            if unit_object >= 0:
                details.append(f"object {unit_object}")
            if source_player >= 0:
                details.append(f"Player {source_player}")

        if condition_type == ConditionId.CHANCE.value:
            quantity = getattr(condition, "quantity", -1)
            if quantity >= 0:
                details.append(f"{quantity}%")

        if condition_type == ConditionId.COMPARE_VARIABLES.value:
            symbols = {0: "=", 1: "<", 2: ">", 3: "<=", 4: ">="}
            variable = getattr(condition, "variable", -1)
            comparison = getattr(condition, "comparison", -1)
            variable2 = getattr(condition, "variable2", -1)
            symbol = symbols.get(comparison, f"comparison {comparison}")
            if variable >= 0 and variable2 >= 0:
                details.append(f"Variable {variable} {symbol} Variable {variable2}")

        if condition_type == ConditionId.DIFFICULTY_LEVEL.value:
            difficulty_value = getattr(condition, "quantity", None)
            difficulty_names = {
                DifficultyLevel.EASIEST.value: "Easiest",
                DifficultyLevel.STANDARD.value: "Standard",
                DifficultyLevel.MODERATE.value: "Moderate",
                DifficultyLevel.HARD.value: "Hard",
                DifficultyLevel.HARDEST.value: "Hardest",
                DifficultyLevel.EXTREME.value: "Extreme",
            }
            details.append(
                difficulty_names.get(
                    difficulty_value,
                    f"Difficulty {difficulty_value}",
                )
            )

        if getattr(condition, "timer", -1) >= 0:
            details.append(f"{condition.timer}s")

        if (
            condition_type not in (
                ConditionId.DIFFICULTY_LEVEL.value,
                ConditionId.DIPLOMACY_STATE.value,
            )
            and getattr(condition, "quantity", -1) >= 0
        ):
            details.append(f"quantity {condition.quantity}")

        if (
            condition_type not in (
                ConditionId.DIPLOMACY_STATE.value,
                ConditionId.HERO_POWER_CAST.value,
            )
            and getattr(condition, "source_player", -1) >= 0
        ):
            details.append(f"player {condition.source_player}")

        if getattr(condition, "object_list", -1) >= 0:
            details.append(f"object {condition.object_list}")

        suffix = f" - {', '.join(details)}" if details else ""
        return f"{display_index}. {condition_name}{suffix}"

    @staticmethod
    def format_effect_item(effect, display_index):
        effect_type = getattr(effect, "effect_type", "?")
        text = str(effect)

        if not text or text.startswith("<"):
            text = f"Effect Type {effect_type}"

        return f"{display_index}. {text}"

    @staticmethod
    def create_logic_heading(text):
        item = QListWidgetItem(text)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setFlags(Qt.NoItemFlags)
        item.setData(Qt.UserRole, None)
        return item

    def add_logic_item(
        self,
        text,
        kind,
        logic_object,
        display_index,
    ):
        item = QListWidgetItem(text)
        item.setData(
            Qt.UserRole,
            {
                "kind": kind,
                "object": logic_object,
                "display_index": display_index,
            },
        )
        self.trigger_logic_list.addItem(item)

    def populate_logic_list(self, trigger):
        self.clear_logic_list()

        condition_count = len(trigger.conditions)
        effect_count = len(trigger.effects)

        self.trigger_logic_list.addItem(
            self.create_logic_heading(
                f"CONDITIONS ({condition_count})"
            )
        )

        if condition_count == 0:
            empty_item = QListWidgetItem("No conditions")
            empty_item.setFlags(Qt.NoItemFlags)
            self.trigger_logic_list.addItem(empty_item)
        else:
            for display_index, condition in enumerate(
                trigger.conditions,
                start=1,
            ):
                self.add_logic_item(
                    self.format_condition_item(
                        condition,
                        display_index,
                    ),
                    "condition",
                    condition,
                    display_index - 1,
                )

        self.trigger_logic_list.addItem(
            self.create_logic_heading(
                f"EFFECTS ({effect_count})"
            )
        )

        if effect_count == 0:
            empty_item = QListWidgetItem("No effects")
            empty_item.setFlags(Qt.NoItemFlags)
            self.trigger_logic_list.addItem(empty_item)
        else:
            for display_index, effect in enumerate(
                trigger.effects,
                start=1,
            ):
                self.add_logic_item(
                    self.format_effect_item(
                        effect,
                        display_index,
                    ),
                    "effect",
                    effect,
                    display_index - 1,
                )

        self.trigger_logic_group.setTitle(
            f"Trigger Logic ({condition_count + effect_count})"
        )

    def show_logic_item_summary(self, current, previous=None):
        item_data = current.data(Qt.UserRole) if current is not None else None
        is_logic_item = isinstance(item_data, dict)
        is_condition = is_logic_item and item_data.get("kind") == "condition"
        condition_index = item_data.get("display_index", -1) if is_condition else -1
        trigger = self.selected_trigger_object()
        condition_count = len(trigger.conditions) if trigger is not None else 0

        self.panel_delete_logic_button.setEnabled(is_logic_item)
        self.panel_move_logic_up_button.setEnabled(
            is_condition and condition_index > 0
        )
        self.panel_move_logic_down_button.setEnabled(
            is_condition and condition_index < condition_count - 1
        )
        self.logic_editor_group.setTitle("Item Editor")
        self.logic_editor_stack.setCurrentWidget(self.logic_summary_page)
        self.trigger_details.clear()

    def show_logic_context_menu(self, position):
        item = self.trigger_logic_list.itemAt(position)
        item_data = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(item_data, dict):
            return
        self.trigger_logic_list.setCurrentItem(item)
        kind = item_data["kind"]
        kind_label = kind.title()
        menu = QMenu(self.trigger_logic_list)
        edit_action = menu.addAction(f"Edit {kind_label}")
        delete_action = menu.addAction(f"Delete {kind_label}")
        move_up_action = None
        move_down_action = None
        change_type_action = None
        if kind == "condition":
            change_type_action = menu.addAction("Change Condition Type...")
            menu.addSeparator()
            move_up_action = menu.addAction("Move Condition Up")
            move_down_action = menu.addAction("Move Condition Down")
            index = item_data["display_index"]
            trigger = self.selected_trigger_object()
            count = len(trigger.conditions) if trigger is not None else 0
            move_up_action.setEnabled(index > 0)
            move_down_action.setEnabled(index < count - 1)
        selected_action = menu.exec(
            self.trigger_logic_list.viewport().mapToGlobal(position)
        )
        if selected_action is edit_action:
            self.edit_logic_item(item)
        elif (
            change_type_action is not None
            and selected_action is change_type_action
        ):
            self.change_selected_condition_type()
        elif selected_action is delete_action:
            self.delete_selected_logic_item()
        elif move_up_action is not None and selected_action is move_up_action:
            self.move_selected_condition_up()
        elif move_down_action is not None and selected_action is move_down_action:
            self.move_selected_condition_down()

    def change_selected_condition_type(self):
        item = self.trigger_logic_list.currentItem()
        item_data = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(item_data, dict):
            return
        if item_data.get("kind") != "condition":
            return

        trigger = self.selected_trigger_object()
        if trigger is None:
            return

        old_condition = item_data["object"]
        index = item_data["display_index"]
        if old_condition not in trigger.conditions:
            QMessageBox.warning(
                self,
                "Change Condition Type",
                "The selected condition is no longer available.",
            )
            return

        dialog = ConditionPickerDialog(self)
        dialog.setWindowTitle("Change Condition Type")
        dialog.dialog_buttons.button(
            QDialogButtonBox.Ok
        ).setText("Change Condition")

        if dialog.exec() != QDialog.Accepted:
            return

        condition_data = dialog.condition_data()
        if condition_data is None:
            QMessageBox.warning(
                self,
                "Unsupported Condition",
                "The selected condition type is not supported yet.",
            )
            return

        new_label = condition_data["label"]
        result = QMessageBox.question(
            self,
            "Change Condition Type",
            (
                f"Replace condition {index + 1} with {new_label}?\n\n"
                "The replacement will remain in the same position. "
                "This action can be undone."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return

        command = ChangeConditionTypeCommand(
            trigger,
            old_condition,
            index,
            condition_data["type"],
            condition_data["condition_id"],
            condition_data["kwargs"],
            new_label,
        )
        try:
            recorded_command = self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="change_condition_type",
            )
            QMessageBox.critical(
                self,
                "Change Condition Type Failed",
                f"The condition type could not be changed.\n\n{error}",
            )
            return

        if recorded_command is None or not self.undo_manager.can_undo():
            QMessageBox.critical(
                self,
                "Undo History Error",
                (
                    "The condition was replaced, but the action was not "
                    "recorded in Undo history."
                ),
            )
            return

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.select_logic_object(command.new_condition)
        self.update_undo_redo_actions()
        self.cancel_logic_edit()

        LoggerService.log_message(
            (
                f"Changed condition {index + 1} on trigger "
                f"[{trigger.trigger_id}] to {new_label}."
            ),
            context="change_condition_type",
        )
        self.statusBar().showMessage(
            f"Changed condition {index + 1} to {new_label}.",
            5000,
        )

    def delete_selected_logic_item(self):
        item = self.trigger_logic_list.currentItem()
        item_data = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(item_data, dict):
            return
        trigger = self.selected_trigger_object()
        if trigger is None:
            return
        kind = item_data["kind"]
        logic_object = item_data["object"]
        index = item_data["display_index"]
        kind_label = kind.title()
        result = QMessageBox.question(
            self,
            f"Delete {kind_label}",
            f"Delete this {kind}?\n\nThis action can be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return
        command = DeleteLogicObjectCommand(
            trigger, kind, logic_object, index,
            description=f"Delete {kind_label}",
        )
        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error, scenario_path=self.scenario_service.current_file,
                context="delete_logic_item",
            )
            QMessageBox.critical(
                self, f"Delete {kind_label} Failed", str(error)
            )
            return
        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.cancel_logic_edit()
        self.update_undo_redo_actions()

    def move_selected_condition_up(self):
        self.move_selected_condition(-1)

    def move_selected_condition_down(self):
        self.move_selected_condition(1)

    def move_selected_condition(self, direction):
        item = self.trigger_logic_list.currentItem()
        item_data = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(item_data, dict) or item_data.get("kind") != "condition":
            return

        trigger = self.selected_trigger_object()
        if trigger is None:
            return

        condition = item_data["object"]
        old_index = item_data["display_index"]
        new_index = old_index + direction
        if new_index < 0 or new_index >= len(trigger.conditions):
            return

        direction_label = "Up" if direction < 0 else "Down"
        command = MoveLogicObjectCommand(
            trigger,
            "condition",
            condition,
            old_index,
            new_index,
            description=f"Move Condition {direction_label}",
        )
        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="move_condition",
            )
            QMessageBox.critical(
                self,
                "Move Condition Failed",
                f"The condition could not be moved.\n\n{error}",
            )
            return

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.select_logic_object(condition)
        self.update_undo_redo_actions()
        LoggerService.log_message(
            (
                f"Moved condition on trigger [{trigger.trigger_id}] "
                f"from {old_index + 1} to {new_index + 1}."
            ),
            context="move_condition",
        )
        self.statusBar().showMessage(
            f"Moved condition {direction_label.lower()}.",
            5000,
        )

    def edit_logic_item(self, item):
        item_data = item.data(Qt.UserRole)

        if not isinstance(item_data, dict):
            return

        kind = item_data["kind"]
        logic_object = item_data["object"]
        display_index = item_data["display_index"]

        if kind == "condition":
            if self.open_wave_1_condition_editor(
                logic_object,
                display_index,
            ):
                return

            QMessageBox.information(
                self,
                "Condition Editor Not Available",
                "This condition type is not editable yet.",
            )
            return

        if kind == "effect":
            if self.open_trigger_effect_editor(
                logic_object,
                display_index,
            ):
                return

            QMessageBox.information(
                self,
                "Effect Editor Not Available",
                "This effect type is not editable yet.",
            )

    @staticmethod
    def set_combo_data(combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
            return True
        return False

    def selected_trigger_object(self):
        selected_item = self.trigger_list.currentItem()
        scenario = self.scenario_service.scenario

        if selected_item is None or scenario is None:
            return None

        trigger_id = selected_item.data(Qt.UserRole)
        for trigger in scenario.trigger_manager.triggers:
            if trigger.trigger_id == trigger_id:
                return trigger

        return None

    def populate_trigger_effect_targets(
        self,
        source_trigger,
        current_target_id,
    ):
        scenario = self.scenario_service.scenario
        self.edit_trigger_effect_target.clear()

        if scenario is None:
            return False

        selected_index = -1
        for trigger in scenario.trigger_manager.triggers:
            if trigger is source_trigger:
                continue

            trigger_name = (trigger.name or "").strip()
            if not trigger_name:
                trigger_name = "Unnamed Trigger"

            self.edit_trigger_effect_target.addItem(
                f"[{trigger.trigger_id}] {trigger_name}",
                trigger.trigger_id,
            )
            if trigger.trigger_id == current_target_id:
                selected_index = (
                    self.edit_trigger_effect_target.count() - 1
                )

        completer = QCompleter(
            self.edit_trigger_effect_target.model(),
            self.edit_trigger_effect_target,
        )
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.edit_trigger_effect_target.setCompleter(completer)

        if selected_index >= 0:
            self.edit_trigger_effect_target.setCurrentIndex(
                selected_index
            )
            return True

        return False

    def open_trigger_effect_editor(
        self,
        effect,
        display_index,
    ):
        effect_type = getattr(effect, "effect_type", -1)

        if effect_type == EffectId.TRIBUTE.value:
            trigger = self.selected_trigger_object()
            if trigger is None:
                return False
            self.set_combo_data(self.edit_tribute_source_player, getattr(effect, "source_player", 1))
            self.set_combo_data(self.edit_tribute_target_player, getattr(effect, "target_player", 1))
            self.set_combo_data(self.edit_tribute_resource, getattr(effect, "tribute_list", 0))
            self.edit_tribute_quantity.setValue(max(0, getattr(effect, "quantity", 0)))
            self.current_edit_logic_object = effect
            self.current_edit_trigger = trigger
            self.current_edit_kind = "effect"
            self.current_edit_display_index = display_index
            self.logic_editor_group.setTitle(f"Edit Effect {display_index + 1} - Tribute")
            self.logic_editor_stack.setCurrentWidget(self.tribute_effect_editor_page)
            return True

        if effect_type == EffectId.CHANGE_OWNERSHIP.value:
            trigger = self.selected_trigger_object()
            if trigger is None:
                return False
            self.set_combo_data(self.edit_change_ownership_source_player, getattr(effect, "source_player", 1))
            self.set_combo_data(self.edit_change_ownership_target_player, getattr(effect, "target_player", 1))
            object_ids = getattr(effect, "selected_object_ids", []) or []
            self.edit_change_ownership_object_ids.setText(", ".join(map(str, object_ids)))
            self.current_edit_logic_object = effect
            self.current_edit_trigger = trigger
            self.current_edit_kind = "effect"
            self.current_edit_display_index = display_index
            self.logic_editor_group.setTitle(f"Edit Effect {display_index + 1} - Change Ownership")
            self.logic_editor_stack.setCurrentWidget(self.change_ownership_effect_editor_page)
            return True

        if effect_type == EffectId.RESEARCH_TECHNOLOGY.value:
            trigger = self.selected_trigger_object()
            if trigger is None:
                return False
            self.set_combo_data(
                self.edit_research_effect_player,
                getattr(effect, "source_player", 1),
            )
            self.set_combo_data(
                self.edit_research_effect_technology,
                getattr(effect, "technology", -1),
            )
            self.current_edit_logic_object = effect
            self.current_edit_trigger = trigger
            self.current_edit_kind = "effect"
            self.current_edit_display_index = display_index
            self.logic_editor_group.setTitle(
                f"Edit Effect {display_index + 1} - "
                "Research Technology"
            )
            self.logic_editor_stack.setCurrentWidget(
                self.research_technology_effect_editor_page
            )
            return True

        supported_types = {
            EffectId.ACTIVATE_TRIGGER.value: "Activate Trigger",
            EffectId.DEACTIVATE_TRIGGER.value: "Deactivate Trigger",
        }
        effect_label = supported_types.get(effect_type)
        if effect_label is None:
            return False

        trigger = self.selected_trigger_object()
        if trigger is None:
            return False

        current_target_id = getattr(effect, "trigger_id", -1)
        self.populate_trigger_effect_targets(
            trigger,
            current_target_id,
        )

        self.current_edit_logic_object = effect
        self.current_edit_trigger = trigger
        self.current_edit_kind = "effect"
        self.current_edit_display_index = display_index

        self.edit_trigger_effect_type_label.setText(effect_label)
        self.logic_editor_group.setTitle(
            f"Edit Effect {display_index + 1} - {effect_label}"
        )
        self.logic_editor_stack.setCurrentWidget(
            self.trigger_effect_editor_page
        )
        return True

    def apply_tribute_effect_edit(self):
        effect = self.current_edit_logic_object
        trigger = self.current_edit_trigger
        if effect is None or trigger is None:
            return
        old_values = {
            "source_player": getattr(effect, "source_player", -1),
            "target_player": getattr(effect, "target_player", -1),
            "tribute_list": getattr(effect, "tribute_list", -1),
            "quantity": getattr(effect, "quantity", -1),
        }
        new_values = {
            "source_player": self.edit_tribute_source_player.currentData(),
            "target_player": self.edit_tribute_target_player.currentData(),
            "tribute_list": self.edit_tribute_resource.currentData(),
            "quantity": self.edit_tribute_quantity.value(),
        }
        if old_values == new_values:
            self.cancel_logic_edit()
            return
        command = EditLogicObjectCommand(
            effect, old_values, new_values, trigger,
            description="Edit Tribute",
        )
        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="edit_effect",
            )
            QMessageBox.critical(
                self,
                "Edit Effect Failed",
                f"The effect could not be updated.\n\n{error}",
            )
            return
        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.select_logic_object(effect)
        self.update_undo_redo_actions()
        self.statusBar().showMessage("Updated Tribute effect.", 5000)

    def apply_change_ownership_effect_edit(self):
        effect = self.current_edit_logic_object
        trigger = self.current_edit_trigger
        if effect is None or trigger is None:
            return
        try:
            object_ids = EffectPickerDialog.parse_object_instance_ids(
                self.edit_change_ownership_object_ids.text()
            )
        except ValueError:
            object_ids = []
        source_player = self.edit_change_ownership_source_player.currentData()
        target_player = self.edit_change_ownership_target_player.currentData()
        if source_player is None or target_player is None or not object_ids:
            QMessageBox.warning(self, "Invalid Change Ownership Effect", "Select players and enter at least one valid object instance ID.")
            return
        old_values = {
            "source_player": getattr(effect, "source_player", -1),
            "target_player": getattr(effect, "target_player", -1),
            "selected_object_ids": list(getattr(effect, "selected_object_ids", []) or []),
        }
        new_values = {
            "source_player": source_player,
            "target_player": target_player,
            "selected_object_ids": object_ids,
        }
        if old_values == new_values:
            self.cancel_logic_edit()
            return
        command = EditLogicObjectCommand(effect, old_values, new_values, trigger, description="Edit Change Ownership")
        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(error, scenario_path=self.scenario_service.current_file, context="edit_effect")
            QMessageBox.critical(self, "Edit Effect Failed", f"The effect could not be updated.\n\n{error}")
            return
        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.select_logic_object(effect)
        self.update_undo_redo_actions()
        self.statusBar().showMessage("Updated Change Ownership effect.", 5000)

    def apply_research_technology_effect_edit(self):
        effect = self.current_edit_logic_object
        trigger = self.current_edit_trigger
        if effect is None or trigger is None:
            return
        if getattr(effect, "effect_type", -1) != (
            EffectId.RESEARCH_TECHNOLOGY.value
        ):
            return

        source_player = self.edit_research_effect_player.currentData()
        technology = self.edit_research_effect_technology.currentData()
        if source_player is None or technology is None:
            QMessageBox.warning(
                self,
                "Invalid Research Technology Effect",
                "Select a player and technology from the dropdown lists.",
            )
            return

        old_values = {
            "source_player": getattr(effect, "source_player", -1),
            "technology": getattr(effect, "technology", -1),
        }
        new_values = {
            "source_player": source_player,
            "technology": technology,
        }
        if old_values == new_values:
            self.cancel_logic_edit()
            return

        command = EditLogicObjectCommand(
            effect,
            old_values,
            new_values,
            trigger,
            description="Edit Research Technology",
        )
        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="edit_effect",
            )
            QMessageBox.critical(
                self,
                "Edit Effect Failed",
                f"The effect could not be updated.\n\n{error}",
            )
            return

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.select_logic_object(effect)
        self.update_undo_redo_actions()
        LoggerService.log_message(
            (
                f"Updated Research Technology on trigger "
                f"[{trigger.trigger_id}]: {old_values} -> {new_values}"
            ),
            context="edit_effect",
        )
        self.statusBar().showMessage(
            "Updated Research Technology effect.",
            5000,
        )

    def apply_trigger_effect_edit(self):
        effect = self.current_edit_logic_object
        trigger = self.current_edit_trigger

        if effect is None or trigger is None:
            return

        effect_type = getattr(effect, "effect_type", -1)
        supported_types = {
            EffectId.ACTIVATE_TRIGGER.value: "Activate Trigger",
            EffectId.DEACTIVATE_TRIGGER.value: "Deactivate Trigger",
        }
        effect_label = supported_types.get(effect_type)
        if effect_label is None:
            return

        target_trigger_id = (
            self.edit_trigger_effect_target.currentData()
        )
        if target_trigger_id is None:
            QMessageBox.warning(
                self,
                "Invalid Target Trigger",
                "Select a target trigger from the dropdown list.",
            )
            return

        old_values = {
            "trigger_id": getattr(effect, "trigger_id", -1),
        }
        new_values = {
            "trigger_id": target_trigger_id,
        }

        if old_values == new_values:
            self.cancel_logic_edit()
            return

        command = EditLogicObjectCommand(
            effect,
            old_values,
            new_values,
            trigger,
            description=f"Edit {effect_label}",
        )

        try:
            self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="edit_effect",
            )
            QMessageBox.critical(
                self,
                "Edit Effect Failed",
                f"The effect could not be updated.\n\n{error}",
            )
            return

        self.scenario_service.mark_modified()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.select_logic_object(effect)
        self.update_undo_redo_actions()

        LoggerService.log_message(
            (
                f"Updated {effect_label} on trigger "
                f"[{trigger.trigger_id}]: {old_values} -> {new_values}"
            ),
            context="edit_effect",
        )
        self.statusBar().showMessage(
            f"Updated {effect_label} effect.",
            5000,
        )

    def open_wave_1_condition_editor(
        self,
        condition,
        display_index,
    ):
        condition_type = getattr(condition, "condition_type", -1)
        trigger = self.selected_trigger_object()

        if trigger is None:
            return False

        self.current_edit_logic_object = condition
        self.current_edit_trigger = trigger
        self.current_edit_kind = "condition"
        self.current_edit_display_index = display_index

        if condition_type == ConditionId.TIMER.value:
            self.edit_timer_seconds.setValue(
                max(0, getattr(condition, "timer", 0))
            )
            self.edit_timer_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.timer_editor_page
            label = "Timer"

        elif condition_type == ConditionId.AND.value:
            page = self.and_editor_page
            label = "Condition Joiner"

        elif condition_type == ConditionId.OR.value:
            page = self.or_editor_page
            label = "Condition Separator"

        elif condition_type == ConditionId.AI_SIGNAL.value:
            self.edit_ai_signal_value.setValue(
                getattr(condition, "ai_signal", -1)
            )
            self.edit_ai_signal_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.ai_signal_editor_page
            label = "AI Signal"

        elif condition_type == ConditionId.AI_SIGNAL_MULTIPLAYER.value:
            signal_value = getattr(condition, "ai_signal", 0)
            self.set_combo_data(
                self.edit_multiplayer_ai_signal_value,
                max(0, min(255, signal_value)),
            )
            self.edit_multiplayer_ai_signal_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.multiplayer_ai_signal_editor_page
            label = "Multiplayer AI Signal"

        elif condition_type == ConditionId.OWN_OBJECTS.value:
            self.set_combo_data(
                self.edit_own_objects_player,
                getattr(condition, "source_player", 1),
            )
            self.set_combo_data(
                self.edit_own_objects_unit,
                getattr(condition, "object_list", -1),
            )
            self.edit_own_objects_quantity.setValue(
                max(1, getattr(condition, "quantity", 1))
            )
            self.edit_own_objects_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.own_objects_editor_page
            label = "Own Objects"

        elif condition_type == ConditionId.OWN_FEWER_OBJECTS.value:
            self.set_combo_data(
                self.edit_own_fewer_player,
                getattr(condition, "source_player", 1),
            )
            self.set_combo_data(
                self.edit_own_fewer_unit,
                getattr(condition, "object_list", -1),
            )
            self.edit_own_fewer_quantity.setValue(
                max(1, getattr(condition, "quantity", 1))
            )
            self.edit_own_fewer_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.own_fewer_editor_page
            label = "Own Fewer Objects"

        elif condition_type == ConditionId.OBJECTS_IN_AREA.value:
            self.set_combo_data(
                self.edit_objects_area_player,
                getattr(condition, "source_player", 1),
            )
            self.set_combo_data(
                self.edit_objects_area_unit,
                getattr(condition, "object_list", -1),
            )
            self.edit_objects_area_quantity.setValue(
                max(1, getattr(condition, "quantity", 1))
            )
            self.edit_objects_area_x1.setValue(
                max(0, getattr(condition, "area_x1", 0))
            )
            self.edit_objects_area_y1.setValue(
                max(0, getattr(condition, "area_y1", 0))
            )
            self.edit_objects_area_x2.setValue(
                max(0, getattr(condition, "area_x2", 0))
            )
            self.edit_objects_area_y2.setValue(
                max(0, getattr(condition, "area_y2", 0))
            )
            self.edit_objects_area_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.objects_area_editor_page
            label = "Objects In Area"

        elif condition_type == ConditionId.ACCUMULATE_ATTRIBUTE.value:
            self.set_combo_data(self.edit_accumulate_attribute_player, getattr(condition, "source_player", 1))
            self.set_combo_data(self.edit_accumulate_attribute_resource, getattr(condition, "attribute", 0))
            self.edit_accumulate_attribute_quantity.setValue(max(0, getattr(condition, "quantity", 0)))
            self.edit_accumulate_attribute_inverted.setChecked(bool(getattr(condition, "inverted", 0)))
            page = self.accumulate_attribute_editor_page
            label = "Accumulate Attribute"

        elif condition_type == ConditionId.RESEARCH_TECHNOLOGY.value:
            self.set_combo_data(
                self.edit_research_technology_player,
                getattr(condition, "source_player", 1),
            )
            self.set_combo_data(
                self.edit_research_technology_technology,
                getattr(condition, "technology", -1),
            )
            self.edit_research_technology_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.research_technology_editor_page
            label = "Research Technology"

        elif condition_type == ConditionId.BUILDING_IS_TRADING.value:
            self.edit_building_is_trading_unit_object.setValue(
                max(0, getattr(condition, "unit_object", 0))
            )
            self.edit_building_is_trading_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.building_is_trading_editor_page
            label = "Building Is Trading"

        elif condition_type == ConditionId.CAPTURE_OBJECT.value:
            self.edit_capture_object_unit_object.setValue(
                max(0, getattr(condition, "unit_object", 0))
            )
            capture_player = getattr(condition, "source_player", 1)
            capture_player_index = (
                self.edit_capture_object_source_player.findData(
                    capture_player
                )
            )
            if capture_player_index >= 0:
                self.edit_capture_object_source_player.setCurrentIndex(
                    capture_player_index
                )
            self.edit_capture_object_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.capture_object_editor_page
            label = "Capture Object"

        elif condition_type == ConditionId.CHANCE.value:
            self.edit_chance_quantity.setValue(
                max(0, min(100, getattr(condition, "quantity", 0)))
            )
            page = self.chance_editor_page
            label = "Chance"

        elif condition_type == ConditionId.COMPARE_VARIABLES.value:
            self.edit_compare_variables_variable.setValue(max(0, getattr(condition, "variable", 0)))
            comparison_index = self.edit_compare_variables_comparison.findData(getattr(condition, "comparison", 0))
            if comparison_index >= 0:
                self.edit_compare_variables_comparison.setCurrentIndex(comparison_index)
            self.edit_compare_variables_variable2.setValue(max(0, getattr(condition, "variable2", 0)))
            self.edit_compare_variables_inverted.setChecked(bool(getattr(condition, "inverted", 0)))
            page = self.compare_variables_editor_page
            label = "Compare Variables"

        elif condition_type == ConditionId.DECISION_TRIGGERED.value:
            self.edit_decision_triggered_id.setValue(
                max(0, getattr(condition, "decision_id", 0))
            )
            decision_option = getattr(condition, "decision_option", -1)
            decision_option_index = (
                self.edit_decision_triggered_option.findData(
                    decision_option
                )
            )
            if decision_option_index >= 0:
                self.edit_decision_triggered_option.setCurrentIndex(
                    decision_option_index
                )
            self.edit_decision_triggered_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.decision_triggered_editor_page
            label = "Decision Triggered"

        elif condition_type == ConditionId.DIFFICULTY_LEVEL.value:
            difficulty_value = getattr(condition, "quantity", DifficultyLevel.STANDARD.value)
            difficulty_index = self.edit_difficulty_level_value.findData(
                difficulty_value
            )
            if difficulty_index >= 0:
                self.edit_difficulty_level_value.setCurrentIndex(
                    difficulty_index
                )
            self.edit_difficulty_level_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.difficulty_level_editor_page
            label = "Difficulty Level"

        elif condition_type == ConditionId.DIPLOMACY_STATE.value:
            self.set_combo_data(
                self.edit_diplomacy_state_source_player,
                getattr(condition, "source_player", 1),
            )
            self.set_combo_data(
                self.edit_diplomacy_state_target_player,
                getattr(condition, "target_player", 2),
            )
            self.set_combo_data(
                self.edit_diplomacy_state_value,
                getattr(condition, "quantity", DiplomacyState.ALLY.value),
            )
            self.edit_diplomacy_state_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.diplomacy_state_editor_page
            label = "Diplomacy State"

        elif condition_type == ConditionId.DISPLAY_TIMER_TRIGGERED.value:
            timer_id = getattr(condition, "timer_id", 0)
            timer_index = self.edit_display_timer_triggered_timer_id.findData(timer_id)
            if timer_index < 0:
                self.edit_display_timer_triggered_timer_id.addItem(
                    f"Timer {timer_id} (outside game UI range)", timer_id
                )
                timer_index = self.edit_display_timer_triggered_timer_id.count() - 1
            self.edit_display_timer_triggered_timer_id.setCurrentIndex(timer_index)
            self.edit_display_timer_triggered_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.display_timer_triggered_editor_page
            label = "Display Timer Triggered"

        elif condition_type == ConditionId.DESTROY_OBJECT.value:
            self.edit_destroy_object_unit_object.setValue(
                max(0, getattr(condition, "unit_object", 0))
            )
            self.edit_destroy_object_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.destroy_object_editor_page
            label = "Destroy Object"

        elif condition_type == ConditionId.HERO_POWER_CAST.value:
            self.set_combo_data(
                self.edit_hero_power_cast_source_player,
                getattr(condition, "source_player", 1),
            )
            page = self.hero_power_cast_editor_page
            label = "Hero Power Cast"

        elif condition_type == ConditionId.LOCAL_TECH_RESEARCHED.value:
            self.set_combo_data(self.edit_local_tech_player, getattr(condition, "source_player", 1))
            self.set_combo_data(self.edit_local_tech_technology, getattr(condition, "local_technology", 1323))
            self.edit_local_tech_object.setValue(getattr(condition, "unit_object", -1))
            self.edit_local_tech_quantity.setValue(getattr(condition, "quantity", -1))
            self.edit_local_tech_x1.setValue(getattr(condition, "area_x1", -1))
            self.edit_local_tech_y1.setValue(getattr(condition, "area_y1", -1))
            self.edit_local_tech_x2.setValue(getattr(condition, "area_x2", -1))
            self.edit_local_tech_y2.setValue(getattr(condition, "area_y2", -1))
            self.edit_local_tech_inverted.setChecked(bool(getattr(condition, "inverted", 0)))
            page = self.local_tech_editor_page
            label = "Local Tech Researched"

        elif condition_type == ConditionId.BRING_OBJECT_TO_OBJECT.value:
            self.edit_bring_object_to_object_unit_object.setValue(
                max(0, getattr(condition, "unit_object", 0))
            )
            self.edit_bring_object_to_object_next_object.setValue(
                max(0, getattr(condition, "next_object", 0))
            )
            self.edit_bring_object_to_object_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.bring_object_to_object_editor_page
            label = "Bring Object To Object"

        elif condition_type == ConditionId.BRING_OBJECT_TO_AREA.value:
            self.edit_bring_object_to_area_unit_object.setValue(
                max(0, getattr(condition, "unit_object", 0))
            )
            self.edit_bring_object_to_area_x1.setValue(
                max(0, getattr(condition, "area_x1", 0))
            )
            self.edit_bring_object_to_area_y1.setValue(
                max(0, getattr(condition, "area_y1", 0))
            )
            self.edit_bring_object_to_area_x2.setValue(
                max(0, getattr(condition, "area_x2", 0))
            )
            self.edit_bring_object_to_area_y2.setValue(
                max(0, getattr(condition, "area_y2", 0))
            )
            self.edit_bring_object_to_area_inverted.setChecked(
                bool(getattr(condition, "inverted", 0))
            )
            page = self.bring_object_to_area_editor_page
            label = "Bring Object To Area"

        else:
            return False

        self.logic_editor_group.setTitle(
            f"Edit Condition {display_index + 1} - {label}"
        )
        self.logic_editor_stack.setCurrentWidget(page)
        return True

    def wave_1_condition_new_values(self, condition_type):
        if condition_type == ConditionId.AI_SIGNAL.value:
            return {
                "ai_signal": self.edit_ai_signal_value.value(),
                "inverted": int(self.edit_ai_signal_inverted.isChecked()),
            }

        if condition_type == ConditionId.AI_SIGNAL_MULTIPLAYER.value:
            return {
                "ai_signal": self.edit_multiplayer_ai_signal_value.currentData(),
                "inverted": int(
                    self.edit_multiplayer_ai_signal_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.TIMER.value:
            return {
                "timer": self.edit_timer_seconds.value(),
                "inverted": int(
                    self.edit_timer_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.OWN_OBJECTS.value:
            return {
                "source_player": self.edit_own_objects_player.currentData(),
                "object_list": self.edit_own_objects_unit.currentData(),
                "quantity": self.edit_own_objects_quantity.value(),
                "inverted": int(
                    self.edit_own_objects_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.OWN_FEWER_OBJECTS.value:
            return {
                "source_player": self.edit_own_fewer_player.currentData(),
                "object_list": self.edit_own_fewer_unit.currentData(),
                "quantity": self.edit_own_fewer_quantity.value(),
                "inverted": int(
                    self.edit_own_fewer_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.OBJECTS_IN_AREA.value:
            x1 = self.edit_objects_area_x1.value()
            y1 = self.edit_objects_area_y1.value()
            x2 = self.edit_objects_area_x2.value()
            y2 = self.edit_objects_area_y2.value()
            return {
                "source_player": self.edit_objects_area_player.currentData(),
                "object_list": self.edit_objects_area_unit.currentData(),
                "quantity": self.edit_objects_area_quantity.value(),
                "area_x1": min(x1, x2),
                "area_y1": min(y1, y2),
                "area_x2": max(x1, x2),
                "area_y2": max(y1, y2),
                "inverted": int(
                    self.edit_objects_area_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.ACCUMULATE_ATTRIBUTE.value:
            return {
                "source_player": self.edit_accumulate_attribute_player.currentData(),
                "attribute": self.edit_accumulate_attribute_resource.currentData(),
                "quantity": self.edit_accumulate_attribute_quantity.value(),
                "inverted": int(self.edit_accumulate_attribute_inverted.isChecked()),
            }

        if condition_type == ConditionId.RESEARCH_TECHNOLOGY.value:
            return {
                "source_player": (
                    self.edit_research_technology_player.currentData()
                ),
                "technology": (
                    self.edit_research_technology_technology.currentData()
                ),
                "inverted": int(
                    self.edit_research_technology_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.BUILDING_IS_TRADING.value:
            return {
                "unit_object": (
                    self.edit_building_is_trading_unit_object.value()
                ),
                "inverted": int(
                    self.edit_building_is_trading_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.CAPTURE_OBJECT.value:
            return {
                "unit_object": self.edit_capture_object_unit_object.value(),
                "source_player": (
                    self.edit_capture_object_source_player.currentData()
                ),
                "inverted": int(
                    self.edit_capture_object_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.CHANCE.value:
            return {"quantity": self.edit_chance_quantity.value()}

        if condition_type == ConditionId.COMPARE_VARIABLES.value:
            return {
                "variable": self.edit_compare_variables_variable.value(),
                "comparison": self.edit_compare_variables_comparison.currentData(),
                "variable2": self.edit_compare_variables_variable2.value(),
                "inverted": int(self.edit_compare_variables_inverted.isChecked()),
            }

        if condition_type == ConditionId.DECISION_TRIGGERED.value:
            return {
                "decision_id": self.edit_decision_triggered_id.value(),
                "decision_option": (
                    self.edit_decision_triggered_option.currentData()
                ),
                "inverted": int(
                    self.edit_decision_triggered_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.DIFFICULTY_LEVEL.value:
            return {
                "quantity": self.edit_difficulty_level_value.currentData(),
                "inverted": int(
                    self.edit_difficulty_level_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.DIPLOMACY_STATE.value:
            return {
                "quantity": self.edit_diplomacy_state_value.currentData(),
                "source_player": self.edit_diplomacy_state_source_player.currentData(),
                "target_player": self.edit_diplomacy_state_target_player.currentData(),
                "inverted": int(self.edit_diplomacy_state_inverted.isChecked()),
            }

        if condition_type == ConditionId.DISPLAY_TIMER_TRIGGERED.value:
            return {
                "timer_id": self.edit_display_timer_triggered_timer_id.currentData(),
                "inverted": int(self.edit_display_timer_triggered_inverted.isChecked()),
            }

        if condition_type == ConditionId.DESTROY_OBJECT.value:
            return {
                "unit_object": (
                    self.edit_destroy_object_unit_object.value()
                ),
                "inverted": int(
                    self.edit_destroy_object_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.HERO_POWER_CAST.value:
            return {
                "source_player": self.edit_hero_power_cast_source_player.currentData(),
            }

        if condition_type == ConditionId.LOCAL_TECH_RESEARCHED.value:
            return {
                "local_technology": self.edit_local_tech_technology.currentData(),
                "source_player": self.edit_local_tech_player.currentData(),
                "unit_object": self.edit_local_tech_object.value(),
                "area_x1": self.edit_local_tech_x1.value(),
                "area_y1": self.edit_local_tech_y1.value(),
                "area_x2": self.edit_local_tech_x2.value(),
                "area_y2": self.edit_local_tech_y2.value(),
                "quantity": self.edit_local_tech_quantity.value(),
                "inverted": int(self.edit_local_tech_inverted.isChecked()),
            }

        if condition_type == ConditionId.BRING_OBJECT_TO_OBJECT.value:
            return {
                "unit_object": (
                    self.edit_bring_object_to_object_unit_object.value()
                ),
                "next_object": (
                    self.edit_bring_object_to_object_next_object.value()
                ),
                "inverted": int(
                    self.edit_bring_object_to_object_inverted.isChecked()
                ),
            }

        if condition_type == ConditionId.BRING_OBJECT_TO_AREA.value:
            x1 = self.edit_bring_object_to_area_x1.value()
            y1 = self.edit_bring_object_to_area_y1.value()
            x2 = self.edit_bring_object_to_area_x2.value()
            y2 = self.edit_bring_object_to_area_y2.value()
            return {
                "unit_object": (
                    self.edit_bring_object_to_area_unit_object.value()
                ),
                "area_x1": min(x1, x2),
                "area_y1": min(y1, y2),
                "area_x2": max(x1, x2),
                "area_y2": max(y1, y2),
                "inverted": int(
                    self.edit_bring_object_to_area_inverted.isChecked()
                ),
            }

        return None

    def apply_wave_1_condition_edit(self):
        condition = self.current_edit_logic_object
        trigger = self.current_edit_trigger

        if condition is None or trigger is None:
            return

        condition_type = getattr(condition, "condition_type", -1)
        new_values = self.wave_1_condition_new_values(condition_type)

        if new_values is None:
            return

        if new_values.get("object_list", 0) is None:
            QMessageBox.warning(
                self,
                "Invalid Object Selection",
                "Select an object from the dropdown list.",
            )
            return

        old_values = {
            field_name: getattr(condition, field_name)
            for field_name in new_values
        }

        if old_values == new_values:
            self.cancel_logic_edit()
            return

        try:
            condition_name = ConditionId(condition_type).name
            condition_name = condition_name.replace("_", " ").title()
        except Exception:
            condition_name = "Condition"

        command = EditLogicObjectCommand(
            condition,
            old_values,
            new_values,
            trigger,
            description=f"Edit {condition_name}",
        )

        try:
            recorded_command = self.undo_manager.execute(command)
        except Exception as error:
            LoggerService.log_exception(
                error,
                scenario_path=self.scenario_service.current_file,
                context="edit_condition",
            )
            QMessageBox.critical(
                self,
                "Edit Condition Failed",
                f"The condition could not be updated.\n\n{error}",
            )
            return

        # Compatibility safeguard: execute() should retain the command. If a
        # stale UndoManager implementation does not, register the already-
        # executed command without applying the edit a second time.
        if not self.undo_manager.can_undo():
            undo_stack = getattr(self.undo_manager, "_undo_stack", None)
            redo_stack = getattr(self.undo_manager, "_redo_stack", None)

            if undo_stack is None or redo_stack is None:
                QMessageBox.critical(
                    self,
                    "Undo History Error",
                    (
                        "The condition was changed, but the edit could not "
                        "be recorded in Undo history."
                    ),
                )
                return

            undo_stack.append(recorded_command or command)
            redo_stack.clear()

        self.scenario_service.mark_modified()
        self.update_undo_redo_actions()
        self.refresh_trigger_ui()
        self.select_trigger_object(trigger)
        self.select_logic_object(condition)
        self.update_undo_redo_actions()

        LoggerService.log_message(
            (
                f"Updated {condition_name} on trigger "
                f"[{trigger.trigger_id}]: {old_values} -> {new_values}; "
                f"undo_available={self.undo_manager.can_undo()}"
            ),
            context="edit_condition",
        )
        self.statusBar().showMessage(
            f"Updated {condition_name} condition.",
            5000,
        )

    def select_logic_object(self, logic_object):
        for row in range(self.trigger_logic_list.count()):
            item = self.trigger_logic_list.item(row)
            item_data = item.data(Qt.UserRole)
            if (
                isinstance(item_data, dict)
                and item_data.get("object") is logic_object
            ):
                self.trigger_logic_list.setCurrentRow(row)
                self.trigger_logic_list.scrollToItem(
                    item,
                    QAbstractItemView.PositionAtCenter,
                )
                return True
        return False

    def cancel_logic_edit(self):
        self.current_edit_logic_object = None
        self.current_edit_trigger = None
        self.current_edit_kind = None
        self.current_edit_display_index = None
        self.logic_editor_group.setTitle("Item Editor")
        self.logic_editor_stack.setCurrentWidget(
            self.logic_summary_page
        )
        self.trigger_details.clear()

    def show_trigger_details(self, row):
        self.clear_logic_list()
        self.logic_editor_group.setTitle("Item Editor")
        self.logic_editor_stack.setCurrentWidget(
            self.logic_summary_page
        )
        self.trigger_details.clear()

        if row < 0:
            self.trigger_logic_group.setTitle("Trigger Logic")
            return

        selected_item = self.trigger_list.currentItem()

        if selected_item is None:
            return

        scenario = self.scenario_service.scenario

        if scenario is None:
            return

        trigger_id = selected_item.data(Qt.UserRole)
        trigger = next(
            (
                current_trigger
                for current_trigger in scenario.trigger_manager.triggers
                if current_trigger.trigger_id == trigger_id
            ),
            None,
        )

        if trigger is None:
            return

        self.populate_logic_list(trigger)
