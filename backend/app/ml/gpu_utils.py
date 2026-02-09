"""GPU detection and configuration utilities for ML training.

Supports NVIDIA CUDA GPUs via CmdStanPy OpenCL backend for Prophet.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def detect_gpu() -> dict[str, Any]:
    """Detect available GPU hardware and return capabilities.

    Returns
    -------
    dict
        Keys: ``available`` (bool), ``device_name``, ``cuda_version``,
        ``gpu_count``, ``memory_mb``.
    """
    info: dict[str, Any] = {
        "available": False,
        "device_name": None,
        "cuda_version": None,
        "gpu_count": 0,
        "memory_mb": 0,
        "opencl_available": False,
    }

    # Check nvidia-smi
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        logger.info("nvidia-smi not found — no NVIDIA GPU detected")
        return info

    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            info["gpu_count"] = len(lines)

            # Parse first GPU
            parts = lines[0].split(", ")
            if len(parts) >= 3:
                info["device_name"] = parts[0].strip()
                info["memory_mb"] = int(float(parts[1].strip()))
                info["cuda_version"] = parts[2].strip()
                info["available"] = True

            logger.info(
                "Detected %d GPU(s): %s (%d MB, driver %s)",
                info["gpu_count"],
                info["device_name"],
                info["memory_mb"],
                info["cuda_version"],
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("nvidia-smi failed: %s", exc)

    # Check OpenCL availability (for CmdStanPy GPU)
    if info["available"]:
        try:
            import pyopencl as cl  # type: ignore
            platforms = cl.get_platforms()
            if platforms:
                info["opencl_available"] = True
                logger.info("OpenCL available with %d platform(s)", len(platforms))
        except ImportError:
            logger.debug("pyopencl not installed — OpenCL GPU acceleration unavailable")
        except Exception as exc:
            logger.debug("OpenCL detection failed: %s", exc)

    return info


def configure_cmdstanpy_gpu(use_gpu: bool = True) -> bool:
    """Configure CmdStanPy to use GPU (OpenCL) backend if available.

    Parameters
    ----------
    use_gpu:
        If ``False``, skip GPU configuration even if available.

    Returns
    -------
    bool
        ``True`` if GPU backend was successfully configured.
    """
    if not use_gpu:
        logger.info("GPU training disabled by flag")
        return False

    gpu_info = detect_gpu()
    if not gpu_info["available"]:
        logger.info("No GPU available, using CPU backend")
        return False

    try:
        import cmdstanpy  # type: ignore

        # Set OpenCL device for Stan
        # CmdStanPy uses STAN_OPENCL=true environment variable
        os.environ["STAN_OPENCL"] = "true"
        os.environ["OPENCL_DEVICE_TYPE"] = "GPU"

        logger.info(
            "CmdStanPy GPU (OpenCL) backend configured: %s (%d MB)",
            gpu_info["device_name"],
            gpu_info["memory_mb"],
        )
        return True
    except ImportError:
        logger.warning("cmdstanpy not installed — cannot configure GPU backend")
        return False
    except Exception as exc:
        logger.warning("Failed to configure GPU backend: %s", exc)
        return False


def get_stan_threads_per_chain(gpu_enabled: bool = False) -> int:
    """Return optimal threads_per_chain for Stan sampling.

    When GPU is enabled, Stan uses fewer CPU threads since the heavy
    linear algebra runs on the GPU.
    """
    cpu_count = os.cpu_count() or 4
    if gpu_enabled:
        # GPU handles LA; use fewer CPU threads
        return max(1, cpu_count // 4)
    return max(1, cpu_count // 2)
