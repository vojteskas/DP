from re import sub
from typing import Literal
import torch
from torch.utils.data import Dataset
from torchaudio import load, save
import os
import pandas as pd
import numpy as np
from RawBoost import process_Rawboost_feature
import tarfile


class ASVspoof5Dataset_base(Dataset):
    """
    Base class for the ASVspoof5 dataset. This class should not be used directly, but rather subclassed.

    param root_dir: Path to the ASVspoof5 folder
    param protocol_file_name: Name of the protocol file to use
    param variant: One of "train", "dev", "eval" to specify the dataset variant
    """

    def __init__(self, root_dir, protocol_file_name, variant: Literal["train", "dev", "eval"] = "train"):
        self.root_dir = root_dir

        protocol_file = os.path.join(self.root_dir, protocol_file_name)
        self.protocol_df = pd.read_csv(protocol_file, sep=" ", header=None)
        self.protocol_df.columns = ["SPEAKER_ID", "AUDIO_FILE_NAME", "GENDER", "-", "SYSTEM_ID", "KEY"]

        if variant == "train":
            self.subdir = "flac_T"
        elif variant == "dev":
            self.subdir = "flac_D"
        elif variant == "eval":
            self.subdir = "flac_E"
        self.rec_dir = os.path.join(self.root_dir, f"{self.subdir}.tar")
        self.tarfile = tarfile.open(self.rec_dir, "r")

        self.SAMPLING_RATE = 16000

    def __len__(self):
        return len(self.protocol_df)

    def __getitem__(self, idx):
        raise NotImplementedError("This method should be implemented in a specific subclass")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.tarfile.close()

    def __del__(self):
        self.tarfile.close()

    def get_labels(self) -> np.ndarray:
        """
        Returns an array of labels for the dataset, where 0 is genuine speech and 1 is spoofing speech
        Used for computing class weights for the loss function and weighted random sampling (see train.py)
        """
        return self.protocol_df["KEY"].map({"bonafide": 0, "spoof": 1}).to_numpy()

    def get_class_weights(self):
        """Returns an array of class weights for the dataset, where 0 is genuine speech and 1 is spoofing speech"""
        labels = self.get_labels()
        class_counts = np.bincount(labels)
        class_weights = 1.0 / class_counts
        return torch.FloatTensor(class_weights)
    
    def load_file(self, audio_file_name):
        """
        Loads the audio file from the tarfile
        """
        member = self.tarfile.getmember(audio_file_name)
        audio_file = self.tarfile.extractfile(member)
        waveform, _ = load(audio_file)
        return waveform


class ASVspoof5Dataset_pair(ASVspoof5Dataset_base):
    """
    Dataset class for ASVspoof5 that provides pairs of genuine and tested speech for differential-based detection.
    """

    def __init__(self, root_dir, protocol_file_name, variant: Literal["train", "dev", "eval"] = "train"):
        super().__init__(root_dir, protocol_file_name, variant)

    def __getitem__(self, idx):
        """
        Returns tuples of the form (test_audio_file_name, gt_waveform, test_waveform, label)
        """
        if torch.is_tensor(idx):
            idx = idx.tolist()

        speaker_id = self.protocol_df.loc[idx, "SPEAKER_ID"]

        test_audio_file_name = self.protocol_df.loc[idx, "AUDIO_FILE_NAME"]
        test_audio_name = os.path.join(self.subdir, f"{test_audio_file_name}.flac")
        test_waveform = self.load_file(test_audio_name)

        label = self.protocol_df.loc[idx, "KEY"]
        label = 0 if label == "bonafide" else 1

        # Get the genuine speech of the same speaker for differentiation
        speaker_recordings_df = self.protocol_df[
            (self.protocol_df["SPEAKER_ID"] == speaker_id) & (self.protocol_df["KEY"] == "bonafide")
        ]
        if speaker_recordings_df.empty:
            raise Exception(f"Speaker {speaker_id} genuine speech not found in protocol file")
        
        # Get a random genuine speech of the speaker using sample()
        gt_audio_file_name = speaker_recordings_df.sample(n=1).iloc[0]["AUDIO_FILE_NAME"]
        gt_audio_name = os.path.join(self.subdir, f"{gt_audio_file_name}.flac")
        gt_waveform = self.load_file(gt_audio_name)

        return test_audio_file_name, gt_waveform, test_waveform, label


class ASVspoof5Dataset_single(ASVspoof5Dataset_base):
    """
    Dataset class for ASVspoof5 that provides single audio files for "normal" classification.
    """

    def __init__(self, root_dir, protocol_file_name, variant: Literal["train", "dev", "eval"] = "train"):
        super().__init__(root_dir, protocol_file_name, variant)

    def __getitem__(self, idx):
        """
        Returns tuples of the form (audio_file_name, waveform, label)
        """
        if torch.is_tensor(idx):
            idx = idx.tolist()

        audio_file_name = self.protocol_df.loc[idx, "AUDIO_FILE_NAME"]
        audio_name = os.path.join(self.subdir, f"{audio_file_name}.flac")
        waveform = self.load_file(audio_name)

        # 0 for genuine speech, 1 for spoofing speech
        label = 0 if self.protocol_df.loc[idx, "KEY"] == "bonafide" else 1

        return audio_file_name, waveform, label

class Args:
    algo = None
    nBands = None
    minF = None
    maxF = None
    minBW = None
    maxBW = None
    minCoeff = None
    maxCoeff = None
    minG = None
    maxG = None
    minBiasLinNonLin = None
    maxBiasLinNonLin = None
    N_f = None
    P = None
    g_sd = None
    SNRmin = None
    SNRmax = None

class DefaultArgs(Args):
    nBands = 5
    minF = 20
    maxF = 8000
    minBW = 100
    maxBW = 1000
    minCoeff = 10
    maxCoeff = 100
    minG = 0
    maxG = 0
    minBiasLinNonLin = 5
    maxBiasLinNonLin = 20
    N_f = 5
    P = 10
    g_sd = 2
    SNRmin = 10
    SNRmax = 40

class ASVspoof5Dataset_pair_augmented(ASVspoof5Dataset_pair):
    """
    Dataset class for ASVspoof5 that provides augmented pairs of genuine and tested speech for differential-based detection.
    """

    def __init__(self, root_dir = "/mnt/matylda2/data/ASVspoof5", protocol_file_name = "ASVspoof5.train.metadata.txt", 
                       variant: Literal["train", "dev", "eval"] = "train", args: Args = DefaultArgs(), algo: int = 0):
        super().__init__(root_dir, protocol_file_name, variant)
        self.args = args
        self.algo = algo

    def __getitem__(self, idx):
        """
        Returns tuples of the form (test_audio_file_name, gt_waveform, test_waveform, label)
        """

        test_audio_file_name, gt_waveform, test_waveform, label = super().__getitem__(idx)

        test_waveform = test_waveform.squeeze()
        test_waveform = process_Rawboost_feature(test_waveform, self.SAMPLING_RATE, self.args, self.algo)
        test_waveform = torch.Tensor(np.expand_dims(test_waveform, axis=0))

        return test_audio_file_name, gt_waveform, test_waveform, label


class ASVspoof5Dataset_single_augmented(ASVspoof5Dataset_single):
    """
    Dataset class for ASVspoof5 that provides augmented single audio files for "normal" classification.
    """

    def __init__(self, root_dir = "/mnt/matylda2/data/ASVspoof5", protocol_file_name = "ASVspoof5.train.metadata.txt", 
                       variant: Literal["train", "dev", "eval"] = "train", args: Args = DefaultArgs(), algo: int = 0):
        super().__init__(root_dir, protocol_file_name, variant)
        self.args = args
        self.algo = algo

    def __getitem__(self, idx):
        """
        Returns tuples of the form (audio_file_name, waveform, label)
        """

        audio_file_name, waveform, label = super().__getitem__(idx)

        waveform = waveform.squeeze()
        waveform = process_Rawboost_feature(waveform, self.SAMPLING_RATE, self.args, self.algo)
        waveform = torch.Tensor(np.expand_dims(waveform, axis=0))

        return audio_file_name, waveform, label