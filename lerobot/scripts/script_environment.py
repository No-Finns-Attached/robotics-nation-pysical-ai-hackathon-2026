import json
import time
from pathlib import Path

from lerobot.robots.so_follower import SO101FollowerConfig, SO101Follower

PORT = "/dev/tty.usbmodem5A460858781"
ROBOT_ID = "my_so101_follower"
OUTPUT_FILE = Path("environment_corners.json")

config = SO101FollowerConfig(
	port=PORT,
	id=ROBOT_ID,
	disable_torque_on_disconnect=False,
	max_relative_target=None,
	use_degrees=True,
)

robot = SO101Follower(config)

START_TS = time.time()
trajectory_samples = []
corners = {"1": None, "2": None, "3": None, "4": None}


def now_s() -> float:
	return time.time() - START_TS


def current_joints() -> dict[str, float]:
	obs = robot.get_observation()
	return {k: float(v) for k, v in obs.items() if k.endswith(".pos")}


def print_joints() -> None:
	joints = current_joints()
	print("\nCurrent joints:")
	for name, value in joints.items():
		print(f"  {name:<18} {value:>8.2f}")


def snapshot(event: str, note: str | None = None, corner: str | None = None) -> None:
	sample = {
		"t": round(now_s(), 3),
		"event": event,
		"joints": current_joints(),
	}
	if note:
		sample["note"] = note
	if corner:
		sample["corner"] = corner
	trajectory_samples.append(sample)


def send_joint_target(joint_name: str, target: float) -> None:
	joints = current_joints()
	if joint_name not in joints:
		raise ValueError(f"Unknown joint: {joint_name}. Available: {list(joints.keys())}")

	if joint_name == "gripper.pos":
		target = min(100.0, max(0.0, float(target)))

	sent = robot.send_action({joint_name: float(target)})
	print(f"Sent {joint_name} -> {float(sent[joint_name]):.2f}")
	snapshot("move", note=f"{joint_name} -> {float(sent[joint_name]):.2f}")


def save_corner(corner_id: str) -> None:
	if corner_id not in corners:
		raise ValueError("Corner must be one of: 1, 2, 3, 4")

	pose = current_joints()
	corners[corner_id] = pose
	snapshot("corner", corner=corner_id, note=f"Corner {corner_id} recorded")
	print(f"Corner {corner_id} recorded.")


def save_output(path: Path = OUTPUT_FILE) -> None:
	data = {
		"metadata": {
			"robot_id": ROBOT_ID,
			"port": PORT,
			"created_at_unix": time.time(),
			"duration_s": round(now_s(), 3),
		},
		"corners": corners,
		"trajectory": trajectory_samples,
	}
	with path.open("w", encoding="utf-8") as f:
		json.dump(data, f, indent=2)
	print(f"Saved environment recording to {path}")


def print_status() -> None:
	print("\nCorner status:")
	for cid in ["1", "2", "3", "4"]:
		state = "set" if corners[cid] is not None else "missing"
		print(f"  corner {cid}: {state}")
	print(f"Samples collected: {len(trajectory_samples)}")


def print_help() -> None:
	print(
		"""
Commands:
  help                        Show this help
  list                        Show current joint positions
  joints                      List available joint names
  nudge <joint> <delta>       Relative move, e.g. nudge shoulder_pan.pos 5
  set <joint> <value>         Absolute move, e.g. set shoulder_lift.pos 20
  open / close                Gripper +/- 10
  mark <1|2|3|4>              Record current pose as a corner
  status                      Show which corners are recorded
  torque off / torque on      Disable/enable torque
  record [note text]          Add manual in-between sample
  save                        Save to environment_corners.json
  done                        Save and exit
  quit / exit                 Exit without saving
"""
	)


def command_loop() -> None:
	print("Environment recorder ready. Type 'help' for commands.")
	print("Goal: move to corners 1..4 and run 'mark <id>' at each corner.")
	print("In-between points are recorded after every motion command.")
	snapshot("start", note="Session started")

	while True:
		try:
			raw = input("env> ").strip()
		except EOFError:
			break

		if not raw:
			continue

		parts = raw.split()
		cmd = parts[0].lower()

		if cmd in {"quit", "exit"}:
			break

		if cmd == "help":
			print_help()
			continue

		if cmd == "list":
			print_joints()
			continue

		if cmd == "joints":
			print("Available joints:")
			for name in current_joints().keys():
				print(f"  {name}")
			continue

		if cmd == "status":
			print_status()
			continue

		if cmd == "open":
			joints = current_joints()
			send_joint_target("gripper.pos", joints["gripper.pos"] + 10.0)
			continue

		if cmd == "close":
			joints = current_joints()
			send_joint_target("gripper.pos", joints["gripper.pos"] - 10.0)
			continue

		if cmd == "torque" and len(parts) == 2:
			mode = parts[1].lower()
			if mode == "off":
				robot.bus.disable_torque()
				print("Torque disabled.")
				snapshot("torque", note="off")
				continue
			if mode == "on":
				robot.bus.enable_torque()
				print("Torque enabled.")
				snapshot("torque", note="on")
				continue
			print("Usage: torque on|off")
			continue

		if cmd == "nudge" and len(parts) == 3:
			joint_name = parts[1]
			delta = float(parts[2])
			joints = current_joints()
			send_joint_target(joint_name, joints[joint_name] + delta)
			continue

		if cmd == "set" and len(parts) == 3:
			joint_name = parts[1]
			target = float(parts[2])
			send_joint_target(joint_name, target)
			continue

		if cmd == "mark" and len(parts) == 2:
			save_corner(parts[1])
			continue

		if cmd == "record":
			note = raw[len("record") :].strip() if len(raw) > len("record") else "manual sample"
			snapshot("manual_record", note=note or "manual sample")
			print("Recorded sample.")
			continue

		if cmd == "save":
			save_output()
			continue

		if cmd == "done":
			save_output()
			print("Done.")
			return

		print("Unknown command. Type 'help'.")


try:
	robot.connect()

	setup = input("Start with torque OFF for manual hand positioning? [y/N]: ").strip().lower()
	if setup in {"y", "yes"}:
		robot.bus.disable_torque()
		input("Move by hand, then press ENTER to enable torque...")
		robot.bus.enable_torque()

	print_joints()
	command_loop()

except KeyboardInterrupt:
	print("\nStopped by user")
finally:
	try:
		robot.disconnect()
	except Exception:
		pass
