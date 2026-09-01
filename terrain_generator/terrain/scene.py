"""Scene JSON helpers and one-click arena export."""

from __future__ import annotations

import json
from pathlib import Path

from .models import ArenaScene
from .generators import generate_terrain
from .mujoco_xml import export_mujoco


def load_scene(path: str | Path) -> ArenaScene:
    path = Path(path)
    return ArenaScene.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_scene(scene: ArenaScene, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scene.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def export_scene(scene: ArenaScene, output_dir: str | Path,
                 include_test_ball: bool = True) -> dict[str, Path]:
    terrain = generate_terrain(scene.terrain)
    paths = export_mujoco(
        terrain, output_dir, elements=scene.elements, model_name=scene.name,
        base_scene=scene.base_scene,
        include_test_ball=include_test_ball,
    )
    paths["scene"] = save_scene(scene, Path(output_dir) / "scene.json")
    return paths
