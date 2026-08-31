"""MuJoCo heightfield and scene export."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
import struct
from xml.etree import ElementTree as ET
import zlib

import numpy as np

from .models import TerrainElement, TerrainMap


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _write_png(path: Path, heights: np.ndarray) -> None:
    pixels = np.rint(np.clip(heights, 0.0, 1.0) * 255.0).astype(np.uint8)
    # Write a dependency-free 8-bit grayscale PNG. MuJoCo loads PNG heightfields
    # directly, and this avoids requiring Pillow just to export terrain.
    raw = b"".join(b"\x00" + row.tobytes() for row in pixels)
    header = struct.pack(">IIBBBBB", pixels.shape[1], pixels.shape[0], 8, 0, 0, 0, 0)
    with path.open("wb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n")
        stream.write(_png_chunk(b"IHDR", header))
        stream.write(_png_chunk(b"IDAT", zlib.compress(raw, level=9)))
        stream.write(_png_chunk(b"IEND", b""))


def _indent_xml(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", short_empty_elements=True) + "\n"


def _unique_name(parent: ET.Element, tag: str, base: str) -> str:
    names = {item.get("name") for item in parent.findall(tag)}
    if base not in names:
        return base
    index = 1
    while f"{base}_{index}" in names:
        index += 1
    return f"{base}_{index}"


def _load_base_scene(base_scene_path: str | Path, model_name: str) -> ET.Element:
    """Load a robot scene template and resolve its relative resources."""

    path = Path(base_scene_path).resolve()
    root = ET.parse(path).getroot()
    root.set("model", model_name)
    for item in root.iter():
        if item.tag in {"include", "mesh", "hfield", "texture", "skin"} and item.get("file"):
            resource = Path(item.get("file", ""))
            if not resource.is_absolute():
                item.set("file", str((path.parent / resource).resolve()))
    return root


def _ensure_child(parent: ET.Element, tag: str) -> ET.Element:
    child = parent.find(tag)
    return child if child is not None else ET.SubElement(parent, tag)


def _ensure_root_child(root: ET.Element, tag: str, before: str = "asset") -> ET.Element:
    child = root.find(tag)
    if child is not None:
        return child
    child = ET.Element(tag)
    children = list(root)
    insert_at = next((index for index, item in enumerate(children) if item.tag == before), len(children))
    root.insert(insert_at, child)
    return child


def _configure_classic_visuals(root: ET.Element) -> None:
    """Apply the classic MuJoCo blue checkerboard and gradient sky."""

    visual = _ensure_root_child(root, "visual")
    headlight = _ensure_child(visual, "headlight")
    headlight.attrib.update({"diffuse": "0.6 0.6 0.6", "ambient": "0.3 0.3 0.3", "specular": "0 0 0"})
    haze = _ensure_child(visual, "rgba")
    haze.attrib.update({"haze": "0.15 0.25 0.35 1"})
    global_view = _ensure_child(visual, "global")
    global_view.attrib.update({"azimuth": "-130", "elevation": "-20"})


def _fmt(values: tuple[float, ...]) -> str:
    return " ".join(f"{value:.6g}" for value in values)


def _local_pose(element: TerrainElement, x: float, y: float, z: float) -> dict[str, str]:
    """Transform a local element point into a MuJoCo geom pose."""

    angle = np.deg2rad(element.yaw)
    world_x = element.x + np.cos(angle) * x - np.sin(angle) * y
    world_y = element.y + np.sin(angle) * x + np.cos(angle) * y
    return {"pos": _fmt((world_x, world_y, element.z + z))}


def _add_box(worldbody: ET.Element, name: str, element: TerrainElement,
             x: float, y: float, z: float, size: tuple[float, float, float],
             rgba: str = "0.48 0.30 0.12 1", extra: dict[str, str] | None = None) -> None:
    attrs = {"name": name, "type": "box", "size": _fmt(size), "rgba": rgba, "friction": "0.8 0.1 0.1"}
    attrs.update(_local_pose(element, x, y, z))
    if element.yaw:
        attrs["euler"] = _fmt((0.0, 0.0, element.yaw))
    if extra:
        attrs.update(extra)
    ET.SubElement(worldbody, "geom", attrs)


def _add_wedge_mesh(asset: ET.Element, mesh_name: str, length: float,
                    width: float, height: float) -> None:
    """Create a closed triangular-prism wedge with its bottom on z=0."""

    lx, wy = length / 2, width / 2
    vertices = _fmt((-lx, -wy, 0.0, lx, -wy, 0.0, lx, -wy, height,
                     -lx, wy, 0.0, lx, wy, 0.0, lx, wy, height))
    faces = "0 1 2 3 4 5 0 1 4 0 4 3 1 2 5 1 5 4 2 0 3 2 3 5"
    ET.SubElement(asset, "mesh", {"name": mesh_name, "vertex": vertices, "face": faces})


def _add_element(asset: ET.Element, worldbody: ET.Element, element: TerrainElement, index: int) -> None:
    p = element.params
    prefix = element.name or f"{element.kind}_{index:03d}"
    rgba = {
        "platform": "0.16 0.40 0.72 1", "stairs": "0.72 0.42 0.14 1",
        "hollow_stairs": "0.82 0.56 0.12 1", "ramp": "0.18 0.52 0.28 1",
        "stepping_stones": "0.35 0.35 0.38 1", "triangle": "0.70 0.18 0.10 1",
        "tire_ring": "0.04 0.04 0.04 1", "slalom_poles": "0.84 0.18 0.12 1",
        "sandpit": "0.78 0.60 0.32 1", "high_wall": "0.18 0.30 0.58 1",
    }[element.kind]

    if element.kind == "platform":
        length, width, height = (float(p.get(key, default)) for key, default in (
            ("length", 2.0), ("width", 2.0), ("height", 0.8)))
        _add_box(worldbody, prefix, element, 0.0, 0.0, height / 2, (length / 2, width / 2, height / 2), rgba)

    elif element.kind in ("stairs", "hollow_stairs"):
        length = float(p.get("length", 3.0))
        width = float(p.get("width", 2.0))
        height = float(p.get("height", 0.8))
        steps = max(1, int(p.get("steps", 8)))
        step_length = length / steps
        thickness = float(p.get("thickness", 0.16)) if element.kind == "hollow_stairs" else None
        for step_index in range(steps):
            step_height = height * (step_index + 1) / steps
            center_x = -length / 2 + step_length * (step_index + 0.5)
            block_height = thickness if thickness is not None else step_height
            center_z = step_height - block_height / 2
            _add_box(worldbody, f"{prefix}_{step_index:02d}", element, center_x, 0.0, center_z,
                     (step_length / 2, width / 2, block_height / 2), rgba)

    elif element.kind == "ramp":
        length = float(p.get("length", 3.0))
        width = float(p.get("width", 2.0))
        height = float(p.get("height", 0.8))
        mesh_name = f"{prefix}_mesh"
        _add_wedge_mesh(asset, mesh_name, length, width, height)
        attrs = {"name": prefix, "type": "mesh", "mesh": mesh_name,
                 "rgba": rgba, "friction": "0.8 0.1 0.1"}
        attrs.update(_local_pose(element, 0.0, 0.0, 0.0))
        if element.yaw:
            attrs["euler"] = _fmt((0.0, 0.0, element.yaw))
        ET.SubElement(worldbody, "geom", attrs)

    elif element.kind == "stepping_stones":
        count = max(1, int(p.get("count", 9)))
        spacing = float(p.get("spacing", 0.85))
        side = float(p.get("size", p.get("radius", 0.34) * 2))
        height = float(p.get("height", 0.45))
        for stone_index in range(count):
            x = (stone_index - (count - 1) / 2) * spacing
            _add_box(worldbody, f"{prefix}_{stone_index:02d}", element, x, 0.0, height / 2,
                     (side / 2, side / 2, height / 2), rgba)

    elif element.kind == "triangle":
        length = float(p.get("length", 2.5))
        width = float(p.get("width", 2.0))
        height = float(p.get("height", 0.8))
        mesh_name = f"{prefix}_mesh"
        _add_wedge_mesh(asset, mesh_name, length, width, height)
        attrs = {"name": prefix, "type": "mesh", "mesh": mesh_name, "rgba": rgba, "friction": "0.8 0.1 0.1"}
        attrs.update(_local_pose(element, 0.0, 0.0, 0.0))
        if element.yaw:
            attrs["euler"] = _fmt((0.0, 0.0, element.yaw))
        ET.SubElement(worldbody, "geom", attrs)

    elif element.kind == "tire_ring":
        count = max(1, int(p.get("count", 3)))
        spacing = float(p.get("spacing", 1.1))
        major = float(p.get("major_radius", 0.27))
        minor = float(p.get("minor_radius", 0.10))
        upright = bool(p.get("upright", False))
        center_offset = (count - 1) * spacing / 2
        mesh_name = f"{prefix}_mesh"
        major_segments, minor_segments = 24, 10
        vertices: list[float] = []
        faces: list[int] = []
        for major_index in range(major_segments):
            major_angle = 2 * np.pi * major_index / major_segments
            for minor_index in range(minor_segments):
                minor_angle = 2 * np.pi * minor_index / minor_segments
                ring_radius = major + minor * np.cos(minor_angle)
                vertices.extend((
                    float(ring_radius * np.cos(major_angle)),
                    float(ring_radius * np.sin(major_angle)),
                    float(minor * np.sin(minor_angle)),
                ))
        for major_index in range(major_segments):
            for minor_index in range(minor_segments):
                next_major = (major_index + 1) % major_segments
                next_minor = (minor_index + 1) % minor_segments
                a = major_index * minor_segments + minor_index
                b = next_major * minor_segments + minor_index
                c = next_major * minor_segments + next_minor
                d = major_index * minor_segments + next_minor
                faces.extend((a, b, c, a, c, d))
        ET.SubElement(asset, "mesh", {
            "name": mesh_name,
            "vertex": _fmt(tuple(vertices)),
            "face": " ".join(str(value) for value in faces),
        })
        for tire_index in range(count):
            x = tire_index * spacing - center_offset
            z = major + minor if upright else minor
            attrs = {"name": f"{prefix}_{tire_index:02d}", "type": "mesh",
                     "mesh": mesh_name, "rgba": rgba, "friction": "0.8 0.1 0.1"}
            attrs.update(_local_pose(element, x, 0.0, z))
            if upright:
                attrs["euler"] = _fmt((0.0, 90.0, element.yaw))
            elif element.yaw:
                attrs["euler"] = _fmt((0.0, 0.0, element.yaw))
            ET.SubElement(worldbody, "geom", attrs)

    elif element.kind == "slalom_poles":
        count = max(1, int(p.get("count", 6)))
        spacing = float(p.get("spacing", 0.8))
        radius = float(p.get("radius", 0.07))
        height = float(p.get("height", 1.2))
        zigzag = float(p.get("zigzag", 0.32))
        for pole_index in range(count):
            x = (pole_index - (count - 1) / 2) * spacing
            y = zigzag if pole_index % 2 else -zigzag
            attrs = {"name": f"{prefix}_{pole_index:02d}", "type": "cylinder",
                     "size": _fmt((radius, height / 2)), "rgba": rgba,
                     "friction": "0.6 0.1 0.1"}
            attrs.update(_local_pose(element, x, y, height / 2))
            ET.SubElement(worldbody, "geom", attrs)

    elif element.kind == "sandpit":
        length = float(p.get("length", 2.4))
        width = float(p.get("width", 2.0))
        depth = max(float(p.get("depth", 0.06)), 1e-3)
        border = max(float(p.get("border", 0.12)), 0.02)
        sand_rgba = "0.78 0.60 0.32 1"
        # The center is a low-friction sand surface; raised borders make the pit
        # visible and keep the component useful when placed over a flat hfield.
        _add_box(worldbody, f"{prefix}_sand", element, 0.0, 0.0, -depth / 2,
                 (length / 2, width / 2, depth / 2), sand_rgba,
                 {"friction": "1.2 0.35 0.02"})
        _add_box(worldbody, f"{prefix}_left", element, -length / 2, 0.0, border / 2,
                 (border / 2, width / 2 + border, border / 2), sand_rgba)
        _add_box(worldbody, f"{prefix}_right", element, length / 2, 0.0, border / 2,
                 (border / 2, width / 2 + border, border / 2), sand_rgba)
        _add_box(worldbody, f"{prefix}_front", element, 0.0, -width / 2, border / 2,
                 (length / 2, border / 2, border / 2), sand_rgba)
        _add_box(worldbody, f"{prefix}_back", element, 0.0, width / 2, border / 2,
                 (length / 2, border / 2, border / 2), sand_rgba)

    elif element.kind == "high_wall":
        length = float(p.get("length", 2.4))
        thickness = float(p.get("thickness", 0.22))
        height = float(p.get("height", 1.2))
        _add_box(worldbody, prefix, element, 0.0, 0.0, height / 2,
                 (length / 2, thickness / 2, height / 2), rgba)


def build_xml(terrain: TerrainMap, heightfield_filename: str = "terrain.png",
              elements: list[TerrainElement] | None = None, model_name: str | None = None,
              include_test_ball: bool = True,
              base_scene_path: str | Path | None = None) -> str:
    """Build a standalone MuJoCo XML scene with optional obstacle components."""

    config = terrain.config
    scene_name = model_name or f"terrain_{config.kind}"
    root = (_load_base_scene(base_scene_path, scene_name) if base_scene_path
            else ET.Element("mujoco", {"model": scene_name}))
    if root.find("compiler") is None:
        compiler = _ensure_root_child(root, "compiler", before="option")
        compiler.attrib.update({"angle": "degree", "coordinate": "local"})
    if root.find("option") is None:
        option = _ensure_root_child(root, "option", before="visual")
        option.attrib.update({"gravity": "0 0 -9.81", "integrator": "RK4"})
    _configure_classic_visuals(root)

    asset = _ensure_child(root, "asset")
    skybox = next((item for item in asset.findall("texture") if item.get("type") == "skybox"), None)
    if skybox is None:
        skybox = ET.SubElement(asset, "texture")
    skybox_name = skybox.get("name", "skybox")
    skybox.attrib.update({
        "name": skybox_name, "type": "skybox", "builtin": "gradient",
        "rgb1": "0.30 0.50 0.72", "rgb2": "0.015 0.035 0.09", "width": "512", "height": "3072",
    })
    texture_name = _unique_name(asset, "texture", "terrain_checker")
    material_name = _unique_name(asset, "material", "terrain_material")
    hfield_name = _unique_name(asset, "hfield", "terrain")
    ET.SubElement(asset, "texture", {
        "name": texture_name, "type": "2d", "builtin": "checker", "mark": "edge",
        "rgb1": "0.08 0.20 0.38", "rgb2": "0.24 0.50 0.78",
        "markrgb": "0.86 0.93 1.0", "width": "300", "height": "300",
    })
    ET.SubElement(asset, "material", {
        "name": material_name, "texture": texture_name, "texuniform": "true",
        "texrepeat": "5 5", "reflectance": "0.15",
    })
    ET.SubElement(asset, "hfield", {
        "name": hfield_name, "file": heightfield_filename,
        # MuJoCo requires all hfield size entries to be strictly positive;
        # the tiny base keeps the physical ground effectively at z=0.
        "size": f"{config.length / 2:.6g} {config.width / 2:.6g} {max(config.height, 1e-6):.6g} 1e-6",
    })

    worldbody = _ensure_child(root, "worldbody")
    ET.SubElement(worldbody, "light", {"pos": "0 0 8", "directional": "true", "dir": "0 0 -1"})
    ET.SubElement(worldbody, "geom", {
        "name": _unique_name(worldbody, "geom", "terrain"), "type": "hfield", "hfield": hfield_name,
        "material": material_name, "contype": "1", "conaffinity": "1",
    })
    for index, obstacle in enumerate(terrain.obstacles):
        ET.SubElement(worldbody, "geom", {
            "name": f"obstacle_{index:03d}", "type": "box",
            "pos": f"{obstacle.x:.6g} {obstacle.y:.6g} {obstacle.height / 2:.6g}",
            "size": f"{obstacle.size_x / 2:.6g} {obstacle.size_y / 2:.6g} {obstacle.height / 2:.6g}",
            "rgba": "0.55 0.12 0.08 1", "friction": "0.8 0.1 0.1",
        })

    for index, element in enumerate(elements or ()):
        _add_element(asset, worldbody, element, index)

    if include_test_ball:
        # A small free body makes the generated scene immediately useful for a smoke test.
        body = ET.SubElement(worldbody, "body", {"name": "test_ball", "pos": "0 0 1.5"})
        ET.SubElement(body, "freejoint")
        ET.SubElement(body, "geom", {"name": "ball", "type": "sphere", "size": "0.18", "mass": "1", "rgba": "0.1 0.35 0.9 1"})
    return _indent_xml(root)


def export_mujoco(terrain: TerrainMap, output_dir: str | Path,
                  elements: list[TerrainElement] | None = None,
                  model_name: str | None = None, include_test_ball: bool = True,
                  base_scene: str | Path | None = None) -> dict[str, Path]:
    """Write ``terrain.xml``, ``terrain.png`` and ``terrain.json``."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    png_path = directory / "terrain.png"
    xml_path = directory / "terrain.xml"
    json_path = directory / "terrain.json"
    _write_png(png_path, terrain.heights)
    xml_path.write_text(build_xml(terrain, elements=elements, model_name=model_name,
                                  include_test_ball=include_test_ball,
                                  base_scene_path=base_scene), encoding="utf-8")
    metadata = {
        "config": terrain.config.to_dict(),
        "height_min": float(terrain.heights.min()),
        "height_max": float(terrain.heights.max()),
        "obstacles": [asdict(obstacle) for obstacle in terrain.obstacles],
        "elements": [element.to_dict() for element in (elements or [])],
    }
    json_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"xml": xml_path, "heightfield": png_path, "metadata": json_path}


def load_and_validate(xml_path: str | Path):
    """Compile an exported scene with MuJoCo and return its model."""

    import mujoco

    return mujoco.MjModel.from_xml_path(str(xml_path))
