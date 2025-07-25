import gym
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import os
import json
from neuromodulator import modulate_reward
from train_ppo import PolicyNetwork, ValueNetwork, compute_gae

def train_emotion_mod(env_name):
    env = gym.make(env_name)
    obs_dim = env.observation_space.shape[0]
    act_dim = env.action_space.shape[0]

    policy = PolicyNetwork(obs_dim, act_dim)
    value_fn = ValueNetwork(obs_dim)
    optimizer_policy = optim.Adam(policy.parameters(), lr=3e-4)
    optimizer_value = optim.Adam(value_fn.parameters(), lr=1e-3)

    max_episodes = 100
    steps_per_update = 2048
    log_dir = f"logs/emotion_mod_{env_name}"
    os.makedirs(log_dir, exist_ok=True)

    for episode in range(max_episodes):
        states, actions, rewards, log_probs, values, masks = [], [], [], [], [], []
        state = env.reset()
        ep_reward = 0

        for _ in range(steps_per_update):
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            action, log_prob, dist = policy.get_action(state_tensor)
            value = value_fn(state_tensor)

            next_state, reward, done, _ = env.step(action.detach().numpy())

            # Apply neuromodulation to the reward
            mod_signal = torch.tensor([0.5])  # Placeholder
            reward = modulate_reward(torch.tensor([reward], dtype=torch.float32), mod_signal).item()

            ep_reward += reward

            states.append(state_tensor)
            actions.append(action)
            rewards.append(torch.tensor([reward], dtype=torch.float32))
            log_probs.append(log_prob)
            values.append(value.squeeze(0))
            masks.append(torch.tensor([1 - done], dtype=torch.float32))

            state = next_state
            if done:
                state = env.reset()

        states = torch.cat(states)
        actions = torch.cat(actions)
        old_log_probs = torch.stack(log_probs).detach()
        values = torch.stack(values).detach()
        returns = compute_gae(rewards, masks, values)
        returns = torch.tensor(returns)
        advantages = returns - values

        for _ in range(4):
            new_mean, new_std = policy(states)
            dist = torch.distributions.Normal(new_mean, new_std)
            new_log_probs = dist.log_prob(actions).sum(dim=-1)
            ratio = (new_log_probs - old_log_probs).exp()

            surr1 = ratio * advantages
            surr2 = torch.clamp(ratio, 0.8, 1.2) * advantages
            policy_loss = -torch.min(surr1, surr2).mean()
            value_loss = (returns - value_fn(states).squeeze()).pow(2).mean()

            optimizer_policy.zero_grad()
            policy_loss.backward()
            optimizer_policy.step()

            optimizer_value.zero_grad()
            value_loss.backward()
            optimizer_value.step()

        with open(f"{log_dir}/ep{episode:03d}.json", "w") as f:
            json.dump({"reward": float(ep_reward)}, f)
        print(f"[Emotion-Mod PPO] Episode {episode} | Reward: {ep_reward:.2f}")

    env.close()
