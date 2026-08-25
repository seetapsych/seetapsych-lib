# -*- coding: utf-8 -*-

import platform
import subprocess

import pynvml


__all__ = [
    'list_nvidia_devices',
]


def list_nvidia_devices():
    """
    Cross-platform detection of NVIDIA GPUs.
    Returns a list of GPU names. Returns an empty list if no NVIDIA GPU or driver is found.
    """
    system = platform.system()
    gpu_names = []

    # 1. Priority: Use pynvml for professional detection (Works on Windows & Linux)
    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            # pynvml 12+ versions may return bytes, need to decode
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            gpu_names.append(name)
        pynvml.nvmlShutdown()
        if gpu_names:
            return gpu_names
    except Exception:
        pass

    # 2. Fallback: Use system commands if pynvml fails
    try:
        if system == "Windows":
            # Method A: Try nvidia-smi (Standard method)
            try:
                output = subprocess.check_output(['nvidia-smi', '--list-gpus'], stderr=subprocess.STDOUT)
                # Output format: "GPU 0: NVIDIA GeForce RTX 3090 (UUID: ...)"
                lines = output.decode('utf-8', errors='ignore').strip().split('\n')
                for line in lines:
                    if "GPU" in line and ":" in line:
                        # Extract name between ":" and "("
                        name = line.split(":")[1].split("(")[0].strip()
                        gpu_names.append(name)
                if gpu_names:
                    return gpu_names
            except Exception:
                pass

            # Method B: Windows specific fallback using wmic (No nvidia-smi dependency)
            # Queries the display adapters directly from the system
            try:
                output = subprocess.check_output(
                    'wmic path win32_VideoController get name',
                    shell=True,
                    stderr=subprocess.STDOUT
                )
                lines = output.decode('gbk', errors='ignore').strip().split('\n')
                for line in lines:
                    line = line.strip()
                    # Filter header and empty lines, look for NVIDIA keyword
                    if line and line != "Name" and "NVIDIA" in line:
                        gpu_names.append(line)
                return gpu_names
            except Exception:
                pass

        elif system == "Linux":
            # Method A: Try nvidia-smi
            try:
                output = subprocess.check_output(['nvidia-smi', '--list-gpus'], stderr=subprocess.STDOUT)
                lines = output.decode('utf-8', errors='ignore').strip().split('\n')
                for line in lines:
                    if "GPU" in line and ":" in line:
                        name = line.split(":")[1].split("(")[0].strip()
                        gpu_names.append(name)
                if gpu_names:
                    return gpu_names
            except Exception:
                pass

            # Method B: Linux specific fallback using lspci (Hardware level check)
            try:
                output = subprocess.check_output('lspci | grep -i nvidia', shell=True, stderr=subprocess.STDOUT)
                devices = output.decode('utf-8', errors='ignore').strip().split('\n')
                for device in devices:
                    if device:
                        gpu_names.append(device.strip())
                return gpu_names
            except Exception:
                pass

    except Exception:
        pass

    return gpu_names

# --- Usage Example ---
if __name__ == "__main__":
    gpus = list_nvidia_devices()

    if len(gpus) > 0:
        print(f"Success: Detected {len(gpus)} NVIDIA GPU(s).")
        for i, name in enumerate(gpus):
            print(f" - GPU {i}: {name}")
    else:
        print("Result: No NVIDIA GPU or compatible driver detected.")