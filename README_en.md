# ArenaX Robotics

[中文](README.md)

Robot Terrain & Policy Validation Environment

ArenaX Robotics is a MuJoCo terrain and scene tool for validating robot policies. It turns parameterized terrain definitions into:

- MuJoCo XML scene files
- PNG heightfields readable by MuJoCo
- JSON metadata describing the generation parameters

Built-in terrain types are `flat`, `slope`, `stairs`, `noise`, and `obstacle_mix`.

The playground includes platforms, trenches, stairs, hollow stairs, ramps, independent square stepping stones, triangle obstacles, horizontal tire rings, slalom poles, sandpits, and high walls. The default platform height is `0.8 m` and the default stepping-stone side length is `0.2 m`. A trench consists of two truncated isosceles-ramp sides with a `0.3 m` center gap and `0.3 m` height. Triangle obstacles default to approximately `30°`, alternate left/right, use `stagger=0.8 m` to avoid face-to-face placement, and rotate every pair by `pair_yaw=90°`.

The default tire-ring outside diameter is `0.74 m`, and the default stepping-stone side length is `0.2 m`. These values can be edited in the PyQt editor. Sandpits default to a surface height of `0.06 m` and expose adjustable roughness, potholes, and gravel parameters.

## Quick start

ArenaX is designed to run from the project-local `.venv` environment.

On Linux/macOS, create the environment and install dependencies with:

```bash
./install.sh
```

To install and launch the PyQt editor in English:

```bash
./install.sh --run --language en
```

On Windows PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1 -Run -Language en
```

The installer uses `uv` to manage `.venv`. If `uv` is missing, it is installed using the official installer. If the requested Python version is not available locally, `uv` can download it automatically.

```bash
./install.sh --python 3.12
```

Generate a noisy terrain:

```bash
python3 -m terrain_generator.cli \
  --type noise \
  --output generated/noise \
  --seed 7 \
  --rows 128 \
  --cols 128 \
  --length 8 \
  --width 8 \
  --height 0.8
```

The output directory contains:

```text
generated/noise/
├── terrain.xml
├── terrain.png
└── terrain.json
```

Validate that the XML compiles in MuJoCo:

```bash
python3 -m terrain_generator.cli \
  --type stairs \
  --output generated/stairs \
  --validate
```

Open an interactive viewer after generation:

```bash
python3 -m terrain_generator.cli \
  --type noise \
  --output generated/noise \
  --seed 7 \
  --view
```

Use the mouse to rotate, zoom, and pan the view. Close the window to exit. `--validate --view` performs both validation and visualization.

## PyQt playground editor

The blue-and-white PyQt editor is obstacle-oriented:

- Select an obstacle type and review the object list on the left.
- Preview the arena from above in the center.
- Edit the selected obstacle parameters on the right.
- Click an empty area to add an obstacle, or click an obstacle to select it.
- Ctrl+click an obstacle to drag it. Use the rotation buttons and then save or delete it.

Launch the editor in English with:

```bash
arenax --edit --language en --output generated/my_arena
```

The CLI entry point is `arenax`. Chinese remains the default; use `--language en` for the English editor and embedded simulation page.
You can also click the **English** button in the editor to switch languages at runtime. The embedded simulation page provides the same switch in its header, and the current scene is preserved.

The right panel provides robot selection, export, and a page-navigation arrow:

- **No robot / M20 / Go2**: select whether to export a plain scene or a scene with the corresponding bundled robot and ONNX policy.
- **Export and view in MuJoCo**: export the scene and open the second page in the same PyQt application. The second page embeds a lightweight MuJoCo `Renderer`.

M20 and Go2 use independent MuJoCo scenes, assets, policies, and runtime configurations. Go2's `go2_amp_dreamwaq` 20,000-step checkpoint is retained as a training artifact; deployment uses the converted `policies/go2/policy.onnx`.

```bash
arenax --robot m20 --policy policies/m20/policy.onnx
arenax --robot go2 --policy policies/go2/policy.onnx
```

The three resource layers are kept separate:

`assets/<robot>/mjcf/` (model assets) → `policies/<robot>/` (policy) → `configs/<robot>.yaml` (observations, PD, and joint mapping).

The preview marks the bundled M20 spawn area with a red circle at world coordinates `x=0, y=0`; the base height is approximately `1.0 m`. Avoid placing obstacles there. A custom robot XML may use a different spawn pose.

Each export creates a timestamped local directory such as `generated/my_arena/output_20260901_153045/`. If an export is repeated within the same second, a numeric suffix is added instead of overwriting the previous result.

The embedded mode does not start a separate MuJoCo viewer or control-panel process, avoiding GLFW keyboard-shortcut and Qt-plugin conflicts. The simulation canvas renders at 1280×720 (720p) and displays at 30 FPS while physics steps are processed in batches in the background.

The legacy standalone control-panel entry point now supports both robots. Select the matching policy profile with `--robot`:

```bash
python3 -m terrain_generator.simulation.control_panel \
  --robot m20 \
  --xml generated/m20_playground/terrain.xml \
  --policy policies/m20/policy.onnx

python3 -m terrain_generator.simulation.control_panel \
  --robot go2 \
  --xml generated/go2_arena/terrain.xml \
  --policy policies/go2/policy.onnx
```

After focusing the canvas:

- Mouse wheel: zoom
- Left drag: rotate
- Right drag: pan
- `W/S`: forward/backward
- `A/D`: strafe left/right
- `Q/E`: turn left/right

The omnidirectional speed slider covers 0–2 m/s and defaults to 1 m/s. Robot collision proxies remain active for physics contacts but are hidden by default in the embedded page and standalone viewer; only the robot visual meshes are rendered.

## Editor and simulation examples

The arena editor provides top-down layout, obstacle parameter editing, and terrain-library loading:

![ArenaX Robotics arena editor](assets/Image/editor-overview.png)

After exporting, run the M20 policy in the embedded MuJoCo page:

![M20 stairs simulation](assets/Image/m20-stairs-simulation.png)

You can also load and validate a complete XML scene from the terrain library:

![Terrain library simulation](assets/Image/terrain-library-simulation.png)

## Terrain library

Standalone MuJoCo XML files can be placed in a directory and loaded from the editor's terrain-library panel or the CLI.

The repository reserves `terrain_library/` at the project root. Copy one or more `.xml` files there and they will be discovered when the editor starts; use **Refresh** after adding files. Other directories can be selected in the editor.

```bash
arenax --terrain-library /path/to/terrain_library --terrain-name rocky --view
```

If `--terrain-name` is omitted, the first XML file in filename order is loaded. Library scenes are loaded from their original XML and do not pass through procedural terrain generation. Importing a library scene displays an overwrite warning because unsaved editor changes are not retained.

When a robot is selected, ArenaX creates a temporary merged robot-plus-library scene before opening the embedded simulation. The merged scene keeps only the ground provided by the library XML. If the library uses `compiler angle="degree"` while the robot uses radians, terrain element `euler` values are converted during import to preserve slope direction and angle.

The main code boundaries are:

- `terrain_generator/terrain/`: terrain models, procedural generation, scene composition, and XML export
- `terrain_generator/simulation/`: robot policies, MuJoCo rendering, interaction, and control
- `terrain_generator/terrain/library.py`: discovery and loading of optional external XML scenes

### Z-fighting

If a base robot XML contains a `worldbody` plane and the exporter adds a heightfield beginning at `z=0`, the surfaces overlap and may flicker because the depth buffer cannot consistently choose one surface. A default `flat` scene uses MuJoCo's plane directly and does not add another heightfield. Non-flat terrain (`slope`, `stairs`, `noise`, and `obstacle_mix`) removes the base plane and uses one heightfield.

## ONNX policies and robot validation

ArenaX includes the DreamWaQ ONNX runtime integration for M20. The M20 MJCF, STL meshes, and ONNX policy are stored in `assets/m20/` and `policies/m20/`; no external download directory is required. Other policies and robot XML files can also be supplied through the CLI.

Use the bundled M20 model and policy. When `--base-scene` is omitted, the bundled model is selected automatically:

```bash
arenax \
  --preset playground \
  --output generated/m20_playground \
  --policy policies/m20/policy.onnx
```

Run an already exported XML scene:

```bash
arenax \
  --xml generated/m20_playground/terrain.xml \
  --policy /path/to/policy.onnx
```

In the embedded robot runtime, click the MuJoCo canvas and use `W/A/S/D/Q/E`. The left panel contains the speed slider and manual reset. When using `arenax --policy` directly, arrow keys and the numeric keypad remain available.

The runtime validates ONNX input dimensions. The current M20 DreamWaQ configuration uses a 57-dimensional observation, 5 history frames, a 342-dimensional policy input, and 16 actions.

The editor exports `terrain.xml`, `terrain.png`, `terrain.json`, and `scene.json`. To load an existing Unitree robot scene:

```bash
python3 -m terrain_generator.cli \
  --edit \
  --language en \
  --base-scene /path/to/unitree_mujoco/terrain_tool/scene.xml \
  --output generated/go2_arena
```

The **Export and view in MuJoCo** button opens the 3D simulation after export. An exported scene can later be loaded and visualized again:

```bash
python3 -m terrain_generator.cli \
  --scene generated/my_arena/output_20260901_153045/scene.json \
  --output generated/my_arena/reexport \
  --validate \
  --view
```

Python usage:

```python
from terrain_generator import TerrainConfig, generate_terrain, export_mujoco

config = TerrainConfig(kind="obstacle_mix", seed=42, rows=128, cols=128)
terrain = generate_terrain(config)
export_mujoco(terrain, "generated/obstacle_mix")
```

## Design notes

Non-flat terrain surfaces use a MuJoCo `hfield` geom, so a scene needs only one terrain geom and avoids the cost of generating many box geoms. Flat scenes use a MuJoCo `plane`; `obstacle_mix` writes box obstacles directly to XML while retaining the same heightfield as the base ground.

Terrain dimensions are controlled by `length`, `width`, and `height`; `rows` and `cols` control heightfield resolution. All random terrain generators accept `seed`, so identical parameters produce reproducible output.

## Roadmap

- Add Perlin/Simplex noise and erosion simulation
- Support obstacle size, heading, and parameter editing throughout the editor
- Add robot spawn poses, routes, and collision-test configuration
- Export PNG/OBJ/PLY and batch scene configurations
- Integrate Gymnasium / dm_control environments
