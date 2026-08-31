"""MuJoCo heightfield and scene export."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
import struct
from xml.etree import ElementTree as ET
import zlib

import numpy as np

from .models import TerrainMap


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


def build_xml(terrain: TerrainMap, heightfield_filename: str = "terrain.png") -> str:
    """Build a standalone MuJoCo XML scene referencing a PNG heightfield."""

    config = terrain.config
    root = ET.Element("mujoco", {"model": f"terrain_{config.kind}"})
    ET.SubElement(root, "compiler", {"angle": "degree", "coordinate": "local"})
    ET.SubElement(root, "option", {"gravity": "0 0 -9.81", "integrator": "RK4"})

    asset = ET.SubElement(root, "asset")
    ET.SubElement(asset, "texture", {
        "name": "terrain_texture", "type": "2d", "builtin": "gradient",
        "rgb1": "0.22 0.34 0.16", "rgb2": "0.55 0.40 0.18", "width": "256", "height": "256",
    })
    ET.SubElement(asset, "material", {"name": "terrain_material", "texture": "terrain_texture", "texrepeat": "4 4"})
    ET.SubElement(asset, "hfield", {
        "name": "terrain", "file": heightfield_filename,
        # MuJoCo requires all hfield size entries to be strictly positive;
        # the tiny base keeps the physical ground effectively at z=0.
        "size": f"{config.length / 2:.6g} {config.width / 2:.6g} {max(config.height, 1e-6):.6g} 1e-6",
    })

    worldbody = ET.SubElement(root, "worldbody")
    ET.SubElement(worldbody, "light", {"pos": "0 0 8", "directional": "true", "dir": "0 0 -1"})
    ET.SubElement(worldbody, "geom", {
        "name": "terrain", "type": "hfield", "hfield": "terrain",
        "material": "terrain_material", "contype": "1", "conaffinity": "1",
    })
    for index, obstacle in enumerate(terrain.obstacles):
        ET.SubElement(worldbody, "geom", {
            "name": f"obstacle_{index:03d}", "type": "box",
            "pos": f"{obstacle.x:.6g} {obstacle.y:.6g} {obstacle.height / 2:.6g}",
            "size": f"{obstacle.size_x / 2:.6g} {obstacle.size_y / 2:.6g} {obstacle.height / 2:.6g}",
            "rgba": "0.55 0.12 0.08 1", "friction": "0.8 0.1 0.1",
        })

    # A small free body makes the generated scene immediately useful for a smoke test.
    body = ET.SubElement(worldbody, "body", {"name": "test_ball", "pos": "0 0 1.5"})
    ET.SubElement(body, "freejoint")
    ET.SubElement(body, "geom", {"name": "ball", "type": "sphere", "size": "0.18", "mass": "1", "rgba": "0.1 0.35 0.9 1"})
    return _indent_xml(root)


def export_mujoco(terrain: TerrainMap, output_dir: str | Path) -> dict[str, Path]:
    """Write ``terrain.xml``, ``terrain.png`` and ``terrain.json``."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    png_path = directory / "terrain.png"
    xml_path = directory / "terrain.xml"
    json_path = directory / "terrain.json"
    _write_png(png_path, terrain.heights)
    xml_path.write_text(build_xml(terrain), encoding="utf-8")
    metadata = {
        "config": terrain.config.to_dict(),
        "height_min": float(terrain.heights.min()),
        "height_max": float(terrain.heights.max()),
        "obstacles": [asdict(obstacle) for obstacle in terrain.obstacles],
    }
    json_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"xml": xml_path, "heightfield": png_path, "metadata": json_path}


def load_and_validate(xml_path: str | Path):
    """Compile an exported scene with MuJoCo and return its model."""

    import mujoco

    return mujoco.MjModel.from_xml_path(str(xml_path))
