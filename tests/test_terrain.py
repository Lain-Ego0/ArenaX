import json

import numpy as np

from terrain_generator import TerrainConfig, export_mujoco, generate_terrain, load_and_validate


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

