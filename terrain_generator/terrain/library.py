"""Optional directory-backed library of ready-made MuJoCo terrains.

Library XML files are treated as opaque scenes: they are loaded directly and
never passed through the procedural terrain generator.  This keeps the
library an extension point that cannot interfere with the main generation
workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from xml.etree import ElementTree as ET

import mujoco

from .mujoco_xml import (
    _expand_includes,
    _indent_xml,
    _merge_included_document,
    _remove_overlapping_ground_planes,
    _resolve_scene_resources,
)


@dataclass(frozen=True, slots=True)
class TerrainAsset:
    name: str
    path: Path


class TerrainLibrary:
    """Discover and load standalone ``.xml`` scenes from a directory."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser().resolve()

    def assets(self) -> list[TerrainAsset]:
        if not self.directory.is_dir():
            return []
        return [TerrainAsset(path.stem, path) for path in sorted(self.directory.glob("*.xml"))]

    def names(self) -> list[str]:
        return [item.name for item in self.assets()]

    def resolve(self, name: str | None = None) -> Path:
        assets = self.assets()
        if not assets:
            raise FileNotFoundError(f"No XML terrain assets found in {self.directory}")
        if name is None:
            return assets[0].path
        candidate = (self.directory / name).resolve()
        if candidate.suffix.lower() != ".xml":
            candidate = candidate.with_suffix(".xml")
        if candidate.parent != self.directory or not candidate.is_file():
            raise FileNotFoundError(f"Terrain asset not found: {name}")
        return candidate

    def load(self, name: str | None = None) -> tuple[Path, mujoco.MjModel]:
        path = self.resolve(name)
        return path, mujoco.MjModel.from_xml_path(str(path))


def discover_terrain_xml(directory: str | Path) -> list[Path]:
    """Small functional API useful to GUI integrations and scripts."""

    return [asset.path for asset in TerrainLibrary(directory).assets()]


def _convert_euler_units(root: ET.Element, source: str, target: str) -> None:
    """Convert XML ``euler`` attributes between MuJoCo angle conventions.

    MuJoCo applies one global ``compiler angle`` setting to a document.  A
    terrain-library scene may use degrees while the bundled M20 model uses
    radians, so the terrain rotations must be converted before the documents
    are merged.  Quaternions are unitless and therefore need no conversion.
    """

    source = source.lower()
    target = target.lower()
    if source == target:
        return
    if {source, target} != {"degree", "radian"}:
        return
    factor = math.pi / 180.0 if source == "degree" else 180.0 / math.pi
    for item in root.iter():
        value = item.get("euler")
        if not value:
            continue
        try:
            angles = [float(token) * factor for token in value.split()]
        except ValueError:
            # Leave malformed/custom attributes untouched; MuJoCo will report
            # the original parse error with the relevant element name.
            continue
        item.set("euler", " ".join(f"{angle:.9g}" for angle in angles))


def compose_robot_scene(terrain_path: str | Path, robot_scene_path: str | Path,
                        output_path: str | Path) -> Path:
    """Compose an opaque library terrain with a robot scene into one XML.

    Library files are not passed through the procedural terrain exporter.  We
    only merge their XML sections with the bundled robot model, expanding
    includes first so mesh paths remain relative to their original files.
    """

    terrain_path = Path(terrain_path).expanduser().resolve()
    robot_scene_path = Path(robot_scene_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    terrain_root = ET.parse(terrain_path).getroot()
    robot_root = ET.parse(robot_scene_path).getroot()
    _expand_includes(terrain_root, terrain_path.parent)
    _resolve_scene_resources(terrain_root, terrain_path.parent)
    _expand_includes(robot_root, robot_scene_path.parent)
    _resolve_scene_resources(robot_root, robot_scene_path.parent)
    # Keep the imported terrain's own ground authoritative.  The M20 scene
    # template contains a convenience floor plane which would otherwise be
    # merged on top of the library floor and cause z-fighting/white patches.
    robot_worldbody = robot_root.find("worldbody")
    if robot_worldbody is not None:
        _remove_overlapping_ground_planes(robot_worldbody)

    terrain_compiler = terrain_root.find("compiler")
    robot_compiler = robot_root.find("compiler")
    terrain_angle = terrain_compiler.get("angle", "degree") if terrain_compiler is not None else "degree"
    robot_angle = robot_compiler.get("angle", "degree") if robot_compiler is not None else terrain_angle
    _convert_euler_units(terrain_root, terrain_angle, robot_angle)
    # The library terrain remains authoritative for world visuals/statistics;
    # importing the robot should contribute its model, assets and actuators
    # without creating duplicate top-level visual/option sections.
    for tag in ("visual", "statistic", "option"):
        for child in list(robot_root.findall(tag)):
            robot_root.remove(child)
    _merge_included_document(terrain_root, robot_root)
    terrain_root.set("model", f"{terrain_root.get('model', terrain_path.stem)}_m20")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_indent_xml(terrain_root), encoding="utf-8")
    return output_path
