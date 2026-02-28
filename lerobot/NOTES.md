# LeRobot SO-101 Notes (macOS)

Short, cleaned command cheatsheet from today.

---

## 1) One-time setup

```bash
# install + login for Hugging Face
pip install huggingface_hub
huggingface-cli login
```

Recommended before any run:
- Activate the environment with `lerobot` installed.
- Confirm serial devices and cameras are connected.

---

## 2) Hardware discovery (mac)

### 2.1 List cameras + indices

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

### 2.2 Camera details / unique id

```bash
system_profiler SPCameraDataType
```

### 2.3 Optional: stable serial port names via symlinks

```bash
sudo mkdir -p /usr/local/var/lerobot

# adjust device paths to your current /dev/cu.* values
sudo ln -sf /dev/cu.usbmodem5AAF2628661 /usr/local/var/lerobot/usbserial_lerobot_follower
sudo ln -sf /dev/cu.usbmodem5AAF2631321 /usr/local/var/lerobot/usbserial_lerobot_leader

ls -l /usr/local/var/lerobot/
```

---

## 3) Quick teleop sanity check (single arm)

```bash
lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port=/usr/local/var/lerobot/usbserial_lerobot_follower \
  --robot.id=my_so101_follower \
  --teleop.type=so101_leader \
  --teleop.port=/usr/local/var/lerobot/usbserial_lerobot_leader \
  --teleop.id=my_so101_leader
```

---

## 4) Recording datasets

### 4.1 Single follower + single leader (2 cameras)

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/usr/local/var/lerobot/usbserial_lerobot_follower \
  --robot.id=my_so101_follower \
  --robot.cameras='{"cam1":{"type":"opencv","index_or_path":0,"width":640,"height":480,"fps":30},"cam2":{"type":"opencv","index_or_path":1,"width":640,"height":480,"fps":30}}' \
  --teleop.type=so101_leader \
  --teleop.port=/usr/local/var/lerobot/usbserial_lerobot_leader \
  --teleop.id=my_so101_leader \
  --display_data=true \
  --dataset.repo_id=cl3mens/so101_cup_movement \
  --dataset.single_task="Cup movement teleop" \
  --dataset.num_episodes=5 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=10
```

Resume recording into an existing local dataset:

```bash
lerobot-record ... --resume=true
```

### 4.2 Bi-arm (2 leaders + 2 followers)

```bash
lerobot-record \
  --robot.type=bi_so_follower \
  --robot.left_arm_config.port=/usr/local/var/lerobot/usbserial_lerobot_follower \
  --robot.right_arm_config.port=/dev/cu.usbmodem5AAF2632181 \
  --robot.id=my_bi_so101_follower \
  --robot.left_arm_config.cameras='{"follower_left":{"type":"opencv","index_or_path":3,"width":640,"height":480,"fps":30},"left_overview":{"type":"opencv","index_or_path":4,"width":1280,"height":720,"fps":30}}' \
  --robot.right_arm_config.cameras='{"follower_right":{"type":"opencv","index_or_path":1,"width":640,"height":480,"fps":30},"right_overview":{"type":"opencv","index_or_path":2,"width":640,"height":480,"fps":30}}' \
  --teleop.type=bi_so_leader \
  --teleop.left_arm_config.port=/usr/local/var/lerobot/usbserial_lerobot_leader \
  --teleop.right_arm_config.port=/dev/cu.usbmodem5A460849961 \
  --teleop.id=my_bi_so101_leader \
  --display_data=true \
  --dataset.repo_id=cl3mens/so101_fill_cup_unified \
  --dataset.single_task="Cup movement teleop" \
  --dataset.num_episodes=5 \
  --dataset.episode_time_s=15 \
  --dataset.reset_time_s=7
```

---

## 5) Dataset management

### 5.1 Local cache path (mac)

```bash
~/.cache/huggingface/lerobot/
```

Remove a local cached dataset copy:

```bash
rm -rf ~/.cache/huggingface/lerobot/cl3mens/so101_cup_movement
```

### 5.2 Inspect episodes

```bash
python see_episodes.py
```

Get dataset info:

```bash
lerobot-edit-dataset \
  --repo_id <your_user>/<your_dataset> \
  --operation.type info
```

Delete bad episode(s):

```bash
lerobot-edit-dataset \
  --repo_id cl3mens/so101_cup_movement \
  --operation.type delete_episodes \
  --operation.episode_indices "[3]"
```

Visualize one episode:

```bash
lerobot-dataset-viz --repo-id cl3mens/so101_fill_cup_unified --episode-index 4
```

Upload local dataset folder to Hugging Face:

```bash
huggingface-cli upload cl3mens/so101_cup_movement_different_start_positions . . --repo-type dataset
```

---

## 6) Async inference

### 6.1 Start local policy server

```bash
python -m lerobot.async_inference.policy_server \
  --host=127.0.0.1 \
  --port=8080
```

### 6.2 Robot client (bi-arm, local server)

```bash
python -m lerobot.async_inference.robot_client \
  --server_address=127.0.0.1:8080 \
  --robot.type=bi_so_follower \
  --robot.left_arm_config.port=/usr/local/var/lerobot/usbserial_lerobot_follower \
  --robot.right_arm_config.port=/dev/cu.usbmodem5AAF2632181 \
  --robot.id=my_bi_so101_follower \
  --robot.left_arm_config.cameras='{"follower_left":{"type":"opencv","index_or_path":3,"width":640,"height":480,"fps":30},"left_overview":{"type":"opencv","index_or_path":4,"width":1280,"height":720,"fps":30}}' \
  --robot.right_arm_config.cameras='{"follower_right":{"type":"opencv","index_or_path":1,"width":640,"height":480,"fps":30},"right_overview":{"type":"opencv","index_or_path":2,"width":640,"height":480,"fps":30}}' \
  --task="Cup movement teleop" \
  --policy_type=act \
  --pretrained_name_or_path=kugelblytz/so101_fill_cup_unified_act_10000steps_bs4_7000 \
  --policy_device=mps \
  --client_device=cpu \
  --actions_per_chunk=100 \
  --chunk_size_threshold=0.2 \
  --aggregate_fn_name=latest_only \
  --fps=30 \
  --debug_visualize_queue_size=true
```

### 6.3 Robot client (single arm, remote server)

Base command:

```bash
python -m lerobot.async_inference.robot_client \
  --server_address=135.181.63.162:8080 \
  --robot.type=so101_follower \
  --robot.port=/usr/local/var/lerobot/usbserial_lerobot_follower \
  --robot.id=my_so101_follower \
  --robot.cameras='{"cam1":{"type":"opencv","index_or_path":0,"width":640,"height":480,"fps":30},"cam2":{"type":"opencv","index_or_path":1,"width":640,"height":480,"fps":30}}' \
  --task="Cup movement teleop" \
  --policy_type=act \
  --pretrained_name_or_path=<MODEL_NAME> \
  --policy_device=cuda \
  --client_device=cpu \
  --fps=30 \
  --actions_per_chunk=<50_or_100> \
  --chunk_size_threshold=<0.2_or_0.5> \
  --aggregate_fn_name=<latest_only_or_weighted_average> \
  --debug_visualize_queue_size=true
```

Notes:
- First run can be slow (model download).
- Your tested combinations were mainly:
  - `actions_per_chunk=100`, `chunk_size_threshold=0.2`, `aggregate_fn_name=latest_only`
  - `actions_per_chunk=50`, `chunk_size_threshold=0.5`, `aggregate_fn_name=weighted_average`

---

## 7) Quick preflight checklist (before record/inference)

1. Activate environment with `lerobot`.
2. Confirm camera indices (`ffmpeg -f avfoundation -list_devices true -i ""`).
3. Confirm serial ports/symlinks (`ls -l /usr/local/var/lerobot/`).
4. Verify robot/camera config matches current hardware.
5. Start with short runs (`num_episodes=1` or short episode time) before full sessions.
