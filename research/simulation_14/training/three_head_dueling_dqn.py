"""
Three-head dueling DQN for state-aware hedged LP decisions.

One shared trunk feeds three dueling heads:
  - cash
  - lp_in_range
  - lp_oor

The active head is selected from the first three observation features, which
encode the current decision state as a one-hot vector.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np
import torch as th
import torch.nn as nn
import torch.nn.functional as F
from gymnasium import spaces
from stable_baselines3 import DQN
from stable_baselines3.common.noise import ActionNoise
from stable_baselines3.common.policies import BasePolicy
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor, FlattenExtractor, create_mlp
from stable_baselines3.common.type_aliases import PyTorchObs, Schedule
from stable_baselines3.dqn.policies import DQNPolicy


THREE_HEAD_STATE_DIM = 3
THREE_HEAD_CASH_STATE = 0
THREE_HEAD_IN_RANGE_STATE = 1
THREE_HEAD_OOR_STATE = 2
THREE_HEAD_NUM_HEADS = 3
MASKED_Q_VALUE = -1.0e9


def build_default_state_action_masks(num_actions: int) -> np.ndarray:
    """Build default masks: cash masks last action, LP states allow all."""
    masks = np.ones((THREE_HEAD_NUM_HEADS, num_actions), dtype=np.bool_)
    masks[THREE_HEAD_CASH_STATE, -1] = False  # last slot masked for cash
    return masks


def normalize_state_action_masks(
    state_action_masks: Optional[Sequence[Sequence[bool]]],
    num_actions: Optional[int] = None,
) -> np.ndarray:
    if state_action_masks is None:
        if num_actions is None:
            raise ValueError("num_actions required when state_action_masks is None")
        return build_default_state_action_masks(num_actions)
    masks = np.asarray(state_action_masks, dtype=np.bool_)
    if masks.ndim != 2 or masks.shape[0] != THREE_HEAD_NUM_HEADS:
        raise ValueError(
            f"state_action_masks must have shape ({THREE_HEAD_NUM_HEADS}, num_actions), "
            f"got {masks.shape}"
        )
    if not np.all(masks.any(axis=1)):
        raise ValueError("Each three-head state must have at least one valid action")
    return masks


def infer_three_head_state_indices(observation: np.ndarray) -> np.ndarray:
    obs = np.asarray(observation, dtype=np.float32)
    if obs.ndim == 1:
        obs = obs.reshape(1, -1)
    if obs.shape[1] < THREE_HEAD_STATE_DIM:
        raise ValueError(
            f"Three-head observation must have at least {THREE_HEAD_STATE_DIM} features, "
            f"got shape {obs.shape}"
        )
    return np.argmax(obs[:, :THREE_HEAD_STATE_DIM], axis=1).astype(np.int64)


def sample_valid_three_head_actions(
    observation: np.ndarray,
    state_action_masks: Optional[Sequence[Sequence[bool]]] = None,
    num_actions: Optional[int] = None,
) -> np.ndarray:
    masks = normalize_state_action_masks(state_action_masks, num_actions=num_actions)
    state_indices = infer_three_head_state_indices(observation)
    actions = []
    for state_idx in state_indices:
        valid_actions = np.flatnonzero(masks[int(state_idx)])
        actions.append(int(np.random.choice(valid_actions)))
    return np.asarray(actions, dtype=np.int64)


class ThreeHeadDuelingQNetwork(BasePolicy):
    """
    Shared-trunk, state-routed dueling Q-network.
    """

    action_space: spaces.Discrete

    def __init__(
        self,
        observation_space: spaces.Space,
        action_space: spaces.Discrete,
        features_extractor: BaseFeaturesExtractor,
        features_dim: int,
        net_arch: Optional[list[int]] = None,
        activation_fn: type[nn.Module] = nn.ReLU,
        normalize_images: bool = True,
        state_action_masks: Optional[Sequence[Sequence[bool]]] = None,
    ) -> None:
        super().__init__(
            observation_space,
            action_space,
            features_extractor=features_extractor,
            normalize_images=normalize_images,
        )

        if net_arch is None:
            net_arch = [64, 64]

        self.net_arch = list(net_arch)
        self.activation_fn = activation_fn
        self.features_dim = int(features_dim)
        self.action_dim = int(self.action_space.n)
        self.state_action_masks_np = normalize_state_action_masks(
            state_action_masks, num_actions=self.action_dim
        )
        self.register_buffer(
            "state_action_masks",
            th.as_tensor(self.state_action_masks_np, dtype=th.bool),
        )

        shared_arch = self.net_arch[:-1]
        latent_dim = self.net_arch[-1] if self.net_arch else self.features_dim
        shared_layers = create_mlp(self.features_dim, latent_dim, shared_arch, self.activation_fn)
        self.shared_net = nn.Sequential(*shared_layers) if shared_layers else nn.Identity()
        self.advantage_nets = nn.ModuleList(
            [
                nn.Sequential(*create_mlp(latent_dim, self.action_dim, [], self.activation_fn))
                for _ in range(THREE_HEAD_NUM_HEADS)
            ]
        )
        self.value_nets = nn.ModuleList(
            [
                nn.Sequential(*create_mlp(latent_dim, 1, [], self.activation_fn))
                for _ in range(THREE_HEAD_NUM_HEADS)
            ]
        )

    def _state_indices_from_features(self, features: th.Tensor) -> th.Tensor:
        if features.shape[1] < THREE_HEAD_STATE_DIM:
            raise RuntimeError(
                f"Three-head observations must begin with a {THREE_HEAD_STATE_DIM}-way state one-hot"
            )
        return th.argmax(features[:, :THREE_HEAD_STATE_DIM], dim=1)

    def _mask_head(self, q_values: th.Tensor, head_idx: int) -> th.Tensor:
        masked = q_values.clone()
        invalid_mask = ~self.state_action_masks[head_idx]
        masked[:, invalid_mask] = MASKED_Q_VALUE
        return masked

    def forward(self, obs: PyTorchObs) -> th.Tensor:
        features = self.extract_features(obs, self.features_extractor)
        latent = self.shared_net(features)
        state_indices = self._state_indices_from_features(features)

        head_q_values = []
        for head_idx in range(THREE_HEAD_NUM_HEADS):
            advantages = self.advantage_nets[head_idx](latent)
            values = self.value_nets[head_idx](latent)
            q_values = values + (advantages - advantages.mean(dim=1, keepdim=True))
            q_values = self._mask_head(q_values, head_idx)
            head_q_values.append(q_values)

        stacked_q = th.stack(head_q_values, dim=1)
        batch_idx = th.arange(stacked_q.shape[0], device=stacked_q.device)
        return stacked_q[batch_idx, state_indices]

    def _predict(self, observation: PyTorchObs, deterministic: bool = True) -> th.Tensor:
        q_values = self(observation)
        return q_values.argmax(dim=1).reshape(-1)

    def _get_constructor_parameters(self) -> dict[str, Any]:
        data = super()._get_constructor_parameters()
        data.update(
            dict(
                net_arch=self.net_arch,
                features_dim=self.features_dim,
                activation_fn=self.activation_fn,
                features_extractor=self.features_extractor,
                state_action_masks=self.state_action_masks_np.tolist(),
            )
        )
        return data


class ThreeHeadDuelingDQNPolicy(DQNPolicy):
    """
    DQN policy using the three-head dueling Q-network.
    """

    q_net: ThreeHeadDuelingQNetwork
    q_net_target: ThreeHeadDuelingQNetwork

    def __init__(
        self,
        observation_space: spaces.Space,
        action_space: spaces.Discrete,
        lr_schedule: Schedule,
        net_arch: Optional[list[int]] = None,
        activation_fn: type[nn.Module] = nn.ReLU,
        features_extractor_class: type[BaseFeaturesExtractor] = FlattenExtractor,
        features_extractor_kwargs: Optional[dict[str, Any]] = None,
        normalize_images: bool = True,
        optimizer_class: type[th.optim.Optimizer] = th.optim.Adam,
        optimizer_kwargs: Optional[dict[str, Any]] = None,
        state_action_masks: Optional[Sequence[Sequence[bool]]] = None,
    ) -> None:
        self.state_action_masks = normalize_state_action_masks(
            state_action_masks, num_actions=int(action_space.n)
        )
        super().__init__(
            observation_space=observation_space,
            action_space=action_space,
            lr_schedule=lr_schedule,
            net_arch=net_arch,
            activation_fn=activation_fn,
            features_extractor_class=features_extractor_class,
            features_extractor_kwargs=features_extractor_kwargs,
            normalize_images=normalize_images,
            optimizer_class=optimizer_class,
            optimizer_kwargs=optimizer_kwargs,
        )

    def make_q_net(self) -> ThreeHeadDuelingQNetwork:
        net_args = self._update_features_extractor(self.net_args, features_extractor=None)
        net_args["state_action_masks"] = self.state_action_masks.tolist()
        return ThreeHeadDuelingQNetwork(**net_args).to(self.device)


class ThreeHeadDuelingDQN(DQN):
    """
    Stable-Baselines3 DQN with a state-aware three-head dueling policy.
    """

    policy_aliases = {
        "MlpPolicy": ThreeHeadDuelingDQNPolicy,
        "CnnPolicy": ThreeHeadDuelingDQNPolicy,
        "MultiInputPolicy": ThreeHeadDuelingDQNPolicy,
    }

    def _state_action_masks(self) -> np.ndarray:
        return self.policy.q_net.state_action_masks_np

    def _sample_valid_actions_for_obs(self, observation: np.ndarray) -> np.ndarray:
        return sample_valid_three_head_actions(
            observation,
            state_action_masks=self._state_action_masks(),
        )

    def predict(
        self,
        observation,
        state: Optional[tuple[np.ndarray, ...]] = None,
        episode_start: Optional[np.ndarray] = None,
        deterministic: bool = False,
    ) -> tuple[np.ndarray, Optional[tuple[np.ndarray, ...]]]:
        if not deterministic and np.random.rand() < self.exploration_rate:
            if self.policy.is_vectorized_observation(observation):
                action = self._sample_valid_actions_for_obs(observation)
            else:
                action = self._sample_valid_actions_for_obs(np.asarray(observation))[0]
                action = np.asarray(action)
            return action, state
        return super().predict(
            observation=observation,
            state=state,
            episode_start=episode_start,
            deterministic=deterministic,
        )

    def _sample_action(
        self,
        learning_starts: int,
        action_noise: Optional[ActionNoise] = None,
        n_envs: int = 1,
    ) -> tuple[np.ndarray, np.ndarray]:
        if self.num_timesteps < learning_starts and not (self.use_sde and self.use_sde_at_warmup):
            if self._last_obs is None:
                unscaled_action = np.array([self.action_space.sample() for _ in range(n_envs)])
            else:
                unscaled_action = self._sample_valid_actions_for_obs(self._last_obs)
        else:
            assert self._last_obs is not None, "self._last_obs was not set"
            unscaled_action, _ = self.predict(self._last_obs, deterministic=False)

        buffer_action = unscaled_action
        action = buffer_action
        return action, buffer_action


class ThreeHeadDoubleDuelingDQN(ThreeHeadDuelingDQN):
    """
    Three-head dueling DQN with Double-DQN target selection.
    """

    def train(self, gradient_steps: int, batch_size: int = 100) -> None:
        self.policy.set_training_mode(True)
        self._update_learning_rate(self.policy.optimizer)

        losses = []
        for _ in range(gradient_steps):
            replay_data = self.replay_buffer.sample(
                batch_size, env=self._vec_normalize_env
            )  # type: ignore[union-attr]
            discounts = (
                replay_data.discounts
                if replay_data.discounts is not None
                else self.gamma
            )

            with th.no_grad():
                next_online_q = self.q_net(replay_data.next_observations)
                next_actions = next_online_q.argmax(dim=1, keepdim=True)
                next_target_q = self.q_net_target(replay_data.next_observations)
                next_q_values = th.gather(next_target_q, dim=1, index=next_actions)
                target_q_values = (
                    replay_data.rewards
                    + (1 - replay_data.dones) * discounts * next_q_values
                )

            current_q_values = self.q_net(replay_data.observations)
            current_q_values = th.gather(
                current_q_values, dim=1, index=replay_data.actions.long()
            )

            loss = F.smooth_l1_loss(current_q_values, target_q_values)
            losses.append(loss.item())

            self.policy.optimizer.zero_grad()
            loss.backward()
            th.nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
            self.policy.optimizer.step()

        self._n_updates += gradient_steps
        self.logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        self.logger.record("train/loss", np.mean(losses))
