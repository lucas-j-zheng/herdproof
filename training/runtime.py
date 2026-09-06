"""Numerical validation shared by inference and training."""
from __future__ import annotations

import math


def ensure_finite(value, label):
    import torch
    tensors = []

    def visit(item):
        if isinstance(item, torch.nn.Module):
            visit(item.state_dict())
        elif isinstance(item, torch.Tensor):
            if item.is_floating_point() or item.is_complex():
                tensors.append(torch.isfinite(item).all())
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, (tuple, list)):
            for child in item:
                visit(child)
        elif isinstance(item, (float, int)) and not math.isfinite(item):
            raise RuntimeError(f"Nonfinite {label}")

    visit(value)
    # Group by device to avoid synchronizing for every individual parameter.
    for device in {t.device for t in tensors}:
        if not torch.stack([t for t in tensors if t.device == device]).all().item():
            raise RuntimeError(f"Nonfinite {label}")
