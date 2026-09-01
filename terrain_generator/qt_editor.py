"""Blue-white PyQt editor with a live top-down arena preview."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import PyQt5
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPolygonF
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QStackedWidget, QStatusBar, QVBoxLayout,
    QWidget,
)

from .models import ArenaScene, TerrainConfig, TerrainElement, SUPPORTED_ELEMENT_TYPES
from .embedded_mujoco import EmbeddedSimulationPage
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
    "slalom_poles": "绕杆",
    "sandpit": "沙坑",
    "high_wall": "高墙",
}

DEFAULT_PARAMS = {
    "platform": {"length": 2.0, "width": 2.0, "height": 0.8},
    "stairs": {"length": 3.0, "width": 2.0, "height": 0.8, "steps": 8},
    "hollow_stairs": {"length": 3.2, "width": 2.4, "height": 0.8, "steps": 8, "thickness": 0.05},
    "ramp": {"length": 3.0, "width": 2.0, "height": 0.8, "thickness": 0.16},
    "stepping_stones": {"rows": 4, "cols": 6, "spacing_x": 0.45, "spacing_y": 0.6, "size": 0.3, "height": 0.3},
    "triangle": {"count": 4, "length": 0.9, "width": 1.0, "height": 0.8, "angle": 30.0, "gap": 0.28, "stagger": 0.8, "pair_yaw": 90.0, "group_spacing": 1.3, "pair_spacing": 1.18},
    "tire_ring": {"count": 3, "spacing": 0.85, "major_radius": 0.27, "minor_radius": 0.10, "upright": False},
    "slalom_poles": {"count": 6, "spacing": 0.8, "radius": 0.07, "height": 1.2, "zigzag": 0.32},
    "sandpit": {"length": 2.4, "width": 2.0, "depth": 0.06, "border": 0.12},
    "high_wall": {"length": 2.4, "thickness": 0.22, "height": 1.2},
}

PARAM_SCHEMA = {
    "platform": [("length", "长度", "m", "float"), ("width", "宽度", "m", "float"), ("height", "高度", "m", "float")],
    "stairs": [("length", "总长度", "m", "float"), ("width", "宽度", "m", "float"), ("height", "总高度", "m", "float"), ("steps", "级数", "级", "int")],
    "hollow_stairs": [("length", "总长度", "m", "float"), ("width", "宽度", "m", "float"), ("height", "总高度", "m", "float"), ("steps", "级数", "级", "int"), ("thickness", "踏板厚度", "m", "float")],
    "ramp": [("length", "长度", "m", "float"), ("width", "宽度", "m", "float"), ("height", "高度", "m", "float")],
    "stepping_stones": [("rows", "行数", "行", "int"), ("cols", "列数", "列", "int"), ("spacing_x", "横向间距", "m", "float"), ("spacing_y", "纵向间距", "m", "float"), ("size", "方柱边长", "m", "float"), ("height", "方柱高度", "m", "float")],
    "triangle": [("count", "数量", "个", "int"), ("length", "单个长度", "m", "float"), ("width", "宽度", "m", "float"), ("height", "高度", "m", "float"), ("angle", "顶角", "deg", "float"), ("gap", "间隙", "m", "float"), ("stagger", "左右错位", "m", "float"), ("pair_yaw", "每组旋转", "deg", "float"), ("group_spacing", "组间距", "m", "float"), ("pair_spacing", "组内间距", "m", "float")],
    "tire_ring": [("count", "数量", "个", "int"), ("spacing", "间距", "m", "float"), ("major_radius", "轮胎主半径", "m", "float"), ("minor_radius", "轮胎厚度", "m", "float"), ("upright", "竖放", "", "bool")],
    "slalom_poles": [("count", "杆数", "根", "int"), ("spacing", "杆间距", "m", "float"), ("radius", "杆半径", "m", "float"), ("height", "杆高", "m", "float"), ("zigzag", "交错距离", "m", "float")],
    "sandpit": [("length", "长度", "m", "float"), ("width", "宽度", "m", "float"), ("depth", "深度", "m", "float"), ("border", "边框宽度", "m", "float")],
    "high_wall": [("length", "墙长", "m", "float"), ("thickness", "墙厚", "m", "float"), ("height", "墙高", "m", "float")],
}

COLORS = {
    "platform": "#2374c6", "stairs": "#3d8ed0", "hollow_stairs": "#5b9fda",
    "ramp": "#2a9d8f", "stepping_stones": "#6b7c93", "triangle": "#e76f51",
    "tire_ring": "#263238", "slalom_poles": "#d1493f", "sandpit": "#c89b5a", "high_wall": "#315f9c",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_M20_SCENE = Path("assets/m20/mjcf/scene.xml")
BUNDLED_M20_POLICY = Path("policies/m20/policy.onnx")


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
        self.element_action = None
        self.element_moved = None
        self.drag_index: int | None = None
        self.edit_mode = False

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

    def hit_test(self, x: float, y: float) -> int | None:
        """Return the topmost approximate element under a world-space point."""

        for index in range(len(self.arena.elements) - 1, -1, -1):
            element = self.arena.elements[index]
            dx, dy = rotate_xy(x - element.x, y - element.y, -element.yaw)
            params = element.params
            if element.kind in ("platform", "stairs", "hollow_stairs", "ramp", "sandpit", "high_wall"):
                length = float(params.get("length", 2.4))
                width = float(params.get("width", params.get("thickness", 1.0)))
                if abs(dx) <= length / 2 + 0.25 and abs(dy) <= width / 2 + 0.25:
                    return index
            elif element.kind == "stepping_stones":
                rows, cols = max(1, int(params.get("rows", 1))), max(1, int(params.get("cols", 9)))
                spacing_x = float(params.get("spacing_x", params.get("spacing", .45)))
                spacing_y = float(params.get("spacing_y", params.get("spacing", .6)))
                if abs(dx) <= cols * spacing_x / 2 + .3 and abs(dy) <= rows * spacing_y / 2 + .3:
                    return index
            elif element.kind in ("triangle", "tire_ring", "slalom_poles"):
                reach = max(float(params.get("length", 1.0)), float(params.get("spacing", .8)) * 2, 1.0)
                if dx * dx + dy * dy <= reach * reach:
                    return index
        return None

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
            rows = max(1, int(p.get("rows", 1)))
            cols = max(1, int(p.get("cols", p.get("count", 9))))
            spacing_x = float(p.get("spacing_x", p.get("spacing", .45)))
            spacing_y = float(p.get("spacing_y", p.get("spacing", .6)))
            side = float(p.get("size", float(p.get("radius", .15)) * 2))
            for row in range(rows):
                row_offset = spacing_x / 2 if row % 2 else 0.0
                for col in range(cols):
                    x = (col - (cols - 1) / 2) * spacing_x + row_offset
                    y = (row - (rows - 1) / 2) * spacing_y
                    points = [(px + x, py + y) for px, py in self.rect_points(element, side, side)]
                    painter.drawPolygon(self.polygon(element, points))
        elif element.kind == "slalom_poles":
            count, spacing = max(1, int(p.get("count", 6))), float(p.get("spacing", .8))
            zigzag, radius = float(p.get("zigzag", .32)), float(p.get("radius", .07))
            for i in range(count):
                x, y = (i - (count - 1) / 2) * spacing, zigzag if i % 2 else -zigzag
                center = self.world_to_view(element.x + rotate_xy(x, y, element.yaw)[0], element.y + rotate_xy(x, y, element.yaw)[1])
                r = max(4, radius * min(self.width() / self.arena.terrain.length, self.height() / self.arena.terrain.width))
                painter.drawEllipse(center, r, r)
        elif element.kind == "sandpit":
            length, width = float(p.get("length", 2.4)), float(p.get("width", 2.0))
            painter.setBrush(QBrush(QColor("#d5b276")))
            painter.drawPolygon(self.polygon(element, self.rect_points(element, length, width)))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#9a743e"), 3))
            painter.drawPolygon(self.polygon(element, self.rect_points(element, length, width)))
        elif element.kind == "high_wall":
            length, thickness = float(p.get("length", 2.4)), float(p.get("thickness", .22))
            painter.drawPolygon(self.polygon(element, self.rect_points(element, length, thickness)))
        elif element.kind == "tire_ring":
            count, spacing, major = max(1, int(p.get("count", 3))), float(p.get("spacing", .85)), float(p.get("major_radius", .27))
            for i in range(count):
                x = (i - (count - 1) / 2) * spacing
                wx, wy = rotate_xy(x, 0, element.yaw)
                center = self.world_to_view(element.x + wx, element.y + wy)
                r = major * min(self.width() / self.arena.terrain.length, self.height() / self.arena.terrain.width)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(color, max(4, int(float(p.get("minor_radius", .10)) * 2 * r))))
                painter.drawEllipse(center, r, r)
        elif element.kind == "triangle":
            count = max(1, int(p.get("count", 4)))
            length, width = float(p.get("length", .9)), float(p.get("width", 1.8))
            group_spacing = float(p.get("group_spacing", width + float(p.get("gap", .28))))
            pair_spacing = float(p.get("pair_spacing", length + float(p.get("gap", .28))))
            for i in range(count):
                pair_slot, group_index = i % 2, i // 2
                groups = (count + 1) // 2
                x = (group_index - (groups - 1) / 2) * group_spacing
                x += -float(p.get("stagger", 0.8)) / 2 if pair_slot == 0 else float(p.get("stagger", 0.8)) / 2
                y = -pair_spacing / 2 if pair_slot == 0 else pair_spacing / 2
                pair_angle = float(p.get("pair_yaw", 90.0))
                points_rotation = pair_angle
                if i % 2 == 0:
                    points = [(length / 2, -width / 2), (-length / 2, 0), (length / 2, width / 2)]
                else:
                    points = [(-length / 2, -width / 2), (length / 2, 0), (-length / 2, width / 2)]
                points = [(rotate_xy(px, py, points_rotation)[0] + x,
                           rotate_xy(px, py, points_rotation)[1] + y) for px, py in points]
                painter.drawPolygon(self.polygon(element, points))

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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.element_action:
            x, y = self.view_to_world(event.x(), event.y())
            ctrl = bool(event.modifiers() & Qt.ControlModifier)
            hit = self.hit_test(x, y)
            if hit is not None:
                self.drag_index = hit
                self.edit_mode = ctrl
            else:
                self.drag_index = None
                self.edit_mode = False
            self.element_action(x, y, ctrl)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.drag_index = None

    def mouseMoveEvent(self, event) -> None:
        self.hover_world = self.view_to_world(event.x(), event.y())
        if self.drag_index is not None and self.edit_mode and self.drag_index < len(self.arena.elements):
            element = self.arena.elements[self.drag_index]
            element.x, element.y = self.hover_world
            if self.element_moved:
                self.element_moved(self.drag_index, *self.hover_world)
        self.update()


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
        self.latest_xml: Path | None = None
        self.latest_policy: Path | None = None
        self.setWindowTitle("MuJoCo 机器人 Play 测试场地编辑器")
        self.resize(1440, 820)
        self.build_ui()
        self.simulation_page = EmbeddedSimulationPage(self)
        self.simulation_page.back_requested.connect(self.show_editor_page)
        self.page_stack.addWidget(self.simulation_page)
        self.apply_style()
        self.refresh()

    def build_ui(self) -> None:
        self.page_stack = QStackedWidget()
        self.setCentralWidget(self.page_stack)
        editor_page = QWidget()
        self.page_stack.addWidget(editor_page)
        main_layout = QHBoxLayout(editor_page)
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
        self.tool_combo.currentIndexChanged.connect(self.tool_changed)
        left_layout.addWidget(QLabel("放置障碍类型"))
        left_layout.addWidget(self.tool_combo)
        left_layout.addWidget(QLabel("点击空白处添加；点击障碍选中。Ctrl+点击进入拖动编辑"))
        self.element_list = QListWidget()
        self.element_list.setSelectionMode(QListWidget.SingleSelection)
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
        self.preview.element_action = self.handle_preview_click
        self.preview.element_moved = self.handle_element_moved
        splitter.addWidget(self.preview)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("障碍编辑"))
        self.params_box = QGroupBox("障碍参数（填写后实时预览）")
        self.params_form = QFormLayout(self.params_box)
        self.param_widgets: dict[str, QWidget] = {}
        right_layout.addWidget(self.params_box)
        action_row = QHBoxLayout()
        self.delete_action = QPushButton("✕ 删除")
        self.delete_action.setObjectName("deleteAction")
        self.delete_action.clicked.connect(self.delete_selected)
        self.confirm_action = QPushButton("✓ 保存障碍")
        self.confirm_action.setObjectName("confirmAction")
        self.confirm_action.clicked.connect(self.confirm_selected)
        action_row.addWidget(self.delete_action)
        action_row.addWidget(self.confirm_action)
        right_layout.addLayout(action_row)
        rotate_box = QGroupBox("快速旋转（吸附到 90°）")
        rotate_layout = QHBoxLayout(rotate_box)
        for text, angle in (("90°", 90), ("180°", 180), ("270°", 270)):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, value=angle: self.rotate_selected(value))
            rotate_layout.addWidget(button)
        right_layout.addWidget(rotate_box)
        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        right_layout.addWidget(self.error_label)
        scene_box = QGroupBox("导出设置")
        scene_form = QFormLayout(scene_box)
        self.output_edit = QLineEdit(str(self.output_dir))
        self.base_scene_edit = QLineEdit(self.scene.base_scene or "")
        scene_form.addRow("输出目录", self.output_edit)
        scene_form.addRow("自定义机器人 XML（可选）", self.base_scene_edit)
        right_layout.addWidget(scene_box)
        self.robot_checkbox = QCheckBox("添加 M20 机器人并运行策略")
        self.robot_checkbox.setToolTip("勾选后使用仓库内置 M20 和 policies/m20/policy.onnx")
        right_layout.addWidget(self.robot_checkbox)
        self.view_button = QPushButton("导出并在 MuJoCo 查看")
        self.view_button.clicked.connect(self.export_and_view)
        right_layout.addWidget(self.view_button)
        self.next_button = QPushButton("→")
        self.next_button.setToolTip("进入 MuJoCo 仿真页面")
        self.next_button.setMinimumHeight(44)
        self.next_button.setVisible(False)
        self.next_button.clicked.connect(self.open_simulation_page)
        right_layout.addWidget(self.next_button)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([250, 850, 330])
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("点击空白处新增障碍，点击障碍选中；Ctrl+点击可拖动编辑")
        self.rebuild_param_form(self.current_kind(), DEFAULT_PARAMS[self.current_kind()])

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
            #deleteAction { background: #d94b55; }
            #deleteAction:hover { background: #b62f3a; }
            #confirmAction { background: #2f9d67; }
            #confirmAction:hover { background: #22794e; }
            #error { color: #d64545; }
        """)

    def current_kind(self) -> str:
        return str(self.tool_combo.currentData())

    def handle_preview_click(self, x: float, y: float, ctrl: bool) -> None:
        index = self.preview.hit_test(x, y)
        if index is None:
            self.add_element_at(x, y)
            return
        self.element_list.clearSelection()
        self.element_list.setCurrentRow(index)
        self.element_list.item(index).setSelected(True)
        self.preview.edit_mode = ctrl
        self.statusBar().showMessage("单障碍编辑：拖动障碍调整位置；使用右侧旋转按钮，确认后保存或删除" if ctrl else "已选中障碍（Ctrl+点击可进入拖动编辑）")

    def handle_element_moved(self, index: int, x: float, y: float) -> None:
        if 0 <= index < len(self.scene.elements):
            self.scene.elements[index].x = x
            self.scene.elements[index].y = y
            self.selected_index = index
            self.preview.selected_index = index
            self.element_list.setCurrentRow(index)
            self.preview.update()

    def tool_changed(self, _index: int) -> None:
        self.rebuild_param_form(self.current_kind(), DEFAULT_PARAMS[self.current_kind()])

    def rebuild_param_form(self, kind: str, values: dict) -> None:
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self.param_widgets.clear()
        for key, label, unit, value_type in PARAM_SCHEMA[kind]:
            if value_type == "int":
                widget = QSpinBox()
                widget.setRange(1, 1000)
                widget.setValue(int(values.get(key, DEFAULT_PARAMS[kind].get(key, 1))))
                widget.valueChanged.connect(self.update_selected)
            elif value_type == "bool":
                widget = QCheckBox("是")
                widget.setChecked(bool(values.get(key, DEFAULT_PARAMS[kind].get(key, False))))
                widget.stateChanged.connect(self.update_selected)
            else:
                widget = self.make_spin(0.001, 100.0, 0.05)
                widget.setValue(float(values.get(key, DEFAULT_PARAMS[kind].get(key, 0.1))))
                widget.valueChanged.connect(self.update_selected)
            self.param_widgets[key] = widget
            self.params_form.addRow(f"{label}{f' ({unit})' if unit else ''}", widget)

    def read_params(self) -> dict:
        values = {}
        kind = self.current_kind()
        for key, _label, _unit, value_type in PARAM_SCHEMA[kind]:
            widget = self.param_widgets[key]
            if value_type == "int":
                values[key] = int(widget.value())
            elif value_type == "bool":
                values[key] = bool(widget.isChecked())
            else:
                values[key] = float(widget.value())
        return values

    def write_params(self, kind: str, values: dict) -> None:
        self.rebuild_param_form(kind, values)

    def add_element_at(self, x: float, y: float) -> None:
        kind = self.current_kind()
        index = len(self.scene.elements)
        element = TerrainElement(kind, x=x, y=y, name=f"{kind}_{index:02d}", params=dict(DEFAULT_PARAMS[kind]))
        self.scene.elements.append(element)
        self.selected_index = index
        self.refresh(select=index)

    def selected_indices(self) -> list[int]:
        return sorted({self.element_list.row(item) for item in self.element_list.selectedItems()})

    def select_element(self, index: int) -> None:
        self.selected_index = index if index >= 0 else None
        self.preview.selected_index = self.selected_index
        if self.selected_index is not None:
            element = self.scene.elements[self.selected_index]
            self.tool_combo.blockSignals(True)
            self.tool_combo.setCurrentIndex(self.tool_combo.findData(element.kind))
            self.tool_combo.blockSignals(False)
            self.write_params(element.kind, element.params)
        self.preview.update()

    def update_selected(self) -> None:
        if self.selected_index is None or self.selected_index >= len(self.scene.elements):
            return
        element = self.scene.elements[self.selected_index]
        element.params = self.read_params()
        self.error_label.setText("")
        self.preview.update()

    def confirm_selected(self) -> None:
        self.update_selected()
        self.statusBar().showMessage("已确认当前障碍参数")

    def rotate_selected(self, angle: float) -> None:
        indices = self.selected_indices()
        if not indices and self.selected_index is not None:
            indices = [self.selected_index]
        for index in indices:
            element = self.scene.elements[index]
            element.yaw = (round((element.yaw + angle) / 90.0) * 90.0) % 360.0
        self.refresh(select=self.selected_index)
        self.statusBar().showMessage(f"已将 {len(indices)} 个障碍旋转并吸附到 90°")

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
        indices = self.selected_indices()
        if not indices and self.selected_index is not None:
            indices = [self.selected_index]
        for index in reversed(indices):
            self.scene.elements.pop(index)
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

    def prepare_scene(self, base_scene_override: Path | None = None) -> None:
        self.scene.base_scene = str(base_scene_override) if base_scene_override else self.base_scene_edit.text().strip() or None
        output_root = Path(self.output_edit.text().strip() or "generated/editor").expanduser().resolve()
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        output_root.mkdir(parents=True, exist_ok=True)
        candidate = output_root / f"output_{timestamp}"
        suffix = 1
        while candidate.exists():
            candidate = output_root / f"output_{timestamp}_{suffix:02d}"
            suffix += 1
        self.output_dir = candidate

    def export(self, base_scene_override: Path | None = None,
               include_test_ball: bool = False) -> dict[str, Path] | None:
        self.prepare_scene(base_scene_override)
        try:
            paths = export_scene(self.scene, self.output_dir, include_test_ball=include_test_ball)
            self.statusBar().showMessage(f"已导出：{paths['xml']}")
            return paths
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return None

    def export_and_view(self) -> None:
        robot_enabled = self.robot_checkbox.isChecked()
        bundled_scene = PROJECT_ROOT / BUNDLED_M20_SCENE if robot_enabled else None
        if robot_enabled:
            bundled_policy = PROJECT_ROOT / BUNDLED_M20_POLICY
            if not bundled_scene.is_file() or not bundled_policy.is_file():
                QMessageBox.critical(
                    self, "M20 资源缺失",
                    f"找不到内置 M20 场景或策略：\n{bundled_scene}\n{bundled_policy}",
                )
                return

        paths = self.export(base_scene_override=bundled_scene)
        if not paths:
            return
        self.latest_xml = paths["xml"]
        self.latest_policy = PROJECT_ROOT / BUNDLED_M20_POLICY if robot_enabled else None
        self.next_button.setVisible(True)
        self.next_button.setEnabled(True)
        mode = "M20 策略场景" if robot_enabled else "普通场景"
        self.statusBar().showMessage(f"已导出 {mode}：点击右侧 → 进入内嵌 MuJoCo 页面")

    def open_simulation_page(self) -> None:
        if self.latest_xml is None:
            return
        config = PROJECT_ROOT / "configs" / "m20.yaml" if self.latest_policy else None
        self.simulation_page.start(self.latest_xml, self.latest_policy, config)
        self.page_stack.setCurrentWidget(self.simulation_page)

    def show_editor_page(self) -> None:
        self.page_stack.setCurrentIndex(0)


def launch_qt_editor(output_dir: str | Path = "generated/editor",
                     base_scene: str | Path | None = None) -> None:
    platform_plugins = Path(PyQt5.__file__).resolve().parent / "Qt5" / "plugins" / "platforms"
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(platform_plugins))
    app = QApplication.instance() or QApplication(sys.argv)
    window = QtArenaEditor(output_dir, base_scene)
    window.show()
    app.exec_()
