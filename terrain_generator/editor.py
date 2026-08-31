"""Small dependency-free GUI for composing standard robot obstacles."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from .models import ArenaScene, TerrainConfig, TerrainElement, SUPPORTED_ELEMENT_TYPES
from .presets import playground_scene
from .scene import export_scene


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


class ArenaEditor:
    def __init__(self, root: tk.Tk, output_dir: str | Path,
                 base_scene: str | Path | None = None) -> None:
        self.root = root
        self.output_dir = Path(output_dir)
        self.scene = ArenaScene(name="edited_arena", terrain=TerrainConfig(
            kind="flat", rows=192, cols=320, length=20.0, width=12.0, height=0.05,
        ), base_scene=str(base_scene) if base_scene else None)
        self.selected_kind = "platform"
        self.selected_index: int | None = None
        self.scale = 40.0
        self.canvas = tk.Canvas(root, width=900, height=560, background="#dce8d4", highlightthickness=0)
        self.canvas.grid(row=0, column=1, rowspan=2, padx=8, pady=8)
        self.canvas.bind("<Button-1>", self.place_element)
        self.listbox = tk.Listbox(root, width=22, height=25)
        self.listbox.grid(row=0, column=0, padx=8, pady=8, sticky="n")
        self.listbox.bind("<<ListboxSelect>>", self.select_element)

        form = tk.Frame(root)
        form.grid(row=0, column=2, padx=8, pady=8, sticky="n")
        tk.Label(form, text="朝向 yaw (deg)").grid(row=0, column=0, sticky="w")
        self.yaw_var = tk.StringVar(value="0")
        tk.Entry(form, textvariable=self.yaw_var, width=18).grid(row=1, column=0, pady=(0, 8))
        tk.Label(form, text="障碍参数 JSON").grid(row=2, column=0, sticky="w")
        self.params_var = tk.StringVar(value=json.dumps(DEFAULT_PARAMS["platform"], ensure_ascii=False))
        tk.Entry(form, textvariable=self.params_var, width=36).grid(row=3, column=0, pady=(0, 8))
        tk.Label(form, text="例如：{\"height\": 1.0}", fg="#555").grid(row=4, column=0, sticky="w")
        tk.Button(form, text="更新选中障碍", command=self.update_selected).grid(row=5, column=0, pady=8, sticky="ew")

        palette = tk.Frame(root)
        palette.grid(row=1, column=0, padx=8, pady=4, sticky="s")
        for row, kind in enumerate(SUPPORTED_ELEMENT_TYPES):
            tk.Button(palette, text=ELEMENT_LABELS[kind], width=15,
                      command=lambda item=kind: self.choose_kind(item)).grid(row=row // 2, column=row % 2, padx=2, pady=2)
        tk.Button(root, text="载入标准测试场地", command=self.load_preset).grid(row=2, column=0, padx=8, pady=4, sticky="ew")
        tk.Button(root, text="删除选中障碍", command=self.delete_selected).grid(row=3, column=0, padx=8, pady=4, sticky="ew")
        tk.Button(root, text="清空障碍", command=self.clear).grid(row=4, column=0, padx=8, pady=4, sticky="ew")
        tk.Button(root, text="一键导出 MuJoCo", command=self.export).grid(row=5, column=0, padx=8, pady=4, sticky="ew")
        self.status = tk.StringVar(value="选择左侧障碍后，在场地中点击放置")
        tk.Label(root, textvariable=self.status, wraplength=170, justify="left").grid(row=6, column=0, padx=8, pady=8)
        root.title("MuJoCo 机器人测试场地编辑器")
        self.redraw()

    def world_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return 450 + x * self.scale, 280 - y * self.scale

    def canvas_to_world(self, x: float, y: float) -> tuple[float, float]:
        return (x - 450) / self.scale, (280 - y) / self.scale

    def choose_kind(self, kind: str) -> None:
        self.selected_kind = kind
        self.params_var.set(json.dumps(DEFAULT_PARAMS[kind], ensure_ascii=False))
        self.status.set(f"当前工具：{ELEMENT_LABELS[kind]}。点击场地放置")

    def place_element(self, event: tk.Event) -> None:
        x, y = self.canvas_to_world(event.x, event.y)
        try:
            params = json.loads(self.params_var.get())
            yaw = float(self.yaw_var.get())
            if not isinstance(params, dict):
                raise ValueError("参数必须是 JSON 对象")
        except (json.JSONDecodeError, ValueError) as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self.scene.elements.append(TerrainElement(self.selected_kind, x=x, y=y, yaw=yaw,
                                                  name=f"{self.selected_kind}_{len(self.scene.elements):02d}", params=params))
        self.selected_index = len(self.scene.elements) - 1
        self.redraw()

    def select_element(self, _event: tk.Event) -> None:
        selection = self.listbox.curselection()
        self.selected_index = selection[0] if selection else None
        if self.selected_index is not None:
            element = self.scene.elements[self.selected_index]
            self.selected_kind = element.kind
            self.yaw_var.set(str(element.yaw))
            self.params_var.set(json.dumps(element.params, ensure_ascii=False))
        self.redraw()

    def update_selected(self) -> None:
        if self.selected_index is None:
            self.status.set("请先在列表中选择一个障碍")
            return
        try:
            params = json.loads(self.params_var.get())
            yaw = float(self.yaw_var.get())
            if not isinstance(params, dict):
                raise ValueError("参数必须是 JSON 对象")
        except (json.JSONDecodeError, ValueError) as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        element = self.scene.elements[self.selected_index]
        element.yaw = yaw
        element.params = params
        self.redraw()

    def delete_selected(self) -> None:
        if self.selected_index is not None:
            self.scene.elements.pop(self.selected_index)
            self.selected_index = None
            self.redraw()

    def clear(self) -> None:
        self.scene.elements.clear()
        self.selected_index = None
        self.redraw()

    def load_preset(self) -> None:
        preset = playground_scene()
        preset.base_scene = self.scene.base_scene
        self.scene = preset
        self.selected_index = None
        self.redraw()

    def export(self) -> None:
        paths = export_scene(self.scene, self.output_dir)
        self.status.set(f"已导出到：{self.output_dir}")
        messagebox.showinfo("导出完成", f"MuJoCo XML：\n{paths['xml']}\n\n可用 --view 打开可视化。")

    def redraw(self) -> None:
        self.canvas.delete("all")
        left, top = self.world_to_canvas(-self.scene.terrain.length / 2, self.scene.terrain.width / 2)
        right, bottom = self.world_to_canvas(self.scene.terrain.length / 2, -self.scene.terrain.width / 2)
        self.canvas.create_rectangle(left, top, right, bottom, fill="#b8d5a8", outline="#54734b", width=2)
        for index, element in enumerate(self.scene.elements):
            cx, cy = self.world_to_canvas(element.x, element.y)
            selected = index == self.selected_index
            radius = 18 if element.kind == "stepping_stones" else 25
            self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                                    fill="#e8a23a" if not selected else "#e33d3d", outline="#432", width=2)
            self.canvas.create_text(cx, cy, text=str(index + 1), fill="white")
        self.listbox.delete(0, tk.END)
        for index, element in enumerate(self.scene.elements):
            self.listbox.insert(tk.END, f"{index + 1}. {ELEMENT_LABELS[element.kind]}")


def launch_editor(output_dir: str | Path = "generated/editor",
                  base_scene: str | Path | None = None) -> None:
    # Keep the old Tk class above for compatibility with downstream imports;
    # the application entry point now uses the blue-white PyQt editor.
    from .qt_editor import launch_qt_editor

    launch_qt_editor(output_dir, base_scene)
