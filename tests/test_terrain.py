import json

import numpy as np

from terrain_generator import (
    ArenaScene, TerrainConfig, export_mujoco, export_scene, generate_terrain,
    load_and_validate,
)
from terrain_generator.presets import playground_scene
from terrain_generator.scene import load_scene


def test_generation_is_reproducible():
    config = TerrainConfig(kind="noise", rows=32, cols=24, seed=123)
    first = generate_terrain(config)
    second = generate_terrain(config)
    np.testing.assert_array_equal(first.heights, second.heights)


def test_all_terrain_types_have_valid_heightfields():
    for kind in ("flat", "slope", "stairs", "noise", "obstacle_mix"):
        terrain = generate_terrain(TerrainConfig(kind=kind, rows=24, cols=24, seed=4, obstacle_count=3))
        assert terrain.heights.shape == (24, 24)
        assert 0.0 <= float(terrain.heights.min()) <= float(terrain.heights.max()) <= 1.0


def test_export_and_mujoco_compile(tmp_path):
    terrain = generate_terrain(TerrainConfig(kind="obstacle_mix", rows=32, cols=32, seed=9, obstacle_count=2))
    paths = export_mujoco(terrain, tmp_path)
    model = load_and_validate(paths["xml"])
    assert model.nhfield == 1
    assert model.ngeom == 4  # heightfield + 2 obstacles + test ball
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    assert metadata["config"]["kind"] == "obstacle_mix"
    xml = paths["xml"].read_text(encoding="utf-8")
    assert 'type="skybox"' in xml
    assert 'builtin="checker"' in xml


def test_playground_scene_round_trip_and_compile(tmp_path):
    scene = playground_scene(seed=2)
    paths = export_scene(scene, tmp_path / "playground")
    loaded = load_scene(paths["scene"])
    assert isinstance(loaded, ArenaScene)
    assert len(loaded.elements) == 10
    model = load_and_validate(paths["xml"])
    assert model.nhfield == 1
    assert model.ngeom == 45


def test_export_can_extend_a_base_mujoco_scene(tmp_path):
    robot_fragment = tmp_path / "robot_fragment.xml"
    robot_fragment.write_text(
        '<worldbody><body name="robot_stub" pos="0 0 0.5">'
        '<freejoint/><geom type="sphere" size="0.1" mass="1"/>'
        '</body></worldbody>',
        encoding="utf-8",
    )
    base_scene = tmp_path / "robot_scene.xml"
    base_scene.write_text(
        '<mujoco model="robot_base"><asset/>'
        '<include file="robot_fragment.xml"/>'
        '<worldbody/></mujoco>',
        encoding="utf-8",
    )
    scene = playground_scene(seed=3)
    scene.base_scene = str(base_scene)
    paths = export_scene(scene, tmp_path / "with_robot")
    model = load_and_validate(paths["xml"])
    assert model.nbody >= 2
    assert str(robot_fragment.resolve()) in paths["xml"].read_text(encoding="utf-8")


def test_base_skybox_is_reused_and_restyled(tmp_path):
    base_scene = tmp_path / "base.xml"
    base_scene.write_text(
        '<mujoco model="base"><asset><texture name="skybox" type="skybox" '
        'builtin="gradient" rgb1="1 1 1" rgb2="0 0 0" width="32" height="32"/>'
        '</asset><worldbody/></mujoco>', encoding="utf-8",
    )
    scene = playground_scene(seed=5)
    scene.base_scene = str(base_scene)
    paths = export_scene(scene, tmp_path / "restyled")
    xml = paths["xml"].read_text(encoding="utf-8")
    assert xml.count('type="skybox"') == 1
    assert 'rgb1="0.30 0.50 0.72"' in xml
