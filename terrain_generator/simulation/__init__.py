"""Robot simulation runtime.

Terrain generation/export lives in :mod:`terrain_generator.generators` and
:mod:`terrain_generator.mujoco_xml`; this package is the explicit simulation
boundary.  Imports are re-exported for backwards compatibility with the
original ``terrain_generator.m20_sim`` module.
"""

from ..m20_sim import KeyboardCommand, M20Simulation, OnnxPolicy, run_m20_policy

__all__ = ["KeyboardCommand", "M20Simulation", "OnnxPolicy", "run_m20_policy"]
