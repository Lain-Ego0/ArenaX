"""PAVE: Policy and Arena Validation Environment."""

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
