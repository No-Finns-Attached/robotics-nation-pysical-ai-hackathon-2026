import time

from lerobot.robots.so_follower import SO101FollowerConfig, SO101Follower

PORT = "/dev/tty.usbmodem5A460858781"
ROBOT_ID = "my_so101_follower"

config = SO101FollowerConfig(
	port=PORT,
	id=ROBOT_ID,
	disable_torque_on_disconnect=False,
	max_relative_target=None,
	use_degrees=True,
)

robot = SO101Follower(config)


def current_joints():
	obs = robot.get_observation()
	return {k: float(v) for k, v in obs.items() if k.endswith(".pos")}


def print_joints():
	joints = current_joints()
	print("\nCurrent joints:")
	for joint, value in joints.items():
		print(f"  {joint:<18} {value:>8.2f}")


def print_help():
	print(
		"""
Commands:
  help                   Show this help
  list                   Show current joint positions
  joints                 Show available joint names
  nudge <joint> <delta>  Relative move, e.g. nudge shoulder_pan.pos 5
  set <joint> <value>    Absolute move, e.g. set gripper.pos 45
  open                   Gripper +10
  close                  Gripper -10
  torque off             Disable torque (free move by hand)
  torque on              Enable torque
  sleep <sec>            Pause
  q / quit / exit        Quit
"""
	)


def validate_joint(joint_name):
	joints = current_joints()
	if joint_name not in joints:
		raise ValueError(f"Unknown joint: {joint_name}. Available: {list(joints.keys())}")
	return joints


def send_joint_target(joint_name, target):
	if joint_name == "gripper.pos":
		target = min(100.0, max(0.0, float(target)))

	sent = robot.send_action({joint_name: float(target)})
	print(f"Sent {joint_name} -> {float(sent[joint_name]):.2f}")


def command_loop():
	print("Manual control ready. Type 'help' for commands.")
	print_joints()

	while True:
		try:
			raw = input("manual> ").strip()
		except EOFError:
			break

		if not raw:
			continue

		parts = raw.split()
		cmd = parts[0].lower()

		if cmd in {"q", "quit", "exit"}:
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

		if cmd == "open":
			joints = validate_joint("gripper.pos")
			send_joint_target("gripper.pos", joints["gripper.pos"] + 10.0)
			continue

		if cmd == "close":
			joints = validate_joint("gripper.pos")
			send_joint_target("gripper.pos", joints["gripper.pos"] - 10.0)
			continue

		if cmd == "torque" and len(parts) == 2:
			mode = parts[1].lower()
			if mode == "off":
				robot.bus.disable_torque()
				print("Torque disabled.")
				continue
			if mode == "on":
				robot.bus.enable_torque()
				print("Torque enabled.")
				continue
			print("Usage: torque on|off")
			continue

		if cmd == "sleep" and len(parts) == 2:
			time.sleep(float(parts[1]))
			continue

		if cmd == "nudge" and len(parts) == 3:
			joint_name = parts[1]
			delta = float(parts[2])
			joints = validate_joint(joint_name)
			send_joint_target(joint_name, joints[joint_name] + delta)
			continue

		if cmd == "set" and len(parts) == 3:
			joint_name = parts[1]
			target = float(parts[2])
			validate_joint(joint_name)
			send_joint_target(joint_name, target)
			continue

		print("Unknown command. Type 'help'.")


try:
	robot.connect()

	free_move = input("Start with torque OFF for manual placement? [y/N]: ").strip().lower()
	if free_move in {"y", "yes"}:
		robot.bus.disable_torque()
		input("Move arm by hand, then press ENTER to enable torque...")
		robot.bus.enable_torque()

	command_loop()

except KeyboardInterrupt:
	print("\nStopped by user")
finally:
	robot.disconnect()
