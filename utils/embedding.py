#!/usr/bin/env python3
"""
embedding.py - Embedding utilities for semantic deduplication.

Uses sentence-transformers (distiluse-base-multilingual-cased-v2) - opensource, no API keys, no rate limits.
"""
import logging
import numpy as np
import re
from typing import List, Dict, Optional

from modules.llm import get_llm_provider
from modules.pipeline.models import TechnicalConfig

logger = logging.getLogger(__name__)

EMBED_DIM = 512  # distiluse-base-multilingual-cased-v2 dimension
SIMILARITY_THRESHOLD = 0.75  # slightly lower threshold for multilingual model

# Lazy-load model to avoid import overhead at module load time
_st_model = None


def _get_model():
    """Get or create the sentence-transformers model (lazy loading)."""
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer("distiluse-base-multilingual-cased-v2")
        logger.info("Embedding model loaded: distiluse-base-multilingual-cased-v2")
    return _st_model


def translate_to_english(text: str) -> str:
    """Translate Vietnamese text to English for better embedding quality."""
    try:
        cfg = TechnicalConfig.load()
        api_key = cfg.api_keys.minimax
        if not api_key:
            logger.warning("No MiniMax API key for translation, using original text")
            return text

        llm = get_llm_provider(
            name="minimax",
            api_key=api_key,
            model="MiniMax-M2.7",
        )
        # Use Vietnamese-to-English specific prompt
        prompt = f"Dịch sang tiếng Anh: {text}"
        result = llm.chat(prompt, max_tokens=200).strip()

        # Clean up - remove markdown formatting, quotes, explanations
        result = re.sub(r"\*\*(.*?)\*\*", r"\1", result)  # Remove **bold**
        result = re.sub(r"\*(.*?)\*", r"\1", result)      # Remove *italic*
        result = re.sub(r'["""""]', "", result)            # Remove quotes

        # Take first line only
        lines = [l.strip() for l in result.split("\n") if l.strip()]
        result = lines[0] if lines else result

        # If result is "Translation:" or too short, use original text
        if result.lower().startswith("translation") or len(result) < 3:
            return text

        # Validate: must be mostly English letters
        english_ratio = sum(1 for c in result if c.isalpha() and ord(c) < 128) / max(len(result), 1)
        if result and len(result) < len(text) * 2 and english_ratio > 0.5:
            return result
        return text
    except Exception as e:
        logger.warning(f"Translation failed: {e}, using original text")
        return text


def create_embedding(text: str) -> Optional[List[float]]:
    """Create embedding vector using sentence-transformers (multilingual).

    Supports Vietnamese directly without translation.
    """
    try:
        model = _get_model()
        embedding = model.encode(text, convert_to_numpy=True)
        embedding = embedding.tolist()
        logger.debug(f"Embedding created: dim={len(embedding)}")
        return embedding
    except Exception as e:
        logger.error(f"Embedding creation failed: {e}")
        return None


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_np = np.array(a)
    b_np = np.array(b)
    dot = np.dot(a_np, b_np)
    norm_a = np.linalg.norm(a_np)
    norm_b = np.linalg.norm(b_np)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def find_similar_ideas(embedding: List[float], project_id: int,
                       threshold: float = SIMILARITY_THRESHOLD) -> List[Dict]:
    """Find ideas with similarity score > threshold using in-memory comparison."""
    from db import get_session
    import db_models as models

    with get_session() as session:
        rows = session.query(models.IdeaEmbedding, models.ContentIdea).join(
            models.ContentIdea,
            models.IdeaEmbedding.content_idea_id == models.ContentIdea.id
        ).filter(
            models.ContentIdea.project_id == project_id
        ).all()

        similar = []
        for emb_record, idea in rows:
            if emb_record.embedding is None:
                continue
            vec = emb_record.embedding.tolist() if hasattr(emb_record.embedding, "tolist") else list(emb_record.embedding)
            sim = cosine_similarity(embedding, vec)
            if sim > threshold:
                similar.append({
                    "idea_id": idea.id,
                    "title_vi": emb_record.title_vi,
                    "title_en": emb_record.title_en,
                    "similarity": round(sim, 4),
                })

        return similar


def save_idea_embedding(idea_id: int, title_vi: str, title_en: str,
                         embedding: List[float]) -> Optional[int]:
    """Save idea embedding to DB. Returns embedding ID or None on failure."""
    from db import get_session
    import db_models as models

    with get_session() as session:
        existing = session.query(models.IdeaEmbedding).filter_by(
            content_idea_id=idea_id
        ).first()

        if existing:
            existing.title_vi = title_vi
            existing.title_en = title_en
            existing.embedding = embedding
            session.flush()
            return existing.id

        record = models.IdeaEmbedding(
            content_idea_id=idea_id,
            title_vi=title_vi,
            title_en=title_en,
            embedding=embedding,
        )
        session.add(record)
        session.flush()
        return record.id


def check_duplicate_ideas(ideas: List[Dict], project_id: int) -> List[Dict]:
    """
    Check ideas for semantic duplicates against existing DB records.
    Returns only non-duplicate ideas.

    Uses multilingual sentence-transformers - no translation needed.
    """
    new_ideas = []
    skipped = []

    for idea in ideas:
        title = idea.get("title", "")
        if not title:
            continue

        # Multilingual model supports Vietnamese directly - no translation needed
        logger.debug(f"Checking idea: '{title}'")

        embedding = create_embedding(title)
        if not embedding:
            logger.warning(f"Could not create embedding for '{title}', including anyway")
            new_ideas.append(idea)
            continue

        similar = find_similar_ideas(embedding, project_id)

        if similar:
            logger.info(f"SKIP duplicate: '{title}' (similar to: {similar[0]['title_vi']}, "
                       f"score={similar[0]['similarity']})")
            # Save dupe as ContentIdea with status=duplicate, then save embedding
            # This ensures subsequent runs catch this idea before calling LLM
            try:
                from db import save_content_ideas
                dupe_ids = save_content_ideas(project_id, [idea])
                if dupe_ids:
                    dupe_id = dupe_ids[0]
                    from db import get_session
                    import db_models as models
                    with get_session() as session:
                        row = session.query(models.ContentIdea).filter_by(id=dupe_id).first()
                        if row:
                            row.status = "duplicate"
                            session.commit()
                    if embedding:
                        from utils.embedding import save_idea_embedding
                        save_idea_embedding(
                            idea_id=dupe_id,
                            title_vi=title,
                            title_en="",
                            embedding=embedding,
                        )
            except Exception as e:
                logger.warning(f"Could not save dupe idea embedding: {e}")
            skipped.append({
                **idea,
                "title_vi": title,
                "similar_to": similar[0]["title_vi"],
                "similarity": similar[0]["similarity"],
            })
        else:
            logger.debug(f"NEW idea: '{title}'")
            new_ideas.append({**idea, "_embedding": embedding})

    if skipped:
        logger.info(f"Deduplication: {len(skipped)} duplicates skipped, "
                    f"{len(new_ideas)} new ideas kept")

    return new_ideas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    test_titles = [
        "3 cách quản lý thời gian hiệu quả",
        "Top 3 phương pháp quản lý thời gian",
        "Tại sao bạn nên thức dậy lúc 5 giờ sáng?",
    ]

    print("Testing translation:")
    for title in test_titles:
        en = translate_to_english(title)
        print(f"  '{title}' → '{en}'")

    print("\nTesting embedding:")
    for title in test_titles:
        en = translate_to_english(title)
        emb = create_embedding(en)
        if emb:
            print(f"  '{en}' → dim={len(emb)}")
        else:
            print(f"  '{en}' → FAILED")
