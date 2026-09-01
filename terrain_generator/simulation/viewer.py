"""Interactive MuJoCo viewer for generated terrains."""

from __future__ import annotations

import time
from pathlib import Path

import mujoco
import mujoco.viewer


def view_xml(xml_path: str | Path) -> None:
    """Open an interactive window and simulate the scene until it closes."""

    model = mujoco.MjModel.from_xml_path(str(xml_path))
    data = mujoco.MjData(model)

    # launch_passive keeps the Python process in control of stepping and camera setup.
    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.cam.lookat[:] = [0.0, 0.0, 0.0]
        viewer.cam.distance = max(model.stat.extent * 1.8, 4.0)
        viewer.cam.azimuth = 135.0
        viewer.cam.elevation = -55.0
        viewer.sync()

        while viewer.is_running():
            step_start = time.perf_counter()
            mujoco.mj_step(model, data)
            viewer.sync()
            remaining = model.opt.timestep - (time.perf_counter() - step_start)
            if remaining > 0:
                time.sleep(remaining)
