from copy import deepcopy
import numpy as np
import torch
from tqdm import tqdm
from typing import Literal

from classifiers.differential.LDAGaussianDiff import LDAGaussianDiff
from trainers.BaseTrainer import BaseTrainer


class LDAGaussianDiffTrainer(BaseTrainer):
    def __init__(self, model: LDAGaussianDiff, device="cuda" if torch.cuda.is_available() else "cpu"):
        super().__init__(model)

        self.device = device  # Much faster to use GPU at least for the feature extraction

        self.model.extractor = self.model.extractor.to(device)

    # Looks like there is no partial_fit method for LDA
    # so we need to extract all the features and then fit the model
    # Apart from fitting all the data, there are alternative options:
    # TODO: 1. (Avg) pool the batch of features and use that to fit the model
    # TODO: 2. Random sample the dataset for a 'reasonable number' of samples to fit the model
    # TODO: 3. Write 'partial_fit' manually
    def train(
        self, train_dataloader, val_dataloader, variant: Literal["all", "avg_pool", "random_sample"] = "all"
    ):
        """
        Train the model on the given dataloader for the given number of epochs

        param train_dataloader: Dataloader loading the training data
        """

        if variant == "all":
            self._train_all(train_dataloader)
        else:
            raise NotImplementedError(f"Training variant {variant} not implemented")

        # self.save_model(f"./LDADiff_{variant}.pt")

        print(f"LDAGuassianDiff model trained")
        print("Validating model")
        validation_accuracy, validation_eer = self.val(val_dataloader)
        print(f"Validation accuracy: {validation_accuracy}, validation EER: {validation_eer}")

    def _train_all(self, train_dataloader):
        """
        Train the model on all the data in the given dataloader
        """
        print(f"Training LDAGuassianDiff model on all data")

        extractor = self.model.extractor
        feature_processor = self.model.feature_processor
        bonafide_features = []
        spoof_features = []

        i = 0

        for gt, test, label in tqdm(train_dataloader):
            feats_gt = extractor.extract_features(gt.to(self.device))
            feats_test = extractor.extract_features(test.to(self.device))

            feats_gt = feature_processor(feats_gt)
            feats_test = feature_processor(feats_test)

            diff = feats_gt - feats_test

            bonafide_features.extend(diff[label == 0].tolist())
            spoof_features.extend(diff[label == 1].tolist())

        # print(f"{len(bonafide_features)} bonafide and {len(spoof_features)} spoof features")

        self.model.fit(np.array(bonafide_features), np.array(spoof_features))

    def val(self, val_dataloader) -> tuple[float, float]:
        """
        Validate the model on the given dataloader

        param val_dataloader: Dataloader loading the validation/dev data

        return: Tuple(accuracy, EER)
        """
        labels = []
        scores = []  # Posterior probabilities
        class_predictions = []  # MAP predictions - defined in the classifier

        for gt, test, label in tqdm(val_dataloader):
            batch_predictions, probs = self.model(gt.to(self.device), test.to(self.device))

            class_predictions.extend(batch_predictions.tolist())
            scores.extend(probs[:, 0].tolist())
            labels.extend(label.tolist())

        # print(f"Labels: {np.array(labels).astype(int)}")
        # print(f"Predic: {np.array(class_predictions)}")
        # print(f"Scores: {np.array(scores)}")

        val_accuracy = np.mean(np.array(labels) == np.array(class_predictions))
        eer = self.calculate_EER(labels, scores)

        return val_accuracy, eer

    def eval(self, eval_dataloader):
        """
        Evaluate the model on the given dataloader

        param eval_dataloader: Dataloader loading the evaluation/test data
        """
        print("Evaluating LDADiff model")
        # Reuse code from val() to evaluate the model on the eval set
        eval_accuracy, eer = self.val(eval_dataloader)
        print(f"Eval accuracy: {eval_accuracy}")
        print(f"Eval EER: {eer}")

#     def save_model(self, path: str):
#         """
#         Save the model to the given path
#         Needs to be custom because the non-PyTorch model can contain a PyTorch component (extractor, feature_processor)

#         param path: Path to save the model to
#         """
#         if (  # If the model contains a PyTorch component, it cannot be saved using inherited method
#             isinstance(self.model.extractor, torch.nn.Module)
#             or isinstance(self.model.feature_processor, torch.nn.Module)
#         ):
#             serialized_model = GMMDiffSaver(deepcopy(self.model))
#             torch.save(serialized_model, path)
#         else:
#             super().save_model(path)

#     def load_model(self, path: str):
#         """
#         Load the model from the given path
#         Needs to be custom because the non-PyTorch model can contain a PyTorch component (extractor, feature_processor)

#         param path: Path to load the model from
#         """
#         serialized_model = torch.load(path)
#         if isinstance(serialized_model, GMMDiffSaver):  # If saved using custom method
#             self.model = serialized_model.model
#             if isinstance(self.model.extractor, torch.nn.Module):
#                 self.model.extractor.load_state_dict(serialized_model.extractor_state_dict)
#             if isinstance(self.model.feature_processor, torch.nn.Module):
#                 self.model.feature_processor.load_state_dict(serialized_model.feature_processor_state_dict)
#         else:
#             super().load_model(path)


# class GMMDiffSaver:
#     """
#     Class to save the GMMDiff model to a file
#     Needs to be custom because the non-PyTorch model can contain a PyTorch component (extractor, feature_processor)
#     PyTorch models can only be saved as a state_dicts, which is exactly what this class does - extract the state_dicts
#     and save them along with the rest of the model

#     param model: GMMDiff model to save
#     """

#     def __init__(self, model: GMMDiff):
#         self.model = model

#         if isinstance(self.model.extractor, torch.nn.Module):
#             self.extractor_state_dict = self.model.extractor.state_dict()
#             self.model.extractor = None
#         if isinstance(self.model.feature_processor, torch.nn.Module):
#             self.feature_processor_state_dict = self.model.feature_processor.state_dict()
#             self.model.feature_processor = None
