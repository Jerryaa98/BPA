import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

from bpa import ot


class BPA(nn.Module):
    supported_distances = ['cosine', 'euclidean']

    def __init__(self,
                 distance_metric: str = 'cosine',
                 ot_reg: float = 0.1,
                 sinkhorn_iterations: int = 10,
                 sigmoid: bool = False,
                 mask_diag: bool = True,
                 max_scale: bool = True):
        """
        :param distance_metric - Compute the cost matrix.
        :param ot_reg - Sinkhorn entropy regularization (lambda). For few-shot classification, 0.1-0.2 works best.
        :param sinkhorn_iterations - Maximum number of sinkhorn iterations.
        :param sigmoid - If to apply sigmoid(log_p) instead of the usual exp(log_p).
        :param mask_diag - Set to true to apply diagonal masking before and after the OT.
        :param max_scale - Re-scale the BPA values to range [0,1].
        """
        super().__init__()

        assert distance_metric.lower() in BPA.supported_distances and sinkhorn_iterations > 0

        self.sinkhorn_iterations = sinkhorn_iterations
        self.distance_metric = distance_metric.lower()
        self.mask_diag = mask_diag
        self.sigmoid = sigmoid
        self.ot_reg = ot_reg
        self.max_scale = max_scale
        self.diagonal_val = 1e3                         # value to mask self-values with

    def compute_cost_matrix(self, x: Tensor) -> Tensor:
        """
        Compute the cost matrix.
        """
        
        # euclidean
        if self.distance_metric == 'euclidean':
            pairwise_dist = torch.cdist(x, x, p=2)
            # scale euclidean distances to [0, 1]
            pairwise_dist = pairwise_dist / pairwise_dist.max()
        # cosine
        elif self.distance_metric == 'cosine':
            x_norm = F.normalize(x, dim=-1, p=2)
            pairwise_dist = 1 - (x_norm @ x_norm.transpose(-2, -1))
        return pairwise_dist

    def mask_diagonal(self, M: Tensor, value: float):
        """
        Mask diagonal with new value.
        """
        if self.mask_diag:
            if M.dim() > 2:
                M[torch.eye(M.shape[1]).repeat(M.shape[0], 1, 1).bool()] = value
            else:
                M.fill_diagonal_(value)
        return M

    def forward(self, x: Tensor) -> Tensor:
        """
        Compute the BPA feature transform.
        """
        # get masked cost matrix
        C = self.compute_cost_matrix(x)
        C = self.mask_diagonal(C, value=self.diagonal_val)

        # compute self-OT
        x_bpa = ot.log_sinkhorn(C, reg=self.ot_reg, num_iters=self.sinkhorn_iterations)
        if self.sigmoid:
            x_bpa = torch.sigmoid(x_bpa)
        else:
            x_bpa = torch.exp(x_bpa)

        # divide the BPA matrix by its maximum value to scale its range into [0, 1]
        if self.max_scale:
            z_max = x_bpa.max().item() if x_bpa.dim() <= 2 else x_bpa.amax(dim=(1, 2), keepdim=True)
            x_bpa = x_bpa / z_max

        # set self-values to 1
        return self.mask_diagonal(x_bpa, value=1)


def cosine_similarity(x: Tensor):
    """
    Compute the pairwise cosine similarity between a matrix to itself.
    """
    x_norm = F.normalize(x, dim=-1, p=2)
    return x_norm @ x_norm.transpose(-2, -1)
