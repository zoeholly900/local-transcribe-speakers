#!/usr/bin/env python3
"""Local ASR + CAM++ sentence embeddings + independent speaker clustering."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import gc
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

try:
    import numpy as np
except ImportError:
    sys.exit("缺少 NumPy。请先运行 setup.sh / setup.ps1，再用 run.sh / run.ps1 启动。")

MODELS = {
    "asr": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "punc": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
    "speaker": "iic/speech_campplus_sv_zh-cn_16k-common",
}
SAMPLE_RATE = 16000


def log(message):
    print(message, flush=True)


@contextmanager
def progress(message):
    """Heartbeat even while a library spends minutes inside one call."""
    started = time.monotonic()
    stop = threading.Event()
    log(message)

    def beat():
        while not stop.wait(20):
            log(f"{message} · 已用 {time.monotonic() - started:.0f} 秒，仍在处理")

    worker = threading.Thread(target=beat, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join()
    log(f"完成 · {time.monotonic() - started:.1f} 秒")


def normalize(vectors):
    x = np.asarray(vectors, dtype=np.float64)
    if x.ndim != 2 or not np.isfinite(x).all():
        raise ValueError("说话人向量必须是有限数值的二维数组。")
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    if np.any(norms < 1e-12):
        raise ValueError("出现空的说话人向量，请检查音频是否只有静音。")
    return x / norms


def renumber(labels):
    """Stable zero-based IDs in order of first appearance."""
    mapping = {}
    return np.array([mapping.setdefault(int(x), len(mapping)) for x in labels], dtype=int)


def merge_similar_centroids(vectors, labels, threshold=0.82):
    """Auto count: repeatedly merge the most similar weighted centroids."""
    labels = renumber(labels)
    while len(np.unique(labels)) > 1:
        ids = np.unique(labels)
        centers = normalize(np.stack([vectors[labels == i].mean(0) for i in ids]))
        similarities = centers @ centers.T
        np.fill_diagonal(similarities, -np.inf)
        a, b = np.unravel_index(np.argmax(similarities), similarities.shape)
        if similarities[a, b] < threshold:
            break
        labels[labels == ids[b]] = ids[a]
        labels = renumber(labels)
    return labels


def cluster_speakers(embeddings, durations, speakers=None, max_speakers=8,
                     merge_threshold=0.82, max_cluster_samples=2000):
    """Long sentences train clusters; short/unselected sentences use centroids.

    Bound the spectral graph to 2,000 sentences for long recordings. The fixed
    random seed makes sampling/clustering reproducible. No UMAP path is used.
    """
    from sklearn.cluster import AgglomerativeClustering, SpectralClustering

    if speakers is not None and speakers < 1 or max_speakers < 1:
        raise ValueError("说话人数必须大于 0。")
    if max_cluster_samples < 2 or not -1 <= merge_threshold <= 1:
        raise ValueError("聚类样本上限至少为 2，相似度阈值必须在 -1 到 1 之间。")
    durations = np.asarray(durations, dtype=float)
    if durations.ndim != 1 or len(durations) != len(embeddings):
        raise ValueError("句子时长与说话人向量数量不一致。")
    if not np.isfinite(durations).all() or np.any(durations < 0):
        raise ValueError("句子时长必须是非负有限数值。")
    if not len(durations):
        return np.array([], dtype=int)
    x = normalize(embeddings)
    eligible = np.flatnonzero(durations >= 1.2)
    if not len(eligible):
        if speakers and speakers > 1:
            raise ValueError("没有达到 1.2 秒的句子，无法按指定人数聚类；请用更长录音或 --speakers 1。")
        log("提示：所有句子都短于 1.2 秒，证据不足，暂归为说话人1。")
        return np.zeros(len(x), dtype=int)
    if speakers and speakers > min(len(eligible), max_cluster_samples):
        raise ValueError("指定人数超过可聚类的长句数，请降低 --speakers 或使用更长录音。")
    if len(eligible) > max_cluster_samples:
        eligible = np.sort(np.random.default_rng(0).choice(
            eligible, max_cluster_samples, replace=False))
    train = x[eligible]
    k = speakers if speakers is not None else min(max_speakers, len(train))
    if k == 1:
        return np.zeros(len(x), dtype=int)
    if len(train) < max(6, 2 * k):
        # Spectral eigensolvers require k < n; average linkage also handles n=2.
        labels = AgglomerativeClustering(n_clusters=k, linkage="average").fit_predict(train)
    else:
        labels = SpectralClustering(
            n_clusters=k, affinity="nearest_neighbors",
            n_neighbors=min(20, max(2, int(math.sqrt(len(train)))), len(train) - 1),
            random_state=0, assign_labels="kmeans", n_init=10,
        ).fit_predict(train)
    if speakers is None:
        labels = merge_similar_centroids(train, labels, merge_threshold)
    labels = renumber(labels)
    centers = normalize(np.stack([train[labels == i].mean(0) for i in np.unique(labels)]))
    all_labels = np.argmax(x @ centers.T, axis=1)
    all_labels[eligible] = labels
    return renumber(all_labels)


def smooth_labels(segments, labels):
    """One simultaneous pass: <=2s interjections flanked by the same speaker.

    Do not bridge silences longer than 2s. Read the original labels so edits
    cannot cascade and erase an entire alternating conversation.
    """
    original = np.asarray(labels, dtype=int)
    if len(original) != len(segments):
        raise ValueError("句子和标签数量不一致。")
    result = original.copy()
    for i in range(1, len(segments) - 1):
        short = segments[i]["end"] - segments[i]["start"] <= 2
        adjacent = (segments[i]["start"] - segments[i - 1]["end"] <= 2
                    and segments[i + 1]["start"] - segments[i]["end"] <= 2)
        if short and adjacent and original[i - 1] == original[i + 1] != original[i]:
            result[i] = original[i - 1]
    return renumber(result)


def timestamp(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def speaker_stats(segments):
    durations = {}
    for s in segments:
        durations[s["speaker"]] = durations.get(s["speaker"], 0) + s["end"] - s["start"]
    total = sum(durations.values())
    return [{"speaker": k, "duration_seconds": round(v, 3),
             "percentage": round(100 * v / total, 2) if total else 0.0}
            for k, v in sorted(durations.items())]


def render_markdown(segments):
    lines = ["# 录音转写", "", "| 说话人 | 句段时长 | 占比 |",
             "|---|---:|---:|"]
    for row in speaker_stats(segments):
        lines.append(f"| 说话人{row['speaker']} | {row['duration_seconds']:.1f} 秒 | {row['percentage']:.1f}% |")
    lines += ["", "占比按识别句段时长计算，不含句间静音；是估算值。说话人编号按首次出现排序，不代表真实身份。", ""]
    if not segments:
        lines.append("未检测到可转写的语音。")
    for s in segments:
        text = " ".join(s["text"].splitlines())
        lines.append(f"[{timestamp(s['start'])}] 说话人{s['speaker']}：{text}")
    return "\n".join(lines) + "\n"


def output_paths(source, out):
    md = Path(out).expanduser() if out else Path("outputs") / (source.stem + ".md")
    if md.suffix.lower() != ".md":
        md = md.with_suffix(".md")
    return md, md.with_suffix(".json")


def resolve_models(engine, whisper_model, allow_download):
    """Only download after explicit consent; inference receives local paths."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from modelscope.hub.snapshot_download import snapshot_download

    paths, missing = {}, []
    keys = ["speaker"] if engine == "whisper" else list(MODELS)
    for key in keys:
        try:
            paths[key] = snapshot_download(MODELS[key], local_files_only=True)
        except Exception:
            missing.append(key)
    if engine == "whisper":
        from faster_whisper.utils import download_model
        if Path(whisper_model).is_dir():
            paths["whisper"] = str(Path(whisper_model).resolve())
        else:
            try:
                paths["whisper"] = download_model(whisper_model, local_files_only=True)
            except Exception:
                missing.append("whisper")
    if missing and not allow_download:
        raise RuntimeError(
            "首次运行缺少模型：" + ", ".join(missing) + "。\n"
            "FunASR + CAM++ 首次下载约 2GB；Whisper 按型号额外下载（small 约 0.5GB）。\n"
            "模型下载需要联网，录音不上传。请先向用户说明大小并等待同意，\n"
            "同意后在原命令末尾加 --download-models；已有完整缓存时无需此选项。"
        )
    for key in missing:
        with progress(f"下载模型 {key}（只下载模型，不上传录音）"):
            paths[key] = (download_model(whisper_model) if key == "whisper"
                          else snapshot_download(MODELS[key]))
    return paths


def require_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise RuntimeError("缺少 ffmpeg。Mac：brew install ffmpeg；Windows：winget install Gyan.FFmpeg；"
                           "Ubuntu/Debian：sudo apt install ffmpeg。安装后重开终端再运行。")


def convert_audio(source, target):
    require_ffmpeg()
    with progress("1/5 转为 16kHz 单声道 WAV"):
        result = subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-c:a", "pcm_s16le", str(target),
        ], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("无法读取录音，请确认文件未损坏、格式受 ffmpeg 支持。\n" + result.stderr[-1500:])


def checked_segment(start, end, text, offset, chunk_duration):
    start, end = float(start), float(end)
    if not math.isfinite(start) or not math.isfinite(end):
        raise RuntimeError("模型返回了无效时间戳。")
    start, end = max(0.0, start), min(chunk_duration, end)
    if not str(text).strip() or end <= start:
        return None
    return {"start": round(offset + start, 3), "end": round(offset + end, 3),
            "text": str(text).strip()}


def recognize(wav, args, paths):
    import soundfile as sf
    if args.engine == "funasr":
        with progress("加载 FunASR（CPU）"):
            from funasr import AutoModel
            model = AutoModel(model=paths["asr"], vad_model=paths["vad"],
                              punc_model=paths["punc"], device="cpu",
                              disable_update=True, ncpu=args.threads)
            # Deliberately never pass spk_model: the built-in UMAP path is unused.
    else:
        with progress("加载 Whisper（CPU int8）"):
            from faster_whisper import WhisperModel
            model = WhisperModel(paths["whisper"], device="cpu", compute_type="int8",
                                 cpu_threads=args.threads, local_files_only=True)
    segments = []
    with sf.SoundFile(wav) as audio:
        duration = len(audio) / audio.samplerate
        count = math.ceil(duration / args.chunk_seconds)
        for i in range(count):
            offset = audio.tell() / audio.samplerate
            samples = audio.read(int(args.chunk_seconds * SAMPLE_RATE), dtype="float32")
            chunk_duration = len(samples) / SAMPLE_RATE
            with progress(f"2/5 识别 {i + 1}/{count} · {timestamp(offset)}"):
                if args.engine == "funasr":
                    result = model.generate(input=samples, batch_size_s=60,
                                            sentence_timestamp=True, hotword=args.hotword,
                                            disable_pbar=True)
                    rows = []
                    for item in result:
                        sentences = item.get("sentence_info", [])
                        if item.get("text", "").strip() and not sentences:
                            raise RuntimeError("FunASR 未返回句子时间戳。请重跑 setup，勿启用 spk_model。")
                        rows.extend((s["start"] / 1000, s["end"] / 1000, s["text"]) for s in sentences)
                else:
                    iterator, _ = model.transcribe(samples, language=args.language,
                                                   beam_size=5, vad_filter=True)
                    rows = ((s.start, s.end, s.text) for s in iterator)
                for start, end, text in rows:
                    segment = checked_segment(start, end, text, offset, chunk_duration)
                    if segment:
                        segments.append(segment)
            log(f"累计 {len(segments)} 句")
    del model
    gc.collect()
    return sorted(segments, key=lambda s: s["start"]), duration


def extract_embeddings(wav, segments, model_path, threads):
    import soundfile as sf
    with progress("加载 CAM++ 说话人模型（CPU）"):
        from funasr import AutoModel
        model = AutoModel(model=model_path, disable_update=True, device="cpu", ncpu=threads)
    embeddings = []
    started = time.monotonic()
    with sf.SoundFile(wav) as audio, progress(f"3/5 逐句提取说话人向量 · 共 {len(segments)} 句"):
        for i, segment in enumerate(segments):
            a = int(segment["start"] * SAMPLE_RATE)
            b = min(len(audio), int(segment["end"] * SAMPLE_RATE))
            audio.seek(a)
            samples = audio.read(b - a, dtype="float32")
            if not len(samples):
                raise RuntimeError(f"第 {i + 1} 句没有有效音频，无法计算说话人向量。")
            if len(samples) < int(0.8 * SAMPLE_RATE):
                samples = np.pad(samples, (0, int(0.8 * SAMPLE_RATE) - len(samples)), mode="wrap")
            result = model.generate(input=samples, disable_pbar=True)
            embedding = result[0]["spk_embedding"]
            if hasattr(embedding, "detach"):
                embedding = embedding.detach().cpu().numpy()
            embeddings.append(np.asarray(embedding).reshape(-1))
            if (i + 1) % 25 == 0 or i + 1 == len(segments):
                elapsed = time.monotonic() - started
                eta = elapsed / (i + 1) * (len(segments) - i - 1)
                log(f"向量 {i + 1}/{len(segments)} · 已用 {elapsed:.0f} 秒 · 预计剩余 {eta:.0f} 秒")
    del model
    gc.collect()
    return np.stack(embeddings)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="免费本地录音转写、分说话人，输出 Markdown 和 JSON。")
    parser.add_argument("audio", type=Path, help="本地录音文件，不接受网络 URL")
    parser.add_argument("--engine", choices=["funasr", "whisper"], default="funasr")
    parser.add_argument("--speakers", type=positive_int, help="指定人数；默认自动估计")
    parser.add_argument("--max-speakers", type=positive_int, default=8, help="自动估计上限（默认 8）")
    parser.add_argument("--merge-threshold", type=float, default=0.82, help="自动合并质心余弦阈值（默认 0.82）")
    parser.add_argument("--hotword", default="", help='FunASR 热词，例如 "Claude Codex WorkBuddy"')
    parser.add_argument("--out", help="输出 Markdown 文件路径，同时生成同名 JSON；默认 outputs/录音名.md")
    parser.add_argument("--whisper-model", default="small", help="Whisper 型号或本地模型目录（默认 small）")
    parser.add_argument("--language", help="Whisper 语言，例如 zh/en；默认自动识别")
    parser.add_argument("--chunk-seconds", type=positive_int, default=300, help="识别分块秒数（默认 300）")
    parser.add_argument("--threads", type=positive_int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--download-models", action="store_true", help="用户同意后，允许下载缺少的模型")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有输出")
    parser.add_argument("--debug", action="store_true", help="报错时显示完整堆栈（可能含本地路径）")
    args = parser.parse_args(argv)
    if not -1 <= args.merge_threshold <= 1:
        parser.error("--merge-threshold 必须在 -1 到 1 之间")
    if args.chunk_seconds > 1800:
        parser.error("--chunk-seconds 请设为 1–1800，避免长音频耗尽内存")
    return args


def run(args):
    source = args.audio.expanduser().resolve()
    if not source.is_file():
        raise RuntimeError("找不到录音文件，请提供本地完整路径，带空格的路径请加引号。")
    md, js = output_paths(source, args.out)
    if source in (md.resolve(), js.resolve()):
        raise RuntimeError("输出路径不能与输入录音相同。")
    if not args.overwrite and (md.exists() or js.exists()):
        raise RuntimeError("输出文件已存在。请换一个 --out 路径，或确认后加 --overwrite。")
    require_ffmpeg()
    if args.engine == "whisper" and args.hotword:
        log("提示：--hotword 仅用于 FunASR，Whisper 本次不使用热词。")
    with progress("检查本地模型缓存"):
        paths = resolve_models(args.engine, args.whisper_model, args.download_models)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="local-transcribe-") as temp:
        wav = Path(temp) / "audio.wav"
        convert_audio(source, wav)
        segments, duration = recognize(wav, args, paths)
        if segments:
            embeddings = extract_embeddings(wav, segments, paths["speaker"], args.threads)
            durations = [s["end"] - s["start"] for s in segments]
            with progress("4/5 聚类与短句平滑"):
                labels = cluster_speakers(embeddings, durations, args.speakers,
                                          args.max_speakers, args.merge_threshold)
                before = len(np.unique(labels))
                labels = smooth_labels(segments, labels)
                for segment, label in zip(segments, labels):
                    segment["speaker"] = int(label) + 1
                log(f"聚类 {before} 人，平滑后 {len(np.unique(labels))} 人（编号不代表真实身份）")
    metadata = {"engine": args.engine, "duration_seconds": round(duration, 3),
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "speakers_requested": args.speakers, "max_speakers": args.max_speakers,
                "merge_threshold": args.merge_threshold, "speaker_stats": speaker_stats(segments),
                "segments": segments}
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_markdown(segments), encoding="utf-8")
    js.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"5/5 完成 · {len(segments)} 句 · {metadata['elapsed_seconds']:.1f} 秒\n{md.resolve()}\n{js.resolve()}")


def main():
    args = parse_args()
    try:
        run(args)
        return 0
    except KeyboardInterrupt:
        log("已停止。原录音未改动；临时 WAV 已清理。")
        return 130
    except Exception as exc:
        if args.debug:
            raise
        if isinstance(exc, ImportError):
            log(f"缺少或无法加载依赖：{exc}\n请重新执行 setup，并用 run 脚本运行；Whisper 需 setup 的可选参数。")
        else:
            log(f"未完成：{exc}\n排查步骤见 AGENTS.md；需要完整错误时加 --debug。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
