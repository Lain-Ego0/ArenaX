"""ArenaX Robotics: robot terrain and policy validation environment.

The public terrain API is exposed lazily so lightweight commands such as
``python -m terrain_generator.cli --help`` do not need to import NumPy and
the rest of the simulation stack just to construct an argument parser.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .terrain import (
        ArenaScene, TerrainConfig, TerrainElement, TerrainMap, export_mujoco,
        export_scene, generate_terrain, load_and_validate, load_scene, save_scene,
        TerrainAsset, TerrainLibrary, compose_robot_scene, discover_terrain_xml,
    )

__all__ = [
    "TerrainConfig",
    "TerrainElement",
    "TerrainMap",
    "ArenaScene",
    "export_mujoco",
    "generate_terrain",
    "load_and_validate",
    "export_scene",
    "load_scene",
    "save_scene",
    "TerrainAsset",
    "TerrainLibrary",
    "compose_robot_scene",
    "discover_terrain_xml",
]

__version__ = "0.1.0"


def __getattr__(name: str):
    """Resolve public terrain names on first use."""

    if name in __all__:
        terrain = import_module(".terrain", __name__)
        value = getattr(terrain, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
