#!/usr/bin/env python3
import time
import json
import argparse
from pathlib import Path
from collections import deque

from lerobot.robots.so_follower import SO101FollowerConfig, SO101Follower

# --- MUST match your setup ---
PORT = "/dev/tty.usbmodem5A460858781"
ROBOT_ID = "my_so101_follower"  # same id you used for calibration
USE_DEGREES = True

# --- Files ---
HOME_POSE_FILE = Path("so101_home_pose.json")
SOFT_LIMITS_FILE = Path("joint_soft_limits.json")  # optional, from your other script

# --- Motion / safety knobs ---
SMOOTH_DT = 0.04
ARRIVAL_TOLERANCE = 0.2
MOVE_TIMEOUT_S = 10.0

# Same idea as your script: per-step cap (degrees for arm joints, 0..100 for gripper)
MAX_RELATIVE_TARGET = 5.0
STEP_CAPS = {
    "shoulder_pan.pos": 2.0,
    "shoulder_lift.pos": 1.8,
    "elbow_flex.pos": 1.8,
    "wrist_flex.pos": 1.8,
    "wrist_roll.pos": 2.2,
    "gripper.pos": 3.0,
}

# Optional soft limits loaded from joint_soft_limits.json (same format as your script)
JOINT_SOFT_LIMITS = {
    "shoulder_pan.pos": None,
    "shoulder_lift.pos": None,
    "elbow_flex.pos": None,
    "wrist_flex.pos": None,
    "wrist_roll.pos": None,
    "gripper.pos": (0.0, 100.0),
}

# Safer move order: open gripper first, then move arm joints, then set gripper target at end.
ARM_MOVE_ORDER = [
    "gripper.pos",
    "wrist_roll.pos",
    "wrist_flex.pos",
    "elbow_flex.pos",
    "shoulder_lift.pos",
    "shoulder_pan.pos",
]

config = SO101FollowerConfig(
    port=PORT,
    id=ROBOT_ID,
    disable_torque_on_disconnect=False,
    max_relative_target=MAX_RELATIVE_TARGET,
    use_degrees=USE_DEGREES,
)

robot = SO101Follower(config)


def current_joints(robot):
    obs = robot.get_observation()
    return {k: float(v) for k, v in obs.items() if k.endswith(".pos")}


def load_soft_limits_from_file(path: Path = SOFT_LIMITS_FILE):
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: failed to read {path}: {e}")
        return

    loaded = {}
    for joint_name, limits in data.items():
        if limits is None:
            loaded[joint_name] = None
            continue
        if isinstance(limits, list) and len(limits) == 2:
            loaded[joint_name] = (float(limits[0]), float(limits[1]))

    if loaded:
        JOINT_SOFT_LIMITS.update(loaded)
        print(f"Loaded soft limits from {path}")


def clamp_target(joint_name: str, target: float):
    lim = JOINT_SOFT_LIMITS.get(joint_name)
    if lim is None:
        return float(target), False
    low, high = lim
    clamped = min(high, max(low, float(target)))
    return clamped, abs(clamped - float(target)) > 1e-9


def step_cap_for(joint_name: str):
    return float(STEP_CAPS.get(joint_name, float("inf")))


def move_joint_smooth(robot, joint_name: str, requested_target: float):
    joints = current_joints(robot)
    if joint_name not in joints:
        raise ValueError(f"Unknown joint {joint_name}. Available: {list(joints.keys())}")

    start = float(joints[joint_name])
    target, was_clamped = clamp_target(joint_name, requested_target)

    # Combine config max_relative_target with per-joint caps
    step_cap = min(float(MAX_RELATIVE_TARGET), step_cap_for(joint_name))
    if step_cap <= 0:
        step_cap = float("inf")

    deadline = time.time() + MOVE_TIMEOUT_S
    stop_reason = "arrived"

    # Simple “stalled” detection (optional)
    remaining_history = deque(maxlen=12)
    stalled_windows = 0

    while True:
        cur = current_joints(robot)[joint_name]
        remaining = target - cur

        if abs(remaining) <= ARRIVAL_TOLERANCE:
            break
        if time.time() > deadline:
            stop_reason = "timeout"
            break

        step = max(-step_cap, min(step_cap, remaining))
        robot.send_action({joint_name: cur + step})
        time.sleep(SMOOTH_DT)

        new_cur = current_joints(robot)[joint_name]
        remaining_history.append(abs(target - new_cur))
        if len(remaining_history) == remaining_history.maxlen:
            improvement = remaining_history[0] - remaining_history[-1]
            if improvement < 0.2:
                stalled_windows += 1
            else:
                stalled_windows = 0
            if stalled_windows >= 4:
                stop_reason = "limited_progress"
                break

    end = current_joints(robot)[joint_name]
    note = " [clamped]" if was_clamped else ""
    if stop_reason != "arrived":
        print(f"Warning: {stop_reason} on {joint_name}, end={end:.2f}, target={target:.2f}{note}")
    print(f"{joint_name}: {start:.2f} -> {end:.2f} (requested {requested_target:.2f}, target {target:.2f}){note}")


def load_home_pose(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    # only keep *.pos keys
    return {k: float(v) for k, v in data.items() if k.endswith(".pos")}


def save_home_pose(path: Path, pose: dict):
    path.write_text(json.dumps(pose, indent=2), encoding="utf-8")
    print(f"Saved home pose to {path}")


def reset_to_home(robot, home_pose: dict):
    # If you want, force gripper to open before moving the rest:
    if "gripper.pos" in home_pose:
        open_val = max(home_pose["gripper.pos"], 70.0)  # tweak if you prefer
        move_joint_smooth(robot, "gripper.pos", open_val)
        time.sleep(0.2)

    for joint in ARM_MOVE_ORDER:
        if joint not in home_pose:
            continue
        # skip gripper here if you already opened it; we’ll set final gripper at the end
        if joint == "gripper.pos":
            continue
        move_joint_smooth(robot, joint, home_pose[joint])
        time.sleep(0.15)

    # Finally set gripper to the desired home value
    if "gripper.pos" in home_pose:
        move_joint_smooth(robot, "gripper.pos", home_pose["gripper.pos"])


def main():
    parser = argparse.ArgumentParser(description="Record and reset SO-101 to a saved home pose.")
    parser.add_argument("--record", action="store_true", help="Record current pose to HOME_POSE_FILE and exit.")
    parser.add_argument("--pose-file", type=str, default=str(HOME_POSE_FILE), help="Path to home pose JSON.")
    args = parser.parse_args()

    pose_path = Path(args.pose_file)

    load_soft_limits_from_file()

    robot.connect()
    try:
        if args.record:
            pose = current_joints(robot)
            save_home_pose(pose_path, pose)
            print("Recorded. Run again without --record to reset to this pose.")
            return

        if not pose_path.exists():
            print(f"No pose file found at {pose_path}.")
            print("Put the arm in your desired start pose and run:")
            print(f"  python {Path(__file__).name} --record --pose-file {pose_path}")
            return

        home_pose = load_home_pose(pose_path)
        print("Current:", current_joints(robot))
        print("Target :", home_pose)
        reset_to_home(robot, home_pose)
        print("Done. Final:", current_joints(robot))

    finally:
        robot.disconnect()


if __name__ == "__main__":
    main()