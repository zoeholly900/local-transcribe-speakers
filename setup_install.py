"""Shared installer, invoked only by the platform setup wrappers."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper", action="store_true")
    args = parser.parse_args()
    if not (3, 10) <= sys.version_info[:2] <= (3, 12):
        sys.exit("请使用 Python 3.10–3.12（推荐 3.11），见 AGENTS.md 的 uv/conda 命令。")
    if sys.prefix == sys.base_prefix:
        sys.exit("请运行 setup.sh / setup.ps1，让它先创建隔离的 .venv。")
    if importlib.util.find_spec("pip") is None:
        # uv venv does not seed pip by default. ensurepip uses bundled wheels.
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], check=True)
    index = os.environ.get("TRANSCRIBE_PIP_INDEX", "https://mirrors.aliyun.com/pypi/simple/")
    pip = [sys.executable, "-m", "pip", "install", "--index-url", index]
    root = Path(__file__).resolve().parent

    def install(command):
        subprocess.run(command, check=True)

    install(pip + ["pip>=24,<27", "setuptools>=70,<81", "wheel"])
    if sys.platform != "darwin":
        # PyPI's Linux torch wheels pull CUDA libraries; use the CPU-only index.
        cpu_index = os.environ.get("TRANSCRIBE_TORCH_INDEX", "https://download.pytorch.org/whl/cpu")
        install([sys.executable, "-m", "pip", "install", "--index-url", cpu_index,
                 "torch==2.8.0", "torchaudio==2.8.0"])
    install(pip + ["-r", str(root / "requirements.txt")])
    # Upstream declares UMAP as mandatory. We deliberately provide the other
    # requirements above and never call its built-in speaker-clustering path.
    install(pip + ["--no-deps", "funasr==1.4.26"])
    if args.whisper:
        install(pip + ["faster-whisper>=1.2,<2"])
    if importlib.util.find_spec("umap") is not None:
        sys.exit("检测到旧 .venv 中装有 UMAP。请将 .venv 改名备份后重新 setup；不会自动删除你的环境。")
    print("正在检查核心依赖；首次导入可能较慢，请等待。", flush=True)
    install([sys.executable, "-c", "from funasr import AutoModel; import torch, torchaudio, sklearn, soundfile; print('核心依赖导入通过')"])
    print("安装完成。运行 ./run.sh 录音.m4a；Windows 运行 .\\run.ps1 录音.m4a。首次模型下载会先停下等待同意。")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        sys.exit("安装未完成，请查看上方错误和 AGENTS.md。可修复网络后重跑同一条 setup 命令。")
