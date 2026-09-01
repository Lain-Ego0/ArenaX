"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .terrain.models import ArenaScene, SUPPORTED_TERRAIN_TYPES, TerrainConfig
from .terrain.mujoco_xml import load_and_validate
from .terrain.presets import playground_scene
from .terrain.scene import export_scene, load_scene


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PAVE: generate and validate robot terrains in MuJoCo")
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
    parser.add_argument("--xml", type=Path, help="run or view an existing MuJoCo XML file directly")
    parser.add_argument("--terrain-library", type=Path,
                        help="optional directory of standalone terrain XML files")
    parser.add_argument("--terrain-name",
                        help="XML stem/name to load from --terrain-library (default: first)")
    parser.add_argument("--base-scene", type=Path, help="append the arena to an existing robot MuJoCo scene")
    parser.add_argument("--no-test-ball", action="store_true", help="do not add the demo free ball")
    parser.add_argument("--edit", action="store_true", help="open the graphical arena editor")
    parser.add_argument("--policy", type=Path, help="run an ONNX policy in the generated or supplied XML scene")
    parser.add_argument("--robot", choices=("m20", "go2"), default="m20", help="robot profile for ONNX inference")
    parser.add_argument("--robot-config", type=Path, help="YAML policy/runtime profile")
    parser.add_argument("--duration", type=float, default=30.0, help="simulation duration per policy episode")
    parser.add_argument("--episodes", type=int, default=1, help="number of policy episodes")
    parser.add_argument("--headless", action="store_true", help="run policy without opening the MuJoCo viewer")
    parser.add_argument("--control-host", help=argparse.SUPPRESS)
    parser.add_argument("--control-port", type=int, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.edit:
        from .editor import launch_editor

        launch_editor(args.output, args.base_scene)
        return 0

    if args.terrain_library:
        if args.xml or args.scene or args.preset or args.base_scene:
            raise SystemExit("--terrain-library cannot be combined with --xml, --scene, --preset, or --base-scene")
        from .terrain.library import TerrainLibrary
        args.xml = TerrainLibrary(args.terrain_library).resolve(args.terrain_name)

    if args.policy and not args.xml and not args.base_scene:
        robot_dir = "m20" if args.robot == "m20" else "go2"
        scene_name = "scene.xml"
        bundled_scene = Path(__file__).resolve().parent.parent / "assets" / robot_dir / "mjcf" / scene_name
        if bundled_scene.is_file():
            args.base_scene = bundled_scene

    if args.xml:
        if args.scene or args.preset or args.base_scene:
            raise SystemExit("--xml cannot be combined with --scene, --preset, or --base-scene")
        paths = {"xml": args.xml}
        scene = None
    elif args.scene:
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
    if scene is not None:
        paths = export_scene(scene, args.output, include_test_ball=not args.no_test_ball)
        print(f"Generated scene: {scene.name} ({len(scene.elements)} obstacle components)")
        for label, path in paths.items():
            print(f"  {label}: {path}")
    if args.validate:
        model = load_and_validate(paths["xml"])
        print(f"MuJoCo validation passed: {model.ngeom} geoms, {model.nhfield} heightfield")
    if args.policy:
        from .simulation.m20 import run_m20_policy

        if args.robot_config is None:
            bundled_config = Path(__file__).resolve().parent.parent / "configs" / f"{args.robot}.yaml"
            if bundled_config.is_file():
                args.robot_config = bundled_config

        run_m20_policy(
            paths["xml"], args.policy, args.robot_config,
            duration=args.duration, episodes=args.episodes, view=not args.headless,
            control_host=args.control_host, control_port=args.control_port,
        )
    elif args.view:
        from .simulation.viewer import view_xml

        view_xml(paths["xml"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
