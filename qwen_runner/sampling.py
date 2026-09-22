"""KSampler's simple/normal sigma selection, using Qwen 2.1's fixed flow shift."""
import math


def sigma_schedule(steps, strength=1.0, shift=0.69, scheduler="simple"):
    total = steps if strength > 0.9999 else int(steps / strength)
    exp_shift = math.exp(shift)
    def shift_time(t):
        return exp_shift / (exp_shift + (1 / t - 1))
    if scheduler == "simple":
        # Comfy's ModelSamplingFlux buffer has 10000 entries: t=0.0001..1.
        result = [shift_time((10000 - int(i * 10000 / total)) / 10000) for i in range(total)]
    elif scheduler == "normal":
        # ModelSamplingFlux.timestep is sigma; normal interpolates these before sigma().
        low = shift_time(0.0001)
        result = [shift_time(1 - i * (1 - low) / max(1, total - 1)) for i in range(total)]
    else:
        raise ValueError(f"Unsupported scheduler: {scheduler}")
    return result[-steps:]  # Diffusers appends terminal zero itself.
