import time
import json
from collections import deque
from pathlib import Path

# Newer LeRobot versions (docs on main / v0.4.x)
from lerobot.robots.so_follower import SO101FollowerConfig, SO101Follower

# If the import above fails, try older path:
# from lerobot.robots.so101_follower import SO101FollowerConfig, SO101Follower

PORT = "/dev/tty.usbmodem5A460858781"
ROBOT_ID = "my_so101_follower"  # IMPORTANT: use the same id you used for calibration
HOLD_HZ = 20
HOLD_SECONDS = 15  # set to None to hold forever until Ctrl+C
ASK_MANUAL_SETUP_EACH_RUN = True
INTER_JOINT_PAUSE_SECONDS = 1.5
ASK_FULL_RANGE_TEST_EACH_RUN = True
JOINT_TEST_DELTAS = {
    "shoulder_pan.pos": 8.0,
    "shoulder_lift.pos": 7.0,
    "elbow_flex.pos": 7.0,
    "wrist_flex.pos": 6.0,
    "wrist_roll.pos": 10.0,
    "gripper.pos": 20.0,
}
FULL_RANGE_PROBE_STEPS = {
    "shoulder_pan.pos": 4.0,
    "shoulder_lift.pos": 3.5,
    "elbow_flex.pos": 3.5,
    "wrist_flex.pos": 3.0,
    "wrist_roll.pos": 5.0,
    "gripper.pos": 10.0,
}
FULL_RANGE_MAX_STEPS_PER_DIRECTION = 24
FULL_RANGE_MIN_PROGRESS = 0.15
SMOOTH_DT = 0.04
SMOOTH_MOVE_TIMEOUT_S = 8.0
ARRIVAL_TOLERANCE = 0.2
PROGRESS_WINDOW_STEPS = 12
MIN_WINDOW_IMPROVEMENT = 0.2
MAX_STALLED_WINDOWS = 4
SOFT_LIMIT_MARGIN = 1.0
AUTO_APPLY_SOFT_LIMITS = True
SOFT_LIMITS_FILE = Path("joint_soft_limits.json")

# Script-level safety envelopes (units: degrees for arm joints, 0..100 for gripper).
# Set an entry to None to disable clamping for that joint.
JOINT_SOFT_LIMITS = {
    "shoulder_pan.pos": None,
    "shoulder_lift.pos": None,
    "elbow_flex.pos": None,
    "wrist_flex.pos": None,
    "wrist_roll.pos": None,
    "gripper.pos": (0.0, 100.0),
}

# Per-cycle smoothing cap (independent from max_relative_target safety cap).
SMOOTH_STEP_CAPS = {
    "shoulder_pan.pos": 2.0,
    "shoulder_lift.pos": 1.8,
    "elbow_flex.pos": 1.8,
    "wrist_flex.pos": 1.8,
    "wrist_roll.pos": 2.2,
    "gripper.pos": 3.0,
}

config = SO101FollowerConfig(
    port=PORT,
    id=ROBOT_ID,
    disable_torque_on_disconnect=False,  # keep servos stiff when script exits
    # Safety: cap per-step movement (small value = safer)
    max_relative_target=5.0,
    # Current source defaults to degrees mode for body joints
    # (gripper is still 0..100)
    use_degrees=True,
)

robot = SO101Follower(config)

def current_joints(robot):
    obs = robot.get_observation()
    return {k: float(v) for k, v in obs.items() if k.endswith(".pos")}


def _joint_step_limit(joint_name):
    limit = config.max_relative_target
    if limit is None:
        return None
    if isinstance(limit, dict):
        return float(limit.get(joint_name.replace(".pos", ""), float("inf")))
    return float(limit)


def _clamp_joint_target(joint_name, target_value):
    target_value = float(target_value)
    limits = JOINT_SOFT_LIMITS.get(joint_name)
    if limits is None:
        return target_value, False

    low, high = limits
    clamped = min(high, max(low, target_value))
    return clamped, abs(clamped - target_value) > 1e-9


def _smooth_step_cap(joint_name):
    cap = SMOOTH_STEP_CAPS.get(joint_name)
    if cap is None:
        return float("inf")
    return float(cap)


def _read_soft_limits_file(path: Path):
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    loaded = {}
    for joint_name, limits in data.items():
        if limits is None:
            loaded[joint_name] = None
            continue

        if not isinstance(limits, list) or len(limits) != 2:
            continue

        low, high = float(limits[0]), float(limits[1])
        loaded[joint_name] = (low, high)

    return loaded


def load_soft_limits_from_file(path: Path = SOFT_LIMITS_FILE):
    loaded = _read_soft_limits_file(path)
    if not loaded:
        return

    JOINT_SOFT_LIMITS.update(loaded)
    print(f"Loaded JOINT_SOFT_LIMITS from {path}")


def save_soft_limits_to_file(path: Path = SOFT_LIMITS_FILE):
    serializable = {}
    for joint_name, limits in JOINT_SOFT_LIMITS.items():
        if limits is None:
            serializable[joint_name] = None
        else:
            serializable[joint_name] = [float(limits[0]), float(limits[1])]

    with path.open("w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)

    print(f"Saved JOINT_SOFT_LIMITS to {path}")


def apply_discovered_soft_limits(discovered_ranges, margin=SOFT_LIMIT_MARGIN):
    applied = {}
    for joint_name, (low, high) in discovered_ranges.items():
        soft_low = low + margin
        soft_high = high - margin
        if soft_low >= soft_high:
            soft_low, soft_high = low, high

        JOINT_SOFT_LIMITS[joint_name] = (float(soft_low), float(soft_high))
        applied[joint_name] = JOINT_SOFT_LIMITS[joint_name]

    return applied


def move_joint_smooth(robot, joint_name, requested_target, pause=0.2):
    joints = current_joints(robot)
    if joint_name not in joints:
        raise ValueError(f"Unknown joint: {joint_name}. Available: {list(joints.keys())}")

    start = float(joints[joint_name])
    requested_target = float(requested_target)
    target, was_clamped = _clamp_joint_target(joint_name, requested_target)

    safety_step_limit = _joint_step_limit(joint_name)
    if safety_step_limit is None or safety_step_limit <= 0:
        safety_step_limit = float("inf")

    step_cap = min(safety_step_limit, _smooth_step_cap(joint_name))

    deadline = time.time() + SMOOTH_MOVE_TIMEOUT_S
    remaining_history = deque(maxlen=PROGRESS_WINDOW_STEPS)
    stalled_windows = 0
    stop_reason = "arrived"

    while True:
        current = current_joints(robot)[joint_name]
        remaining = target - current
        if abs(remaining) <= ARRIVAL_TOLERANCE:
            break

        if time.time() > deadline:
            stop_reason = "timeout"
            break

        step = max(-step_cap, min(step_cap, remaining))
        command = current + step
        robot.send_action({joint_name: command})
        time.sleep(SMOOTH_DT)

        latest = current_joints(robot)[joint_name]
        remaining_history.append(abs(target - latest))

        if len(remaining_history) == PROGRESS_WINDOW_STEPS:
            improvement = remaining_history[0] - remaining_history[-1]
            if improvement < MIN_WINDOW_IMPROVEMENT:
                stalled_windows += 1
            else:
                stalled_windows = 0

            if stalled_windows >= MAX_STALLED_WINDOWS:
                stop_reason = "limited_progress"
                break

    end = current_joints(robot)[joint_name]
    clamp_note = " [clamped by JOINT_SOFT_LIMITS]" if was_clamped else ""

    if stop_reason == "limited_progress":
        print(
            f"Warning: limited progress on {joint_name}; stopping at {end:.2f} "
            f"(requested {requested_target:.2f}, target {target:.2f}){clamp_note}"
        )
    elif stop_reason == "timeout":
        print(
            f"Warning: timeout on {joint_name}; stopping at {end:.2f} "
            f"(requested {requested_target:.2f}, target {target:.2f}){clamp_note}"
        )

    print(f"Moved {joint_name}: {start:.2f} -> {end:.2f} (requested {requested_target:.2f}, target {target:.2f})")
    time.sleep(pause)


def nudge_joint(robot, joint_name, delta, pause=0.4):
    joints = current_joints(robot)
    if joint_name not in joints:
        raise ValueError(f"Unknown joint: {joint_name}. Available: {list(joints.keys())}")

    requested_end = float(joints[joint_name]) + float(delta)
    move_joint_smooth(robot, joint_name, requested_end, pause=pause)


def move_joint_to(robot, joint_name, target_value, pause=0.35):
    move_joint_smooth(robot, joint_name, target_value, pause=pause)


def sweep_all_joints_bidirectional(robot, deltas):
    for joint_name, delta in deltas.items():
        joints = current_joints(robot)
        if joint_name not in joints:
            print(f"Skipping {joint_name} (not found in observation keys)")
            continue

        print(f"\nTesting {joint_name} with ±{delta}")
        nudge_joint(robot, joint_name, +delta)
        nudge_joint(robot, joint_name, -delta)
        print(f"Pause {INTER_JOINT_PAUSE_SECONDS:.1f}s before next joint...")
        time.sleep(INTER_JOINT_PAUSE_SECONDS)


def probe_joint_limit(robot, joint_name, direction, step_size):
    """Probe one side of joint travel; returns the furthest reached value."""
    reached = current_joints(robot)[joint_name]
    stalled_count = 0

    for _ in range(FULL_RANGE_MAX_STEPS_PER_DIRECTION):
        before = current_joints(robot)[joint_name]
        nudge_joint(robot, joint_name, direction * step_size, pause=0.05)
        after = current_joints(robot)[joint_name]

        if direction > 0:
            reached = max(reached, after)
        else:
            reached = min(reached, after)

        moved = abs(after - before)
        if moved < FULL_RANGE_MIN_PROGRESS:
            stalled_count += 1
        else:
            stalled_count = 0

        if stalled_count >= 3:
            break

        if joint_name == "gripper.pos" and (after <= 0.2 or after >= 99.8):
            break

    return reached


def run_full_range_test(robot, joint_steps):
    print("\nStarting FULL RANGE test (one joint at a time)...")
    print("This may take a while. Keep workspace clear.")

    discovered_ranges = {}

    for joint_name, step_size in joint_steps.items():
        joints = current_joints(robot)
        if joint_name not in joints:
            print(f"Skipping {joint_name} (not found in observation keys)")
            continue

        start = joints[joint_name]
        print(f"\n[Full range] {joint_name} (step {step_size})")

        high = probe_joint_limit(robot, joint_name, direction=+1, step_size=step_size)
        time.sleep(0.25)
        low = probe_joint_limit(robot, joint_name, direction=-1, step_size=step_size)

        move_joint_to(robot, joint_name, start, pause=0.2)
        discovered_ranges[joint_name] = (low, high)
        print(f"Discovered {joint_name}: min={low:.2f}, max={high:.2f}, start={start:.2f}")

        print(f"Pause {INTER_JOINT_PAUSE_SECONDS:.1f}s before next joint...")
        time.sleep(INTER_JOINT_PAUSE_SECONDS)

    print("\nFull range summary:")
    for joint_name, (low, high) in discovered_ranges.items():
        print(f"  {joint_name}: min={low:.2f}, max={high:.2f}, span={high - low:.2f}")

    print("\nSuggested JOINT_SOFT_LIMITS with margin:")
    for joint_name, (low, high) in discovered_ranges.items():
        soft_low = low + SOFT_LIMIT_MARGIN
        soft_high = high - SOFT_LIMIT_MARGIN
        if soft_low >= soft_high:
            soft_low, soft_high = low, high
        print(f"  {joint_name}: ({soft_low:.2f}, {soft_high:.2f})")

    if AUTO_APPLY_SOFT_LIMITS and discovered_ranges:
        print("\nAuto-applying discovered limits...")
        applied = apply_discovered_soft_limits(discovered_ranges)
        for joint_name, (low, high) in applied.items():
            print(f"  applied {joint_name}: ({low:.2f}, {high:.2f})")
        save_soft_limits_to_file()


def hold_position(robot, target, hold_seconds=15, hz=20):
    """Actively hold a target pose by repeatedly sending it."""
    period = 1.0 / hz
    t0 = time.time()
    while hold_seconds is None or (time.time() - t0) < hold_seconds:
        robot.send_action(target)
        time.sleep(period)


def maybe_manual_setup(robot):
    """Optional free-move mode for setup: torque off, then torque back on."""
    if not ASK_MANUAL_SETUP_EACH_RUN:
        return

    answer = input("Enable manual setup mode (torque OFF) so you can position by hand? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        return

    print("Torque disabled. Move the arm by hand to your desired start pose.")
    robot.bus.disable_torque()
    input("Press ENTER when done to re-enable torque and continue...")
    robot.bus.enable_torque()
    time.sleep(0.2)
    print("Torque re-enabled.")

try:
    load_soft_limits_from_file()

    robot.connect()
    maybe_manual_setup(robot)

    baseline = current_joints(robot)
    print("Current joints:", baseline)

    run_full_range = False
    if ASK_FULL_RANGE_TEST_EACH_RUN:
        answer = input("Run FULL RANGE test now? [y/N]: ").strip().lower()
        run_full_range = answer in {"y", "yes"}

    if run_full_range:
        run_full_range_test(robot, FULL_RANGE_PROBE_STEPS)
    else:
        # Test all 6 joints in both directions from live pose
        sweep_all_joints_bidirectional(robot, JOINT_TEST_DELTAS)

    final_target = current_joints(robot)
    print("Final joints:", final_target)
    print(f"Holding current pose at {HOLD_HZ}Hz for {HOLD_SECONDS} seconds...")
    # hold_position(robot, final_target, hold_seconds=HOLD_SECONDS, hz=HOLD_HZ)

except KeyboardInterrupt:
    print("Stopped by user")
finally:
    robot.disconnect()