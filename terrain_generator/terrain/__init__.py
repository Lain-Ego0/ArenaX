"""Terrain-generation boundary.

All procedural generation, scene composition and MuJoCo XML export APIs live
under this namespace.  The modules at ``terrain_generator.*`` remain thin
compatibility entry points for existing scripts.
"""

from .generators import generate_terrain
from .models import (
    ArenaScene, Obstacle, TerrainConfig, TerrainElement, TerrainMap,
    SUPPORTED_ELEMENT_TYPES, SUPPORTED_TERRAIN_TYPES,
)
from .mujoco_xml import build_xml, export_mujoco, load_and_validate
from .scene import export_scene, load_scene, save_scene
from .presets import playground_scene
from .library import TerrainAsset, TerrainLibrary, discover_terrain_xml

__all__ = [
    "ArenaScene", "Obstacle", "TerrainConfig", "TerrainElement", "TerrainMap",
    "SUPPORTED_ELEMENT_TYPES", "SUPPORTED_TERRAIN_TYPES", "generate_terrain",
    "build_xml", "export_mujoco", "load_and_validate", "export_scene",
    "load_scene", "save_scene", "playground_scene", "TerrainAsset",
    "TerrainLibrary", "discover_terrain_xml",
]

