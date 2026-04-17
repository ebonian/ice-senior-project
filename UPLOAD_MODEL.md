# Uploading a Trained Model to the Model Service

This guide explains how to promote a trained model from the research repo into the production model service (`model/`).

## Compatible Architectures

| Architecture | Training script | Compatible |
| ------------ | --------------- | ---------- |
| DuelingDQN | `uniswap_v3_dqn_paper.py` | Yes |
| LSTM-DQN | custom DQN training | Yes |
| PPO (Stable Baselines3) | `uniswap_v3_ppo_paper.py` | Yes (startup file copy via metadata + artifact folder/zip) |

## Checkpoint Formats

For DQN/LSTM strategies, the model service expects a `.pth` file containing either:

- A full training checkpoint dict with a `q_network` key (as produced by DQN training scripts)
- A raw `state_dict` matching the DuelingDQN or LSTMDuelingDQN layer names

### DQN layer names (DuelingDQN)
```
feature_layer.0.weight, feature_layer.0.bias,
feature_layer.2.weight, feature_layer.2.bias,
value_stream.0.weight, value_stream.0.bias,
value_stream.2.weight, value_stream.2.bias,
advantage_stream.0.weight, advantage_stream.0.bias,
advantage_stream.2.weight, advantage_stream.2.bias
```

### Metadata JSON

Each `.pth` file needs a matching `.json` file with the same name:

**DQN:**
```json
{
  "architecture": "dqn",
  "state_dim": 38,
  "action_dim": 7,
  "hidden_dims": [128, 128]
}
```

**LSTM-DQN:**
```json
{
  "architecture": "lstm_dqn",
  "state_dim": 38,
  "action_dim": 7,
  "seq_len": 24,
  "lstm_hidden": 64,
  "fc_hidden": 64
}
```

**SB3 PPO (artifact folder or zip):**
```json
{
  "architecture": "sb3_ppo",
  "state_dim": 38,
  "action_dim": 7,
  "model_path": "default"
}
```

## Method A: File Copy (before startup)

Place your model artifacts in `model/weights/`. The service auto-discovers them on startup.

```bash
# From research repo root
cp kongtrae/models/comparison_dqn_best.pth  ../model/weights/my_strategy.pth
cp kongtrae/models/my_strategy.json         ../model/weights/my_strategy.json
```

The service will log `├ my_strategy (dqn)` on startup.

To replace the default model with the simulation_13 PPO artifact:

```bash
rm -f ../model/weights/default.pth
mkdir -p ../model/weights/default
cp -r research/simulation_13/best_model_paper/best_model/. ../model/weights/default/
cat > ../model/weights/default.json <<'JSON'
{
  "architecture": "sb3_ppo",
  "state_dim": 38,
  "action_dim": 7,
  "model_path": "default"
}
JSON
```

## Method B: Upload API (hot-reload on running service)

No restart needed. The model is saved to disk and loaded into memory immediately.
This endpoint currently supports **DQN/LSTM-DQN only**.

```bash
# DQN upload
curl -X POST http://localhost:4001/models/my_strategy/upload \
  -H "Authorization: Bearer $MODEL_API_KEY" \
  -F "file=@kongtrae/models/comparison_dqn_best.pth" \
  -F "architecture=dqn" \
  -F "hidden_dims=[128, 128]"

# LSTM-DQN upload
curl -X POST http://localhost:4001/models/my_strategy/upload \
  -H "Authorization: Bearer $MODEL_API_KEY" \
  -F "file=@path/to/lstm_model.pth" \
  -F "architecture=lstm_dqn" \
  -F "seq_len=24" \
  -F "lstm_hidden=64" \
  -F "fc_hidden=64"
```

## Method C: Convert a DQN/LSTM Training Checkpoint

If your training script saves a full checkpoint (with optimizer, epsilon, etc.), extract just the weights:

```python
import torch

# Load full training checkpoint
ckpt = torch.load("comparison_dqn_best.pth", map_location="cpu", weights_only=True)

# Extract only the q_network state dict
state_dict = ckpt["q_network"]

# Save clean weights (this is what the model service loads)
torch.save(state_dict, "clean_model.pth")
```

The model service handles both formats (full checkpoint with `q_network` key, or raw state dict), so this step is optional but produces a smaller file.

## Verification

### Check health endpoint
```bash
curl http://localhost:4001/health
# {"status":"healthy","models_loaded":2}
```

### List loaded models
```bash
curl http://localhost:4001/models
# Shows all loaded strategies with architecture and load time
```

### Test inference
```bash
curl -X POST http://localhost:4001/infer/my_strategy \
  -H "Authorization: Bearer $MODEL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"has_position": false}'
```

### Quick local verification (no server needed)
```python
import torch
from app.nn.dqn import DuelingDQN

ckpt = torch.load("weights/my_strategy.pth", map_location="cpu", weights_only=True)
state_dict = ckpt["q_network"] if "q_network" in ckpt else ckpt

model = DuelingDQN(state_dim=38, action_dim=7, hidden_dims=[128, 128])
model.load_state_dict(state_dict)
model.eval()

obs = torch.randn(1, 38)
with torch.no_grad():
    q = model(obs)
print(f"Output shape: {q.shape}")  # Should be [1, 7]
print(f"Action: {q.argmax(dim=1).item()}")  # 0-6
```
