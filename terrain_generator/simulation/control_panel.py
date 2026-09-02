"""PyQt control panel for M20 and Go2 MuJoCo policy viewers."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import PyQt5
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..i18n import normalize_language, tr


class ControlBridge:
    """A localhost command channel between the panel and M20 subprocess."""

    def __init__(self) -> None:
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.server.settimeout(0.5)
        self.port = self.server.getsockname()[1]
        self.connection: socket.socket | None = None
        self.lock = Lock()
        self.closed = False
        self.thread = Thread(target=self._accept, name="arenax-control-bridge", daemon=True)
        self.thread.start()

    def _accept(self) -> None:
        while not self.closed:
            try:
                connection, _address = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self.lock:
                self.connection = connection
            return

    def send(self, operation: str, **values: Any) -> bool:
        payload = {"op": operation, **values}
        encoded = (json.dumps(payload) + "\n").encode("utf-8")
        with self.lock:
            connection = self.connection
            if connection is None:
                return False
            try:
                connection.sendall(encoded)
                return True
            except OSError:
                self.connection = None
                return False

    def close(self) -> None:
        self.closed = True
        with self.lock:
            connection = self.connection
            self.connection = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.server.close()


class RobotControlPanel(QMainWindow):
    """Mouse-driven control panel for a selected robot policy."""

    def __init__(self, xml_path: Path, policy_path: Path, config_path: Path | None,
                 duration: float, episodes: int, language: str = "zh",
                 robot: str = "m20") -> None:
        super().__init__()
        self.language = normalize_language(language)
        if robot not in ("m20", "go2"):
            raise ValueError(f"unsupported robot: {robot}")
        self.robot = robot
        self.robot_label = "M20" if robot == "m20" else "Go2"
        self.xml_path = xml_path
        self.policy_path = policy_path
        self.config_path = config_path
        self.duration = duration
        self.episodes = episodes
        self.bridge = ControlBridge()
        self.simulation_process: subprocess.Popen | None = None
        self.buttons: list[QPushButton] = []
        self.setWindowTitle(self.panel_title())
        self.resize(360, 520)
        self.build_ui()
        self.start_simulation()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_simulation)
        self.poll_timer.start(500)

    def build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel(self.policy_title())
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #125a9e;")
        self.title_label = title
        layout.addWidget(self.title_label)
        self.language_button = QPushButton()
        self.language_button.clicked.connect(self.toggle_language)
        layout.addWidget(self.language_button)
        self.status_label = QLabel(tr(self.language, "正在启动 MuJoCo viewer…"))
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.motion_box = QGroupBox(tr(self.language, "移动控制"))
        motion = QGridLayout(self.motion_box)
        self.add_button(motion, f"↑\n{tr(self.language, '前进')}", 0, 1, lambda: self.adjust(0, 0.1))
        self.add_button(motion, f"←\n{tr(self.language, '左移')}", 1, 0, lambda: self.adjust(1, 0.2))
        self.add_button(motion, tr(self.language, "停止"), 1, 1, self.stop_command)
        self.add_button(motion, f"→\n{tr(self.language, '右移')}", 1, 2, lambda: self.adjust(1, -0.2))
        self.add_button(motion, f"↓\n{tr(self.language, '后退')}", 2, 1, lambda: self.adjust(0, -0.1))
        layout.addWidget(self.motion_box)

        self.turn_box = QGroupBox(tr(self.language, "转向"))
        turn_layout = QHBoxLayout(self.turn_box)
        self.add_button(turn_layout, f"↶ {tr(self.language, '左转')}", None, None, lambda: self.adjust(2, 0.2))
        self.add_button(turn_layout, f"↷ {tr(self.language, '右转')}", None, None, lambda: self.adjust(2, -0.2))
        layout.addWidget(self.turn_box)

        self.gear_box = QGroupBox(tr(self.language, "速度档位"))
        gear_layout = QHBoxLayout(self.gear_box)
        self.add_button(gear_layout, tr(self.language, "低速"), None, None, lambda: self.set_gear(1))
        self.add_button(gear_layout, tr(self.language, "中速"), None, None, lambda: self.set_gear(2))
        self.add_button(gear_layout, tr(self.language, "高速"), None, None, lambda: self.set_gear(3))
        layout.addWidget(self.gear_box)

        bottom = QHBoxLayout()
        self.reset_button = QPushButton(tr(self.language, "重置机器人"))
        self.reset_button.clicked.connect(lambda: self.bridge.send("reset"))
        self.reset_button.setEnabled(False)
        bottom.addWidget(self.reset_button)
        self.close_button = QPushButton(tr(self.language, "关闭控制面板"))
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)
        layout.addStretch(1)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f5f9fd; color: #17324d; font-size: 14px; }
            QGroupBox { border: 1px solid #bed3e6; border-radius: 8px; margin-top: 12px; padding: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #2374c6; }
            QPushButton { background: #2374c6; color: white; border: 0; border-radius: 5px; padding: 10px; font-weight: 600; }
            QPushButton:hover { background: #155d9f; }
            QPushButton:disabled { background: #aab8c4; }
        """)
        self.set_language(self.language)

    def set_language(self, language: str) -> None:
        self.language = normalize_language(language)
        self.language_button.setText(tr(self.language, "English") if self.language == "zh" else tr(self.language, "中文"))
        self.language_button.setToolTip(
            tr(self.language, "切换到英文") if self.language == "zh" else tr(self.language, "切换到中文")
        )
        self.setWindowTitle(self.panel_title())
        self.title_label.setText(self.policy_title())
        self.motion_box.setTitle(tr(self.language, "移动控制"))
        self.turn_box.setTitle(tr(self.language, "转向"))
        self.gear_box.setTitle(tr(self.language, "速度档位"))
        labels = [
            f"↑\n{tr(self.language, '前进')}", f"←\n{tr(self.language, '左移')}",
            tr(self.language, "停止"), f"→\n{tr(self.language, '右移')}",
            f"↓\n{tr(self.language, '后退')}", f"↶ {tr(self.language, '左转')}",
            f"↷ {tr(self.language, '右转')}", tr(self.language, "低速"),
            tr(self.language, "中速"), tr(self.language, "高速"),
        ]
        for button, label in zip(self.buttons, labels):
            button.setText(label)
        self.reset_button.setText(tr(self.language, "重置机器人"))
        self.close_button.setText(tr(self.language, "关闭控制面板"))
        if self.status_label.text() in {
            tr("zh", "正在启动 MuJoCo viewer…"),
            tr("en", "正在启动 MuJoCo viewer…"),
        }:
            self.status_label.setText(tr(self.language, "正在启动 MuJoCo viewer…"))

    def toggle_language(self) -> None:
        self.set_language("en" if self.language == "zh" else "zh")

    def panel_title(self) -> str:
        title = tr(self.language, "ArenaX Robotics · M20 控制面板")
        return title.replace("M20", self.robot_label)

    def policy_title(self) -> str:
        title = tr(self.language, "M20 策略控制")
        return title.replace("M20", self.robot_label)

    def add_button(self, layout: Any, text: str, row: int | None, column: int | None,
                   callback) -> None:
        button = QPushButton(text)
        button.setMinimumHeight(52)
        button.setEnabled(False)
        button.clicked.connect(callback)
        self.buttons.append(button)
        if row is None:
            layout.addWidget(button)
        else:
            layout.addWidget(button, row, column)

    def start_simulation(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        runtime_python = project_root / ".venv" / "bin" / "python"
        if not runtime_python.is_file():
            runtime_python = Path(sys.executable)
        log_path = self.xml_path.with_name("mujoco.log")
        command = [
            str(runtime_python), "-m", "terrain_generator.cli", "--xml", str(self.xml_path),
            "--policy", str(self.policy_path), "--control-host", "127.0.0.1",
            "--control-port", str(self.bridge.port), "--robot", self.robot,
            "--duration", str(self.duration),
            "--episodes", str(self.episodes),
        ]
        if self.config_path:
            command.extend(("--robot-config", str(self.config_path)))
        try:
            with log_path.open("w", encoding="utf-8") as log_file:
                self.simulation_process = subprocess.Popen(
                    command, cwd=str(project_root), stdout=log_file,
                    stderr=subprocess.STDOUT, start_new_session=True,
                )
        except OSError as exc:
            self.on_failed(str(exc))

    def poll_simulation(self) -> None:
        if self.simulation_process is None:
            return
        if self.simulation_process.poll() is not None:
            if self.simulation_process.returncode != 0:
                log_path = self.xml_path.with_name("mujoco.log")
                details = log_path.read_text(encoding="utf-8")[-4000:] if log_path.exists() else ""
                if self.language == "en":
                    self.on_failed(f"Process exited with code={self.simulation_process.returncode}\n{details}")
                else:
                    self.on_failed(f"进程退出 code={self.simulation_process.returncode}\n{details}")
            self.poll_timer.stop()
            return
        if self.bridge.connection is not None:
            for button in self.buttons:
                button.setEnabled(True)
            self.reset_button.setEnabled(True)
            self.status_label.setText(tr(self.language, "MuJoCo 已启动，请使用本面板控制机器人。"))

    def adjust(self, axis: int, delta: float) -> None:
        self.bridge.send("adjust", axis=axis, delta=delta)

    def stop_command(self) -> None:
        self.bridge.send("stop")

    def set_gear(self, gear: int) -> None:
        self.bridge.send("gear", gear=gear)

    def on_failed(self, message: str) -> None:
        self.status_label.setText(tr(self.language, "MuJoCo 启动失败"))
        QMessageBox.critical(self, tr(self.language, "MuJoCo 启动失败"), message)

    def closeEvent(self, event) -> None:
        self.bridge.send("quit")
        self.bridge.close()
        if self.simulation_process is not None:
            try:
                self.simulation_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.simulation_process.terminate()
        event.accept()


M20ControlPanel = RobotControlPanel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ArenaX Robotics robot PyQt control panel")
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--robot", choices=("m20", "go2"), default="m20",
                        help="robot profile for the policy (default: m20)")
    parser.add_argument("--robot-config", type=Path)
    parser.add_argument("--duration", type=float, default=3600.0)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--language", choices=("zh", "en"), default="zh")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    platform_plugins = Path(PyQt5.__file__).resolve().parent / "Qt5" / "plugins" / "platforms"
    # The editor may have started with the system PyQt5 and passed its
    # plugin path to this .venv child. Always prefer the child interpreter's
    # matching Qt plugins, otherwise xcb/Wayland loading can fail.
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platform_plugins)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Noto Sans", 11) if args.language == "en" else QFont("Noto Sans CJK SC", 11))
    window = RobotControlPanel(
        args.xml.resolve(), args.policy.resolve(),
        args.robot_config.resolve() if args.robot_config else None,
        args.duration, args.episodes, args.language, args.robot,
    )
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
