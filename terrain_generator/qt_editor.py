"""Blue-white PyQt editor with a live top-down arena preview."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPolygonF
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QPlainTextEdit, QSplitter, QStatusBar, QVBoxLayout,
    QWidget,
)

from .models import ArenaScene, TerrainConfig, TerrainElement, SUPPORTED_ELEMENT_TYPES
from .presets import playground_scene
from .scene import export_scene, load_scene


ELEMENT_LABELS = {
    "platform": "高台",
    "stairs": "台阶",
    "hollow_stairs": "镂空台阶",
    "ramp": "斜坡",
    "stepping_stones": "梅花桩",
    "triangle": "三角障碍",
    "tire_ring": "轮胎圈",
}

DEFAULT_PARAMS = {
    "platform": {"length": 2.0, "width": 2.0, "height": 0.8},
    "stairs": {"length": 3.0, "width": 2.0, "height": 0.8, "steps": 8},
    "hollow_stairs": {"length": 3.0, "width": 2.0, "height": 0.8, "steps": 8, "thickness": 0.16},
    "ramp": {"length": 3.0, "width": 2.0, "height": 0.8, "thickness": 0.16},
    "stepping_stones": {"count": 9, "spacing": 0.85, "radius": 0.34, "height": 0.45},
    "triangle": {"length": 2.5, "width": 2.0, "height": 0.8},
    "tire_ring": {"count": 3, "spacing": 1.1, "major_radius": 0.52, "minor_radius": 0.14, "upright": True},
}

COLORS = {
    "platform": "#2374c6", "stairs": "#3d8ed0", "hollow_stairs": "#5b9fda",
    "ramp": "#2a9d8f", "stepping_stones": "#6b7c93", "triangle": "#e76f51",
    "tire_ring": "#263238",
}


def rotate_xy(x: float, y: float, yaw: float) -> tuple[float, float]:
    import math

    angle = math.radians(yaw)
    return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)


class PreviewWidget(QWidget):
    """Paint a live, lightweight top-down representation of the arena."""

    element_added = None

    def __init__(self, scene: ArenaScene, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.arena = scene
        self.selected_index: int | None = None
        self.setMinimumSize(700, 520)
        self.setMouseTracking(True)
        self.hover_world: tuple[float, float] | None = None

    def set_scene(self, scene: ArenaScene) -> None:
        self.arena = scene
        self.update()

    def world_to_view(self, x: float, y: float) -> QPointF:
        margin = 35.0
        config = self.arena.terrain
        scale = min((self.width() - margin * 2) / config.length,
                    (self.height() - margin * 2) / config.width)
        return QPointF(self.width() / 2 + x * scale, self.height() / 2 - y * scale)

    def view_to_world(self, x: float, y: float) -> tuple[float, float]:
        margin = 35.0
        config = self.arena.terrain
        scale = min((self.width() - margin * 2) / config.length,
                    (self.height() - margin * 2) / config.width)
        return (x - self.width() / 2) / scale, (self.height() / 2 - y) / scale

    def polygon(self, element: TerrainElement, points: list[tuple[float, float]]) -> QPolygonF:
        return QPolygonF([self.world_to_view(element.x + rotate_xy(x, y, element.yaw)[0],
                                              element.y + rotate_xy(x, y, element.yaw)[1]) for x, y in points])

    def rect_points(self, element: TerrainElement, length: float, width: float) -> list[tuple[float, float]]:
        return [(-length / 2, -width / 2), (length / 2, -width / 2),
                (length / 2, width / 2), (-length / 2, width / 2)]

    def draw_element(self, painter: QPainter, element: TerrainElement, selected: bool) -> None:
        import math

        p = element.params
        color = QColor("#f04f4f" if selected else COLORS[element.kind])
        painter.setPen(QPen(QColor("#ffffff"), 2 if selected else 1))
        painter.setBrush(QBrush(color))
        if element.kind == "platform":
            shape = self.polygon(element, self.rect_points(element, float(p.get("length", 2)), float(p.get("width", 2))))
            painter.drawPolygon(shape)
        elif element.kind in ("stairs", "hollow_stairs"):
            length, width = float(p.get("length", 3)), float(p.get("width", 2))
            steps = max(1, int(p.get("steps", 8)))
            for i in range(steps):
                x = -length / 2 + length * (i + 0.5) / steps
                step = length / steps
                points = [(x - step / 2, -width / 2), (x + step / 2, -width / 2),
                          (x + step / 2, width / 2), (x - step / 2, width / 2)]
                painter.setBrush(QBrush(QColor(color).lighter(100 + i * 5)))
                painter.drawPolygon(self.polygon(element, points))
                if element.kind == "hollow_stairs":
                    painter.setPen(QPen(QColor("#ffffff"), 1))
                    inner = self.polygon(element, [(x - step * .35, -width * .35), (x + step * .35, -width * .35),
                                                   (x + step * .35, width * .35), (x - step * .35, width * .35)])
                    painter.drawPolygon(inner)
        elif element.kind == "ramp":
            shape = self.polygon(element, self.rect_points(element, float(p.get("length", 3)), float(p.get("width", 2))))
            painter.drawPolygon(shape)
            center = self.world_to_view(element.x, element.y)
            painter.setPen(QPen(QColor("#d8fff7"), 3))
            painter.drawLine(center, self.world_to_view(element.x + rotate_xy(float(p.get("length", 3)) / 2, 0, element.yaw)[0],
                                                               element.y + rotate_xy(float(p.get("length", 3)) / 2, 0, element.yaw)[1]))
        elif element.kind == "stepping_stones":
            count, spacing, radius = max(1, int(p.get("count", 9))), float(p.get("spacing", .85)), float(p.get("radius", .34))
            points = [(0.0, 0.0)] + [(spacing * math.cos(2 * math.pi * i / max(count - 1, 1)),
                                     spacing * math.sin(2 * math.pi * i / max(count - 1, 1))) for i in range(count - 1)]
            for x, y in points[:count]:
                center = self.world_to_view(element.x + rotate_xy(x, y, element.yaw)[0], element.y + rotate_xy(x, y, element.yaw)[1])
                r = max(4, radius * min(self.width() / self.arena.terrain.length, self.height() / self.arena.terrain.width))
                painter.drawEllipse(center, r, r)
        elif element.kind == "triangle":
            length, width = float(p.get("length", 2.5)), float(p.get("width", 2))
            painter.drawPolygon(self.polygon(element, [(-length / 2, -width / 2), (length / 2, 0), (-length / 2, width / 2)]))
        elif element.kind == "tire_ring":
            count, spacing, major = max(1, int(p.get("count", 3))), float(p.get("spacing", 1.1)), float(p.get("major_radius", .52))
            for i in range(count):
                x = (i - (count - 1) / 2) * spacing
                wx, wy = rotate_xy(x, 0, element.yaw)
                center = self.world_to_view(element.x + wx, element.y + wy)
                r = major * min(self.width() / self.arena.terrain.length, self.height() / self.arena.terrain.width)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(color, max(5, int(float(p.get("minor_radius", .14)) * 2 * r))))
                painter.drawEllipse(center, r, r)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f5f9fd"))
        config = self.arena.terrain
        top_left = self.world_to_view(-config.length / 2, config.width / 2)
        bottom_right = self.world_to_view(config.length / 2, -config.width / 2)
        painter.setPen(QPen(QColor("#9bb8d2"), 2))
        painter.setBrush(QBrush(QColor("#e8f2fb")))
        painter.drawRect(QRectF(top_left, bottom_right))
        painter.setPen(QPen(QColor("#c7dbea"), 1, Qt.DashLine))
        for x in range(-int(config.length / 2), int(config.length / 2) + 1):
            a, b = self.world_to_view(x, -config.width / 2), self.world_to_view(x, config.width / 2)
            painter.drawLine(a, b)
        for y in range(-int(config.width / 2), int(config.width / 2) + 1):
            a, b = self.world_to_view(-config.length / 2, y), self.world_to_view(config.length / 2, y)
            painter.drawLine(a, b)
        for index, element in enumerate(self.arena.elements):
            self.draw_element(painter, element, index == self.selected_index)
            center = self.world_to_view(element.x, element.y)
            painter.setPen(QPen(QColor("#17324d"), 1))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(center + QPointF(4, -4), str(index + 1))
        if self.hover_world:
            x, y = self.hover_world
            painter.setPen(QPen(QColor("#2374c6"), 1, Qt.DotLine))
            painter.drawLine(self.world_to_view(x, -config.width / 2), self.world_to_view(x, config.width / 2))
            painter.drawLine(self.world_to_view(-config.length / 2, y), self.world_to_view(config.length / 2, y))
        painter.end()

    def mouseMoveEvent(self, event) -> None:
        self.hover_world = self.view_to_world(event.x(), event.y())
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.element_added:
            self.element_added(*self.view_to_world(event.x(), event.y()))


class QtArenaEditor(QMainWindow):
    def __init__(self, output_dir: str | Path, base_scene: str | Path | None = None) -> None:
        super().__init__()
        self.output_dir = Path(output_dir)
        self.scene = ArenaScene(
            name="edited_arena",
            terrain=TerrainConfig(kind="flat", rows=192, cols=320, length=20.0, width=12.0, height=0.05),
            base_scene=str(base_scene) if base_scene else None,
        )
        self.selected_index: int | None = None
        self.setWindowTitle("MuJoCo 机器人 Play 测试场地编辑器")
        self.resize(1440, 820)
        self.build_ui()
        self.apply_style()
        self.refresh()

    def build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        title = QLabel("PLAYGROUND\n场地组件")
        title.setObjectName("title")
        left_layout.addWidget(title)
        self.tool_combo = QComboBox()
        for kind in SUPPORTED_ELEMENT_TYPES:
            self.tool_combo.addItem(ELEMENT_LABELS[kind], kind)
        left_layout.addWidget(QLabel("放置障碍类型"))
        left_layout.addWidget(self.tool_combo)
        left_layout.addWidget(QLabel("点击中央场地即可放置"))
        self.element_list = QListWidget()
        self.element_list.currentRowChanged.connect(self.select_element)
        left_layout.addWidget(self.element_list, 1)
        self.preset_button = QPushButton("载入标准测试场地")
        self.preset_button.clicked.connect(self.load_preset)
        left_layout.addWidget(self.preset_button)
        self.delete_button = QPushButton("删除选中障碍")
        self.delete_button.clicked.connect(self.delete_selected)
        left_layout.addWidget(self.delete_button)
        self.clear_button = QPushButton("清空场地")
        self.clear_button.clicked.connect(self.clear)
        left_layout.addWidget(self.clear_button)
        splitter.addWidget(left)

        self.preview = PreviewWidget(self.scene)
        self.preview.element_added = self.add_element_at
        splitter.addWidget(self.preview)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("实时参数"))
        form_box = QGroupBox("选中障碍")
        form = QFormLayout(form_box)
        self.x_spin = self.make_spin()
        self.y_spin = self.make_spin()
        self.z_spin = self.make_spin()
        self.yaw_spin = self.make_spin(-180, 180, 1)
        for spin in (self.x_spin, self.y_spin, self.z_spin, self.yaw_spin):
            spin.valueChanged.connect(self.update_selected)
        form.addRow("X (m)", self.x_spin)
        form.addRow("Y (m)", self.y_spin)
        form.addRow("Z (m)", self.z_spin)
        form.addRow("Yaw (deg)", self.yaw_spin)
        right_layout.addWidget(form_box)
        right_layout.addWidget(QLabel("障碍参数 JSON（修改后立即预览）"))
        self.params_edit = QPlainTextEdit()
        self.params_edit.setMaximumHeight(150)
        self.params_edit.textChanged.connect(self.update_selected)
        right_layout.addWidget(self.params_edit)
        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        right_layout.addWidget(self.error_label)
        scene_box = QGroupBox("导出设置")
        scene_form = QFormLayout(scene_box)
        self.output_edit = QLineEdit(str(self.output_dir))
        self.base_scene_edit = QLineEdit(self.scene.base_scene or "")
        scene_form.addRow("输出目录", self.output_edit)
        scene_form.addRow("机器人 XML", self.base_scene_edit)
        right_layout.addWidget(scene_box)
        self.export_button = QPushButton("一键导出 MuJoCo")
        self.export_button.clicked.connect(self.export)
        right_layout.addWidget(self.export_button)
        self.view_button = QPushButton("导出并打开 MuJoCo")
        self.view_button.clicked.connect(self.export_and_view)
        right_layout.addWidget(self.view_button)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([250, 850, 330])
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("选择障碍类型后，在中央场地点击放置；修改参数会实时更新预览")

    @staticmethod
    def make_spin(minimum: float = -100, maximum: float = 100, step: float = 0.1) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(3)
        return spin

    def apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f5f9fd; color: #17324d; font-size: 13px; }
            #title { color: #125a9e; font-size: 24px; font-weight: 700; padding: 10px 2px; }
            QGroupBox { border: 1px solid #bed3e6; border-radius: 8px; margin-top: 12px; padding: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #2374c6; }
            QComboBox, QLineEdit, QPlainTextEdit, QDoubleSpinBox, QListWidget { background: white; border: 1px solid #b7cde1; border-radius: 5px; padding: 5px; }
            QListWidget::item:selected { background: #d9ecff; color: #125a9e; }
            QPushButton { background: #2374c6; color: white; border: 0; border-radius: 5px; padding: 9px; font-weight: 600; }
            QPushButton:hover { background: #155d9f; }
            QPushButton:pressed { background: #0d477c; }
            #error { color: #d64545; }
        """)

    def current_kind(self) -> str:
        return str(self.tool_combo.currentData())

    def add_element_at(self, x: float, y: float) -> None:
        kind = self.current_kind()
        index = len(self.scene.elements)
        element = TerrainElement(kind, x=x, y=y, name=f"{kind}_{index:02d}", params=dict(DEFAULT_PARAMS[kind]))
        self.scene.elements.append(element)
        self.selected_index = index
        self.refresh(select=index)

    def select_element(self, index: int) -> None:
        self.selected_index = index if index >= 0 else None
        self.preview.selected_index = self.selected_index
        if self.selected_index is not None:
            element = self.scene.elements[self.selected_index]
            self.x_spin.blockSignals(True); self.y_spin.blockSignals(True)
            self.z_spin.blockSignals(True); self.yaw_spin.blockSignals(True)
            self.x_spin.setValue(element.x); self.y_spin.setValue(element.y)
            self.z_spin.setValue(element.z); self.yaw_spin.setValue(element.yaw)
            self.x_spin.blockSignals(False); self.y_spin.blockSignals(False)
            self.z_spin.blockSignals(False); self.yaw_spin.blockSignals(False)
            self.params_edit.blockSignals(True)
            self.params_edit.setPlainText(json.dumps(element.params, indent=2, ensure_ascii=False))
            self.params_edit.blockSignals(False)
        self.preview.update()

    def update_selected(self) -> None:
        if self.selected_index is None or self.selected_index >= len(self.scene.elements):
            return
        element = self.scene.elements[self.selected_index]
        element.x, element.y, element.z, element.yaw = (self.x_spin.value(), self.y_spin.value(), self.z_spin.value(), self.yaw_spin.value())
        try:
            params = json.loads(self.params_edit.toPlainText() or "{}")
            if not isinstance(params, dict):
                raise ValueError("参数必须是 JSON 对象")
            element.params = params
            self.error_label.setText("")
        except (json.JSONDecodeError, ValueError) as exc:
            self.error_label.setText(f"参数错误：{exc}")
        self.preview.update()

    def refresh(self, select: int | None = None) -> None:
        self.preview.set_scene(self.scene)
        self.preview.selected_index = self.selected_index
        self.element_list.blockSignals(True)
        self.element_list.clear()
        for index, element in enumerate(self.scene.elements):
            item = QListWidgetItem(f"{index + 1:02d}  {ELEMENT_LABELS[element.kind]}")
            self.element_list.addItem(item)
        self.element_list.blockSignals(False)
        if select is not None and 0 <= select < self.element_list.count():
            self.element_list.setCurrentRow(select)
            self.select_element(select)
        else:
            self.preview.update()

    def delete_selected(self) -> None:
        if self.selected_index is not None:
            self.scene.elements.pop(self.selected_index)
            self.selected_index = None
            self.refresh()

    def clear(self) -> None:
        self.scene.elements.clear()
        self.selected_index = None
        self.refresh()

    def load_preset(self) -> None:
        base_scene = self.scene.base_scene
        self.scene = playground_scene()
        self.scene.base_scene = base_scene
        self.selected_index = None
        self.refresh()

    def prepare_scene(self) -> None:
        self.scene.base_scene = self.base_scene_edit.text().strip() or None
        self.output_dir = Path(self.output_edit.text().strip() or "generated/editor")

    def export(self) -> dict[str, Path] | None:
        self.prepare_scene()
        try:
            paths = export_scene(self.scene, self.output_dir)
            self.statusBar().showMessage(f"已导出：{paths['xml']}")
            return paths
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return None

    def export_and_view(self) -> None:
        paths = self.export()
        if not paths:
            return
        command = [sys.executable, "-m", "terrain_generator.cli", "--scene", str(paths["scene"]),
                   "--output", str(self.output_dir), "--view", "--no-test-ball"]
        subprocess.Popen(command, cwd=str(Path.cwd()))


def launch_qt_editor(output_dir: str | Path = "generated/editor",
                     base_scene: str | Path | None = None) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = QtArenaEditor(output_dir, base_scene)
    window.show()
    app.exec_()
