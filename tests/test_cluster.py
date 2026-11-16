"""Synthetic vectors only: python tests/test_cluster.py or python -m pytest."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcribe import (cluster_speakers, merge_similar_centroids, normalize,
                        render_markdown, smooth_labels, speaker_stats,
                        checked_segment, output_paths, parse_args)


def blobs(groups=3, count=30):
    rng = np.random.default_rng(42)
    centers = np.eye(12)[:groups]
    x = np.concatenate([c + rng.normal(0, 0.025, (count, 12)) for c in centers])
    return normalize(x), np.repeat(np.arange(groups), count)


class ClusterTests(unittest.TestCase):
    def test_manual_spectral(self):
        x, truth = blobs()
        labels = cluster_speakers(x, np.full(len(x), 3), speakers=3)
        self.assertEqual(len(set(labels)), 3)
        for group in set(truth):
            self.assertEqual(len(set(labels[truth == group])), 1)

    def test_auto_three_speakers(self):
        x, truth = blobs()
        labels = cluster_speakers(x, np.full(len(x), 3))
        self.assertEqual(len(set(labels)), 3)
        for group in set(truth):
            self.assertEqual(len(set(labels[truth == group])), 1)

    def test_auto_one_speaker(self):
        x, _ = blobs(groups=1)
        self.assertEqual(set(cluster_speakers(x, np.full(len(x), 3))), {0})

    def test_manual_count_does_not_merge(self):
        x, _ = blobs(groups=1)
        self.assertEqual(len(set(cluster_speakers(x, np.full(len(x), 3), speakers=2))), 2)

    def test_small_spectral_graph(self):
        x, _ = blobs(groups=2, count=8)
        labels = cluster_speakers(x, [1.2] * 16, speakers=2)
        self.assertEqual(set(labels[:8]), {0})
        self.assertEqual(set(labels[8:]), {1})

    def test_auto_cap(self):
        x, _ = blobs(groups=5)
        self.assertLessEqual(len(set(cluster_speakers(x, np.full(len(x), 3), max_speakers=2))), 2)

    def test_centroid_merge(self):
        x = normalize([[1, 0], [.99, .01], [0, 1], [0.01, .99]])
        self.assertEqual(merge_similar_centroids(x, [0, 1, 2, 3]).tolist(), [0, 0, 1, 1])

    def test_tiny_samples(self):
        for count in range(1, 6):
            x = np.eye(count)
            labels = cluster_speakers(x, np.full(count, 2), speakers=count)
            self.assertEqual(len(set(labels)), count)
        self.assertEqual(cluster_speakers([[1, 0], [-1, 0]], [2, 2], speakers=1).tolist(), [0, 0])

    def test_nearest_short_sentence(self):
        x, _ = blobs(groups=2)
        x = np.vstack([x, x[0], x[-1]])
        labels = cluster_speakers(x, [3] * 60 + [0.4, 1], speakers=2)
        self.assertEqual(labels[-2], labels[0])
        self.assertEqual(labels[-1], labels[59])

    def test_no_long_sentences(self):
        x = np.eye(3)
        self.assertEqual(cluster_speakers(x, [.2, .6, 1]).tolist(), [0, 0, 0])
        with self.assertRaises(ValueError):
            cluster_speakers(x, [.2, .6, 1], speakers=2)

    def test_bounded_sampling_deterministic(self):
        x, _ = blobs(groups=2, count=100)
        a = cluster_speakers(x, [3] * 200, speakers=2, max_cluster_samples=50)
        b = cluster_speakers(x, [3] * 200, speakers=2, max_cluster_samples=50)
        np.testing.assert_array_equal(a, b)
        self.assertEqual(set(a[:100]), {0})
        self.assertEqual(set(a[100:]), {1})

    def test_empty_and_invalid(self):
        self.assertEqual(len(cluster_speakers(np.empty((0, 12)), [])), 0)
        for vectors, durations, count in [([[0, 0]], [2], None),
                                           ([[float('nan'), 1]], [2], None),
                                           ([[1, 0]], [2], 2),
                                           ([[1, 0]], [-2], None),
                                           ([[1, 0]], [], None)]:
            with self.assertRaises(ValueError):
                cluster_speakers(vectors, durations, speakers=count)


class OutputTests(unittest.TestCase):
    def test_smoothing(self):
        segments = [{"start": 0, "end": 3}, {"start": 3, "end": 5},
                    {"start": 5, "end": 9}]
        self.assertEqual(smooth_labels(segments, [0, 1, 0]).tolist(), [0, 0, 0])
        segments[1]["end"] = 5.1
        self.assertEqual(smooth_labels(segments, [0, 1, 0]).tolist(), [0, 1, 0])

    def test_smoothing_no_cascade_or_silence_bridge(self):
        segments = [{"start": i, "end": i + 1} for i in range(5)]
        self.assertEqual(smooth_labels(segments, [0, 1, 0, 1, 0]).tolist(), [0, 0, 1, 0, 0])
        segments = [{"start": 0, "end": 1}, {"start": 10, "end": 11}, {"start": 20, "end": 21}]
        self.assertEqual(smooth_labels(segments, [0, 1, 0]).tolist(), [0, 1, 0])

    def test_markdown_and_stats(self):
        segments = [{"start": 0, "end": 3, "speaker": 1, "text": "今天讨论虚构项目。"},
                    {"start": 3661, "end": 3662, "speaker": 2, "text": "好的。\n下周继续。"}]
        md = render_markdown(segments)
        self.assertIn("[01:01:01] 说话人2：好的。 下周继续。", md)
        self.assertIn("75.0%", md)
        self.assertEqual(sum(x["percentage"] for x in speaker_stats(segments)), 100)
        self.assertIn("未检测到", render_markdown([]))
        self.assertNotIn("nan", render_markdown([]))

    def test_chunk_offsets_and_paths(self):
        self.assertEqual(checked_segment(1, 3, "虚构", 300, 2),
                         {"start": 301, "end": 302, "text": "虚构"})
        self.assertIsNone(checked_segment(2, 2, "虚构", 0, 3))
        self.assertEqual(output_paths(Path("录音.m4a"), "稿.json"), (Path("稿.md"), Path("稿.json")))
        self.assertEqual(parse_args(["录音.m4a"]).max_speakers, 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
