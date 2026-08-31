"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .models import ArenaScene, SUPPORTED_TERRAIN_TYPES, TerrainConfig
from .mujoco_xml import load_and_validate
from .presets import playground_scene
from .scene import export_scene, load_scene


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate procedural MuJoCo terrains")
    parser.add_argument("--type", dest="kind", choices=SUPPORTED_TERRAIN_TYPES, default="noise")
    parser.add_argument("--output", type=Path, default=Path("generated/terrain"))
    parser.add_argument("--rows", type=int, default=128)
    parser.add_argument("--cols", type=int, default=128)
    parser.add_argument("--length", type=float, default=8.0, help="terrain size along X in meters")
    parser.add_argument("--width", type=float, default=8.0, help="terrain size along Y in meters")
    parser.add_argument("--height", type=float, default=0.8, help="maximum height in meters")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--noise-scale", type=float, default=0.18)
    parser.add_argument("--noise-smoothness", type=int, default=8)
    parser.add_argument("--stair-count", type=int, default=8)
    parser.add_argument("--obstacle-count", type=int, default=18)
    parser.add_argument("--obstacle-size", type=float, default=0.35)
    parser.add_argument("--obstacle-height", type=float, default=0.35)
    parser.add_argument("--validate", action="store_true", help="compile the generated XML with MuJoCo")
    parser.add_argument("--view", action="store_true", help="open the generated scene in the interactive viewer")
    parser.add_argument("--preset", choices=("playground",), help="use a ready-made robot test arena")
    parser.add_argument("--scene", type=Path, help="load an arena scene JSON file")
    parser.add_argument("--base-scene", type=Path, help="append the arena to an existing robot MuJoCo scene")
    parser.add_argument("--no-test-ball", action="store_true", help="do not add the demo free ball")
    parser.add_argument("--edit", action="store_true", help="open the graphical arena editor")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.edit:
        from .editor import launch_editor

        launch_editor(args.output, args.base_scene)
        return 0

    if args.scene:
        scene = load_scene(args.scene)
        if args.base_scene:
            scene.base_scene = str(args.base_scene)
    elif args.preset == "playground":
        scene = playground_scene(seed=args.seed)
        scene.base_scene = str(args.base_scene) if args.base_scene else None
    else:
        config = TerrainConfig(
            kind=args.kind, rows=args.rows, cols=args.cols, length=args.length,
            width=args.width, height=args.height, seed=args.seed,
            noise_scale=args.noise_scale, noise_smoothness=args.noise_smoothness,
            stair_count=args.stair_count, obstacle_count=args.obstacle_count,
            obstacle_size=args.obstacle_size, obstacle_height=args.obstacle_height,
        )
        scene = ArenaScene(name="terrain", terrain=config)
        scene.base_scene = str(args.base_scene) if args.base_scene else None
    paths = export_scene(scene, args.output, include_test_ball=not args.no_test_ball)
    print(f"Generated scene: {scene.name} ({len(scene.elements)} obstacle components)")
    for label, path in paths.items():
        print(f"  {label}: {path}")
    if args.validate:
        model = load_and_validate(paths["xml"])
        print(f"MuJoCo validation passed: {model.ngeom} geoms, {model.nhfield} heightfield")
    if args.view:
        from .viewer import view_xml

        view_xml(paths["xml"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
