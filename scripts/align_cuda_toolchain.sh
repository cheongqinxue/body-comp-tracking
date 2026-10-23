#!/usr/bin/env bash
# Align pip CUDA compiler packages with PyTorch CUDA 13.0 (llm conda env).
#
# Run once after creating/upgrading the llm env, or whenever pip upgrades
# nvidia-cuda-crt / nvidia-cuda-cccl back to 13.3.x.
set -euo pipefail

CONDA_ENV="${CONDA_ENV:-llm}"
PYTHON="${PYTHON:-${HOME}/anaconda3/envs/${CONDA_ENV}/bin/python}"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Python not found: ${PYTHON}" >&2
  echo "Set PYTHON or CONDA_ENV if your conda install differs." >&2
  exit 1
fi

echo "Aligning CUDA compiler toolchain in: ${CONDA_ENV}" >&2
"${PYTHON}" -m pip install \
  'nvidia-cuda-nvcc==13.0.88' \
  'nvidia-nvvm==13.0.88' \
  'nvidia-cuda-crt==13.0.88' \
  'nvidia-cuda-cccl==13.0.85'

CU13="$("${PYTHON}" -c "import nvidia.cu13, pathlib; print(pathlib.Path(nvidia.cu13.__file__).resolve().parent)")"

# FlashInfer's linker expects lib64/libcudart.so; pip cu13 ships lib/libcudart.so.13.
if [[ -d "${CU13}/lib" && ! -e "${CU13}/lib64" ]]; then
  ln -sf lib "${CU13}/lib64"
  echo "Created ${CU13}/lib64 -> lib" >&2
fi
if [[ -f "${CU13}/lib/libcudart.so.13" && ! -e "${CU13}/lib/libcudart.so" ]]; then
  ln -sf libcudart.so.13 "${CU13}/lib/libcudart.so"
  echo "Created ${CU13}/lib/libcudart.so -> libcudart.so.13" >&2
fi

echo >&2
echo "Compiler toolchain (should all be 13.0.x):" >&2
"${PYTHON}" -m pip show \
  nvidia-cuda-nvcc nvidia-nvvm nvidia-cuda-crt nvidia-cuda-cccl \
  nvidia-nvjitlink nvidia-cuda-nvrtc \
  2>/dev/null | rg '^(Name|Version):'

echo >&2
echo "PyTorch CUDA:" >&2
"${PYTHON}" -c "import torch; print(torch.__version__, 'cuda', torch.version.cuda)"

echo >&2
echo "Done. Re-run only if pip upgrades crt/cccl/nvcc again." >&2
