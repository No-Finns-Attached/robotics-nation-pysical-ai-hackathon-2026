import json
import time
from pathlib import Path

from lerobot.robots.so_follower import SO101FollowerConfig, SO101Follower

PORT = "/dev/tty.usbmodem5A460858781"
ROBOT_ID = "my_so101_follower"
ENV_FILE = Path("environment_corners.json")

# Motion tuning
MOVE_DURATION_S = 2.5
MOVE_HZ = 25
PAUSE_BETWEEN_SEGMENTS_S = 0.6
UPDOWN_DELTA = 8.0
UPDOWN_CYCLES = 2
USE_CLEARANCE_WAYPOINT = True
USE_EXTRA_HIGH_CLEARANCE = True
TRANSIT_KEEP_HIGH_JOINTS = [
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
]
DESCEND_DURATION_SCALE = 1.2
PRELIFT_JOINTS = ["shoulder_lift.pos", "elbow_flex.pos"]
PRELIFT_DURATION_SCALE = 0.8

config = SO101FollowerConfig(
    port=PORT,
    id=ROBOT_ID,
    disable_torque_on_disconnect=False,
    max_relative_target=5.0,
    use_degrees=True,
)

robot = SO101Follower(config)


def capture_pose_manually(prompt_text):
    print("Torque OFF: you can move the arm by hand now.")
    robot.bus.disable_torque()
    input(prompt_text)
    pose = current_joints()
    robot.bus.enable_torque()
    print("Torque ON.")
    return pose


def load_corners(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    corners_raw = data.get("corners", {})
    required = ["1", "2", "3", "4"]
    missing = [corner for corner in required if corners_raw.get(corner) is None]
    if missing:
        raise ValueError(f"Missing recorded corners: {missing}")

    corners = {}
    for corner_id in required:
        corners[corner_id] = {k: float(v) for k, v in corners_raw[corner_id].items() if k.endswith(".pos")}

    return corners


def current_joints():
    obs = robot.get_observation()
    return {k: float(v) for k, v in obs.items() if k.endswith(".pos")}


def interpolate_and_send(target_pose, duration_s=MOVE_DURATION_S, hz=MOVE_HZ):
    start_pose = current_joints()
    keys = sorted(set(start_pose.keys()) | set(target_pose.keys()))

    steps = max(2, int(duration_s * hz))
    for i in range(1, steps + 1):
        alpha = i / steps
        cmd = {}
        for key in keys:
            start = float(start_pose.get(key, target_pose.get(key, 0.0)))
            end = float(target_pose.get(key, start))
            cmd[key] = start + alpha * (end - start)

        if "gripper.pos" in cmd:
            cmd["gripper.pos"] = min(100.0, max(0.0, cmd["gripper.pos"]))

        robot.send_action(cmd)
        time.sleep(1.0 / hz)


def move_to_pose(name, pose):
    print(f"Moving to {name}...")
    interpolate_and_send(pose)
    print(f"Reached {name}: {current_joints()}")
    time.sleep(PAUSE_BETWEEN_SEGMENTS_S)


def build_lateral_pose(target_pose, high_pose):
    """Move sideways while keeping lift/elbow/wrist in high safe posture."""
    lateral = dict(target_pose)
    for joint_name in TRANSIT_KEEP_HIGH_JOINTS:
        if joint_name in high_pose:
            lateral[joint_name] = high_pose[joint_name]
    return lateral


def build_prelift_pose(current_pose, high_pose):
    """Lift critical joints first while keeping the rest near current pose."""
    prelift = dict(current_pose)
    for joint_name in PRELIFT_JOINTS:
        if joint_name in high_pose:
            prelift[joint_name] = high_pose[joint_name]
    return prelift


def move_to_pose_via_clearance(name, pose, clearance_pose=None, extra_high_clearance_pose=None):
    if clearance_pose is None and extra_high_clearance_pose is None:
        move_to_pose(name, pose)
        return

    high_pose = extra_high_clearance_pose if extra_high_clearance_pose is not None else clearance_pose
    current_pose = current_joints()

    print(f"Moving to {name} via high staged transit...")
    # Stage 1a: pre-lift shoulder + elbow first (multi-joint lift)
    prelift_pose = build_prelift_pose(current_pose, high_pose)
    interpolate_and_send(prelift_pose, duration_s=MOVE_DURATION_S * PRELIFT_DURATION_SCALE, hz=MOVE_HZ)
    time.sleep(0.1)

    # Stage 1b: go fully to captured high pose
    interpolate_and_send(high_pose)
    time.sleep(0.15)

    # Stage 2: move laterally while keeping arm high
    lateral_pose = build_lateral_pose(pose, high_pose)
    interpolate_and_send(lateral_pose)
    time.sleep(0.15)

    # Stage 3: controlled descend to final target
    interpolate_and_send(pose, duration_s=MOVE_DURATION_S * DESCEND_DURATION_SCALE, hz=MOVE_HZ)

    print(f"Reached {name}: {current_joints()}")
    time.sleep(PAUSE_BETWEEN_SEGMENTS_S)


def average_pose(poses):
    keys = sorted({k for pose in poses for k in pose.keys()})
    result = {}
    for key in keys:
        vals = [float(pose[key]) for pose in poses if key in pose]
        result[key] = sum(vals) / len(vals)
    return result


def run_environment_test(corners, clearance_pose=None, extra_high_clearance_pose=None):
    print("\n=== Environment Test Start ===")

    # 1) Along edges: 1 -> 2 -> 3 -> 4 -> 1
    print("\n[1/3] Edge traversal")
    edge_order = ["1", "2", "3", "4", "1"]
    for corner_id in edge_order:
        move_to_pose_via_clearance(
            f"corner {corner_id}",
            corners[corner_id],
            clearance_pose,
            extra_high_clearance_pose,
        )

    # 2) Diagonals
    print("\n[2/3] Diagonal traversal")
    diagonal_order = ["1", "3", "2", "4", "1"]
    for corner_id in diagonal_order:
        move_to_pose_via_clearance(
            f"corner {corner_id}",
            corners[corner_id],
            clearance_pose,
            extra_high_clearance_pose,
        )

    # 3) Up/down around center
    print("\n[3/3] Up/down motion")
    center = average_pose(list(corners.values()))
    move_to_pose_via_clearance("center", center, clearance_pose, extra_high_clearance_pose)

    for i in range(UPDOWN_CYCLES):
        up_pose = dict(center)
        down_pose = dict(center)
        up_pose["shoulder_lift.pos"] = center["shoulder_lift.pos"] + UPDOWN_DELTA
        down_pose["shoulder_lift.pos"] = center["shoulder_lift.pos"] - UPDOWN_DELTA

        move_to_pose_via_clearance(f"up cycle {i + 1}", up_pose, clearance_pose, extra_high_clearance_pose)
        move_to_pose_via_clearance(f"down cycle {i + 1}", down_pose, clearance_pose, extra_high_clearance_pose)

    move_to_pose_via_clearance("center (final)", center, clearance_pose, extra_high_clearance_pose)

    print("\n=== Environment Test Done ===")


try:
    corners = load_corners(ENV_FILE)

    robot.connect()

    print("Loaded corners from environment_corners.json")
    clearance_pose = None
    extra_high_clearance_pose = None
    if USE_CLEARANCE_WAYPOINT:
        use_clearance = input(
            "Capture CURRENT pose as a safe clearance waypoint for transit moves? [Y/n]: "
        ).strip().lower()
        if use_clearance not in {"n", "no"}:
            clearance_pose = capture_pose_manually(
                "Move robot to a safe raised transit pose, then press ENTER to capture..."
            )
            print(f"Captured clearance waypoint: {clearance_pose}")

            if USE_EXTRA_HIGH_CLEARANCE:
                use_extra = input(
                    "Capture an EXTRA-HIGH clearance waypoint (recommended if touching table)? [Y/n]: "
                ).strip().lower()
                if use_extra not in {"n", "no"}:
                    extra_high_clearance_pose = capture_pose_manually(
                        "Move robot to an even higher safe transit pose, then press ENTER to capture..."
                    )
                    print(f"Captured extra-high clearance waypoint: {extra_high_clearance_pose}")

    proceed = input("Run edges + diagonals + up/down now? [y/N]: ").strip().lower()
    if proceed in {"y", "yes"}:
        run_environment_test(
            corners,
            clearance_pose=clearance_pose,
            extra_high_clearance_pose=extra_high_clearance_pose,
        )
    else:
        print("Cancelled.")

except KeyboardInterrupt:
    print("\nStopped by user")
finally:
    try:
        robot.disconnect()
    except Exception:
        pass
