"""Lossless prefix caching with configurable CPU spill; no global monkeypatches."""


class PrefixLayer:
    def __init__(self, policy, reserve_bytes):
        self.policy, self.reserve_bytes = policy, reserve_bytes
        self.k = self.v = None

    def store(self, k, v):
        import torch
        self.compute_device = k.device
        target = k.device
        if self.policy == 'cpu':
            target = torch.device('cpu')
        elif self.policy == 'auto' and k.device.type == 'cuda':
            required = (k.numel() * k.element_size() + v.numel() * v.element_size())
            free, _ = torch.cuda.mem_get_info(k.device)
            if free < self.reserve_bytes + 2 * required:
                target = torch.device('cpu')
        self.k, self.v = k.to(target), v.to(target)

    def get(self):
        if self.k is None: raise RuntimeError('Prefix cache was not populated')
        return self.k.to(self.compute_device), self.v.to(self.compute_device)


class PrefixCache:
    def __init__(self, num_layers, device='auto', reserve_bytes=2**30):
        self.layer_caches = [PrefixLayer(device, reserve_bytes) for _ in range(num_layers)]

    def get_layer(self, layer_idx):
        return self.layer_caches[layer_idx]
