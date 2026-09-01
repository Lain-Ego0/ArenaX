"""Lightweight MuJoCo rendering embedded in the PAVE Qt application."""

from __future__ import annotations

import queue
import time
from pathlib import Path
from threading import Event
from typing import Any

import mujoco
import numpy as np
from PyQt5.QtCore import QPoint, QThread, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QKeyEvent, QWheelEvent
from PyQt5.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from .m20_sim import M20Simulation


class MuJoCoRenderWorker(QThread):
    """Simulate and render MuJoCo in one worker thread, without GLFW viewer."""

    frame_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, xml_path: Path, policy_path: Path | None = None,
                 config_path: Path | None = None, width: int = 1280,
                 height: int = 720) -> None:
        super().__init__()
        self.xml_path = xml_path
        self.policy_path = policy_path
        self.config_path = config_path
        self.width = width
        self.height = height
        self.commands: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.stop_event = Event()

    def send(self, operation: str, **values: Any) -> None:
        self.commands.put((operation, values))

    def stop(self) -> None:
        self.stop_event.set()

    def _apply_commands(self, simulation: M20Simulation | None,
                        model: mujoco.MjModel, data: mujoco.MjData,
                        camera: mujoco.MjvCamera | None = None) -> None:
        if camera is None:
            camera = self._camera(simulation)
        while True:
            try:
                operation, values = self.commands.get_nowait()
            except queue.Empty:
                return
            if operation == "stop":
                if simulation is not None:
                    simulation.command.stop()
                else:
                    self.stop_event.set()
            elif operation == "reset":
                if simulation is not None:
                    simulation.reset()
                else:
                    mujoco.mj_resetData(model, data)
                    mujoco.mj_forward(model, data)
            elif simulation is not None and operation == "adjust":
                simulation.command.adjust(int(values["axis"]), float(values["delta"]))
            elif simulation is not None and operation == "gear":
                simulation.command.set_gear(int(values["gear"]))
            elif simulation is not None and operation == "speed":
                simulation.command.set_speed(float(values["speed"]))
            elif simulation is not None and operation == "motion":
                simulation.command.set_motion(float(values.get("vx", 0.0)),
                                              float(values.get("vy", 0.0)),
                                              float(values.get("yaw", 0.0)))
            elif operation == "zoom":
                camera.distance = float(np.clip(camera.distance * float(values.get("factor", 1.0)), 0.2, 100.0))
            elif operation == "rotate":
                camera.azimuth += float(values.get("dx", 0.0))
                camera.elevation = float(np.clip(camera.elevation + float(values.get("dy", 0.0)), -89.0, 89.0))
            elif operation == "pan":
                # Pan in camera-local screen coordinates.  The scale is
                # proportional to distance, making the gesture predictable.
                camera.lookat[0] += float(values.get("dx", 0.0)) * camera.distance * 0.002
                camera.lookat[1] += float(values.get("dy", 0.0)) * camera.distance * 0.002

    @staticmethod
    def _camera(simulation: M20Simulation | None) -> mujoco.MjvCamera:
        camera = mujoco.MjvCamera()
        mujoco.mjv_defaultCamera(camera)
        if simulation is not None:
            camera.type = mujoco.mjtCamera.mjCAMERA_TRACKING
            camera.trackbodyid = simulation.base_body_id
            camera.distance = 3.0
            camera.elevation = -20.0
            camera.azimuth = 60.0
        else:
            camera.type = mujoco.mjtCamera.mjCAMERA_FREE
            camera.lookat[:] = [0.0, 0.0, 0.0]
            camera.distance = 14.0
            camera.elevation = -35.0
            camera.azimuth = 90.0
        return camera

    def run(self) -> None:
        renderer = None
        try:
            simulation = (
                M20Simulation(self.xml_path, self.policy_path, self.config_path)
                if self.policy_path is not None else None
            )
            model = simulation.model if simulation is not None else mujoco.MjModel.from_xml_path(str(self.xml_path))
            data = simulation.data if simulation is not None else mujoco.MjData(model)
            # MuJoCo defaults to a 640x480 offscreen framebuffer. The Qt
            # canvas is wider, so enlarge the model framebuffer before the
            # renderer allocates its OpenGL resources.
            model.vis.global_.offwidth = max(int(model.vis.global_.offwidth), self.width)
            model.vis.global_.offheight = max(int(model.vis.global_.offheight), self.height)
            renderer = mujoco.Renderer(model, height=self.height, width=self.width)
            camera = self._camera(simulation)
            self.status_changed.emit(
                "M20 ONNX 策略已启动" if simulation is not None else "MuJoCo 场景已加载"
            )

            # Render at a stable cadence while stepping simulation in small
            # batches.  This avoids a sleep/wake cycle for every 5 ms physics
            # tick and keeps Qt responsive on slower machines.
            start_wall = time.perf_counter()
            next_frame = start_wall
            while not self.stop_event.is_set():
                self._apply_commands(simulation, model, data, camera)
                if self.stop_event.is_set():
                    break
                now = time.perf_counter()
                target_sim_time = now - start_wall
                # Catch up to wall clock, capped to prevent a long render or
                # policy inference pause from creating an unbounded backlog.
                steps = 0
                while data.time < target_sim_time and steps < 24:
                    if simulation is not None:
                        simulation._step()
                        if simulation._is_fallen():
                            simulation.reset()
                    else:
                        mujoco.mj_step(model, data)
                    steps += 1
                if now >= next_frame:
                    renderer.update_scene(data, camera=camera)
                    rgb = renderer.render()
                    image = QImage(
                        rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                        QImage.Format_RGB888,
                    ).copy()
                    self.frame_ready.emit(image)
                    next_frame = now + 1.0 / 30.0
                # If one physics step overshot the wall clock, yield until the
                # next tick instead of spinning a CPU core.
                delay = min(0.004, max(0.0, data.time - target_sim_time))
                if delay:
                    time.sleep(delay)
        except Exception as exc:  # pragma: no cover - backend/display dependent
            self.error_occurred.emit(f"MuJoCo 内嵌仿真启动失败：{exc}")
        finally:
            if renderer is not None:
                renderer.close()


class MuJoCoCanvas(QLabel):
    """Qt canvas forwarding camera gestures and robot keys to the page."""

    camera_command = pyqtSignal(str, object)
    key_command = pyqtSignal(int, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last_pos: QPoint | None = None
        self._button = Qt.NoButton
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def mousePressEvent(self, event) -> None:
        self.setFocus(Qt.MouseFocusReason)
        self._last_pos = event.pos()
        self._button = event.button()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._last_pos = None
        self._button = Qt.NoButton
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._last_pos is not None and self._button in (Qt.LeftButton, Qt.RightButton):
            delta = event.pos() - self._last_pos
            self._last_pos = event.pos()
            operation = "rotate" if self._button == Qt.LeftButton else "pan"
            self.camera_command.emit(operation, (delta.x(), delta.y()))
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        # One wheel notch is 120 degrees.  Positive delta zooms in.
        steps = event.angleDelta().y() / 120.0
        self.camera_command.emit("zoom", steps)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not event.isAutoRepeat():
            self.key_command.emit(int(event.key()), True)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not event.isAutoRepeat():
            self.key_command.emit(int(event.key()), False)
        event.accept()


class EmbeddedSimulationPage(QWidget):
    """Second page with mouse controls on the left and MuJoCo on the right."""

    back_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.worker: MuJoCoRenderWorker | None = None
        self.last_image: QImage | None = None
        self.control_buttons: list[QPushButton] = []
        self.pressed_keys: set[int] = set()
        self.speed_slider: QSlider | None = None
        self.speed_value_label: QLabel | None = None
        self.build_ui()

    def build_ui(self) -> None:
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        back_button = QPushButton("← 返回地形编辑")
        back_button.clicked.connect(self.go_back)
        header.addWidget(back_button)
        title = QLabel("PAVE · MuJoCo 仿真验证")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #125a9e;")
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)

        content = QHBoxLayout()
        left = QVBoxLayout()
        self.status_label = QLabel("等待加载场景…")
        self.status_label.setWordWrap(True)
        left.addWidget(self.status_label)

        motion_box = QGroupBox("机器人控制")
        motion = QGridLayout(motion_box)
        self.add_button(motion, "↑\n前进", 0, 1, lambda: self.adjust(0, 0.1))
        self.add_button(motion, "←\n左移", 1, 0, lambda: self.adjust(1, 0.2))
        self.add_button(motion, "停止", 1, 1, lambda: self.send("stop"))
        self.add_button(motion, "→\n右移", 1, 2, lambda: self.adjust(1, -0.2))
        self.add_button(motion, "↓\n后退", 2, 1, lambda: self.adjust(0, -0.1))
        left.addWidget(motion_box)

        turn_box = QGroupBox("转向")
        turn = QHBoxLayout(turn_box)
        self.add_button(turn, "↶ 左转", None, None, lambda: self.adjust(2, 0.2))
        self.add_button(turn, "↷ 右转", None, None, lambda: self.adjust(2, -0.2))
        left.addWidget(turn_box)

        gear_box = QGroupBox("速度档位")
        gear = QHBoxLayout(gear_box)
        self.add_button(gear, "低速", None, None, lambda: self.send("gear", gear=1))
        self.add_button(gear, "中速", None, None, lambda: self.send("gear", gear=2))
        self.add_button(gear, "高速", None, None, lambda: self.send("gear", gear=3))
        left.addWidget(gear_box)

        speed_box = QGroupBox("全向速度（m/s）")
        speed_layout = QHBoxLayout(speed_box)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(0, 200)
        self.speed_slider.setValue(100)
        self.speed_slider.setToolTip("WASD 的线速度，0–2 m/s")
        self.speed_slider.valueChanged.connect(self.speed_changed)
        self.speed_value_label = QLabel("1.00")
        self.speed_value_label.setMinimumWidth(42)
        speed_layout.addWidget(self.speed_slider, 1)
        speed_layout.addWidget(self.speed_value_label)
        left.addWidget(speed_box)

        bottom = QHBoxLayout()
        self.add_button(bottom, "重置", None, None, lambda: self.send("reset"))
        left.addLayout(bottom)
        left.addStretch(1)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(260)
        content.addWidget(left_widget)

        self.render_label = MuJoCoCanvas()
        self.render_label.setText("MuJoCo 渲染画面")
        self.render_label.setAlignment(Qt.AlignCenter)
        self.render_label.setMinimumSize(854, 480)
        self.render_label.setStyleSheet("background: #101820; color: #dcecff;")
        self.render_label.camera_command.connect(self.camera_command)
        self.render_label.key_command.connect(self.key_command)
        content.addWidget(self.render_label, 1)
        root.addLayout(content, 1)
        self.setStyleSheet("""
            QWidget { background: #f5f9fd; color: #17324d; font-size: 14px; }
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
        self.control_buttons.append(button)
        if row is None:
            layout.addWidget(button)
        else:
            layout.addWidget(button, row, column)

    def start(self, xml_path: Path, policy_path: Path | None = None,
              config_path: Path | None = None) -> None:
        self.stop_worker()
        self.last_image = None
        self.render_label.setPixmap(QPixmap())
        self.render_label.setText("正在加载 MuJoCo…")
        self.status_label.setText("正在启动内嵌 MuJoCo…")
        self.worker = MuJoCoRenderWorker(xml_path, policy_path, config_path)
        self.worker.frame_ready.connect(self.show_frame)
        self.worker.status_changed.connect(self.status_label.setText)
        self.worker.error_occurred.connect(self.show_error)
        for button in self.control_buttons:
            button.setEnabled(policy_path is not None)
        self.pressed_keys.clear()
        if self.speed_slider is not None:
            self.speed_slider.setValue(100)
        if policy_path is None:
            self.status_label.setText("场景已准备，机器人控制需要勾选 M20 策略")
        self.worker.start()

    def stop_worker(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None

    def send(self, operation: str, **values: Any) -> None:
        if self.worker is not None:
            self.worker.send(operation, **values)

    def adjust(self, axis: int, delta: float) -> None:
        self.send("adjust", axis=axis, delta=delta)

    def speed_changed(self, value: int) -> None:
        speed = value / 100.0
        if self.speed_value_label is not None:
            self.speed_value_label.setText(f"{speed:.2f}")
        self.send("speed", speed=speed)
        self.update_motion_command()

    def update_motion_command(self) -> None:
        if self.speed_slider is None:
            return
        speed = self.speed_slider.value() / 100.0
        vx = vy = yaw = 0.0
        # W/S forward/back, A/D lateral, Q/E turn left/right.
        if Qt.Key_W in self.pressed_keys:
            vx += speed
        if Qt.Key_S in self.pressed_keys:
            vx -= speed
        if Qt.Key_A in self.pressed_keys:
            vy += speed
        if Qt.Key_D in self.pressed_keys:
            vy -= speed
        if Qt.Key_Q in self.pressed_keys:
            yaw += 1.0
        if Qt.Key_E in self.pressed_keys:
            yaw -= 1.0
        self.send("motion", vx=vx, vy=vy, yaw=yaw)

    def key_command(self, key: int, pressed: bool) -> None:
        if key not in (Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D, Qt.Key_Q, Qt.Key_E):
            return
        if pressed:
            self.pressed_keys.add(key)
        else:
            self.pressed_keys.discard(key)
        self.update_motion_command()

    def camera_command(self, operation: str, values: object) -> None:
        if operation == "zoom":
            steps = float(values)
            self.send("zoom", factor=0.85 ** steps)
        elif operation in ("rotate", "pan"):
            dx, dy = values  # type: ignore[misc]
            self.send(operation, dx=float(dx), dy=float(dy))

    def show_frame(self, image: QImage) -> None:
        self.last_image = image
        self.update_render_pixmap()

    def update_render_pixmap(self) -> None:
        if self.last_image is None:
            return
        pixmap = QPixmap.fromImage(self.last_image)
        target = self.render_label.size()
        if pixmap.size() == target:
            self.render_label.setPixmap(pixmap)
        else:
            # Fast scaling keeps the GUI thread below the 30 FPS frame budget;
            # the source image is already rendered at 720p.
            self.render_label.setPixmap(pixmap.scaled(
                target, Qt.KeepAspectRatio, Qt.FastTransformation
            ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_render_pixmap()

    def show_error(self, message: str) -> None:
        self.status_label.setText(message)
        self.render_label.setText(message)
        for button in self.control_buttons:
            button.setEnabled(False)

    def go_back(self) -> None:
        self.stop_worker()
        self.back_requested.emit()

    def closeEvent(self, event) -> None:
        self.stop_worker()
        event.accept()
