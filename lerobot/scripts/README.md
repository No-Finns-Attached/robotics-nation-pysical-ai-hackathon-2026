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

## 5) Command to start recording

repo_id is your huggingface repository id.

```bash
lerobot-record   --robot.type=so101_follower   --robot.port=/dev/ttyACM0   --robot.id=my_so101_follower   --robot.cameras="{wrist: {type: opencv, index_or_path: '/dev/video2', width: 640, height: 480, fps: 30}, external: {type: opencv, index_or_path: '/dev/video0', width: 640, height: 480, fps: 30}}"   --teleop.type=so101_leader   --teleop.port=/dev/ttyACM1   --teleop.id=my_so101_leader   --display_data=true   --dataset.repo_id=pauliusrag/test1_so101   --dataset.single_task="test1"   --dataset.num_episodes=5   --dataset.episode_time_s=30   --dataset.reset_time_s=10
```

Camera devices can be listed with LeRobot:

```bash
lerobot-find-cameras opencv
```

You can also use:

```bash
v4l2-ctl --list-devices
```

## 6) Start lerobot server

```bash
python -m lerobot.async_inference.policy_server --host=127.0.0.1 --port=8080
```

## 7) Run trained model

```bash
python -m lerobot.async_inference.robot_client \
  --server_address=xxx.xxxx.xx.xxx:xxxx \
  --robot.type=so101_follower \
  --robot.port=/dev/follower_right \
  --robot.id=follower_so101 \
  --robot.cameras="{wrist: {type: opencv, index_or_path: \"/dev/cam_wrist_right\", width: 640, height: 480, fps: 30}, external: {type: opencv, index_or_path: \"/dev/cam_overview\", width: 640, height: 480, fps: 30}}" \
  --task="dummy" \
  --policy_type=act \
  --pretrained_name_or_path=kugelblytz/test_right7_so101_act_20000steps_bs4_14000 \
  --policy_device=cuda \
  --actions_per_chunk=90 \
  --chunk_size_threshold=0.2 \
  --aggregate_fn_name=latest_only \
  --debug_visualize_queue_size=True
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

Use Macbook, Linux sucks. Don't forget to use Codex :)

- Keep `ROBOT_ID` consistent with the ID used during calibration.
- Update `PORT` values inside scripts if they differ from your machine.
- Linux examples use `/dev/ttyACM*`; on macOS it is often `/dev/tty.usbmodem*`.
- If you move scripts to a separate folder, keep related JSON files with them:
  - `environment_corners.json`
  - `joint_soft_limits.json`
  - `so101_home_pose.json`
