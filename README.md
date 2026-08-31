# MuJoCo Terrain Generator

一个从零开始的 MuJoCo 地形生成器。它把参数化地形生成成：

- MuJoCo XML 场景文件
- MuJoCo 可读取的 PNG 高度图
- 描述生成参数的 JSON 元数据

当前内置基础地形类型：`flat`、`slope`、`stairs`、`noise`、`obstacle_mix`。

机器人 play 测试障碍组件：高台、台阶、镂空台阶、斜坡、独立小方柱梅花桩、三角障碍、平放汽车轮胎圈、绕杆、沙坑、高墙。

默认尺寸约定：轮胎圈外径 `0.74 m`、小方柱边长 `0.45 m`；这些尺寸都可以在 PyQt 编辑器右侧参数 JSON 中修改。

## 快速开始

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

导出的 XML 会保留基础场景中的机器人 include、asset 和 worldbody 内容，并把相对资源路径转换为可加载的路径。

## 蓝白色 PyQt 图形化编辑器

编辑器使用蓝白色界面：左侧选择障碍类型和管理组件，中间是场地俯视预览，右侧可以修改位置、朝向和障碍参数。点击场地放置或修改参数后，中央预览会立即更新。

```bash
python3 -m terrain_generator.cli \
  --edit \
  --output generated/my_arena
```

编辑器会导出 `terrain.xml`、`terrain.png`、`terrain.json` 和 `scene.json`。如果需要直接加载宇树机器人场景，可以这样启动：

```bash
python3 -m terrain_generator.cli \
  --edit \
  --base-scene /path/to/unitree_mujoco/terrain_tool/scene.xml \
  --output generated/go2_arena
```

点击“导出并打开 MuJoCo”可以在导出后自动打开三维仿真窗口。以后也可以直接回读并可视化场景：

```bash
python3 -m terrain_generator.cli \
  --scene generated/my_arena/scene.json \
  --output generated/my_arena_export \
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
