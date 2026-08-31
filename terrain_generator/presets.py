"""Ready-to-use robot play-ground layouts."""

from .models import ArenaScene, TerrainConfig, TerrainElement


def playground_scene(seed: int = 7) -> ArenaScene:
    """Return a compact arena containing the common benchmark obstacles."""

    terrain = TerrainConfig(
        kind="flat", rows=192, cols=320, length=20.0, width=12.0,
        height=0.05, seed=seed,
    )
    elements = [
        TerrainElement("platform", x=-7.0, y=2.7, name="high_platform", params={
            "length": 2.4, "width": 3.0, "height": 1.0,
        }),
        TerrainElement("stairs", x=-3.6, y=2.8, name="stairs", params={
            "length": 3.2, "width": 2.4, "height": 0.8, "steps": 8,
        }),
        TerrainElement("hollow_stairs", x=0.2, y=2.8, name="hollow_stairs", params={
            "length": 3.2, "width": 2.4, "height": 0.8, "steps": 8, "thickness": 0.16,
        }),
        TerrainElement("ramp", x=4.1, y=2.8, name="ramp", params={
            "length": 3.2, "width": 2.4, "height": 0.8, "thickness": 0.16,
        }),
        TerrainElement("stepping_stones", x=-5.8, y=-2.8, name="stepping_stones", params={
            "count": 9, "spacing": 0.85, "radius": 0.34, "height": 0.45,
        }),
        TerrainElement("triangle", x=-0.8, y=-2.8, name="triangle_obstacle", params={
            "length": 2.8, "width": 2.0, "height": 0.85,
        }),
        TerrainElement("tire_ring", x=4.4, y=-2.8, name="tire_rings", params={
            "count": 3, "spacing": 1.1, "major_radius": 0.52, "minor_radius": 0.14,
            "upright": True,
        }),
    ]
    return ArenaScene(name="playground", terrain=terrain, elements=elements)

