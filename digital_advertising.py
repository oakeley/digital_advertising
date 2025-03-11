#!/usr/bin/env python
# coding: utf-8

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import pandas as pd
import random
from typing import Optional
from torchrl.envs import EnvBase
from torchrl.data import OneHot, Bounded, Unbounded, Binary, Composite
from torchrl.data.replay_buffers import TensorDictReplayBuffer
from torchrl.objectives import DQNLoss
from torchrl.collectors import SyncDataCollector
from torchrl.modules import EGreedyModule, MLP, QValueModule
from tensordict import TensorDict, TensorDictBase
from tensordict.nn import TensorDictModule, TensorDictSequential






# Generate Realistic Synthetic Data. This is coming from Ilja's code
# Platzierung:
#    - Organisch: Erscheint aufgrund des Suchalgorithmus, ohne Bezahlung.
#    - Paid: Wird aufgrund einer Werbekampagne oder bezahlten Platzierung angezeigt.
# Kosten:
#    - Organisch: Es fallen in der Regel keine direkten Kosten pro Klick oder Impression an.
#    - Paid: Werbetreibende zahlen oft pro Klick (CPC) oder pro Impression (CPM = pro Sichtkontakt, unabhängig ob jemand klickt oder nicht).
def generate_synthetic_data(num_samples=1000):
    data = {
        "keyword": [f"Keyword_{i}" for i in range(num_samples)],        # Eindeutiger Name oder Identifier für das Keyword
        "competitiveness": np.random.uniform(0, 1, num_samples),        # Wettbewerbsfähigkeit des Keywords (Wert zwischen 0 und 1). Je mehr Leute das Keyword wollen, desto näher bei 1 und somit desto teurer.
        "difficulty_score": np.random.uniform(0, 1, num_samples),       # Schwierigkeitsgrad des Keywords organisch gute Platzierung zu erreichen (Wert zwischen 0 und 1). 1 = mehr Aufwand und Optimierung nötig.
        "organic_rank": np.random.randint(1, 11, num_samples),          # Organischer Rang, z.B. Position in Suchergebnissen (1 bis 10)
        "organic_clicks": np.random.randint(50, 5000, num_samples),     # Anzahl der Klicks auf organische Suchergebnisse
        "organic_ctr": np.random.uniform(0.01, 0.3, num_samples),       # Klickrate (CTR) für organische Suchergebnisse
        "paid_clicks": np.random.randint(10, 3000, num_samples),        # Anzahl der Klicks auf bezahlte Anzeigen
        "paid_ctr": np.random.uniform(0.01, 0.25, num_samples),         # Klickrate (CTR) für bezahlte Anzeigen
        "ad_spend": np.random.uniform(10, 10000, num_samples),          # Werbebudget bzw. Ausgaben für Anzeigen
        "ad_conversions": np.random.randint(0, 500, num_samples),       # Anzahl der Conversions (Erfolge) von Anzeigen
        "ad_roas": np.random.uniform(0.5, 5, num_samples),              # Return on Ad Spend (ROAS) für Anzeigen, wobei Werte < 1 Verlust anzeigen
        "conversion_rate": np.random.uniform(0.01, 0.3, num_samples),   # Conversion-Rate (Prozentsatz der Besucher, die konvertieren)
        "cost_per_click": np.random.uniform(0.1, 10, num_samples),      # Kosten pro Klick (CPC)
        "cost_per_acquisition": np.random.uniform(5, 500, num_samples), # Kosten pro Akquisition (CPA)
        "previous_recommendation": np.random.choice([0, 1], size=num_samples),  # Frühere Empfehlung (0 = nein, 1 = ja)
        "impression_share": np.random.uniform(0.1, 1.0, num_samples),   # Anteil an Impressionen (Sichtbarkeit der Anzeige) im Vergleich mit allen anderen die dieses Keyword wollen
        "conversion_value": np.random.uniform(0, 10000, num_samples)    # Monetärer Wert der Conversions (Ein monetärer Wert, der den finanziellen Nutzen aus den erzielten Conversions widerspiegelt. Dieser Wert gibt an, wie viel Umsatz oder Gewinn durch die Conversions generiert wurde – je höher der Wert, desto wertvoller sind die Conversions aus Marketingsicht.)
    }
    return pd.DataFrame(data)

# Example
'''
test = generate_synthetic_data(10)
test.head()
print(test.shape)
print(test.columns)
'''


# Load synthetic dataset
''''
dataset = generate_synthetic_data(1000)
'''


def read_and_organize_csv(file_path):
    """
    Reads a CSV file, organizes the data by keywords, and returns the organized DataFrame.
    This function performs the following steps:
    1. Reads the CSV file from the given file path into a DataFrame.
    2. Drops the 'step' column from the DataFrame.
    3. Extracts unique keywords from the 'keyword' column.
    4. Organizes the data by iterating through the first 5000 rows for each keyword and concatenates the rows into a new DataFrame.
    Args:
        file_path (str): The file path to the CSV file.
    Returns:
        pd.DataFrame: A DataFrame containing the organized data, with the index reset.
    """
    df = pd.read_csv(file_path)
    organized_data = pd.DataFrame()

    # Skip the 'step' column
    df = df.drop(columns=['step'])

    # Get unique keywords
    keywords = df['keyword'].unique()

    # Organize data
    for i in range(5000):
        for keyword in keywords:
            keyword_data = df[df['keyword'] == keyword]
            if len(keyword_data) > i:
                organized_data = pd.concat([organized_data, keyword_data.iloc[[i]]])

    return organized_data.reset_index(drop=True)

# Example usage
''''
dataset = pd.read_csv('data/organized_dataset.csv')
dataset.head()
'''

def split_dataset_by_ratio(dataset, train_ratio=0.8):
    """
    Splits the dataset into training and test sets based on keywords.
    
    Args:
        dataset (pd.DataFrame): The dataset to split.
        train_ratio (float): Ratio of keywords to include in the training set (0.0-1.0).
        
    Returns:
        tuple: (training_dataset, test_dataset)
    """
    # Get all unique keywords
    keywords = dataset['keyword'].unique()
    
    # Fetch the amount of rows for each keyword
    entries_in_dataset = len(dataset) / keywords.size
    
    # Split rows into training and test sets
    rows_training = round((len(dataset) * train_ratio) / keywords.size) * keywords.size # Round to the nearest multiple of the number of keywords
    rows_test = int(len(dataset) - rows_training)

    # Create training and test datasets
    train_dataset = dataset.iloc[0:rows_training].reset_index(drop=True)
    test_dataset = dataset.iloc[rows_training:].reset_index(drop=True)
    
    print(f"Training dataset: {len(train_dataset)} rows, {len(train_dataset['keyword'].unique())} keywords")
    print(f"Test dataset: {len(test_dataset)} rows, {len(test_dataset['keyword'].unique())} keywords")
    
    return train_dataset, test_dataset


def get_entry_from_dataset(df, index):
    """
    Retrieves a subset of rows from the DataFrame based on unique keywords.
    This function calculates the number of unique keywords in the DataFrame
    and uses this number to determine the subset of rows to return. The subset
    is determined by the given index and the number of unique keywords.
    Parameters:
    df (pandas.DataFrame): The DataFrame containing the dataset.
    index (int): The index to determine which subset of rows to retrieve.
    Returns:
    pandas.DataFrame: A subset of the DataFrame containing rows corresponding
                      to the specified index and the number of unique keywords.
    """
    # Count unique keywords
    seen_keywords = set()
    if not hasattr(get_entry_from_dataset, "unique_keywords"):
        seen_keywords = set()
        for i, row in df.iterrows():
            keyword = row['keyword']
            if keyword in seen_keywords:
                break
            seen_keywords.add(keyword)
        get_entry_from_dataset.unique_keywords = seen_keywords
        get_entry_from_dataset.keywords_amount = len(seen_keywords)
    else:
        seen_keywords = get_entry_from_dataset.unique_keywords

    # Get the subset of rows based on the index
    keywords_amount = get_entry_from_dataset.keywords_amount
    return df.iloc[index * keywords_amount:index * keywords_amount + keywords_amount].reset_index(drop=True)

# Example usage
'''
entry = get_entry_from_dataset(dataset, 0)
print(entry)

entry = get_entry_from_dataset(dataset, 1)
print(entry)
'''


# Define a Custom TorchRL Environment
class AdOptimizationEnv(EnvBase):
    """
    AdOptimizationEnv is an environment for optimizing digital advertising strategies using reinforcement learning.
    Attributes:
        initial_cash (float): Initial cash balance for the environment.
        dataset (pd.DataFrame): Dataset containing keyword metrics.
        num_features (int): Number of features for each keyword.
        num_keywords (int): Number of keywords in the dataset.
        action_spec (OneHot): Action specification for the environment.
        reward_spec (Unbounded): Reward specification for the environment.
        observation_spec (Composite): Observation specification for the environment.
        done_spec (Composite): Done specification for the environment.
        current_step (int): Current step in the environment.
        holdings (torch.Tensor): Tensor representing the current holdings of keywords.
        cash (float): Current cash balance.
        obs (TensorDict): Current observation of the environment.
    Methods:
        __init__(self, dataset, initial_cash=100000.0, device="cpu"):
            Initializes the AdOptimizationEnv with the given dataset, initial cash, and device.
        _reset(self, tensordict=None):
            Resets the environment to the initial state and returns the initial observation.
        _step(self, tensordict):
            Takes a step in the environment using the given action and returns the next state, reward, and done flag.
        _compute_reward(self, action, current_pki, action_idx):
            Computes the reward based on the selected keyword's metrics.
        _set_seed(self, seed: Optional[int]):
            Sets the random seed for the environment.
    """

    def __init__(self, dataset, initial_cash=100000.0, device="cpu"):
        """
        Initializes the digital advertising environment.
        Args:
            dataset (Any): The dataset containing keyword features and other relevant data.
            initial_cash (float, optional): The initial amount of cash available for advertising. Defaults to 100000.0.
            device (str, optional): The device to run the environment on, either "cpu" or "cuda". Defaults to "cpu".
        Attributes:
            initial_cash (float): The initial amount of cash available for advertising.
            dataset (Any): The dataset containing keyword features and other relevant data.
            num_features (int): The number of features in the dataset.
            num_keywords (int): The number of keywords in the dataset.
            action_spec (OneHot): The specification for the action space, which includes selecting a keyword to buy or choosing to buy nothing.
            reward_spec (Unbounded): The specification for the reward space, which is unbounded and of type torch.float32.
            observation_spec (Composite): The specification for the observation space, which includes keyword features, cash, holdings, and step count.
            done_spec (Composite): The specification for the done space, which includes flags for done, terminated, and truncated states.
        """
        super().__init__(device=device)
        self.initial_cash = initial_cash
        self.dataset = dataset
        self.num_features = len(feature_columns)
        self.num_keywords = get_entry_from_dataset(self.dataset, 0).shape[0]
        self.action_spec = OneHot(n=self.num_keywords + 1) # select which one to buy or the last one to buy nothing
        self.reward_spec = Unbounded(shape=(1,), dtype=torch.float32)
        self.observation_spec = Composite(
            observation = Composite(
                keyword_features=Unbounded(shape=(self.num_keywords, self.num_features), dtype=torch.float32),
                cash=Unbounded(shape=(1,), dtype=torch.float32),
                holdings=Bounded(low=0, high=1, shape=(self.num_keywords,), dtype=torch.int, domain="discrete")
            ),
            step_count=Unbounded(shape=(1,), dtype=torch.int64)
        )
        self.done_spec = Composite(
            done=Binary(shape=(1,), dtype=torch.bool),
            terminated=Binary(shape=(1,), dtype=torch.bool),
            truncated=Binary(shape=(1,), dtype=torch.bool)
        )
        
        self.reset()

    def _reset(self, tensordict=None):
        """
        Resets the environment to its initial state.
        Args:
            tensordict (TensorDict, optional): A TensorDict to be updated with the reset state. If None, a new TensorDict is created.
        Returns:
            TensorDict: A TensorDict containing the reset state of the environment, including:
                - "done" (torch.tensor): A boolean tensor indicating if the episode is done.
                - "observation" (TensorDict): A TensorDict containing the initial observation with:
                    - "keyword_features" (torch.tensor): Features of the current keywords.
                    - "cash" (torch.tensor): The initial cash balance.
                    - "holdings" (torch.tensor): The initial holdings state for each keyword.
                - "step_count" (torch.tensor): The current step count, initialized to 0.
                - "terminated" (torch.tensor): A boolean tensor indicating if the episode is terminated.
                - "truncated" (torch.tensor): A boolean tensor indicating if the episode is truncated.
        """
        self.current_step = 0
        self.holdings = torch.zeros(self.num_keywords, dtype=torch.int, device=self.device) # 0 = not holding, 1 = holding keyword
        self.cash = self.initial_cash
        #sample = self.dataset.sample(1)
        #state = torch.tensor(sample[feature_columns].values, dtype=torch.float32).squeeze()
        # Create the initial observation.
        keyword_features = torch.tensor(get_entry_from_dataset(self.dataset, self.current_step)[feature_columns].values, dtype=torch.float32, device=self.device)
        obs = TensorDict({
            "keyword_features": keyword_features,  # Current pki for each keyword
            "cash": torch.tensor(self.cash, dtype=torch.float32, device=self.device),  # Current cash balance
            "holdings": self.holdings.clone()  # 1 for each keyword if we are holding
        }, batch_size=[])
        #return TensorDict({"observation": state}, batch_size=[])
        # step_count initialisieren
        if tensordict is None:
            tensordict = TensorDict({
                "done": torch.tensor(False, dtype=torch.bool, device=self.device),
                "observation": obs,
                "step_count": torch.tensor(self.current_step, dtype=torch.int64, device=self.device),
                "terminated": torch.tensor(False, dtype=torch.bool, device=self.device),
                "truncated": torch.tensor(False, dtype=torch.bool, device=self.device)
            },
            batch_size=[])
        else:
            tensordict["done"] = torch.tensor(False, dtype=torch.bool, device=self.device)
            tensordict["observation"] = obs
            tensordict["step_count"] = torch.tensor(self.current_step, dtype=torch.int64, device=self.device)
            tensordict["terminated"] = torch.tensor(False, dtype=torch.bool, device=self.device)
            tensordict["truncated"] = torch.tensor(False, dtype=torch.bool, device=self.device)
        
        self.obs = obs
        #print(result)
        print(f'Reset: Step: {self.current_step}')
        return tensordict


    def _step(self, tensordict):
        """
        Perform a single step in the environment using the provided tensor dictionary.
        Args:
            tensordict (TensorDict): A dictionary containing the current state and action.
        Returns:
            TensorDict: A dictionary containing the next state, reward, and termination status.
        The function performs the following steps:
        1. Extracts the action from the input tensor dictionary.
        2. Determines the index of the selected keyword.
        3. Retrieves the current entry from the dataset based on the current step.
        4. Updates the holdings based on the selected action.
        5. Calculates the reward based on the action taken.
        6. Advances to the next time step and checks for termination conditions.
        7. Retrieves the next keyword features for the subsequent state.
        8. Updates the observation state with the new keyword features, cash balance, and holdings.
        9. Updates the tensor dictionary with the new state, reward, and termination status.
        10. Returns the updated tensor dictionary containing the next state, reward, and termination status.
        """
        # Get the action from the input tensor dictionary. 
        action = tensordict["action"]
        #action_idx = action.argmax(dim=-1).item()  # Get the index of the selected keyword
        true_indices = torch.nonzero(action, as_tuple=True)[0]
        action_idx = true_indices[0] if len(true_indices) > 0 else self.action_spec.n - 1

        current_pki = get_entry_from_dataset(self.dataset, self.current_step)
        #action = tensordict["action"].argmax(dim=-1).item()
        
        # Update holdings based on action (only one keyword is selected)
        new_holdings = torch.zeros_like(self.holdings)
        if action_idx < self.num_keywords:
            new_holdings[action_idx] = 1
        self.holdings = new_holdings

        # Calculate the reward based on the action taken.
        reward = self._compute_reward(action, current_pki, action_idx)

         # Move to the next time step.
        self.current_step += 1
        terminated = self.current_step >= (len(self.dataset) // self.num_keywords) - 2 # -2 to avoid going over the last index
        truncated = False

        # Get next pki for the keywords
        next_keyword_features = torch.tensor(get_entry_from_dataset(self.dataset, self.current_step)[feature_columns].values, dtype=torch.float32, device=self.device)
        # todo: most probably we need to remove some columns from the state so we only have the features for the agent to see... change it also in reset
        next_obs = TensorDict({
            "keyword_features": next_keyword_features,  # next pki for each keyword
            "cash": torch.tensor(self.cash, dtype=torch.float32, device=self.device),  # Current cash balance
            "holdings": self.holdings.clone()
        }, batch_size=[])
        
        # Update the state
        self.obs = next_obs
        print(f'Step: {self.current_step}, Action: {action_idx}, Reward: {reward}')
        tensordict["done"] = torch.tensor(terminated or truncated, dtype=torch.bool, device=self.device)
        
        tensordict["done"] = torch.tensor(terminated or truncated, dtype=torch.bool, device=self.device)
        tensordict["observation"] = self.obs
        tensordict["reward"] = torch.tensor(reward, dtype=torch.float32, device=self.device)
        tensordict["step_count"] = torch.tensor(self.current_step-1, dtype=torch.int64, device=self.device)
        tensordict["terminated"] = torch.tensor(terminated, dtype=torch.bool, device=self.device)
        tensordict["truncated"] = torch.tensor(truncated, dtype=torch.bool, device=self.device)
        next = TensorDict({
            "done": torch.tensor(terminated or truncated, dtype=torch.bool, device=self.device),
            "observation": next_obs,
            "reward": torch.tensor(reward, dtype=torch.float32, device=self.device),
            "step_count": torch.tensor(self.current_step, dtype=torch.int64, device=self.device),
            "terminated": torch.tensor(terminated, dtype=torch.bool, device=self.device),
            "truncated": torch.tensor(truncated, dtype=torch.bool, device=self.device)

        }, batch_size=tensordict.batch_size)
        
        return next
    
        

    def _compute_reward(self, action, current_pki, action_idx):
        """Compute reward based on the selected keyword's metrics"""
        if action_idx == self.num_keywords:
            return 0.0
        
        reward = 0.0
        # Iterate thourh all keywords
        for i in range(self.num_keywords):
            sample = current_pki.iloc[i]
            cost = sample["ad_spend"]
            ctr = sample["paid_ctr"]
            if action[i] == True and cost > 5000:
                reward += 1.0
            elif action[i] == False and ctr > 0.15:
                reward += 1.0
            else:
                reward -= 1.0
        return reward

    def _set_seed(self, seed: Optional[int]):
        rng = torch.manual_seed(seed)
        self.rng = rng


class FlattenInputs(nn.Module):
    """
    A custom PyTorch module to flatten and combine keyword features, cash, and holdings into a single tensor.
    Methods
    -------
    forward(keyword_features, cash, holdings)
        Flattens and combines the input tensors into a single tensor.
    Parameters
    ----------
    keyword_features : torch.Tensor
        A tensor containing keyword features with shape [batch, num_keywords, feature_dim] or [num_keywords, feature_dim].
    cash : torch.Tensor
        A tensor containing cash values with shape [batch] or [batch, 1] or a scalar.
    holdings : torch.Tensor
        A tensor containing holdings with shape [batch, num_keywords] or [num_keywords].
    Returns
    -------
    torch.Tensor
        A combined tensor with all inputs flattened and concatenated along the appropriate dimension.
    """
    def forward(self, keyword_features, cash, holdings):
        # Check if we have a batch dimension
        has_batch = keyword_features.dim() > 2
        
        if has_batch:
            batch_size = keyword_features.shape[0]
            # Flatten keyword features while preserving batch dimension: 
            # [batch, num_keywords, feature_dim] -> [batch, num_keywords * feature_dim]
            flattened_features = keyword_features.reshape(batch_size, -1)
            
            # Ensure cash has correct dimensions [batch, 1]
            if cash.dim() == 1:  # [batch]
                cash = cash.unsqueeze(-1)  # [batch, 1]
            elif cash.dim() == 0:  # scalar
                cash = cash.unsqueeze(0).expand(batch_size, 1)  # [batch, 1]
            
            # Ensure holdings has correct dimensions [batch, num_keywords]
            if holdings.dim() == 1:  # [num_keywords]
                holdings = holdings.unsqueeze(0).expand(batch_size, -1)  # [batch, num_keywords]
            
            # Convert holdings to float
            holdings = holdings.float()
            
            # Combine all inputs along dimension 1
            combined = torch.cat([flattened_features, cash, holdings], dim=1)
        else:
            # No batch dimension - single sample case
            # Flatten keyword features: [num_keywords, feature_dim] -> [num_keywords * feature_dim]
            flattened_features = keyword_features.reshape(-1)
            
            # Ensure cash has a dimension
            cash = cash.unsqueeze(-1) if cash.dim() == 0 else cash
            
            # Convert holdings to float
            holdings = holdings.float()
            
            # Combine all inputs
            combined = torch.cat([flattened_features, cash, holdings], dim=0)
            
        return combined




# Select the best device for our machine
device = torch.device(
    "cuda" if torch.cuda.is_available() else
    "mps" if torch.backends.mps.is_available() else
    "cpu"
)
print(device)

feature_columns = ["competitiveness", "difficulty_score", "organic_rank", "organic_clicks", "organic_ctr", "paid_clicks", "paid_ctr", "ad_spend", "ad_conversions", "ad_roas", "conversion_rate", "cost_per_click"]

# Load the organized dataset
dataset = pd.read_csv('data/organized_dataset.csv')
# We split it into training and test data
dataset_training, dataset_test = split_dataset_by_ratio(dataset, train_ratio=0.8)


# Initialize Environment
env = AdOptimizationEnv(dataset_training, device=device)
state_dim = env.num_features

# Define data and dimensions
feature_dim = len(feature_columns)
num_keywords = env.num_keywords
action_dim = env.action_spec.shape[-1]
total_input_dim = feature_dim * num_keywords + 1 + num_keywords  # features per keyword + cash + holdings

value_mlp = MLP(in_features=total_input_dim, out_features=action_dim, num_cells=[128, 64])

flatten_module = TensorDictModule(
    FlattenInputs(),
    in_keys=[("observation", "keyword_features"), ("observation", "cash"), ("observation", "holdings")],
    out_keys=["flattened_input"]
)
#value_net = TensorDictModule(value_mlp, in_keys=["observation"], out_keys=["action_value"])
value_net = TensorDictModule(value_mlp, in_keys=["flattened_input"], out_keys=["action_value"])
policy = TensorDictSequential(flatten_module, value_net, QValueModule(spec=env.action_spec))

# Make sure your policy is on the correct device
policy = policy.to(device)

exploration_module = EGreedyModule(
    env.action_spec, annealing_num_steps=100_000, eps_init=0.5
)
exploration_module = exploration_module.to(device)
policy_explore = TensorDictSequential(policy, exploration_module).to(device)


from torchrl.collectors import SyncDataCollector
from torchrl.data import LazyTensorStorage, ReplayBuffer
from torch.optim import Adam
from torchrl.objectives import DQNLoss, SoftUpdate

init_rand_steps = 5000
frames_per_batch = 100
optim_steps = 10
collector = SyncDataCollector(
    env,
    policy_explore,
    frames_per_batch=frames_per_batch,
    total_frames=-1,
    init_random_frames=init_rand_steps,
)
rb = ReplayBuffer(storage=LazyTensorStorage(100_000))


#actor = QValueActor(value_net, in_keys=["observation"], action_space=spec)
loss = DQNLoss(value_network=policy, action_space=env.action_spec, delay_value=True).to(device)
optim = Adam(loss.parameters(), lr=0.02)
updater = SoftUpdate(loss, eps=0.99)


import time
total_count = 0
total_episodes = 0
t0 = time.time()
# Evaluation parameters
evaluation_frequency = 1000  # Run evaluation every 1000 steps
best_test_reward = float('-inf')
test_env = AdOptimizationEnv(dataset_test, device=device) # Create a test environment with the test dataset
for i, data in enumerate(collector):
    # Write data in replay buffer
    print(f'data: step_count: {data["step_count"]}')
    rb.extend(data.to(device))
    #max_length = rb[:]["next", "step_count"].max()
    max_length = rb[:]["step_count"].max()
    if len(rb) > init_rand_steps:
        # Optim loop (we do several optim steps
        # per batch collected for efficiency)
        for _ in range(optim_steps):
            sample = rb.sample(128)
            # Make sure sample is on the correct device
            sample = sample.to(device)  # Move the sample to the specified device
            loss_vals = loss(sample)
            loss_vals["loss"].backward()
            optim.step()
            optim.zero_grad()
            # Update exploration factor
            exploration_module.step(data.numel())
            # Update target params
            updater.step()
            if i % 10 == 0: # Fixed condition (was missing '== 0')
                print(f"Max num steps: {max_length}, rb length {len(rb)}")
            total_count += data.numel()
            total_episodes += data["next", "done"].sum()

            # Evaluate on test data periodically
            if total_count % evaluation_frequency == 0:
                print(f"\n--- Testing model performance after {total_count} training steps ---")
                # Use policy without exploration for evaluation
                eval_policy = TensorDictSequential(flatten_module, value_net, QValueModule(spec=env.action_spec)).to(device)
                
                # Reset the test environment
                test_td = test_env.reset()
                total_test_reward = 0.0
                done = False
                max_test_steps = 100  # Limit test steps to avoid infinite loops
                test_step = 0
                
                # Run the model on test environment until done or max steps reached
                while not done and test_step < max_test_steps:
                    # Forward pass through policy without exploration
                    with torch.no_grad():
                        test_td = eval_policy(test_td)
                    
                    # Step in the test environment
                    test_td = test_env.step(test_td)
                    reward = test_td["reward"].item()
                    total_test_reward += reward
                    done = test_td["done"].item()
                    test_step += 1
                
                print(f"Test performance: Total reward = {total_test_reward}, Steps = {test_step}")
                
                # Save model if it's the best so far
                if total_test_reward > best_test_reward:
                    best_test_reward = total_test_reward
                    print(f"New best model! Saving with reward: {best_test_reward}")

                    # Create the directory if it doesn't exist
                    import os
                    os.makedirs('saves', exist_ok=True)
                    torch.save({
                        'policy_state_dict': policy.state_dict(),
                        'optimizer_state_dict': optim.state_dict(),
                        'total_steps': total_count,
                        'test_reward': best_test_reward,
                    }, 'saves/best_model.pt')
                
                print("--- Testing completed ---\n")
    
    if total_count > 10_000:
        break

t1 = time.time()

print(
    f"Finished after {total_count} steps, {total_episodes} episodes and in {t1-t0}s."
)
print(f"Best test performance: {best_test_reward}")


''''
Todo:
- Clean up the code
- Split training and test data (RB)
- Implement tensorbaord (PK, MAC)
- Implement the visualization (see tensorboard) (EO)
- Implement the saving of the model (RB)
- Implement the inference (RB)
- Implement the optuna hyperparameter tuning (UT)
'''''
