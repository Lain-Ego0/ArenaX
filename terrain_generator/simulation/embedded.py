"""Qt embedded simulation page.

The implementation remains in ``embedded_mujoco`` for source compatibility;
this module provides the explicit simulation namespace used by new code.
"""

from ..embedded_mujoco import EmbeddedSimulationPage, MuJoCoCanvas, MuJoCoRenderWorker

__all__ = ["EmbeddedSimulationPage", "MuJoCoCanvas", "MuJoCoRenderWorker"]

