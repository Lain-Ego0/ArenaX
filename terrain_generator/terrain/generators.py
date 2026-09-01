"""Procedural heightfield generators."""

from __future__ import annotations

import numpy as np

from .models import Obstacle, TerrainConfig, TerrainMap


def _normalize(values: np.ndarray) -> np.ndarray:
    values = values.astype(np.float32, copy=False)
    low, high = float(values.min()), float(values.max())
    if high - low < 1e-8:
        return np.zeros_like(values, dtype=np.float32)
    return ((values - low) / (high - low)).astype(np.float32)


def _smooth_noise(rows: int, cols: int, rng: np.random.Generator, smoothness: int) -> np.ndarray:
    """Create interpolated multi-scale noise using only NumPy."""

    # A coarse random lattice is resized with separable linear interpolation.
    grid_rows = max(2, rows // smoothness + 2)
    grid_cols = max(2, cols // smoothness + 2)
    coarse = rng.random((grid_rows, grid_cols), dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, grid_cols)
    x_new = np.linspace(0.0, 1.0, cols)
    horizontal = np.stack([np.interp(x_new, x_old, row) for row in coarse], axis=0)
    y_old = np.linspace(0.0, 1.0, grid_rows)
    y_new = np.linspace(0.0, 1.0, rows)
    return np.stack([np.interp(y_new, y_old, horizontal[:, col]) for col in range(cols)], axis=1)


def _make_obstacles(config: TerrainConfig, rng: np.random.Generator) -> list[Obstacle]:
    obstacles: list[Obstacle] = []
    half_x, half_y = config.length / 2, config.width / 2
    margin = max(config.obstacle_size, 0.1)
    for _ in range(config.obstacle_count):
        x = float(rng.uniform(-half_x + margin, half_x - margin))
        y = float(rng.uniform(-half_y + margin, half_y - margin))
        size_x = float(config.obstacle_size * rng.uniform(0.65, 1.35))
        size_y = float(config.obstacle_size * rng.uniform(0.65, 1.35))
        height = float(config.obstacle_height * rng.uniform(0.7, 1.3))
        obstacles.append(Obstacle(x=x, y=y, size_x=size_x, size_y=size_y, height=height))
    return obstacles


def generate_terrain(config: TerrainConfig) -> TerrainMap:
    """Generate a deterministic terrain from ``config``."""

    rng = np.random.default_rng(config.seed)
    rows, cols = config.rows, config.cols
    y = np.linspace(0.0, 1.0, rows, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, cols, dtype=np.float32)[None, :]

    if config.kind == "flat":
        heights = np.zeros((rows, cols), dtype=np.float32)
    elif config.kind == "slope":
        heights = np.broadcast_to(y, (rows, cols)).copy()
    elif config.kind == "stairs":
        step = np.floor(y * config.stair_count) / max(config.stair_count - 1, 1)
        heights = np.broadcast_to(np.clip(step, 0.0, 1.0), (rows, cols)).copy()
    elif config.kind == "noise":
        coarse = _smooth_noise(rows, cols, rng, config.noise_smoothness)
        detail = _smooth_noise(rows, cols, rng, max(1, config.noise_smoothness // 3))
        heights = _normalize((1.0 - config.noise_scale) * coarse + config.noise_scale * detail)
    elif config.kind == "obstacle_mix":
        base = 0.15 * _smooth_noise(rows, cols, rng, config.noise_smoothness)
        heights = _normalize(base)
    else:  # guarded by TerrainConfig, kept for type-checkers and future callers
        raise ValueError(f"unsupported terrain kind: {config.kind}")

    obstacles = _make_obstacles(config, rng) if config.kind == "obstacle_mix" else []
    return TerrainMap(heights=heights, config=config, obstacles=obstacles)

