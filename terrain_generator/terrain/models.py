"""Data structures shared by generators and exporters."""

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


SUPPORTED_TERRAIN_TYPES = ("flat", "slope", "stairs", "noise", "obstacle_mix")
SUPPORTED_ELEMENT_TYPES = (
    "platform",
    "trench",
    "stairs",
    "hollow_stairs",
    "ramp",
    "stepping_stones",
    "triangle",
    "tire_ring",
    "slalom_poles",
    "sandpit",
    "high_wall",
)


@dataclass(slots=True)
class TerrainConfig:
    """Parameters controlling one generated terrain."""

    kind: str = "noise"
    rows: int = 128
    cols: int = 128
    length: float = 8.0
    width: float = 8.0
    height: float = 0.8
    seed: int = 0
    noise_scale: float = 0.18
    noise_smoothness: int = 8
    stair_count: int = 8
    obstacle_count: int = 18
    obstacle_size: float = 0.35
    obstacle_height: float = 0.35
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.kind = self.kind.lower().strip()
        if self.kind not in SUPPORTED_TERRAIN_TYPES:
            raise ValueError(f"kind must be one of {SUPPORTED_TERRAIN_TYPES}, got {self.kind!r}")
        if self.rows < 2 or self.cols < 2:
            raise ValueError("rows and cols must both be at least 2")
        if self.length <= 0 or self.width <= 0:
            raise ValueError("length and width must be positive")
        if self.height < 0:
            raise ValueError("height cannot be negative")
        if self.noise_scale < 0:
            raise ValueError("noise_scale cannot be negative")
        if self.noise_smoothness < 1:
            raise ValueError("noise_smoothness must be at least 1")
        if self.stair_count < 1 or self.obstacle_count < 0:
            raise ValueError("stair_count must be positive and obstacle_count non-negative")
        if self.obstacle_size <= 0 or self.obstacle_height < 0:
            raise ValueError("obstacle_size must be positive and obstacle_height non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Obstacle:
    """An axis-aligned box obstacle in world coordinates."""

    x: float
    y: float
    size_x: float
    size_y: float
    height: float


@dataclass(slots=True)
class TerrainElement:
    """A reusable obstacle component placed in the arena.

    ``params`` contains dimensions specific to ``kind``. Coordinates are in
    meters, with the element's local X axis rotated by ``yaw`` around Z.
    """

    kind: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    name: str = ""

    def __post_init__(self) -> None:
        self.kind = self.kind.lower().strip()
        if self.kind not in SUPPORTED_ELEMENT_TYPES:
            raise ValueError(f"kind must be one of {SUPPORTED_ELEMENT_TYPES}, got {self.kind!r}")
        if not np.isfinite([self.x, self.y, self.z, self.yaw]).all():
            raise ValueError("element pose must contain only finite values")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArenaScene:
    """A complete robot play/test arena."""

    terrain: TerrainConfig
    elements: list[TerrainElement] = field(default_factory=list)
    name: str = "arena"
    base_scene: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_scene": self.base_scene,
            "terrain": self.terrain.to_dict(),
            "elements": [element.to_dict() for element in self.elements],
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "ArenaScene":
        terrain_values = dict(values.get("terrain", {}))
        elements = [TerrainElement(**item) for item in values.get("elements", [])]
        return cls(
            name=str(values.get("name", "arena")),
            terrain=TerrainConfig(**terrain_values),
            elements=elements,
            base_scene=values.get("base_scene"),
        )


@dataclass(slots=True)
class TerrainMap:
    """Heightfield plus the physical dimensions needed to export it."""

    heights: np.ndarray
    config: TerrainConfig
    obstacles: list[Obstacle] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.heights = np.asarray(self.heights, dtype=np.float32)
        if self.heights.shape != (self.config.rows, self.config.cols):
            raise ValueError(
                f"height shape {self.heights.shape} does not match "
                f"({self.config.rows}, {self.config.cols})"
            )
        if not np.isfinite(self.heights).all():
            raise ValueError("heights must contain only finite values")
        self.heights = np.clip(self.heights, 0.0, 1.0)
