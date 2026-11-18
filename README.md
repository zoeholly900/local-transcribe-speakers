# 本地转写 · 分说话人

**长录音整理工具**：把一场几十分钟到几小时的会议、访谈、课程录音，免费在自己电脑上整理成「谁在什么时间说了什么」的 Markdown 和 JSON，丢给你的 AI agent 接着做纪要、提金句、写文章。

它不是语音输入法（说一句出一句、实时打字），而是对标通义听悟、飞书妙记、讯飞听见这类「录音转文字＋分发言人」工具的本地版。

**把这句话丢给你的 agent（Claude Code / Codex / WorkBuddy）：**

```text
请按 https://github.com/zoeholly900/local-transcribe-speakers 中的 AGENTS.md，在我的电脑上安装并运行这个项目，
把「<录音完整路径>」转成文字、分出谁在说话，交给我 Markdown 和 JSON。
首次下载模型约 2GB，请先告诉我并等我同意；不要上传录音或转写结果。
```

效果示例（虚构）：`[00:00:12] 说话人2：我们下周再讨论这个方案。`

## 它的四个点

1. **免费、不限时长**：全在你自己的电脑上算，没有会员，没有分钟额度。
2. **录音不出电脑**：访谈、面试、咨询、内部会议、带学员或孩子的录音，不用先传到谁的服务器。安装包和首次模型下载要联网，识别过程不上传。也请让你的 agent 把原文和音频留在本地，别发给云端模型。
3. **分出谁说了什么，带时间戳**：每句一行，顶部有各人说话时长占比。
4. **出来就是给 AI 用的格式**：`.md` 和 `.json`，直接交给 agent 写纪要、提金句、改写成文章。安装也是一句话丢给 agent。

## 如实说短板

- 要在自己的电脑上跑，比云端慢，不是实时的：真人 10 分钟录音约 1 分钟出稿（M 系列 CPU）。
- 个别词不如听悟这类云端服务准，英文工具名和人名尤其容易错；可用 `--hotword` 给热词，英文多时试 `--engine whisper`。
- 分说话人是算法估计，不是 100%：短句、插话、抢话、声音相近的人会分错；署名引用前请回听。
- 第一次要下载约 2GB 模型。

## 真人实测

真人 10 分钟 6 人会议实测（一位主讲＋五位参与者，M 系列 CPU）：

| 做法 | 分出人数 | 与人工确认标签的对齐率 | 耗时 |
|---|---|---|---|
| 默认自动估计 | 5 人 | 89.3% | 57 秒 |
| `--speakers 6`（按真实人数指定） | 6 人 | 72.1% | 58 秒 |

- **指定了真实人数反而更差**：有位参与者只说了约半分钟，强制分成 6 组时算法把主讲拆成了两个人、没有把这位小声说话的人单独分出来。人数不确定时先用默认自动估计。
- **自动估计没分出的**：说话最少的那位被并进了主讲。
- 对照标签本身是同一套声纹向量聚类，再用自我介绍等线索人工确认的，不是逐句人工听写，所以这是「对齐率」，不是严格准确率。只测了一段录音。
- 合并阈值（`--merge-threshold`）扫了 0.70 / 0.76 / 0.88 / 0.92：0.70–0.82 结果相同（5 人，89.3%），调高会过度拆分（0.88 → 7 人 74.7%，0.92 → 8 人 64.4%），所以默认值 0.82 不变。
- 耗时参考：已有 M 系列 CPU 流程处理过 4 小时录音，识别约 22 分钟、向量约 6 分钟；换机器和分块设置会变，并非性能承诺。

录音和转写不在仓库里，也不会进示例。

## 它是怎么做到的

大白话：先把录音按停顿切成一句一句，每句转成文字；再给每句话取一个「声纹」（一串数字，同一个人说的话声纹相近）；最后把声纹相近的句子归成一堆，一堆就是一个人。

```text
录音 ──ffmpeg──▶ 16kHz 单声道
        │
   ① 切句   FSMN-VAD 按停顿切成一句一句
        │
   ② 识别   Paraformer 转成文字，CT-Transformer 加标点
        │
   ③ 取声纹  CAM++ 给每一句取一个说话人向量
        │
   ④ 聚类   我们自己做：先故意多分几组（上限 8）
        │
   ⑤ 合并   声纹质心相似度 ≥0.82 的并成一个人（可 --speakers 指定人数）
        │
   ⑥ 平滑   被同一个人夹在中间的 2 秒内短句，并回这个人
        │
     出稿   .md（说话人＋时间戳＋占比）＋ .json
```

④⑤⑥ 是本项目自己的一步，原因：

- **不用 FunASR 自带的说话人聚类**：在我们的 4 小时真实录音上，它把全场并成了 1 个人；并且它的 UMAP 路径与新版 NumPy 有冲突。所以只借 CAM++ 取声纹，聚类自己做。
- **先多分再合并**：直接猜人数容易少猜；先切细再把相似的并起来，同一人在「近话筒」和「走动答疑」两种音色下被拆开，也能并回去。
- **短句归属和平滑**：短于 1.2 秒的句子声纹不稳，不参与聚类，按最近的人归属；被夹在中间的极短句并回前后同一人，减少「嗯」「对」造成的跳来跳去。

## 致谢与许可

本项目代码是 MIT（见 [LICENSE](LICENSE)），**只分发我们自己写的代码**。下列上游不随仓库分发：库由 `pip` 安装，**模型权重从官方下载，遵守各自的许可**。许可证以官方为准，核对日期 2026-11-16；换了模型版本请重看其模型卡。

| 项目 | 作者/机构 | 用来做什么 | 许可证 |
|---|---|---|---|
| [FunASR](https://github.com/modelscope/FunASR) | 阿里巴巴达摩院语音团队 / FunASR contributors | 语音识别工具包 | [MIT](https://github.com/modelscope/FunASR/blob/v1.4.26/LICENSE) |
| [Paraformer / SeACo-Paraformer](https://modelscope.cn/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch) | 阿里巴巴语音团队 | 中文识别（含热词） | 模型卡声明 Apache-2.0 |
| [FSMN-VAD](https://modelscope.cn/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch) | 阿里达摩院语音团队 | 切句 | 模型卡声明 Apache-2.0 |
| [CT-Transformer 标点](https://modelscope.cn/models/iic/punc_ct-transformer_cn-en-common-vocab471067-large) | 阿里语音团队 | 加标点 | 模型卡声明 Apache-2.0 |
| [CAM++](https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common) / [3D-Speaker](https://github.com/modelscope/3D-Speaker) | 阿里语音 / 3D-Speaker 团队 | 说话人向量 | 模型卡 Apache-2.0；3D-Speaker 代码 [Apache-2.0](https://github.com/modelscope/3D-Speaker/blob/main/LICENSE) |
| [ModelScope](https://github.com/modelscope/modelscope) | 魔搭社区 | 模型下载 | [Apache-2.0](https://github.com/modelscope/modelscope/blob/master/LICENSE) |
| [Whisper](https://github.com/openai/whisper)（可选） | OpenAI | 英文工具名更强的可选引擎 | [MIT](https://github.com/openai/whisper/blob/main/LICENSE) |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [CTranslate2](https://github.com/OpenNMT/CTranslate2)（可选） | SYSTRAN / OpenNMT | 跑 Whisper | MIT |
| [PyTorch](https://github.com/pytorch/pytorch) | PyTorch contributors | 模型运行 | [BSD 风格](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| [scikit-learn](https://github.com/scikit-learn/scikit-learn) | scikit-learn developers | 谱聚类 | [BSD-3-Clause](https://github.com/scikit-learn/scikit-learn/blob/main/COPYING) |
| [NumPy](https://github.com/numpy/numpy) / [SciPy](https://github.com/scipy/scipy) | NumPy / SciPy developers | 数值计算 | BSD-3-Clause |
| [soundfile](https://github.com/bastibe/python-soundfile) | Bastian Bechtold 等 | 读音频 | BSD-3-Clause |
| [FFmpeg](https://ffmpeg.org/)（系统依赖，不分发） | FFmpeg developers | 音频转码 | LGPL / GPL，视你装的构建而定 |

**关于模型许可**：以上四个 `iic/` 模型当前官方模型卡均写 Apache-2.0。但 FunASR 仓库另有一份针对其部分模型的 [MODEL_LICENSE](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)（要求注明出处、保留模型名称，商业使用条款未明），只在模型卡链接它的模型上适用。你换用其他模型，或要商用、再分发模型，请先读该模型的官方模型卡。我们不能把上游权重算作 MIT。

论文引用（BibTeX）在 [CITATIONS.bib](CITATIONS.bib)：FunASR、Paraformer、SeACo-Paraformer、Deep-FSMN、CT-Transformer、CAM++、3D-Speaker、Whisper、ModelScope、PyTorch、scikit-learn、NumPy、SciPy。

安装运行见 [AGENTS.md](AGENTS.md)。
