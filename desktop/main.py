from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.core.command_worker import CommandWorker
from desktop.core.device_manager import list_devices, resolve_adb
from desktop.core.runner import build_capture_command, build_child_environment, build_replay_command
from desktop.core.workflow import list_workflows, summarize_workflow


APP_NAME = "ADB Flow Studio"
DATA_DIR = Path.home() / "Documents" / APP_NAME
WORKFLOWS_DIR = DATA_DIR / "workflows"
LOGS_DIR = DATA_DIR / "logs"
STATE_ROLE = int(Qt.ItemDataRole.UserRole) + 1


STYLESHEET = """
QMainWindow, QWidget#MainCanvas { background: #F4F7FB; color: #172033; }
QFrame#Sidebar { background: #111827; border: none; }
QLabel#Brand { color: #FFFFFF; font-size: 20px; font-weight: 800; letter-spacing: 1px; }
QLabel#BrandSub { color: #98A2B3; font-size: 10px; font-weight: 600; }
QPushButton#NavButton { color: #B7C0CF; background: transparent; text-align: left; padding: 12px 14px; border: none; border-radius: 9px; font-size: 13px; font-weight: 600; }
QPushButton#NavButton:hover { background: #1F2937; color: #FFFFFF; }
QPushButton#NavButton:checked { background: #25324A; color: #FFFFFF; border-left: 3px solid #4F8CFF; }
QLabel#PageTitle { font-size: 25px; font-weight: 800; color: #101828; }
QLabel#PageSubtitle { font-size: 12px; color: #667085; }
QLabel#Muted { color: #667085; }
QLabel#CardTitle { color: #667085; font-size: 11px; font-weight: 700; }
QLabel#CardValue { color: #101828; font-size: 22px; font-weight: 800; }
QFrame#Panel { background: #FFFFFF; border: 1px solid #E4E7EC; border-radius: 14px; }
QFrame#MetricCard { background: #FFFFFF; border: 1px solid #E4E7EC; border-radius: 13px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #FFFFFF; color: #101828; border: 1px solid #D0D5DD; border-radius: 8px; padding: 8px 10px; min-height: 20px; }
QComboBox QAbstractItemView { background: #FFFFFF; selection-background-color: #E8F0FF; color: #101828; }
QCheckBox { color: #344054; spacing: 8px; }
QPushButton { background: #FFFFFF; color: #344054; border: 1px solid #D0D5DD; border-radius: 8px; padding: 9px 13px; font-weight: 600; }
QPushButton:hover { background: #F9FAFB; }
QPushButton:disabled { color: #98A2B3; background: #F2F4F7; border-color: #EAECF0; }
QPushButton#PrimaryButton { background: #246BFD; color: #FFFFFF; border: 1px solid #246BFD; }
QPushButton#PrimaryButton:hover { background: #1758DC; }
QPushButton#DangerButton { background: #FFF1F0; color: #B42318; border: 1px solid #FECDCA; }
QPushButton#DangerButton:hover { background: #FEE4E2; }
QLabel#StatusPill { background: #EAF7EF; color: #167647; border: 1px solid #B7E4C7; border-radius: 10px; padding: 6px 10px; font-weight: 700; }
QLabel#StatusPill[offline="true"] { background: #FFF4E5; color: #9A6700; border-color: #F5D49A; }
QPlainTextEdit { background: #101828; color: #D0D5DD; border: 1px solid #25324A; border-radius: 10px; padding: 8px; font-family: Consolas, 'Cascadia Mono', monospace; font-size: 11px; }
QListWidget { background: #FFFFFF; border: 1px solid #E4E7EC; border-radius: 9px; padding: 4px; }
QListWidget::item { padding: 10px; border-radius: 6px; }
QListWidget::item:selected { background: #E8F0FF; color: #1849A9; }
QProgressBar { background: #EAECF0; border: none; border-radius: 6px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #246BFD; border-radius: 6px; }
"""


def _panel() -> QFrame:
    frame = QFrame()
    frame.setObjectName("Panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)
    return frame


def _section_title(title: str, subtitle: str = "") -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    title_label = QLabel(title)
    title_label.setStyleSheet("font-size: 15px; font-weight: 800; color: #101828;")
    layout.addWidget(title_label)
    if subtitle:
        sub_label = QLabel(subtitle)
        sub_label.setObjectName("Muted")
        sub_label.setWordWrap(True)
        layout.addWidget(sub_label)
    return widget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1050, 700)
        self.resize(1280, 820)
        self.settings = QSettings("ADBFlowStudio", "ADBFlowStudio")
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.adb_path = str(self.settings.value("adbPath", "", type=str) or "")
        self.resolved_adb_path: Path | None = None
        self.active_worker: CommandWorker | None = None
        self.active_operation = ""
        self.capture_output_path = ""

        self._build_ui()
        self.refresh_workflows()
        self.refresh_devices()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("MainCanvas")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(218)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(16, 24, 16, 18)
        side_layout.setSpacing(8)

        brand = QLabel("ADB FLOW")
        brand.setObjectName("Brand")
        brand_sub = QLabel("STUDIO  /  WINDOWS AUTOMATION")
        brand_sub.setObjectName("BrandSub")
        side_layout.addWidget(brand)
        side_layout.addWidget(brand_sub)
        side_layout.addSpacing(24)

        self.stack = QStackedWidget()
        self.nav_buttons: list[QPushButton] = []
        self.page_titles = [
            ("Dashboard", "Overview of your device and automation workflows"),
            ("Capture", "Record Android touch actions over ADB"),
            ("Replay", "Replay saved workflows with repeat and stop controls"),
            ("License", "Offline activation and license status"),
            ("Settings", "Configure ADB and local application preferences"),
        ]

        nav_items = [
            ("⌂", "Dashboard"),
            ("●", "Capture"),
            ("↻", "Replay"),
            ("♙", "License"),
            ("⚙", "Settings"),
        ]
        for index, (symbol, title) in enumerate(nav_items):
            button = QPushButton(f"  {symbol}     {title}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            side_layout.addWidget(button)
            self.nav_buttons.append(button)

        side_layout.addStretch(1)
        sidebar_footer = QLabel("ADB ONLY  •  OFFLINE-FIRST")
        sidebar_footer.setObjectName("BrandSub")
        side_layout.addWidget(sidebar_footer)

        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(28, 22, 28, 24)
        main_layout.setSpacing(18)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(14)
        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(4)
        self.page_title = QLabel("Dashboard")
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel(self.page_titles[0][1])
        self.page_subtitle.setObjectName("PageSubtitle")
        title_column.addWidget(self.page_title)
        title_column.addWidget(self.page_subtitle)
        header_layout.addLayout(title_column, 1)

        device_column = QVBoxLayout()
        device_column.setContentsMargins(0, 0, 0, 0)
        device_column.setSpacing(4)
        device_label = QLabel("ANDROID DEVICE")
        device_label.setObjectName("CardTitle")
        device_column.addWidget(device_label)
        device_row = QHBoxLayout()
        device_row.setSpacing(6)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(245)
        self.device_combo.currentIndexChanged.connect(self._update_device_status)
        device_row.addWidget(self.device_combo, 1)
        refresh_button = QPushButton("↻")
        refresh_button.setToolTip("Refresh connected Android devices")
        refresh_button.setFixedWidth(38)
        refresh_button.clicked.connect(self.refresh_devices)
        device_row.addWidget(refresh_button)
        device_column.addLayout(device_row)
        header_layout.addLayout(device_column)
        self.status_pill = QLabel("Checking ADB…")
        self.status_pill.setObjectName("StatusPill")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        main_layout.addWidget(header)

        self.dashboard_page = self._build_dashboard_page()
        self.capture_page = self._build_capture_page()
        self.replay_page = self._build_replay_page()
        self.license_page = self._build_license_page()
        self.settings_page = self._build_settings_page()
        for page in (
            self.dashboard_page,
            self.capture_page,
            self.replay_page,
            self.license_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)

        main_layout.addWidget(self.stack, 1)
        root_layout.addWidget(sidebar)
        root_layout.addWidget(main_area, 1)
        self.setCentralWidget(root)
        self.nav_buttons[0].setChecked(True)

    def _metric_card(self, title: str, value: str, detail: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName("MetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(7)
        title_label = QLabel(title.upper())
        title_label.setObjectName("CardTitle")
        value_label = QLabel(value)
        value_label.setObjectName("CardValue")
        detail_label = QLabel(detail)
        detail_label.setObjectName("Muted")
        detail_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)
        return card, value_label

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        intro = QFrame()
        intro.setObjectName("Panel")
        intro_layout = QHBoxLayout(intro)
        intro_layout.setContentsMargins(22, 20, 22, 20)
        intro_text = QVBoxLayout()
        welcome = QLabel("Your Android workflow, under control.")
        welcome.setStyleSheet("font-size: 20px; font-weight: 800; color: #101828;")
        description = QLabel(
            "Capture touch gestures, save them as JSON, and replay them through ADB. "
            "Keep the phone unlocked and on the intended screen before a real replay."
        )
        description.setObjectName("Muted")
        description.setWordWrap(True)
        intro_text.addWidget(welcome)
        intro_text.addWidget(description)
        intro_layout.addLayout(intro_text, 1)
        capture_quick = QPushButton("Start Capture")
        capture_quick.setObjectName("PrimaryButton")
        capture_quick.clicked.connect(lambda: self.switch_page(1))
        intro_layout.addWidget(capture_quick, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(intro)

        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        card, self.dashboard_device_value = self._metric_card("ADB Connection", "Checking…", "USB debugging status")
        metrics.addWidget(card)
        card, self.dashboard_workflow_value = self._metric_card("Saved Workflows", "0", "JSON files in your workflow folder")
        metrics.addWidget(card)
        card, self.dashboard_license_value = self._metric_card("License", "Phase 2", "Offline license activation is not wired yet")
        metrics.addWidget(card)
        layout.addLayout(metrics)

        lower = QHBoxLayout()
        lower.setSpacing(14)
        recent_panel = _panel()
        recent_panel.layout().addWidget(_section_title("Recent Workflows", "Select a saved workflow to prepare it for replay."))
        self.recent_workflows = QListWidget()
        self.recent_workflows.itemDoubleClicked.connect(self._open_recent_workflow)
        recent_panel.layout().addWidget(self.recent_workflows, 1)
        lower.addWidget(recent_panel, 3)

        quick_panel = _panel()
        quick_panel.layout().addWidget(_section_title("Quick Actions", "Common tasks"))
        replay_quick = QPushButton("↻   Open Replay Manager")
        replay_quick.clicked.connect(lambda: self.switch_page(2))
        settings_quick = QPushButton("⚙   Configure ADB")
        settings_quick.clicked.connect(lambda: self.switch_page(4))
        quick_panel.layout().addWidget(replay_quick)
        quick_panel.layout().addWidget(settings_quick)
        note = QLabel(
            "Safety note\nDry Run is enabled by default. It previews the workflow without sending touch input."
        )
        note.setWordWrap(True)
        note.setStyleSheet("background: #EFF6FF; color: #1849A9; border-radius: 8px; padding: 12px;")
        quick_panel.layout().addWidget(note)
        quick_panel.layout().addStretch(1)
        lower.addWidget(quick_panel, 2)
        layout.addLayout(lower, 1)
        return page

    def _build_capture_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        panel = _panel()
        panel.layout().addWidget(_section_title("Capture a Workflow", "Record single-finger taps, swipes, and long presses from the connected Android device."))
        path_label = QLabel("Save JSON as")
        path_label.setObjectName("CardTitle")
        panel.layout().addWidget(path_label)
        path_row = QHBoxLayout()
        self.capture_output_edit = QLineEdit()
        self.capture_output_edit.setText(str(WORKFLOWS_DIR / f"workflow-{datetime.now():%Y%m%d-%H%M%S}.json"))
        self.capture_output_edit.setPlaceholderText("Choose an output JSON file")
        path_row.addWidget(self.capture_output_edit, 1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_capture_output)
        path_row.addWidget(browse_button)
        panel.layout().addLayout(path_row)

        self.capture_state_checkbox = QCheckBox("Capture foreground/window snapshots")
        self.capture_state_checkbox.setChecked(True)
        self.capture_ui_checkbox = QCheckBox("Capture visible UI text (slower; may not work in every app)")
        self.capture_ui_checkbox.setChecked(False)
        panel.layout().addWidget(self.capture_state_checkbox)
        panel.layout().addWidget(self.capture_ui_checkbox)

        button_row = QHBoxLayout()
        self.capture_start_button = QPushButton("●   Start Capture")
        self.capture_start_button.setObjectName("PrimaryButton")
        self.capture_start_button.clicked.connect(self.start_capture)
        self.capture_stop_button = QPushButton("■   Stop and Save")
        self.capture_stop_button.setObjectName("DangerButton")
        self.capture_stop_button.setEnabled(False)
        self.capture_stop_button.clicked.connect(self.stop_operation)
        button_row.addWidget(self.capture_start_button)
        button_row.addWidget(self.capture_stop_button)
        button_row.addStretch(1)
        panel.layout().addLayout(button_row)
        self.capture_status_label = QLabel("Ready. Connect and authorize an Android device first.")
        self.capture_status_label.setObjectName("Muted")
        panel.layout().addWidget(self.capture_status_label)
        layout.addWidget(panel)

        log_panel = _panel()
        log_panel.layout().addWidget(_section_title("Capture Log", "Live output from the recorder."))
        self.capture_log = QPlainTextEdit()
        self.capture_log.setReadOnly(True)
        self.capture_log.setMinimumHeight(240)
        log_panel.layout().addWidget(self.capture_log, 1)
        layout.addWidget(log_panel, 1)
        return page

    def _build_replay_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        panel = _panel()
        panel.layout().addWidget(_section_title("Replay Manager", "Choose a workflow and control how many times it runs."))
        panel.layout().addWidget(QLabel("Workflow JSON"))
        workflow_row = QHBoxLayout()
        self.workflow_path_combo = QComboBox()
        self.workflow_path_combo.setEditable(True)
        self.workflow_path_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.workflow_path_combo.setMinimumWidth(400)
        self.workflow_path_combo.currentTextChanged.connect(self._update_workflow_summary)
        workflow_row.addWidget(self.workflow_path_combo, 1)
        browse_workflow = QPushButton("Browse…")
        browse_workflow.clicked.connect(self._browse_replay_input)
        workflow_row.addWidget(browse_workflow)
        reload_workflows_button = QPushButton("Refresh")
        reload_workflows_button.clicked.connect(self.refresh_workflows)
        workflow_row.addWidget(reload_workflows_button)
        panel.layout().addLayout(workflow_row)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        count_column = QVBoxLayout()
        count_column.addWidget(QLabel("Repeat count"))
        self.repeat_count_spin = QSpinBox()
        self.repeat_count_spin.setRange(1, 1000)
        self.repeat_count_spin.setValue(1)
        self.repeat_count_spin.setToolTip("Number of complete replay cycles.")
        count_column.addWidget(self.repeat_count_spin)
        controls.addLayout(count_column)

        delay_column = QVBoxLayout()
        delay_column.addWidget(QLabel("Delay between runs (seconds)"))
        self.repeat_delay_spin = QDoubleSpinBox()
        self.repeat_delay_spin.setRange(0, 3600)
        self.repeat_delay_spin.setDecimals(1)
        self.repeat_delay_spin.setSingleStep(1)
        self.repeat_delay_spin.setValue(1)
        delay_column.addWidget(self.repeat_delay_spin)
        controls.addLayout(delay_column)
        controls.addStretch(1)
        panel.layout().addLayout(controls)

        self.dry_run_checkbox = QCheckBox("Dry Run — preview only; do not touch the phone")
        self.dry_run_checkbox.setChecked(True)
        self.verify_state_checkbox = QCheckBox("Verify screen state before each action (may stop early)")
        self.verify_state_checkbox.setChecked(False)
        panel.layout().addWidget(self.dry_run_checkbox)
        panel.layout().addWidget(self.verify_state_checkbox)

        self.workflow_summary_label = QLabel("Select a workflow JSON file to see its action count.")
        self.workflow_summary_label.setObjectName("Muted")
        self.workflow_summary_label.setWordWrap(True)
        panel.layout().addWidget(self.workflow_summary_label)

        buttons = QHBoxLayout()
        self.replay_start_button = QPushButton("▶   Start Replay")
        self.replay_start_button.setObjectName("PrimaryButton")
        self.replay_start_button.clicked.connect(self.start_replay)
        self.replay_stop_button = QPushButton("■   Stop Replay")
        self.replay_stop_button.setObjectName("DangerButton")
        self.replay_stop_button.setEnabled(False)
        self.replay_stop_button.clicked.connect(self.stop_operation)
        buttons.addWidget(self.replay_start_button)
        buttons.addWidget(self.replay_stop_button)
        buttons.addStretch(1)
        panel.layout().addLayout(buttons)

        self.replay_progress_label = QLabel("Ready")
        self.replay_progress_label.setObjectName("Muted")
        panel.layout().addWidget(self.replay_progress_label)
        self.replay_progress = QProgressBar()
        self.replay_progress.setRange(0, 1)
        self.replay_progress.setValue(0)
        panel.layout().addWidget(self.replay_progress)
        layout.addWidget(panel)

        log_panel = _panel()
        log_panel.layout().addWidget(_section_title("Replay Log", "Each repeat cycle writes to a separate log file."))
        self.replay_log = QPlainTextEdit()
        self.replay_log.setReadOnly(True)
        self.replay_log.setMinimumHeight(190)
        log_panel.layout().addWidget(self.replay_log, 1)
        layout.addWidget(log_panel, 1)
        return page

    def _build_license_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = _panel()
        panel.layout().addWidget(_section_title("Offline License Manager", "License activation is planned for the next implementation phase."))
        status = QLabel("LICENSE SYSTEM NOT IMPLEMENTED IN THIS BUILD")
        status.setStyleSheet("background: #FFF4E5; color: #9A6700; border: 1px solid #F5D49A; border-radius: 8px; padding: 12px; font-weight: 800;")
        panel.layout().addWidget(status)
        body = QLabel(
            "The planned commercial version will use a digitally signed license key bound to a PC. "
            "License validation will run locally and will not require an internet connection. "
            "The private signing key will stay outside the application and source repository.\n\n"
            "This first desktop build does not yet enforce licensing and is not ready for commercial distribution."
        )
        body.setWordWrap(True)
        body.setStyleSheet("font-size: 13px; color: #344054; line-height: 1.4;")
        panel.layout().addWidget(body)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = _panel()
        panel.layout().addWidget(_section_title("ADB Configuration", "Select Android Platform Tools or use an adb executable already on PATH."))
        panel.layout().addWidget(QLabel("ADB executable path"))
        row = QHBoxLayout()
        self.adb_path_edit = QLineEdit(self.adb_path)
        self.adb_path_edit.setPlaceholderText("Example: C:\\platform-tools\\adb.exe")
        row.addWidget(self.adb_path_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_adb)
        row.addWidget(browse)
        panel.layout().addLayout(row)

        buttons = QHBoxLayout()
        auto_detect = QPushButton("Auto-detect ADB")
        auto_detect.clicked.connect(self._auto_detect_adb)
        save = QPushButton("Save Settings")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self.save_settings)
        buttons.addWidget(auto_detect)
        buttons.addWidget(save)
        buttons.addStretch(1)
        panel.layout().addLayout(buttons)

        help_label = QLabel(
            "On the phone, enable Developer options and USB debugging, connect by USB, then accept the "
            "authorization prompt. A device marked unauthorized must be approved on the phone."
        )
        help_label.setWordWrap(True)
        help_label.setObjectName("Muted")
        panel.layout().addWidget(help_label)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def switch_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.page_title.setText(self.page_titles[index][0])
        self.page_subtitle.setText(self.page_titles[index][1])
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

    def _current_adb_setting(self) -> str:
        if hasattr(self, "adb_path_edit"):
            return self.adb_path_edit.text().strip()
        return self.adb_path

    def refresh_devices(self) -> None:
        configured = self._current_adb_setting()
        adb = resolve_adb(configured or None)
        previous_serial = self.device_combo.currentData() if hasattr(self, "device_combo") else None
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if adb is None:
            self.resolved_adb_path = None
            self.device_combo.addItem("ADB not found — configure Settings", None)
            self.status_pill.setText("ADB not found")
            self.status_pill.setProperty("offline", True)
            self.dashboard_device_value.setText("Not found")
            self.device_combo.blockSignals(False)
            self._refresh_metric_counts()
            return

        self.resolved_adb_path = adb
        try:
            devices = list_devices(adb)
        except (OSError, ValueError, TimeoutError, Exception) as exc:
            self.device_combo.addItem("Could not query ADB devices", None)
            self.status_pill.setText("ADB error")
            self.status_pill.setProperty("offline", True)
            self.dashboard_device_value.setText("Error")
            self.capture_status_label.setText(f"ADB error: {exc}")
            self.device_combo.blockSignals(False)
            self._refresh_metric_counts()
            return

        if not devices:
            self.device_combo.addItem("No Android device connected", None)
            self.status_pill.setText("No device")
            self.status_pill.setProperty("offline", True)
            self.dashboard_device_value.setText("No device")
        else:
            for device in devices:
                self.device_combo.addItem(device.display_name, device.serial)
                index = self.device_combo.count() - 1
                self.device_combo.setItemData(index, device.state, STATE_ROLE)
            preferred_index = self.device_combo.findData(previous_serial) if previous_serial else -1
            if preferred_index < 0:
                preferred_index = next(
                    (i for i, device in enumerate(devices) if device.state == "device"),
                    0,
                )
            self.device_combo.setCurrentIndex(preferred_index)
            authorized_count = sum(device.state == "device" for device in devices)
            if authorized_count:
                self.status_pill.setText(f"{authorized_count} device(s) ready")
                self.status_pill.setProperty("offline", False)
                self.dashboard_device_value.setText(f"{authorized_count} ready")
            else:
                self.status_pill.setText("Authorize phone")
                self.status_pill.setProperty("offline", True)
                self.dashboard_device_value.setText("Unauthorized")
        self.device_combo.blockSignals(False)
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)
        self._refresh_metric_counts()
        self._update_device_status()

    def _update_device_status(self, *_args: object) -> None:
        serial = self.device_combo.currentData()
        state = self.device_combo.currentData(STATE_ROLE)
        if serial and state == "device":
            self.capture_status_label.setText(f"Ready to capture on {serial}.")
        elif self.resolved_adb_path is not None:
            self.capture_status_label.setText("Connect a device and authorize USB debugging before capturing.")
        self._refresh_metric_counts()

    def _refresh_metric_counts(self) -> None:
        if hasattr(self, "dashboard_workflow_value"):
            self.dashboard_workflow_value.setText(str(len(list_workflows(WORKFLOWS_DIR))))
        if hasattr(self, "recent_workflows"):
            self.recent_workflows.clear()
            for path in list_workflows(WORKFLOWS_DIR)[:12]:
                try:
                    summary = summarize_workflow(path)
                    label = f"{path.name}    ·    {summary.action_count} actions"
                except (OSError, ValueError):
                    label = f"{path.name}    ·    unreadable JSON"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.recent_workflows.addItem(item)

    def refresh_workflows(self) -> None:
        if not hasattr(self, "workflow_path_combo"):
            return
        current_text = self.workflow_path_combo.currentText().strip()
        paths = list_workflows(WORKFLOWS_DIR)
        self.workflow_path_combo.blockSignals(True)
        self.workflow_path_combo.clear()
        for path in paths:
            self.workflow_path_combo.addItem(str(path), str(path))
        if current_text:
            existing_index = self.workflow_path_combo.findData(current_text)
            if existing_index >= 0:
                self.workflow_path_combo.setCurrentIndex(existing_index)
            else:
                self.workflow_path_combo.setEditText(current_text)
        elif paths:
            self.workflow_path_combo.setCurrentIndex(0)
        self.workflow_path_combo.blockSignals(False)
        self._refresh_metric_counts()
        self._update_workflow_summary()

    def _selected_serial(self) -> str | None:
        serial = self.device_combo.currentData()
        state = self.device_combo.currentData(STATE_ROLE)
        return str(serial) if serial and state == "device" else None

    def _require_device(self) -> str | None:
        serial = self._selected_serial()
        if not self.resolved_adb_path:
            QMessageBox.warning(self, "ADB not configured", "Open Settings and select adb.exe first.")
            return None
        if not serial:
            QMessageBox.warning(
                self,
                "Android device not ready",
                "Connect your phone, enable USB debugging, accept the authorization prompt, then refresh devices.",
            )
            return None
        return serial

    def _browse_capture_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save workflow JSON", self.capture_output_edit.text(), "Workflow JSON (*.json)"
        )
        if path:
            if not path.lower().endswith(".json"):
                path += ".json"
            self.capture_output_edit.setText(path)

    def _browse_replay_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open workflow JSON", str(WORKFLOWS_DIR), "Workflow JSON (*.json)"
        )
        if path:
            self.workflow_path_combo.setEditText(path)
            self._update_workflow_summary()

    def _browse_adb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select adb executable", self.adb_path_edit.text(), "ADB executable (adb.exe);;All files (*)"
        )
        if path:
            self.adb_path_edit.setText(path)

    def _auto_detect_adb(self) -> None:
        adb = resolve_adb(None)
        if adb is None:
            QMessageBox.information(
                self, "ADB not found",
                "ADB was not found on PATH or in common Android SDK locations. Browse to adb.exe manually.",
            )
            return
        self.adb_path_edit.setText(str(adb))
        self.save_settings()

    def save_settings(self) -> None:
        self.adb_path = self.adb_path_edit.text().strip()
        self.settings.setValue("adbPath", self.adb_path)
        self.settings.sync()
        self.refresh_devices()
        QMessageBox.information(self, "Settings saved", "ADB settings were saved on this PC.")

    def start_capture(self) -> None:
        if self.active_worker is not None:
            return
        serial = self._require_device()
        if not serial:
            return
        output_path = Path(self.capture_output_edit.text().strip()).expanduser()
        if not str(output_path):
            QMessageBox.warning(self, "Choose output file", "Choose a path for the workflow JSON.")
            return
        if output_path.exists():
            answer = QMessageBox.question(
                self,
                "Overwrite workflow?",
                f"The file already exists and will be overwritten:\n{output_path}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            command = build_capture_command(
                output_path=output_path,
                serial=serial,
                capture_state=self.capture_state_checkbox.isChecked(),
                capture_ui_hierarchy=self.capture_ui_checkbox.isChecked(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Cannot start capture", str(exc))
            return
        self.capture_output_path = str(output_path)
        self.capture_log.clear()
        self.capture_status_label.setText("Recording… use the phone, then press Stop and Save.")
        self._start_worker(
            command=command,
            operation="capture",
            env=build_child_environment(self.resolved_adb_path),
            log_widget=self.capture_log,
        )
        self.capture_start_button.setEnabled(False)
        self.capture_stop_button.setEnabled(True)

    def _update_workflow_summary(self, *_args: object) -> None:
        if not hasattr(self, "workflow_summary_label"):
            return
        path_text = self.workflow_path_combo.currentText().strip()
        if not path_text:
            self.workflow_summary_label.setText("Select a workflow JSON file to see its action count.")
            return
        path = Path(path_text).expanduser()
        if not path.is_file():
            self.workflow_summary_label.setText("Workflow file not found. Choose a JSON file or select one from the list.")
            return
        try:
            summary = summarize_workflow(path)
            screen_text = ""
            if summary.display_width and summary.display_height:
                screen_text = f"  ·  Recorded display: {summary.display_width} × {summary.display_height}"
            self.workflow_summary_label.setText(
                f"{summary.action_count} actions  ·  {summary.tap_count} taps  ·  "
                f"{summary.swipe_count} swipes  ·  {summary.long_press_count} long presses{screen_text}"
            )
        except (OSError, ValueError) as exc:
            self.workflow_summary_label.setText(f"Could not read workflow: {exc}")

    def start_replay(self) -> None:
        if self.active_worker is not None:
            return
        serial = self._require_device()
        if not serial:
            return
        workflow_path = Path(self.workflow_path_combo.currentText().strip()).expanduser()
        if not workflow_path.is_file():
            QMessageBox.warning(self, "Choose workflow", "Select an existing workflow JSON file.")
            return
        try:
            summary = summarize_workflow(workflow_path)
            if summary.action_count == 0:
                raise ValueError("This workflow contains no actions.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid workflow", str(exc))
            return

        dry_run = self.dry_run_checkbox.isChecked()
        verify_state = self.verify_state_checkbox.isChecked()
        if not dry_run:
            verification_text = (
                "Screen-state verification is ON."
                if verify_state
                else "Screen-state verification is OFF, so replay will not stop if the phone is on the wrong screen."
            )
            answer = QMessageBox.warning(
                self,
                "Confirm real replay",
                f"This will send touch input to the Android phone.\n\n"
                f"Workflow: {workflow_path.name}\nActions: {summary.action_count}\n"
                f"Repeat count: {self.repeat_count_spin.value()}\n\n"
                f"Keep the phone unlocked, place it on the intended screen, and do not touch it during replay.\n"
                f"{verification_text}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = LOGS_DIR / f"replay-{timestamp}.jsonl"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            command = build_replay_command(
                input_path=workflow_path,
                log_path=log_path,
                serial=serial,
                verify_state=verify_state,
                dry_run=dry_run,
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Cannot start replay", str(exc))
            return

        repeat_count = self.repeat_count_spin.value()
        self.replay_log.clear()
        self.replay_progress.setRange(0, repeat_count)
        self.replay_progress.setValue(0)
        self.replay_progress_label.setText("Preparing dry run…" if dry_run else "Preparing real replay…")
        self._start_worker(
            command=command,
            operation="replay",
            env=build_child_environment(self.resolved_adb_path),
            log_widget=self.replay_log,
            repeat_count=repeat_count,
            delay_between_runs=self.repeat_delay_spin.value(),
        )
        self.replay_start_button.setEnabled(False)
        self.replay_stop_button.setEnabled(True)

    def _start_worker(
        self,
        command: list[str],
        operation: str,
        env: dict[str, str],
        log_widget: QPlainTextEdit,
        repeat_count: int = 1,
        delay_between_runs: float = 0.0,
    ) -> None:
        self.active_operation = operation
        worker = CommandWorker(
            command=command,
            working_dir=ROOT,
            env=env,
            repeat_count=repeat_count,
            delay_between_runs=delay_between_runs,
            operation_name="capture" if operation == "capture" else "replay",
        )
        self.active_worker = worker
        worker.output.connect(lambda line, box=log_widget: self._append_log(box, line))
        worker.run_progress.connect(self._on_run_progress)
        worker.action_progress.connect(self._on_action_progress)
        worker.operation_finished.connect(
            lambda success, message, op=operation: self._finish_operation(op, success, message)
        )
        worker.start()

    @staticmethod
    def _append_log(widget: QPlainTextEdit, line: str) -> None:
        widget.appendPlainText(line)
        scrollbar = widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_run_progress(self, current: int, total: int) -> None:
        if self.active_operation == "replay":
            self.replay_progress.setRange(0, total)
            self.replay_progress.setValue(max(0, current - 1))
            self.replay_progress_label.setText(f"Run {current}/{total}")

    def _on_action_progress(self, run_index: int, action_index: int, action_total: int) -> None:
        if self.active_operation == "replay":
            self.replay_progress_label.setText(
                f"Run {run_index}/{self.repeat_count_spin.value()}  ·  Action {action_index}/{action_total}"
            )

    def stop_operation(self) -> None:
        if self.active_worker is None:
            return
        self.capture_status_label.setText("Stopping and saving current capture…")
        self.replay_progress_label.setText("Stopping replay…")
        self._append_log(
            self.capture_log if self.active_operation == "capture" else self.replay_log,
            "Stop requested by user.",
        )
        self.active_worker.stop()
        self.capture_stop_button.setEnabled(False)
        self.replay_stop_button.setEnabled(False)

    def _finish_operation(self, operation: str, success: bool, message: str) -> None:
        if self.active_worker is not None:
            self.active_worker = None
        stopped = message.startswith("Stopped by user")
        if operation == "capture":
            self.capture_start_button.setEnabled(True)
            self.capture_stop_button.setEnabled(False)
            if stopped:
                self.capture_status_label.setText("Capture stopped. The latest completed gestures were saved.")
            elif success:
                self.capture_status_label.setText(f"Capture finished: {self.capture_output_path}")
            else:
                self.capture_status_label.setText(message)
            self._append_log(self.capture_log, message)
            self.refresh_workflows()
            if self.capture_output_path and Path(self.capture_output_path).is_file():
                self.workflow_path_combo.setEditText(self.capture_output_path)
                self._update_workflow_summary()
        else:
            self.replay_start_button.setEnabled(True)
            self.replay_stop_button.setEnabled(False)
            self.replay_progress_label.setText(message)
            if success:
                self.replay_progress.setValue(self.replay_progress.maximum())
            self._append_log(self.replay_log, message)
        self._refresh_metric_counts()

    def _open_recent_workflow(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.workflow_path_combo.setEditText(str(path))
            self._update_workflow_summary()
            self.switch_page(2)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt callback name
        if self.active_worker is not None:
            answer = QMessageBox.question(
                self,
                "Operation still running",
                "An ADB operation is still running. Stop it and close the application?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.active_worker.stop()
            self.active_worker.wait(3500)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ADBFlowStudio")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
