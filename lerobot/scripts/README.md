# SO-101 Quick Startup (LeRobot)

This is a quick personal startup guide for getting the SO-101 follower/leader running and for using the custom helper scripts in this repo.

## 1) Environment Setup

```bash
conda create -y -n lerobot python=3.10
conda activate lerobot

git clone https://github.com/huggingface/lerobot.git
cd lerobot

pip install -e .
pip install -e ".[feetech]"
```

## 2) Find Ports

```bash
lerobot-find-port
```

Use the detected ports in the next commands.

## 3) Calibrate

Follower:

```bash
lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=my_so101_follower
```

Leader:

```bash
lerobot-calibrate \
  --teleop.type=so101_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.id=my_so101_leader
```

## 4) Teleoperate (leader -> follower)

```bash
lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=my_so101_follower \
  --teleop.type=so101_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.id=my_so101_leader
```

---

## Custom Python Scripts (quick overview)

- `script.py`  
  Main follower control/testing script (smooth motion, optional full-range probing, optional soft-limit auto-apply).

- `script_manual.py`  
  Interactive terminal manual control (`nudge`, `set`, `torque on/off`, `open/close`).

- `script_environment.py`  
  Record environment corners (`mark 1..4`) and in-between trajectory samples to `environment_corners.json`.

- `script_environment_test.py`  
  Playback test inside recorded environment (edges, diagonals, up/down), with clearance waypoint capture and staged transit.

- `starting_pos.py`  
  Record/reset a reusable home pose (`--record` then reset), optionally using soft limits.

## Typical Run Order

1. Run `script_environment.py` and record 4 corners.
2. Run `script_environment_test.py` and capture clearance waypoint(s).
3. Use `script_manual.py` for direct manual tweaks.
4. Use `starting_pos.py --record` to save your preferred startup pose.

## Notes

- Keep `ROBOT_ID` consistent with the ID used during calibration.
- Update `PORT` values inside scripts if they differ from your machine.
- Linux examples use `/dev/ttyACM*`; on macOS it is often `/dev/tty.usbmodem*`.
- If you move scripts to a separate folder, keep related JSON files with them:
  - `environment_corners.json`
  - `joint_soft_limits.json`
  - `so101_home_pose.json`
