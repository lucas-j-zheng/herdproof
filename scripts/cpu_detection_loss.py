"""Keep YOLO loss/label indexing on CPU while convolution/backprop uses MPS.

PyTorch's MPS boolean indexing failed with inconsistent tensor lengths during
this run. This changes placement only, preserving the upstream loss formula and
autograd copies. No installed package files are modified.
https://github.com/pytorch/pytorch/issues/178079
"""
import torch
from ultralytics.utils.loss import v8DetectionLoss


def enable_cpu_detection_loss():
    original_init = v8DetectionLoss.__init__
    original_call = v8DetectionLoss.__call__

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.device = torch.device("cpu")
        self.stride = self.stride.cpu()
        self.proj = self.proj.cpu()
        self.assigner = self.assigner.cpu()
        self.bbox_loss = self.bbox_loss.cpu()

    def call(self, preds, batch):
        features = preds[1] if isinstance(preds, tuple) else preds
        device = features[0].device
        cpu_features = [x.to("cpu") for x in features]
        cpu_batch = {k:(v.to("cpu") if isinstance(v,torch.Tensor) else v) for k,v in batch.items()}
        loss, items = original_call(self, cpu_features, cpu_batch)
        return loss.to(device), items.to(device)

    v8DetectionLoss.__init__ = initialize
    v8DetectionLoss.__call__ = call
