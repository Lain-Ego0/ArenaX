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
        # The open-frame staircase is an intentional benchmark obstacle.  It
        # is separate from the obsolete staircase that used to be hard-coded
        # in the bundled robot XML and caused the startup clutter.
        TerrainElement("hollow_stairs", x=0.2, y=2.8, name="hollow_stairs", params={
            "length": 3.2, "width": 2.4, "height": 0.8, "steps": 8, "thickness": 0.05,
        }),
        # Keep the ramp clear of the stairs and the slalom lane below.
        TerrainElement("ramp", x=3.8, y=3.6, name="ramp", params={
            "length": 3.2, "width": 2.4, "height": 0.8, "thickness": 0.16,
        }),
        TerrainElement("stepping_stones", x=-5.8, y=-2.8, name="stepping_stones", params={
            "rows": 4, "cols": 6, "spacing_x": 0.45, "spacing_y": 0.6,
            "size": 0.3, "height": 0.3,
        }),
        TerrainElement("triangle", x=-0.8, y=-2.8, name="triangle_obstacle", params={
            "count": 4, "length": 0.9, "width": 1.0, "height": 0.85,
            "angle": 30.0, "gap": 0.28, "stagger": 0.8,
            "pair_yaw": 90.0, "group_spacing": 2.1, "pair_spacing": 1.18,
        }),
        TerrainElement("tire_ring", x=4.4, y=-2.8, name="tire_rings", params={
            "count": 3, "spacing": 0.85, "major_radius": 0.27, "minor_radius": 0.10,
            "upright": False,
        }),
        # Move obstacle 8 away from both the ramp and the high wall.
        TerrainElement("slalom_poles", x=7.2, y=1.5, name="slalom_poles", params={
            "count": 6, "spacing": 0.8, "radius": 0.07, "height": 1.2, "zigzag": 0.32,
        }),
        TerrainElement("sandpit", x=7.0, y=-2.8, name="sandpit", params={
            "length": 2.4, "width": 2.0, "depth": 0.06, "surface_height": 0.06,
            "roughness": 0.018, "surface_grid": 13, "potholes": 7,
            "gravel_count": 18, "gravel_size": 0.035,
        }),
        TerrainElement("high_wall", x=8.8, y=0.0, name="high_wall", params={
            "length": 2.4, "thickness": 0.22, "height": 0.3,
        }),
    ]
    return ArenaScene(name="playground", terrain=terrain, elements=elements)
