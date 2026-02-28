from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

repo_id = "cl3mens/so101_cup_movement_different_start_positions"
meta = LeRobotDatasetMetadata(repo_id)

print("num_episodes:", meta.total_episodes)
print("episode_indices:", list(range(meta.total_episodes)))