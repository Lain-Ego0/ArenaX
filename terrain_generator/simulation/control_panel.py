"""PyQt control panel for the M20 MuJoCo policy viewer."""

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
from PyQt5.QtWidgets import (
    QApplication, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


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


class M20ControlPanel(QMainWindow):
    """Mouse-driven command panel; MuJoCo runs in a separate process."""

    def __init__(self, xml_path: Path, policy_path: Path, config_path: Path | None,
                 duration: float, episodes: int) -> None:
        super().__init__()
        self.xml_path = xml_path
        self.policy_path = policy_path
        self.config_path = config_path
        self.duration = duration
        self.episodes = episodes
        self.bridge = ControlBridge()
        self.simulation_process: subprocess.Popen | None = None
        self.buttons: list[QPushButton] = []
        self.setWindowTitle("ArenaX Robotics · M20 控制面板")
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

        title = QLabel("M20 策略控制")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #125a9e;")
        layout.addWidget(title)
        self.status_label = QLabel("正在启动 MuJoCo viewer…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        motion_box = QGroupBox("移动控制")
        motion = QGridLayout(motion_box)
        self.add_button(motion, "↑\n前进", 0, 1, lambda: self.adjust(0, 0.1))
        self.add_button(motion, "←\n左移", 1, 0, lambda: self.adjust(1, 0.2))
        self.add_button(motion, "停止", 1, 1, self.stop_command)
        self.add_button(motion, "→\n右移", 1, 2, lambda: self.adjust(1, -0.2))
        self.add_button(motion, "↓\n后退", 2, 1, lambda: self.adjust(0, -0.1))
        layout.addWidget(motion_box)

        turn_box = QGroupBox("转向")
        turn_layout = QHBoxLayout(turn_box)
        self.add_button(turn_layout, "↶ 左转", None, None, lambda: self.adjust(2, 0.2))
        self.add_button(turn_layout, "↷ 右转", None, None, lambda: self.adjust(2, -0.2))
        layout.addWidget(turn_box)

        gear_box = QGroupBox("速度档位")
        gear_layout = QHBoxLayout(gear_box)
        self.add_button(gear_layout, "低速", None, None, lambda: self.set_gear(1))
        self.add_button(gear_layout, "中速", None, None, lambda: self.set_gear(2))
        self.add_button(gear_layout, "高速", None, None, lambda: self.set_gear(3))
        layout.addWidget(gear_box)

        bottom = QHBoxLayout()
        self.reset_button = QPushButton("重置机器人")
        self.reset_button.clicked.connect(lambda: self.bridge.send("reset"))
        self.reset_button.setEnabled(False)
        bottom.addWidget(self.reset_button)
        close_button = QPushButton("关闭控制面板")
        close_button.clicked.connect(self.close)
        bottom.addWidget(close_button)
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
            "--control-port", str(self.bridge.port), "--duration", str(self.duration),
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
                self.on_failed(f"进程退出 code={self.simulation_process.returncode}\n{details}")
            self.poll_timer.stop()
            return
        if self.bridge.connection is not None:
            for button in self.buttons:
                button.setEnabled(True)
            self.reset_button.setEnabled(True)
            self.status_label.setText("MuJoCo 已启动，请使用本面板控制机器人。")

    def adjust(self, axis: int, delta: float) -> None:
        self.bridge.send("adjust", axis=axis, delta=delta)

    def stop_command(self) -> None:
        self.bridge.send("stop")

    def set_gear(self, gear: int) -> None:
        self.bridge.send("gear", gear=gear)

    def on_failed(self, message: str) -> None:
        self.status_label.setText("MuJoCo 启动失败")
        QMessageBox.critical(self, "MuJoCo 启动失败", message)

    def closeEvent(self, event) -> None:
        self.bridge.send("quit")
        self.bridge.close()
        if self.simulation_process is not None:
            try:
                self.simulation_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.simulation_process.terminate()
        event.accept()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ArenaX Robotics M20 PyQt control panel")
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--robot-config", type=Path)
    parser.add_argument("--duration", type=float, default=3600.0)
    parser.add_argument("--episodes", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    platform_plugins = Path(PyQt5.__file__).resolve().parent / "Qt5" / "plugins" / "platforms"
    # The editor may have started with the system PyQt5 and passed its
    # plugin path to this .venv child. Always prefer the child interpreter's
    # matching Qt plugins, otherwise xcb/Wayland loading can fail.
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platform_plugins)
    app = QApplication.instance() or QApplication(sys.argv)
    window = M20ControlPanel(
        args.xml.resolve(), args.policy.resolve(),
        args.robot_config.resolve() if args.robot_config else None,
        args.duration, args.episodes,
    )
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
