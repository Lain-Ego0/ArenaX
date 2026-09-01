"""Optional directory-backed library of ready-made MuJoCo terrains.

Library XML files are treated as opaque scenes: they are loaded directly and
never passed through the procedural terrain generator.  This keeps the
library an extension point that cannot interfere with the main generation
workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mujoco


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

