"""
Compute-Split RAG Engine — ONNX Runtime Cross-Encoder Re-Ranker
================================================================
Filters raw scraped articles before they reach the LLM Editor, using a
lightweight cross-encoder model (~30MB ONNX) that runs entirely on CPU
via ONNX Runtime.

CRITICAL: This module imports ZERO PyTorch/CUDA dependencies. This prevents
the 500MB-1GB VRAM leak that occurs when Python imports torch in a
CUDA_VISIBLE_DEVICES environment — preserving 100% of GPU VRAM for Ollama.
"""
from __future__ import annotations

import os
import time
import threading
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger("cross_encoder")

# ─── Module-level singleton cache ────────────────────────────────────────────
_model_lock = threading.Lock()
_onnx_session = None              # ONNX InferenceSession (lazy-loaded)
_tokenizer = None                 # HuggingFace Tokenizer (Rust-based)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_DIR = os.path.join(_PROJECT_ROOT, "models", "cross-encoder")
_ONNX_PATH = os.path.join(_MODEL_DIR, "model.onnx")
_TOKENIZER_PATH = _MODEL_DIR     # tokenizer.json lives in the model dir

_SIMILARITY_THRESHOLD = 0.30     # Minimum score to be considered relevant
_DEDUP_CHAR_OVERLAP = 0.6        # Snippet overlap ratio to flag duplicates
_MAX_SEQ_LENGTH = 512


def _load_model():
    """
    Lazy-loads the ONNX cross-encoder model and tokenizer once.

    Loading priority:
      1. CROSS_ENCODER_PATH env var (custom override)
      2. ./models/cross-encoder/model.onnx (pre-bundled, air-gapped)
    """
    global _onnx_session, _tokenizer
    if _onnx_session is not None and _tokenizer is not None:
        return True

    with _model_lock:
        if _onnx_session is not None and _tokenizer is not None:
            return True

        # Resolve model directory
        custom_path = os.environ.get("CROSS_ENCODER_PATH")
        model_dir = custom_path if custom_path else _MODEL_DIR
        onnx_file = os.path.join(model_dir, "model.onnx")

        if not os.path.exists(onnx_file):
            print(
                f"[CROSS_ENCODER] ONNX model not found at {onnx_file}. "
                f"Run 'python scripts/export_onnx.py' to create it. Using keyword fallback.",
                flush=True
            )
            return False

        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            # ONNX Runtime — CPU-only provider, zero CUDA interaction
            print(f"[CROSS_ENCODER] Loading ONNX model from {onnx_file}...", flush=True)
            t0 = time.time()
            _onnx_session = ort.InferenceSession(
                onnx_file,
                providers=["CPUExecutionProvider"]
            )

            # Tokenizer — Rust-based (from tokenizers library), no Python ML deps
            tokenizer_file = os.path.join(model_dir, "tokenizer.json")
            if os.path.exists(tokenizer_file):
                _tokenizer = Tokenizer.from_file(tokenizer_file)
            else:
                # Try loading from pretrained config
                _tokenizer = Tokenizer.from_pretrained("cross-encoder/ms-marco-MiniLM-L-6-v2")

            elapsed = time.time() - t0
            print(
                f"[CROSS_ENCODER] ONNX model loaded in {elapsed:.1f}s. "
                f"CPU-only, zero CUDA context. GPU VRAM untouched.",
                flush=True
            )
            return True

        except ImportError as e:
            print(f"[CROSS_ENCODER] Missing dependency ({e}) - using keyword fallback.", flush=True)
            return False
        except Exception as e:
            print(f"[CROSS_ENCODER] Model load failed ({e}) - using keyword fallback.", flush=True)
            return False


def _onnx_score_pairs(pairs: List[Tuple[str, str]]) -> List[float]:
    """
    Scores query-document pairs using the ONNX cross-encoder.
    Returns a list of relevance scores.
    """
    if _onnx_session is None or _tokenizer is None:
        return []

    # Tokenize all pairs
    all_input_ids = []
    all_attention_masks = []

    for query, doc in pairs:
        # Encode as a pair (cross-encoder style: [CLS] query [SEP] doc [SEP])
        encoding = _tokenizer.encode(query, doc)
        ids = encoding.ids[:_MAX_SEQ_LENGTH]
        mask = encoding.attention_mask[:_MAX_SEQ_LENGTH]

        # Pad to max length in batch
        all_input_ids.append(ids)
        all_attention_masks.append(mask)

    # Pad all sequences to the same length
    max_len = max(len(ids) for ids in all_input_ids)
    padded_ids = np.zeros((len(pairs), max_len), dtype=np.int64)
    padded_mask = np.zeros((len(pairs), max_len), dtype=np.int64)

    for i, (ids, mask) in enumerate(zip(all_input_ids, all_attention_masks)):
        padded_ids[i, :len(ids)] = ids
        padded_mask[i, :len(mask)] = mask

    # Run ONNX inference
    input_feed = {
        "input_ids": padded_ids,
        "attention_mask": padded_mask,
    }
    outputs = _onnx_session.run(None, input_feed)
    logits = outputs[0]  # Shape: (batch, num_labels) or (batch,)

    # Cross-encoder for relevance typically outputs a single logit per pair
    if logits.ndim == 2:
        scores = logits[:, 0].tolist()  # Take first column (relevance score)
    else:
        scores = logits.tolist()

    return scores


def _keyword_score(query: str, snippet: str) -> float:
    """Pure-Python fallback: naive keyword density scorer (no ML required)."""
    if not snippet:
        return 0.0
    query_terms = set(query.lower().split())
    snippet_words = snippet.lower().split()
    if not snippet_words:
        return 0.0
    hits = sum(1 for w in snippet_words if w in query_terms)
    return hits / (len(snippet_words) ** 0.5)


def _is_duplicate(a: str, b: str) -> bool:
    """Checks if two snippets share more than _DEDUP_CHAR_OVERLAP of trigrams."""
    if not a or not b:
        return False
    def trigrams(s):
        s = s.lower()
        return set(s[i:i+3] for i in range(len(s) - 2))
    tg_a = trigrams(a)
    tg_b = trigrams(b)
    if not tg_a or not tg_b:
        return False
    overlap = len(tg_a & tg_b) / min(len(tg_a), len(tg_b))
    return overlap >= _DEDUP_CHAR_OVERLAP


def _deduplicate(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Removes near-duplicate articles based on snippet trigram similarity."""
    unique = []
    for article in articles:
        snippet = article.get("snippet", "")
        is_dup = any(_is_duplicate(snippet, u.get("snippet", "")) for u in unique)
        if not is_dup:
            unique.append(article)
    return unique


def rerank(
    query: str,
    articles: List[Dict[str, Any]],
    top_k: int = 5
) -> tuple[List[Dict[str, Any]], int]:
    """
    Re-ranks raw scraped articles by relevance to the query using the ONNX cross-encoder.

    Args:
        query:    The original search query / subject string.
        articles: Raw list of article dicts (each has 'title', 'snippet' keys).
        top_k:    Maximum number of articles to return after re-ranking.

    Returns:
        Tuple of (top-k high-signal articles, count of articles dropped).
    """
    if not articles:
        return [], 0

    original_count = len(articles)

    # Step 1: Deduplicate before scoring
    deduped = _deduplicate(articles)
    dropped_dups = original_count - len(deduped)
    if dropped_dups > 0:
        print(f"[CROSS_ENCODER] Removed {dropped_dups} near-duplicate articles.", flush=True)

    if not deduped:
        return [], original_count

    # Step 2: Build query-document pairs
    pairs = []
    for article in deduped:
        doc = f"{article.get('title', '')} — {article.get('snippet', '')}"
        pairs.append((query, doc[:_MAX_SEQ_LENGTH]))

    # Step 3: Score all pairs
    model_loaded = _load_model()
    if model_loaded and _onnx_session is not None:
        try:
            print(f"[CROSS_ENCODER] Scoring {len(pairs)} article(s) via ONNX on CPU...", flush=True)
            t0 = time.time()
            scores = _onnx_score_pairs(pairs)
            elapsed = time.time() - t0
            print(f"[CROSS_ENCODER] Scored {len(pairs)} articles in {elapsed:.2f}s (ONNX CPU).", flush=True)
        except Exception as e:
            print(f"[CROSS_ENCODER] ONNX inference failed ({e}), falling back to keyword scorer.", flush=True)
            scores = [_keyword_score(query, a.get("snippet", "")) for a in deduped]
    else:
        print("[CROSS_ENCODER] Using keyword fallback scorer.", flush=True)
        scores = [_keyword_score(query, a.get("snippet", "")) for a in deduped]

    # Step 4: Attach scores and sort descending
    scored = sorted(
        zip(scores, deduped),
        key=lambda x: x[0],
        reverse=True
    )

    # Step 5: Apply top_k cap
    results = []
    for score, article in scored[:top_k]:
        article_with_score = dict(article)
        article_with_score["_relevance_score"] = round(float(score), 4)
        results.append(article_with_score)

    below_threshold = sum(1 for s, _ in scored if s < _SIMILARITY_THRESHOLD)
    dropped_total = (original_count - len(deduped)) + (len(deduped) - len(results))

    print(
        f"[CROSS_ENCODER] Re-ranked {original_count} -> {len(results)} articles "
        f"(dropped {dropped_total}: {dropped_dups} dups + {len(deduped) - len(results)} low-signal). "
        f"{below_threshold} were below threshold {_SIMILARITY_THRESHOLD}.",
        flush=True
    )

    return results, dropped_total


def quality_gate(articles: List[Dict[str, Any]], min_score: float = _SIMILARITY_THRESHOLD) -> bool:
    """
    Returns True if the top article's relevance score exceeds the quality threshold.
    Used by the Editor node to decide if a context loopback is needed.
    """
    if not articles:
        return False
    top_score = articles[0].get("_relevance_score", None)
    if top_score is None:
        return True
    return top_score >= min_score
