# PAVE

Policy and Arena Validation Environment

一个面向机器人策略验证的 MuJoCo 地形与场景工具。它把参数化地形生成成：

- MuJoCo XML 场景文件
- MuJoCo 可读取的 PNG 高度图
- 描述生成参数的 JSON 元数据

当前内置基础地形类型：`flat`、`slope`、`stairs`、`noise`、`obstacle_mix`。

机器人 play 测试障碍组件：高台、台阶、镂空台阶、斜坡、独立小方柱梅花桩、三角障碍、平放汽车轮胎圈、绕杆、沙坑、高墙。三角障碍默认采用约 `30°` 坡度，按左、右、左、右交错，并带有通过方向错位参数 `stagger=0.8m`，避免左右障碍面对面；每两个障碍按 `pair_yaw=90°` 旋转。

默认尺寸约定：轮胎圈外径 `0.74 m`、梅花桩边长 `0.3 m`；这些尺寸都可以在 PyQt 编辑器右侧障碍参数中修改。

## 快速开始

建议使用项目自己的 `.venv` 环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

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

输出目录中会有：

```text
generated/noise/
├── terrain.xml
├── terrain.png
└── terrain.json
```

验证 XML 是否可以被 MuJoCo 编译：

```bash
python3 -m terrain_generator.cli \
  --type stairs \
  --output generated/stairs \
  --validate
```

生成后直接打开交互式可视化窗口：

```bash
python3 -m terrain_generator.cli \
  --type noise \
  --output generated/noise \
  --seed 7 \
  --view
```

窗口打开后可以用鼠标旋转、缩放和移动视角；关闭窗口即可结束程序。`--validate --view` 可以同时编译检查并打开窗口。

一键生成包含全部常用障碍的标准测试场地：

```bash
python3 -m terrain_generator.cli \
  --preset playground \
  --output generated/playground \
  --validate \
  --view
```

如果已有宇树机器人场景（例如包含 `go2.xml` 的 `scene.xml`），可以直接在其基础上追加障碍：

```bash
python3 -m terrain_generator.cli \
  --preset playground \
  --base-scene /path/to/unitree_mujoco/terrain_tool/scene.xml \
  --output generated/go2_playground \
  --validate \
  --view \
  --no-test-ball
```

导出的 XML 会保留基础场景中的机器人、asset 和 worldbody 内容；对带有网格资源的机器人 include 会自动展开，并把资源路径转换为可加载的路径。

## 蓝白色 PyQt 图形化编辑器

编辑器使用蓝白色界面，所有操作都以障碍对象为中心：左侧选择新增障碍类型和对象列表，中间是场地俯视预览，右侧编辑当前障碍的参数。点击空白处按当前类型新增，点击障碍即可选中；按住 Ctrl 点击障碍进入单对象编辑，可直接拖动障碍改变位置，使用右侧旋转按钮改变朝向，最后点击“保存障碍”或“删除”。

```bash
pave \
  --edit \
  --output generated/my_arena
```

编辑器右侧提供两个导出操作：

- **导出并在 MuJoCo 查看**：只加载刚导出的场景进行可视化。
- **导出并添加机器人（MuJoCo 查看）**：在 MuJoCo 中自动加入仓库内置 M20，加载 `policies/m20/policy.onnx`，同时打开 PyQt 控制面板和策略仿真窗口。

每次点击都会在输出目录下新建本地时间命名的子目录，例如 `generated/my_arena/output_20260901_153045/`；如果同一秒重复导出，会自动追加序号，不会覆盖已有结果。

## ONNX 策略与机器人验证

PAVE 当前接入 M20 的 DreamWaQ ONNX 推理运行时。M20 的 MJCF、STL 网格和 ONNX 策略均已放入本仓库的 `assets/m20/` 和 `policies/m20/`，不再依赖下载目录。也可以通过命令行传入其他策略或机器人 XML。

使用仓库内置的 DreamWaQ M20 模型和策略（未指定 `--base-scene` 时会自动使用内置模型）：

```bash
pave \
  --preset playground \
  --output generated/m20_playground \
  --policy policies/m20/policy.onnx
```

也可以直接运行已经导出的 XML：

```bash
pave \
  --xml generated/m20_playground/terrain.xml \
  --policy /path/to/policy.onnx
```

机器人运行时请使用独立的 PyQt 控制面板点击操作：方向、转向、停止、速度档位和重置都在面板中完成，不需要把键盘焦点放到 MuJoCo viewer。这样不会触发 viewer 的键盘快捷键。直接使用 `pave --policy` 时仍可使用方向键或数字小键盘控制。

运行时会校验 ONNX 输入维度。目前 M20 DreamWaQ 配置为 `57` 维观测、`5` 帧历史，即 `342` 维策略输入，动作维度为 `16`。

编辑器会导出 `terrain.xml`、`terrain.png`、`terrain.json` 和 `scene.json`。如果需要直接加载宇树机器人场景，可以这样启动：

```bash
python3 -m terrain_generator.cli \
  --edit \
  --base-scene /path/to/unitree_mujoco/terrain_tool/scene.xml \
  --output generated/go2_arena
```

点击“导出并在 MuJoCo 查看”可以在导出后自动打开三维仿真窗口。以后也可以直接回读并可视化场景（将路径替换为实际生成的时间目录）：

```bash
python3 -m terrain_generator.cli \
  --scene generated/my_arena/output_20260901_153045/scene.json \
  --output generated/my_arena/reexport \
  --validate \
  --view
```

在 Python 中使用：

```python
from terrain_generator import TerrainConfig, generate_terrain, export_mujoco

config = TerrainConfig(kind="obstacle_mix", seed=42, rows=128, cols=128)
terrain = generate_terrain(config)
export_mujoco(terrain, "generated/obstacle_mix")
```

## 设计说明

地形表面使用 MuJoCo 的 `hfield` geom 表示，因此场景中只需要一个地形 geom，仿真效率比生成大量 box geom 更好。`obstacle_mix` 会把箱型障碍物直接写入 XML，并保留同一张高度图作为基础地面。

地形的物理尺寸由 `length`、`width`、`height` 控制；`rows` 和 `cols` 控制高度图采样分辨率。所有随机地形均支持 `seed`，相同参数会得到可复现结果。

## 后续扩展方向

- 增加 Perlin/Simplex 噪声和侵蚀模拟
- 支持编辑器中的障碍尺寸、朝向和参数面板
- 增加机器人 spawn pose、路线和碰撞测试配置
- 输出 PNG/OBJ/PLY 以及批量场景配置
- 接入 Gymnasium / dm_control 环境
