"""M20 ONNX policy inference and MuJoCo simulation control."""

from __future__ import annotations

import json
import socket
import sys
import time
from threading import Lock, Thread
from pathlib import Path
from typing import Any

import mujoco
import mujoco.viewer
import numpy as np
import yaml


def _quat_rotate_inverse_wxyz(quat: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Rotate a world-frame vector into a body frame using a wxyz quaternion."""

    qw, qx, qy, qz = np.asarray(quat, dtype=np.float64)
    vec = np.asarray(vector, dtype=np.float64)
    qvec = np.array([qx, qy, qz], dtype=np.float64)
    a = vec * (2.0 * qw * qw - 1.0)
    b = np.cross(qvec, vec) * qw * 2.0
    c = qvec * np.dot(qvec, vec) * 2.0
    return a - b + c


def _gravity_orientation(quat: np.ndarray) -> np.ndarray:
    """Return the projected-gravity convention used by the supplied policy."""

    qw, qx, qy, qz = np.asarray(quat, dtype=np.float64)
    return np.array([
        2.0 * (-qz * qx + qw * qy),
        -2.0 * (qz * qy + qw * qx),
        1.0 - 2.0 * (qw * qw + qz * qz),
    ], dtype=np.float32)


class OnnxPolicy:
    """Small ONNX Runtime adapter with an explicit input-size check."""

    def __init__(self, path: str | Path) -> None:
        policy_path = Path(path).expanduser().resolve()
        if not policy_path.is_file():
            raise FileNotFoundError(f"ONNX policy not found: {policy_path}")
        try:
            import onnxruntime as ort
        except ImportError as first_error:  # pragma: no cover - depends on local setup
            # The Qt editor can be launched by an IDE using system Python.
            # Reuse the repository environment's packages in that case so
            # the embedded page remains in the same PyQt application.
            # ``m20.py`` lives in terrain_generator/simulation/, so walking
            # exactly two parents (the old location) no longer reaches the
            # repository root.  Locate the first ancestor that owns .venv so
            # IDE-launched system Python can reuse the project environment.
            module_path = Path(__file__).resolve()
            project_root = next(
                (parent for parent in module_path.parents if (parent / ".venv").is_dir()),
                module_path.parents[2],
            )
            site_package_dirs = sorted(project_root.glob(".venv/lib/python*/site-packages"))
            for site_packages in reversed(site_package_dirs):
                site_packages_text = str(site_packages)
                if site_packages_text not in sys.path:
                    sys.path.insert(0, site_packages_text)
            try:
                import onnxruntime as ort
            except ImportError as exc:
                raise RuntimeError(
                    "onnxruntime is required; activate .venv and install the project dependencies"
                ) from (exc if site_package_dirs else first_error)

        self.path = policy_path
        # A single worker avoids ONNX Runtime oversubscribing the render/
        # simulation thread (the default multi-thread pool is a common source
        # of visible stutter for small locomotion policies).
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(
            str(policy_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or not outputs:
            raise ValueError("PAVE expects an ONNX policy with one input and at least one output")
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name
        shape = inputs[0].shape
        self.input_size = shape[-1] if shape and isinstance(shape[-1], int) else None

    def __call__(self, observation: np.ndarray) -> np.ndarray:
        observation = np.asarray(observation, dtype=np.float32).reshape(-1)
        if self.input_size is not None and observation.size != self.input_size:
            raise ValueError(
                f"policy input mismatch: ONNX expects {self.input_size} values, "
                f"PAVE produced {observation.size}"
            )
        result = self.session.run(
            [self.output_name], {self.input_name: observation.reshape(1, -1)}
        )[0]
        return np.asarray(result, dtype=np.float32).reshape(-1)


class M20ControlClient:
    """Receive commands from the separate PyQt control panel process."""

    def __init__(self, simulation: "M20Simulation", host: str, port: int) -> None:
        self.simulation = simulation
        self.host = host
        self.port = port
        self.socket: socket.socket | None = None
        self.thread = Thread(target=self._run, name="pave-control-client", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not self.simulation.stop_requested:
            try:
                connection = socket.create_connection((self.host, self.port), timeout=1.0)
                self.socket = connection
                print(f"Control panel connected: {self.host}:{self.port}")
                self._receive(connection)
                return
            except OSError:
                time.sleep(0.1)
        print("Control panel connection was not established")

    def _receive(self, connection: socket.socket) -> None:
        buffer = b""
        connection.settimeout(0.5)
        with connection:
            while not self.simulation.stop_requested:
                try:
                    chunk = connection.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    if raw:
                        self._handle(json.loads(raw.decode("utf-8")))

    def _handle(self, command: dict[str, Any]) -> None:
        operation = command.get("op")
        if operation == "adjust":
            self.simulation.command.adjust(int(command["axis"]), float(command["delta"]))
        elif operation == "stop":
            self.simulation.command.stop()
        elif operation == "gear":
            self.simulation.command.set_gear(int(command["gear"]))
        elif operation == "reset":
            self.simulation.request_reset()
        elif operation == "quit":
            self.simulation.request_stop()

    def close(self) -> None:
        self.simulation.request_stop()
        if self.socket is not None:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _load_config(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "configs" / "m20.yaml"
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"M20 config not found: {config_path}")
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}
    config["_path"] = str(config_path)
    return config


class KeyboardCommand:
    """Latched command keys that do not collide with MuJoCo viewer shortcuts."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._lock = Lock()
        self.command = np.asarray(config.get("cmd_init", [0.0, 0.0, 0.0]), dtype=np.float32)
        # The UI exposes one omnidirectional speed slider (0..2 m/s).  Keep
        # the old per-axis limits as a fallback for callers using the
        # headless runtime, but use the selected speed for both vx and vy.
        self.max_command = np.asarray(config.get("max_cmd", [1.0, 1.0, 2.0]), dtype=np.float32)
        self.speed = float(np.clip(config.get("default_speed", 1.0), 0.0, 2.0))
        self.gear_speeds = {int(k): float(v) for k, v in config.get(
            "gear_speeds", {1: 0.5, 2: 1.0, 3: 1.5}
        ).items()}
        self.gear = int(config.get("default_gear", 1))
        self._set_gear(self.gear)

    def set_speed(self, speed: float) -> None:
        """Set the omnidirectional linear speed in metres per second."""

        with self._lock:
            self.speed = float(np.clip(speed, 0.0, 2.0))
            self.max_command[0] = self.speed
            self.max_command[1] = self.speed
            self._clamp()

    def speed_value(self) -> float:
        with self._lock:
            return float(self.speed)

    def set_motion(self, vx: float, vy: float, yaw: float = 0.0) -> None:
        """Set a complete velocity command, clamped to the slider limits."""

        with self._lock:
            self.command[:] = (vx, vy, yaw)
            self._clamp()

    def _clamp(self) -> None:
        self.command[0] = np.clip(self.command[0], -self.max_command[0], self.max_command[0])
        self.command[1] = np.clip(self.command[1], -self.max_command[1], self.max_command[1])
        self.command[2] = np.clip(self.command[2], -self.max_command[2], self.max_command[2])

    def _set_gear(self, gear: int) -> None:
        self.gear = int(np.clip(gear, 1, 3))
        # Gear remains available to older clients.  Explicit speed-slider
        # updates always take precedence over the gear defaults.
        if self.speed <= 0.0:
            self.speed = self.gear_speeds.get(self.gear, self.max_command[0])
        self.max_command[0] = self.speed
        self.max_command[1] = self.speed
        self._clamp()

    def stop(self) -> None:
        with self._lock:
            self.command[:] = 0.0

    def adjust(self, axis: int, delta: float) -> None:
        with self._lock:
            self.command[axis] += delta
            self._clamp()

    def set_gear(self, gear: int) -> None:
        with self._lock:
            self._set_gear(gear)

    def values(self) -> np.ndarray:
        with self._lock:
            return self.command.copy()

    def gear_value(self) -> int:
        with self._lock:
            return self.gear

    def handle_key(self, key: int) -> bool:
        """Apply one key press; return whether the command changed."""

        import glfw

        changed = True
        # In the embedded Qt canvas W/A/S/D/Q/E are latched by the page.  The
        # native MuJoCo callback remains one-shot, so arrows/keypad/F-keys are
        # retained as compatibility shortcuts there.
        with self._lock:
            if key == glfw.KEY_W:
                self.command[0] = self.speed
            elif key == glfw.KEY_S:
                self.command[0] = -self.speed
            elif key == glfw.KEY_A:
                self.command[1] = self.speed
            elif key == glfw.KEY_D:
                self.command[1] = -self.speed
            elif key == glfw.KEY_Q:
                self.command[2] = abs(self.max_command[2]) * 0.5
            elif key == glfw.KEY_E:
                self.command[2] = -abs(self.max_command[2]) * 0.5
            elif key in (glfw.KEY_UP, glfw.KEY_KP_8, glfw.KEY_6):
                self.command[0] += 0.1
            elif key in (glfw.KEY_DOWN, glfw.KEY_KP_2, glfw.KEY_7):
                self.command[0] -= 0.1
            elif key in (glfw.KEY_LEFT, glfw.KEY_KP_4, glfw.KEY_8):
                self.command[1] += 0.2
            elif key in (glfw.KEY_RIGHT, glfw.KEY_KP_6, glfw.KEY_9):
                self.command[1] -= 0.2
            elif key in (glfw.KEY_F8, glfw.KEY_KP_7):
                self.command[2] += 0.2
            elif key in (glfw.KEY_F9, glfw.KEY_KP_9):
                self.command[2] -= 0.2
            elif key in (glfw.KEY_F10, glfw.KEY_KP_5):
                self.command[:] = 0.0
            elif key in (glfw.KEY_F11, glfw.KEY_KP_1):
                self._set_gear(1)
            elif key in (glfw.KEY_F12, glfw.KEY_KP_3):
                self._set_gear(2)
            elif key == glfw.KEY_HOME or key == glfw.KEY_KP_0:
                self._set_gear(3)
            else:
                changed = False
            if changed and key not in (glfw.KEY_F10, glfw.KEY_KP_5, glfw.KEY_F11, glfw.KEY_KP_1,
                                       glfw.KEY_F12, glfw.KEY_KP_3, glfw.KEY_HOME, glfw.KEY_KP_0):
                self._clamp()
            command = self.command.copy()
            gear = self.gear
        if changed:
            print(
                f"command: vx={command[0]:+.2f}, vy={command[1]:+.2f}, "
                f"yaw={command[2]:+.2f}, gear={gear}"
            )
        return changed


class M20Simulation:
    """Run the supplied DreamWaQ M20 policy against a MuJoCo XML scene."""

    def __init__(self, xml_path: str | Path, policy_path: str | Path,
                 config_path: str | Path | None = None) -> None:
        self.config = _load_config(config_path)
        self.xml_path = Path(xml_path).expanduser().resolve()
        if not self.xml_path.is_file():
            raise FileNotFoundError(f"MuJoCo XML not found: {self.xml_path}")

        self.model = mujoco.MjModel.from_xml_path(str(self.xml_path))
        self.model.opt.timestep = float(self.config.get("simulation_dt", 0.005))
        self.data = mujoco.MjData(self.model)
        self.policy = OnnxPolicy(policy_path)
        self.command = KeyboardCommand(self.config)

        self.num_actions = int(self.config.get("num_actions", 16))
        self.num_obs = int(self.config.get("num_obs", 57))
        self.num_obs_hist = int(self.config.get("num_obs_hist", 5))
        self.control_decimation = int(self.config.get("control_decimation", 4))
        self.default_angles = np.asarray(self.config["default_angles"], dtype=np.float32)
        self.kps = np.asarray(self.config["kps"], dtype=np.float32)
        self.kds = np.asarray(self.config["kds"], dtype=np.float32)
        self.torque_limits = np.asarray(self.config["torque_limits"], dtype=np.float32)
        self.cmd_scale = np.asarray(self.config.get("cmd_scale", [2, 2, 0.25]), dtype=np.float32)
        self.wheel_indices = np.asarray(self.config.get("wheel_indices", [3, 7, 11, 15]), dtype=np.int32)
        self.joint_names = list(self.config.get("joint_names", []))
        if len(self.joint_names) != self.num_actions:
            raise ValueError("M20 config joint_names must contain exactly num_actions entries")
        for values_name, values in (("default_angles", self.default_angles), ("kps", self.kps),
                                    ("kds", self.kds), ("torque_limits", self.torque_limits)):
            if len(values) != self.num_actions:
                raise ValueError(f"M20 config {values_name} must contain {self.num_actions} entries")

        self.joint_ids = [self._named_id(mujoco.mjtObj.mjOBJ_JOINT, name) for name in self.joint_names]
        self.actuator_ids = [self._actuator_for_joint(name) for name in self.joint_names]
        self.base_body_id = self._find_base_body(self.config.get("base_body_names", ["base_link"]))
        self.base_joint_id = self._find_free_joint(self.base_body_id)
        self.base_qpos_adr = int(self.model.jnt_qposadr[self.base_joint_id])
        self.base_qvel_adr = int(self.model.jnt_dofadr[self.base_joint_id])

        self.action = np.zeros(self.num_actions, dtype=np.float32)
        self.observation = np.zeros(self.num_obs, dtype=np.float32)
        self.observation_history = np.zeros(self.num_obs * (self.num_obs_hist + 1), dtype=np.float32)
        self.counter = 0
        self.reset_requested = False
        self._reset_lock = Lock()
        self.stop_requested = False
        self._episode_start_x = 0.0
        self._episode_max_tilt = 0.0
        self._episode_fallen = False
        self._print_contract()
        self.reset()

    def _named_id(self, object_type: mujoco.mjtObj, name: str) -> int:
        object_id = mujoco.mj_name2id(self.model, object_type, name)
        if object_id < 0:
            raise ValueError(f"M20 model does not contain object type {object_type}: {name}")
        return object_id

    def _actuator_for_joint(self, joint_name: str) -> int:
        joint_id = self.joint_ids[self.joint_names.index(joint_name)]
        for actuator_id in range(self.model.nu):
            if int(self.model.actuator_trnid[actuator_id, 0]) == joint_id:
                return actuator_id
        raise ValueError(f"M20 model has no actuator for joint: {joint_name}")

    def _find_base_body(self, names: list[str]) -> int:
        for name in names:
            body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, name)
            if body_id >= 0:
                return body_id
        raise ValueError(f"M20 model has no base body named one of {names}")

    def _find_free_joint(self, body_id: int) -> int:
        for joint_id in range(self.model.njnt):
            if self.model.jnt_bodyid[joint_id] == body_id and self.model.jnt_type[joint_id] == mujoco.mjtJoint.mjJNT_FREE:
                return joint_id
        raise ValueError("M20 base body must have a free joint")

    def _print_contract(self) -> None:
        expected_input = self.num_obs * (self.num_obs_hist + 1)
        print(f"M20 XML: {self.xml_path}")
        print(f"ONNX: {self.policy.path}")
        print(f"Policy contract: input={self.policy.input_size}, expected={expected_input}, output={self.num_actions}")
        print("M20 joint order:", ", ".join(self.joint_names))
        if self.policy.input_size is not None and self.policy.input_size != expected_input:
            raise ValueError(
                f"M20 DreamWaQ policy expects {self.policy.input_size} observations, "
                f"but config produces {expected_input}"
            )

    def _state(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        positions = np.array([
            self.data.qpos[int(self.model.jnt_qposadr[joint_id])] for joint_id in self.joint_ids
        ], dtype=np.float32)
        velocities = np.array([
            self.data.qvel[int(self.model.jnt_dofadr[joint_id])] for joint_id in self.joint_ids
        ], dtype=np.float32)
        base_qpos = self.data.qpos[self.base_qpos_adr:self.base_qpos_adr + 7]
        base_qvel = self.data.qvel[self.base_qvel_adr:self.base_qvel_adr + 6]
        quat = np.asarray(base_qpos[3:7], dtype=np.float32)
        angular_velocity = np.asarray(base_qvel[3:6], dtype=np.float32)
        linear_velocity = _quat_rotate_inverse_wxyz(quat, base_qvel[:3]).astype(np.float32)
        return positions, velocities, quat, angular_velocity, linear_velocity

    def reset(self) -> None:
        mujoco.mj_resetData(self.model, self.data)
        base_height = self.config.get("init_base_height")
        if base_height is not None:
            self.data.qpos[self.base_qpos_adr + 2] = float(base_height)
        self.data.qpos[self.base_qpos_adr + 3:self.base_qpos_adr + 7] = [1.0, 0.0, 0.0, 0.0]
        for joint_id, angle in zip(self.joint_ids, self.default_angles):
            self.data.qpos[int(self.model.jnt_qposadr[joint_id])] = float(angle)
        self.data.qvel[:] = 0.0
        self.data.ctrl[:] = 0.0
        self.action[:] = 0.0
        self.observation[:] = 0.0
        self.observation_history[:] = 0.0
        self.counter = 0
        self._episode_start_x = 0.0
        self._episode_max_tilt = 0.0
        self._episode_fallen = False
        mujoco.mj_forward(self.model, self.data)
        self._episode_start_x = float(self.data.qpos[self.base_qpos_adr])

    def request_reset(self) -> None:
        with self._reset_lock:
            self.reset_requested = True

    def request_stop(self) -> None:
        self.stop_requested = True

    def _compute_observation(self) -> None:
        positions, velocities, quat, angular_velocity, _ = self._state()
        dof_error = (positions - self.default_angles) * float(self.config.get("dof_pos_scale", 1.0))
        dof_error[self.wheel_indices] = 0.0
        dof_velocity = velocities * float(self.config.get("dof_vel_scale", 0.05))
        self.observation[:3] = self.command.values() * self.cmd_scale
        self.observation[3:6] = angular_velocity * float(self.config.get("ang_vel_scale", 0.25))
        self.observation[6:9] = _gravity_orientation(quat)
        self.observation[9:9 + self.num_actions] = dof_error
        self.observation[9 + self.num_actions:9 + 2 * self.num_actions] = dof_velocity
        self.observation[9 + 2 * self.num_actions:9 + 3 * self.num_actions] = self.action
        self.observation_history[:-self.num_obs] = self.observation_history[self.num_obs:]
        self.observation_history[-self.num_obs:] = self.observation

    def _compute_torques(self) -> np.ndarray:
        positions, velocities, _, _, _ = self._state()
        position_error = self.default_angles - positions
        position_error[self.wheel_indices] = 0.0
        position_target_offset = self.action * float(self.config.get("action_scale", 0.25))
        position_target_offset[self.wheel_indices] = 0.0
        wheel_velocity_target = np.zeros_like(self.action)
        wheel_velocity_target[self.wheel_indices] = self.action[self.wheel_indices] * float(self.config.get("vel_scale", 5.0))
        torques = self.kps * (position_target_offset + position_error) + self.kds * (
            wheel_velocity_target - velocities
        )
        return np.clip(torques, -self.torque_limits, self.torque_limits)

    def _apply_torques(self, torques: np.ndarray) -> None:
        self.data.ctrl[:] = 0.0
        for action_index, actuator_id in enumerate(self.actuator_ids):
            self.data.ctrl[actuator_id] = torques[action_index]

    def _is_fallen(self) -> bool:
        _, _, quat, _, _ = self._state()
        return bool(
            self.data.qpos[self.base_qpos_adr + 2] < 0.20
            or _gravity_orientation(quat)[2] > -0.20
        )

    def _handle_key(self, key: int) -> None:
        import glfw

        if key in (glfw.KEY_END, glfw.KEY_KP_DECIMAL):
            self.request_reset()
            return
        self.command.handle_key(key)

    def _setup_camera(self, viewer: Any) -> None:
        viewer.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
        viewer.cam.trackbodyid = self.base_body_id
        viewer.cam.distance = 2.5
        viewer.cam.elevation = -20.0
        viewer.cam.azimuth = 60.0

    def _step(self) -> None:
        with self._reset_lock:
            reset_requested = self.reset_requested
            self.reset_requested = False
        if reset_requested:
            self.reset()
        if self.counter % self.control_decimation == 0:
            self._compute_observation()
            self.action = self.policy(self.observation_history)
            if self.action.size != self.num_actions:
                raise ValueError(
                    f"policy output mismatch: expected {self.num_actions}, got {self.action.size}"
                )
        self._apply_torques(self._compute_torques())
        mujoco.mj_step(self.model, self.data)
        _, _, quat, _, _ = self._state()
        tilt = float(np.arccos(np.clip(-_gravity_orientation(quat)[2], -1.0, 1.0)))
        self._episode_max_tilt = max(self._episode_max_tilt, tilt)
        self.counter += 1

    def _summary(self) -> dict[str, float | bool]:
        distance = float(self.data.qpos[self.base_qpos_adr] - self._episode_start_x)
        return {
            "survived": not self._episode_fallen,
            "sim_time": float(self.data.time),
            "distance_x": distance,
            "max_tilt_deg": float(np.rad2deg(self._episode_max_tilt)),
        }

    def run(self, duration: float = 30.0, episodes: int = 1, view: bool = True) -> list[dict[str, float | bool]]:
        if duration <= 0 or episodes <= 0:
            raise ValueError("duration and episodes must be positive")
        self.stop_requested = False
        summaries: list[dict[str, float | bool]] = []

        def loop(viewer: Any | None = None) -> None:
            episode = 0
            wall_clock = time.perf_counter()
            while (episode < episodes and not self.stop_requested
                   and (viewer is None or viewer.is_running())):
                if self.data.time >= duration:
                    summaries.append(self._summary())
                    episode += 1
                    if episode >= episodes:
                        break
                    self.reset()
                    wall_clock = time.perf_counter()
                    continue
                self._step()
                if self._is_fallen():
                    self._episode_fallen = True
                    summaries.append(self._summary())
                    episode += 1
                    if episode >= episodes:
                        break
                    self.reset()
                    wall_clock = time.perf_counter()
                    continue
                if viewer is not None:
                    viewer.sync()
                    remaining = self.model.opt.timestep - (time.perf_counter() - wall_clock)
                    if remaining > 0:
                        time.sleep(remaining)
                    wall_clock = time.perf_counter()
            if episode and len(summaries) < episode:
                summaries.append(self._summary())

        if view:
            with mujoco.viewer.launch_passive(
                self.model, self.data, key_callback=self._handle_key
            ) as viewer:
                self._setup_camera(viewer)
                viewer.sync()
                loop(viewer)
        else:
            loop()
        for index, summary in enumerate(summaries, start=1):
            print(f"Episode {index}: {summary}")
        return summaries


def run_m20_policy(xml_path: str | Path, policy_path: str | Path,
                   config_path: str | Path | None = None, *,
                   duration: float = 30.0, episodes: int = 1, view: bool = True,
                   control_host: str | None = None, control_port: int | None = None) -> None:
    simulation = M20Simulation(xml_path, policy_path, config_path)
    control_client = None
    if control_host is not None or control_port is not None:
        if control_host is None or control_port is None:
            raise ValueError("control_host and control_port must be provided together")
        control_client = M20ControlClient(simulation, control_host, control_port)
        control_client.start()
    try:
        simulation.run(duration=duration, episodes=episodes, view=view)
    finally:
        if control_client is not None:
            control_client.close()
