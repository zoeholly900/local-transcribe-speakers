# Agent 操作说明

目标：在用户电脑上将本地录音转成带时间戳、说话人及占比的 Markdown，同时交付 JSON。只使用 CLI 和本地文件；不上传录音、转写结果或音频片段，不将内容回传给云端模型。不自动发布、提交 Git 或改动原录音。

## 1. 检查环境

在仓库目录操作。先确定录音完整路径与输出位置，不要把真实录音或结果加入仓库。运行 `ffmpeg -version`；缺少时按平台安装：

| 平台 | ffmpeg | Python |
|---|---|---|
| macOS（Apple Silicon） | `brew install ffmpeg` | `brew install python@3.11` |
| Windows x64 PowerShell | `winget install Gyan.FFmpeg` | `winget install Python.Python.3.11` |
| Ubuntu / Debian Linux | `sudo apt update` 后 `sudo apt install ffmpeg python3-venv` | 先 `python3 --version`，不合适时用下面 uv/conda |

Windows 安装后重开 PowerShell，让 PATH 生效。其他 Linux 发行版用本机包管理器安装 ffmpeg。全部在 CPU 上运行，Mac 不需要 CUDA；Windows ARM / Linux ARM 是否有对应 PyTorch/Whisper wheel 取决于上游，未验证。

推荐 Python 3.11，支持范围 3.10–3.12。3.13+ 可能没有 FunASR 依赖的 wheel，不要硬装或修改系统 Python。已有 uv 时：

```sh
uv venv --python 3.11 .venv
```

uv 会在需要时下载 Python。已有 conda 时可先 `conda create -n local-transcribe python=3.11 -y`、`conda activate local-transcribe`，再 `python -m venv .venv`。随后仍执行 setup。不必激活 `.venv`。

## 2. 一条 setup

macOS / Linux：

```sh
./setup.sh
```

Windows PowerShell：

```powershell
.\setup.ps1
```

setup 创建仓库内 `.venv`、安装固定范围依赖并检查导入，不下载模型。macOS 可用 `PYTHON=/完整路径/python3.11 ./setup.sh`，Windows 可用 `.\setup.ps1 -Python 'C:\完整路径\python.exe'` 指定解释器。已有 `.venv` 会复用；版本不对时先改名备份，再建新环境。不要借用别人的环境作为安装方案。

pip 默认 `https://mirrors.aliyun.com/pypi/simple/`。Windows/Linux 的 PyTorch 例外：从官方 `https://download.pytorch.org/whl/cpu` 安装 CPU wheel，避免自动拉入 CUDA。若镜像无对应包或超时，修复网络后重跑；可显式设置 `TRANSCRIBE_PIP_INDEX=https://pypi.org/simple`，CPU wheel 源可用 `TRANSCRIBE_TORCH_INDEX` 指向可信且包含对应 CPU wheel 的镜像。PowerShell 环境变量语法是 `$env:TRANSCRIBE_PIP_INDEX='https://pypi.org/simple'`。

## 3. 一条 run；首次下载先等用户

```sh
./run.sh "/完整路径/录音.m4a" --out "/完整路径/转写.md"
```

```powershell
.\run.ps1 'C:\完整路径\录音.m4a' --out 'C:\完整路径\转写.md'
```

等价入口：macOS/Linux `.venv/bin/python transcribe.py 录音.m4a`，Windows `.venv\Scripts\python.exe transcribe.py 录音.m4a`。不带 `--out` 时写入**当前工作目录**的 `outputs/录音名.md` 和 `.json`；`--out` 是文件路径，不是目录，扩展名统一为 `.md`。已有输出默认拒绝覆盖；确认需要覆盖时加 `--overwrite`。

**首次模型下载约 2GB（另需 Python 包及临时磁盘空间）。先告诉用户大小、来源、只下载模型不上传录音，然后等待明确同意。** 命令检测到缺少模型会停下；用户同意后，原命令追加 `--download-models` 再运行。不要自行替用户同意。已存在缓存不会重复要求确认。网络中断后可重试同一命令；缓存不全、损坏或磁盘不足时不要把失败说成成功。

默认用 ModelScope 的 `paraformer-zh` 对应模型、`fsmn-vad`、`ct-punc` 和独立 CAM++，模型 ID 见 `transcribe.py` 的 `MODELS`。缓存由 ModelScope 管理（通常 `~/.cache/modelscope`，可在运行前设置 `MODELSCOPE_CACHE`）。程序先只查本地缓存，再将本地模型路径传给 FunASR，关闭更新检查；缓存完整后可断网运行。

常用参数：

```sh
./run.sh 录音.m4a --speakers 3 --hotword "Claude Codex WorkBuddy" --out 转写.md
```

- `--speakers N`：手动指定聚类人数；人数多于有效长句数会报错。平滑可能消除仅占一个短句的组，日志会报告平滑前后人数。
- 默认自动人数：先按 `--max-speakers 8` 上限聚类，再重复合并质心余弦相似度 ≥`--merge-threshold 0.82` 的组；阈值越低越易合并。它是启发式估计，不能保证真实人数。编号只按首次出现排序，不能据此猜真实姓名。
- `--chunk-seconds 300`：默认每 5 分钟识别一块，累计全局时间戳；块边界可能切断词句，必要时调整分块长度后回听该处。
- `--threads 4`：默认最多 4 个 CPU 线程，可调。内存不足时先把块长降至 60–120 秒。
- `--hotword "词1 词2"`：只传给 FunASR，不能保证所有热词正确。

### 可选 Whisper

英文或英文工具名较多时可试 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)，它仍使用同一套 CAM++、聚类和平滑流程，时间戳来自 Whisper 句段：

```sh
./setup.sh --whisper
./run.sh 录音.m4a --engine whisper --whisper-model small --language zh
```

```powershell
.\setup.ps1 -Whisper
.\run.ps1 录音.m4a --engine whisper --whisper-model small --language zh
```

默认 `small`，CPU int8；省略 `--language` 时自动识别。模型从 Hugging Face 的 `Systran/faster-whisper-small` 下载，约 0.5GB；其他型号大小不同，仍需先说明并等待同意再加 `--download-models`。CAM++ 仍从 ModelScope 下载。`--whisper-model` 也接受已下载的 CTranslate2 模型目录。

海外通常直接使用 Hugging Face 官方源即可；中国大陆访问 HF 困难时，可在用户信任镜像的前提下设置 `HF_ENDPOINT=https://hf-mirror.com`（PowerShell：`$env:HF_ENDPOINT='https://hf-mirror.com'`）。这是第三方镜像，并非本项目服务；只影响 HF 模型，不会把 FunASR/CAM++ 的 ModelScope ID 自动改成 HF ID。默认中文流程保持 ModelScope。参考 [FunASR API 文档](https://github.com/modelscope/FunASR/blob/main/docs/python_api.md)。

## 4. 验证与交付

1. 先跑 `.venv/bin/python -m pytest`（Windows 用 `.venv\Scripts\python.exe -m pytest`）。也可 `python tests/test_cluster.py`，只需 NumPy 和 scikit-learn，不下载模型、不读音频。
2. 先用约 3 分钟的本地录音试跑，确认退出码 0，`.md` 和 `.json` 都存在。不要打印或上传真实转写原文。用本地代码检查 `segments` 非空（静音应为空并提示）、时间戳递增、`0 <= start < end <= duration_seconds`、每句有 `text` 和从 1 开始的整数 `speaker`；统计占比总和约 100%，四舍五入允许误差。空录音结果的统计为空。
3. 再跑全长。心跳每 20 秒、向量每 25 句输出一次，不能因短暂无输出就判断死机。4 小时 WAV 约 460MB 临时磁盘，识别一次只读一个块；向量一次只读一句，聚类最多抽取 2,000 个 ≥1.2 秒长句，其余按最近质心归属。随机种子固定，稀少说话人仍可能被漏采样。
4. 交付两个文件的完整路径，报告句数、估计人数及耗时。请用户本地回听短句、抢话、署名引用处；不要宣称逐字准确、身份已确认或多人重叠已分离。输出原句，不做基于猜测的人名修正。

## 踩坑与报错

- **不要给 FunASR 设置 `spk_model`**：在已验证的长录音中，其自带聚类把全场并成 1 人。本项目仅用 `AutoModel(CAM++)` 提向量，sklearn `SpectralClustering(nearest_neighbors)` 独立聚类；邻居数不超过训练样本数减 1，小样本退化为凝聚聚类。
- **UMAP / NumPy 报 `Cannot interpret 'torch.float32' as a data type`**：走到了不需要的自带聚类。不要装 UMAP 补救。FunASR 1.4.26 的包元数据默认要求 UMAP，所以 setup 用 `--no-deps` 单独安装 FunASR，其他运行依赖在 `requirements.txt` 中明确安装。不用 `pip install funasr`、`funasr[all]` 或自动补齐依赖。`pip check` 因此会报告缺 `umap-learn`，这一项是刻意绕开；其他缺依赖仍需修复。
- **短句不稳定**：短于 0.8 秒的波形循环填充后取向量，只有 ≥1.2 秒句子参与聚类。夹在同一人两句之间、长度 ≤2 秒且间隔不超过 2 秒的句子并入该人。全是短句时自动模式暂归为 1 人并提示证据不足；手动多人数会报错。
- **缺 ffmpeg / 文件找不到**：按第 1 步安装，重开终端；完整路径加引号，确认文件可读。ffmpeg 处理格式转换，不需要手工转 wav。
- **No matching distribution / Python 3.13+**：按第 1 步使用 uv/conda 的 3.11，新建 `.venv`，不要降级系统 Python。
- **句子时间戳缺失**：必须 `sentence_timestamp=True`，固定本项目 FunASR 版本；不要为了获得时间戳打开 `spk_model`。
- **Whisper ModuleNotFoundError / DLL 加载失败**：先重跑带 Whisper 参数的 setup；Windows 使用 64 位 Python，必要时安装微软 Visual C++ 2015–2022 x64 Runtime。
- **pip 报 `Unable to connect to proxy ... Operation not permitted`**：是 agent 的沙箱拦了本机代理，不是项目坏了；向用户申请放行网络/代理后重跑 setup（验收中 Codex 即遇到，放行后一次装好）。
- **模型下载失败**：检查磁盘、代理和模型源连接，重试；不要关闭 TLS 校验、上传录音到网页或偷偷切换云识别。
- **任务失败或中断**：退出码非 0 不能交付为成功。正常中断会清理临时 WAV；强制终止或断电可能残留系统临时目录中的 `local-transcribe-*`，只清理确认属于本次的目录。不会自动断点续跑。`--debug` 提供完整堆栈，分享前去除个人路径或内容。

代码许可证为 MIT；FunASR、PyTorch、faster-whisper、模型权重各用各的许可证。本仓库不分发模型或真实音频。
