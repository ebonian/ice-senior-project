"""
Double DQN + dueling-network variants used by Kongtrae.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import torch as th
import torch.nn as nn
import torch.nn.functional as F
from gymnasium import spaces
from stable_baselines3 import DQN
from stable_baselines3.common.policies import BasePolicy
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor, FlattenExtractor, create_mlp
from stable_baselines3.common.type_aliases import PyTorchObs, Schedule
from stable_baselines3.dqn.policies import DQNPolicy


class DuelingQNetwork(BasePolicy):
    """Dueling Q-network with a shared trunk and separate value/advantage heads."""

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
        self.features_dim = features_dim
        self.action_dim = int(self.action_space.n)

        shared_arch = self.net_arch[:-1]
        latent_dim = self.net_arch[-1] if self.net_arch else self.features_dim
        shared_layers = create_mlp(self.features_dim, latent_dim, shared_arch, self.activation_fn)
        self.shared_net = nn.Sequential(*shared_layers) if shared_layers else nn.Identity()
        self.advantage_net = nn.Sequential(*create_mlp(latent_dim, self.action_dim, [], self.activation_fn))
        self.value_net = nn.Sequential(*create_mlp(latent_dim, 1, [], self.activation_fn))

    def forward(self, obs: PyTorchObs) -> th.Tensor:
        features = self.extract_features(obs, self.features_extractor)
        latent = self.shared_net(features)
        advantages = self.advantage_net(latent)
        values = self.value_net(latent)
        return values + (advantages - advantages.mean(dim=1, keepdim=True))

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
            )
        )
        return data


class DuelingDQNPolicy(DQNPolicy):
    """DQN policy that uses the dueling Q-network architecture."""

    q_net: DuelingQNetwork
    q_net_target: DuelingQNetwork

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
    ) -> None:
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

    def make_q_net(self) -> DuelingQNetwork:
        net_args = self._update_features_extractor(self.net_args, features_extractor=None)
        return DuelingQNetwork(**net_args).to(self.device)


class DuelingDQN(DQN):
    """Stable-Baselines3 DQN with a dueling-network head."""

    policy_aliases = {
        "MlpPolicy": DuelingDQNPolicy,
        "CnnPolicy": DuelingDQNPolicy,
        "MultiInputPolicy": DuelingDQNPolicy,
    }


class DoubleDuelingDQN(DQN):
    """
    Stable-Baselines3 DQN with Double-DQN target selection and a dueling head.
    """

    policy_aliases = {
        "MlpPolicy": DuelingDQNPolicy,
        "CnnPolicy": DuelingDQNPolicy,
        "MultiInputPolicy": DuelingDQNPolicy,
    }

    def train(self, gradient_steps: int, batch_size: int = 100) -> None:
        self.policy.set_training_mode(True)
        self._update_learning_rate(self.policy.optimizer)

        losses = []
        for _ in range(gradient_steps):
            replay_data = self.replay_buffer.sample(batch_size, env=self._vec_normalize_env)  # type: ignore[union-attr]
            discounts = replay_data.discounts if replay_data.discounts is not None else self.gamma

            with th.no_grad():
                next_online_q = self.q_net(replay_data.next_observations)
                next_actions = next_online_q.argmax(dim=1, keepdim=True)
                next_target_q = self.q_net_target(replay_data.next_observations)
                next_q_values = th.gather(next_target_q, dim=1, index=next_actions)
                target_q_values = replay_data.rewards + (1 - replay_data.dones) * discounts * next_q_values

            current_q_values = self.q_net(replay_data.observations)
            current_q_values = th.gather(current_q_values, dim=1, index=replay_data.actions.long())

            loss = F.smooth_l1_loss(current_q_values, target_q_values)
            losses.append(loss.item())

            self.policy.optimizer.zero_grad()
            loss.backward()
            th.nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
            self.policy.optimizer.step()

        self._n_updates += gradient_steps
        self.logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        self.logger.record("train/loss", np.mean(losses))
