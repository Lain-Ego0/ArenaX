"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .generators import generate_terrain
from .models import SUPPORTED_TERRAIN_TYPES, TerrainConfig
from .mujoco_xml import export_mujoco, load_and_validate


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = TerrainConfig(
        kind=args.kind, rows=args.rows, cols=args.cols, length=args.length,
        width=args.width, height=args.height, seed=args.seed,
        noise_scale=args.noise_scale, noise_smoothness=args.noise_smoothness,
        stair_count=args.stair_count, obstacle_count=args.obstacle_count,
        obstacle_size=args.obstacle_size, obstacle_height=args.obstacle_height,
    )
    terrain = generate_terrain(config)
    paths = export_mujoco(terrain, args.output)
    print(f"Generated {config.kind} terrain ({config.rows} x {config.cols})")
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
