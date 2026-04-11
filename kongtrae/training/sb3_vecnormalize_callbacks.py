import os

from stable_baselines3.common.callbacks import BaseCallback, EvalCallback


class VecNormalizeCheckpointCallback(BaseCallback):
    """Save VecNormalize stats alongside model checkpoints."""

    def __init__(self, save_freq: int, save_path: str, name_prefix: str, verbose: int = 0):
        super().__init__(verbose=verbose)
        self.save_freq = max(int(save_freq), 1)
        self.save_path = save_path
        self.name_prefix = name_prefix

    def _init_callback(self) -> None:
        os.makedirs(self.save_path, exist_ok=True)

    def _on_step(self) -> bool:
        if self.n_calls % self.save_freq != 0:
            return True

        vec_env = self.model.get_vec_normalize_env()
        if vec_env is None:
            return True

        save_file = os.path.join(
            self.save_path,
            f"{self.name_prefix}_{self.num_timesteps}_steps_vecnormalize.pkl",
        )
        vec_env.save(save_file)
        if self.verbose > 0:
            print(f"Saved VecNormalize checkpoint to {save_file}")
        return True


class EvalCallbackWithVecNormalize(EvalCallback):
    """EvalCallback that persists best-model VecNormalize statistics."""

    def __init__(self, *args, vecnormalize_filename: str = "best_vecnormalize.pkl", **kwargs):
        super().__init__(*args, **kwargs)
        self.vecnormalize_filename = vecnormalize_filename

    def _on_step(self) -> bool:
        best_before = self.best_mean_reward
        continue_training = super()._on_step()
        improved = self.best_mean_reward > best_before
        if improved and self.best_model_save_path:
            vec_env = self.model.get_vec_normalize_env()
            if vec_env is not None:
                os.makedirs(self.best_model_save_path, exist_ok=True)
                vec_path = os.path.join(self.best_model_save_path, self.vecnormalize_filename)
                vec_env.save(vec_path)
                if self.verbose > 0:
                    print(f"Saved best VecNormalize to {vec_path}")
        return continue_training
