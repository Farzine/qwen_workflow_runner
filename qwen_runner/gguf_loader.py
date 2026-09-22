"""Load matching Qwen 2.1 GGUF tensors using Diffusers' packed GGUF kernels.

Does not import ComfyUI and does not expand the entire model to BF16.
Rejects incomplete/name-mismatched/shape-mismatched files before inference.
"""
from collections import Counter


def load_gguf_transformer(path, config_directory, dtype):
    import gguf
    import numpy as np
    import torch
    from accelerate import init_empty_weights
    from diffusers import QwenImage21Transformer2DModel, GGUFQuantizationConfig
    from diffusers.quantizers.gguf.gguf_quantizer import GGUFQuantizer
    from diffusers.quantizers.gguf.utils import GGUFParameter, SUPPORTED_GGUF_QUANT_TYPES

    config = QwenImage21Transformer2DModel.load_config(str(config_directory), local_files_only=True)
    with init_empty_weights():
        model = QwenImage21Transformer2DModel.from_config(config)
    expected = {k: tuple(v.shape) for k, v in model.state_dict().items()}
    reader = gguf.GGUFReader(str(path))
    tensors = {}
    for tensor in reader.tensors:
        name = tensor.name.removeprefix('model.diffusion_model.').removeprefix('diffusion_model.')
        if name in tensors:
            raise ValueError(f"Duplicate GGUF tensor: {name}")
        tensors[name] = tensor
    missing, extra = set(expected) - set(tensors), set(tensors) - set(expected)
    if missing or extra:
        raise ValueError(f"GGUF is not a matching Qwen Image 2.1 transformer. Missing: {sorted(missing)[:8]}; unexpected: {sorted(extra)[:8]}")
    state, counts = {}, Counter()
    for name, tensor in tensors.items():
        shape = tuple(int(x) for x in reversed(tensor.shape))
        original = reader.get_field(f'comfy.gguf.orig_shape.{tensor.name}')
        if original is not None:
            shape = tuple(int(original.parts[i][0]) for i in original.data)
        if shape != expected[name]:
            raise ValueError(f"GGUF {name}: shape {shape} != expected {expected[name]}")
        counts[tensor.tensor_type.name] += 1
        owner_name, parameter = name.rsplit('.', 1)
        owner = model.get_submodule(owner_name)
        quantized_linear = (isinstance(owner, torch.nn.Linear) and parameter == 'weight'
                            and tensor.tensor_type not in {gguf.GGMLQuantizationType.F32, gguf.GGMLQuantizationType.F16, gguf.GGMLQuantizationType.BF16})
        if quantized_linear:
            if tensor.tensor_type not in SUPPORTED_GGUF_QUANT_TYPES:
                raise ValueError(f"Unsupported GGUF quantization: {tensor.tensor_type}")
            value = GGUFParameter(torch.from_numpy(np.array(tensor.data, copy=True)), quant_type=tensor.tensor_type)
            if tuple(value.quant_shape) != shape:
                raise ValueError(f"Packed tensor layout does not decode to {shape}: {name}")
            state[name] = value
        else:
            # Norms and unquantized weights retain ordinary PyTorch parameters.
            value = torch.from_numpy(np.array(gguf.quants.dequantize(tensor.data, tensor.tensor_type), copy=True)).reshape(shape)
            state[name] = value.to(dtype)
    quantizer = GGUFQuantizer(GGUFQuantizationConfig(compute_dtype=dtype))
    quantizer.validate_environment()
    quantizer.preprocess_model(model, device_map=None, state_dict=state, keep_in_fp32_modules=[])
    for name, value in state.items():
        owner_name, parameter = name.rsplit('.', 1)
        owner = model.get_submodule(owner_name)
        if parameter in owner._parameters:
            owner._parameters[parameter] = value if isinstance(value, GGUFParameter) else torch.nn.Parameter(value, requires_grad=False)
        else:
            owner._buffers[parameter] = value
    model = quantizer.postprocess_model(model)
    model.hf_quantizer = quantizer
    model.eval()
    if any(p.device.type == 'meta' for p in model.parameters()):
        raise RuntimeError('GGUF loader left an uninitialized parameter')
    return model, {"loader": "strict_native_diffusers_gguf", "tensor_count": len(tensors),
                   "tensor_types": dict(counts), "storage": "packed quantized linear weights; floating norms"}
