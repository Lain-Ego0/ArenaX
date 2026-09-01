# Bundled M20 model

This directory contains the M20 MuJoCo scene and mesh assets used by PAVE's
DreamWaQ inference example. The scene is self-contained relative to this
directory: `mjcf/scene.xml` includes `M20.xml`, and `M20.xml` resolves meshes
from `../meshes/`.

The corresponding policy is in `policies/m20/policy.onnx`.
