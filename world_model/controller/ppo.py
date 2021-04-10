"""This is a proximal policy  optimization  algotrithm for the gym environment CarRacing"""
import logging, os

logging.disable(logging.WARNING)
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import tensorflow as tf
from tensorflow.keras.layers import Input, Dense, Lambda
import gym
from world_model.data.car_racing import CarRacingWrapper
import numpy as np

tf.keras.backend.set_floatx('float64')

GAMMA = 0.95
UPDATE_INTERVAL = 5
ACTOR_LR = 0.0003
CRITIC_LR = 0.0003
CLIP_RATIO = 0.1
LMBDA = 0.1
EPOCHS = 5


class Actor:
    def __init__(self, state_dim, action_dim, action_bound, std_bound):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.action_bound = action_bound
        self.std_bound = std_bound
        self.model = self.create_model()
        self.opt = tf.keras.optimizers.Adam(ACTOR_LR)

    def get_action(self, state, action_only=False):
        state = np.reshape(state, [1, self.state_dim])
        mu, std = self.model.predict(state)
        action = np.random.normal(mu[0], std[0], size=self.action_dim)
        action = np.clip(action, self.action_bound[0], self.action_bound[1])
        if action_only:
            return action
        else:
            log_policy = self.log_pdf(mu, std, action)
            return log_policy, action

    def log_pdf(self, mu, std, action):
        std = tf.clip_by_value(std, self.std_bound[0], self.std_bound[1])
        var = std ** 2
        log_policy_pdf = -0.5 * (action - mu) ** 2 / \
            var - 0.5 * tf.math.log(var * 2 * np.pi)
        return tf.reduce_sum(log_policy_pdf, 1, keepdims=True)

    def create_model(self):
        init = tf.keras.initializers.Orthogonal()
        state_input = Input((self.state_dim,))
        dense_1 = Dense(32, activation='relu', kernel_initializer=init)(state_input)
        dense_2 = Dense(32, activation='relu', kernel_initializer=init)(dense_1)
        out_mu = Dense(self.action_dim, activation='tanh')(dense_2)
        #mu_output = Lambda(lambda x: x * self.action_bound)(out_mu)
        std_output = Dense(self.action_dim, activation='softplus')(dense_2)
        return tf.keras.models.Model(state_input, [out_mu, std_output])

    def compute_loss(self, log_old_policy, log_new_policy, actions, gaes):
        ratio = tf.exp(log_new_policy - tf.stop_gradient(log_old_policy))
        gaes = tf.stop_gradient(gaes)
        clipped_ratio = tf.clip_by_value(
            ratio, 1.0-CLIP_RATIO, 1.0+CLIP_RATIO)
        surrogate = -tf.minimum(ratio * gaes, clipped_ratio * gaes)
        return tf.reduce_mean(surrogate)

    def train(self, log_old_policy, states, actions, gaes):
        with tf.GradientTape() as tape:
            mu, std = self.model(states, training=True)
            log_new_policy = self.log_pdf(mu, std, actions)
            loss = self.compute_loss(
                log_old_policy, log_new_policy, actions, gaes)
        grads = tape.gradient(loss, self.model.trainable_variables)
        self.opt.apply_gradients(zip(grads, self.model.trainable_variables))
        return loss


class Critic:
    def __init__(self, state_dim):
        self.state_dim = state_dim
        self.model = self.create_model()
        self.opt = tf.keras.optimizers.Adam(CRITIC_LR)

    def create_model(self):
        init = tf.keras.initializers.Orthogonal()
        return tf.keras.Sequential([
            Input((self.state_dim,)),
            Dense(32, activation='relu', kernel_initializer=init),
            Dense(32, activation='relu', kernel_initializer=init),
            Dense(1, activation='linear')
        ])

    def compute_loss(self, v_pred, td_targets):
        mse = tf.keras.losses.MeanSquaredError()
        return mse(td_targets, v_pred)

    def train(self, states, td_targets):
        with tf.GradientTape() as tape:
            v_pred = self.model(states, training=True)
            assert v_pred.shape == td_targets.shape
            loss = self.compute_loss(v_pred, tf.stop_gradient(td_targets))
        grads = tape.gradient(loss, self.model.trainable_variables)
        self.opt.apply_gradients(zip(grads, self.model.trainable_variables))
        return loss


class Agent:
    def __init__(self, env):
        self.env = env
        self.state_dim = 35
        self.action_dim = self.env.action_space.shape[0]
        self.action_bound = []
        self.action_bound.append(self.env.action_space.low)
        self.action_bound.append(self.env.action_space.high)
        self.std_bound = [1e-2, 1.0]

        self.actor_opt = tf.keras.optimizers.Adam(ACTOR_LR)
        self.critic_opt = tf.keras.optimizers.Adam(CRITIC_LR)
        self.actor = Actor(self.state_dim, self.action_dim,
                           self.action_bound, self.std_bound)
        self.critic = Critic(self.state_dim)

    def gae_target(self, rewards, v_values, next_v_value, done):
        n_step_targets = np.zeros_like(rewards)
        gae = np.zeros_like(rewards)
        gae_cumulative = 0
        forward_val = 0

        if not done:
            forward_val = next_v_value

        for k in reversed(range(0, len(rewards))):
            delta = rewards[k] + GAMMA * forward_val - v_values[k]
            gae_cumulative = GAMMA * LMBDA * gae_cumulative + delta
            gae[k] = gae_cumulative
            forward_val = v_values[k]
            n_step_targets[k] = gae[k] + v_values[k]
        return gae, n_step_targets

    def list_to_batch(self, list):
        batch = list[0]
        for elem in list[1:]:
            batch = np.append(batch, elem, axis=0)
        return batch

    def train_step(self):
        pass

    def train(self, max_episodes=1000):
        for ep in range(max_episodes):
            state_batch = []
            action_batch = []
            reward_batch = []
            old_policy_batch = []

            episode_reward, done = 0, False

            state = self.env.reset()

            while not done:
                log_old_policy, action = self.actor.get_action(state)

                next_state, reward, done, _ = self.env.step(action)

                state = np.reshape(state, [1, self.state_dim])
                action = np.reshape(action, [1, self.action_dim])
                next_state = np.reshape(next_state, [1, self.state_dim])
                reward = np.reshape(reward, [1, 1])
                log_old_policy = np.reshape(log_old_policy, [1, 1])

                state_batch.append(state)
                action_batch.append(action)
                reward_batch.append((reward+8)/8)
                old_policy_batch.append(log_old_policy)

                if len(state_batch) >= UPDATE_INTERVAL or done:
                    states = self.list_to_batch(state_batch)
                    actions = self.list_to_batch(action_batch)
                    rewards = self.list_to_batch(reward_batch)
                    old_policys = self.list_to_batch(old_policy_batch)

                    v_values = self.critic.model.predict(states)
                    next_v_value = self.critic.model.predict(next_state)

                    gaes, td_targets = self.gae_target(
                        rewards, v_values, next_v_value, done)

                    for epoch in range(EPOCHS):
                        actor_loss = self.actor.train(
                            old_policys, states, actions, gaes)
                        critic_loss = self.critic.train(states, td_targets)

                    state_batch = []
                    action_batch = []
                    reward_batch = []
                    old_policy_batch = []

                episode_reward += reward[0][0]
                state = next_state[0]

            print('EP{} EpisodeReward={}'.format(ep, episode_reward))
            #wandb.log({'Reward': episode_reward})

    def play(self, episodes=5, limit_steps=False, max_steps=100, render=False):
        rewards = []
        print("Playing...")

        for e in range(episodes):
            state_new = np.expand_dims(self.env.reset(), axis=0)
            reward_per_episode = []

            t = 0
            done = False
            while not done:
                if render:
                    self.env.render("human")
                state = state_new
                action = self.actor.get_action(state, action_only=True)
                state_new, reward, done, _ = self.env.step(action)
                state_new = np.expand_dims(state_new, axis=0)
                reward_per_episode.append(reward)

                if done:
                    rewards.append(np.sum(reward_per_episode))
                    break
                if limit_steps:
                    if t == max_steps - 1:
                        rewards.append(np.sum(reward_per_episode))
                        break

        print(
            f"Mean EpisodeReward= {np.mean(rewards)}"
        )

        self.env.close()


def main():
    env = CarRacingWrapper()
    agent = Agent(env)
    episodes = 3
    #agent.play(episodes=1, render=True)
    agent.train(episodes)
    agent.play(episodes=1, render=True)


if __name__ == "__main__":
    main()