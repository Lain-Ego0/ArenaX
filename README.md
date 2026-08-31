# MuJoCo Terrain Generator

一个从零开始的 MuJoCo 地形生成器。它把参数化地形生成成：

- MuJoCo XML 场景文件
- MuJoCo 可读取的 PNG 高度图
- 描述生成参数的 JSON 元数据

当前内置地形类型：`flat`、`slope`、`stairs`、`noise`、`obstacle_mix`。

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
- 支持圆柱、台阶、沟壑等局部地形组件
- 增加 viewer 与机器人 spawn pose
- 输出 PNG/OBJ/PLY 以及批量场景配置
- 接入 Gymnasium / dm_control 环境
