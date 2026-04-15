# Tech Debt Fix — VideoBoostAI

## Status
- **Author**: Claude
- **Date**: 2026-04-15
- **Approved**: Yes (inline design approved)

## Scope
Fix 5 tech debt issues in priority order. All changes on branch `fix/tech-debt`.

---

## Issue #1 — Fix `optimal_post_time` Export

### Problem
`modules/content/__init__.py` does not export `optimal_post_time` → `AttributeError` when tests import it.

### Fix
Add `optimal_post_time` to `__init__.py`:
```python
from .optimal_post_time import optimal_post_time
```

---

## Issue #2 — Replace Bare `except:` Clauses

### Problem
4+ bare `except:` in `content_pipeline.py` silently swallow exceptions with no context.

### Fix
Replace each bare `except:` with structured error handling:

| Location | Old | New Action |
|----------|-----|------------|
| Line ~134 | `except Exception as e: logger.warning(...)` | Log warning + set checkpoint=None, continue |
| Line ~185 | `except Exception as e: logger.warning(...)` | Log warning + set checkpoint=None, continue |
| Line ~229 | `except Exception as e: logger.warning(...)` | Log error + continue or re-raise depending on severity |
| Line ~298 | `except Exception as e: logger.warning(...)` | Log error + re-raise to prevent silent data loss |

Each re-raised exception must include original context: `raise XxxError(...) from e`.

---

## Issue #3 — Fix Broken Test Imports

### Problem
`test_optimal_post_time.py` fails to import `optimal_post_time`. Also pgvector missing in test env.

### Fix
1. Add `pgvector` to `requirements.txt` or test requirements
2. Verify all `modules.content.__init__.py` exports are matched by test imports

---

## Issue #4 — Split `db.py`

### Problem
1453-line `db.py` mixes engine setup, ORM imports, and ~30 helper functions. Violates single responsibility.

### New Structure
```
db/
  __init__.py      # re-exports everything for backward compatibility
  config.py        # engine/session setup, BASE_URL, get_engine(), get_session()
  models.py        # ORM model imports (TopicSource, ContentIdea, IdeaEmbedding, Run, etc.)
  helpers.py       # all helper functions (get_content_idea, mark_topic_source_completed, etc.)
db_models.py       # keep as-is (actual ORM class definitions, referenced by db/models.py)
```

### Constraints
- All existing `from db import *` calls must continue to work (backward compat via `__init__.py`)
- Helpers in `helpers.py` must retain full existing signatures
- No logic changes — only file reorganization

---

## Issue #5 — Fix Implicit Provider Registration

### Problem
`pipeline_runner.py` imports providers `# noqa: F401` purely for registration side-effects. If `__init__.py` registration order changes, providers silently disappear.

### Fix
Create `modules/pipeline/providers.py`:
```python
# Explicit provider registration — no side-effect magic
from modules.media.tts import MiniMaxTTSProvider, EdgeTTSProvider
from modules.media.image_gen import MiniMaxImageProvider, WaveSpeedImageProvider, KieImageProvider
from modules.media.lipsync import WaveSpeedLipsyncProvider, KieLipsyncProvider
from modules.media.music import MiniMaxMusicProvider
from core.plugins import PluginRegistry

def register_all():
    registry = PluginRegistry.get_instance()
    registry.register_tts_provider(MiniMaxTTSProvider())
    registry.register_tts_provider(EdgeTTSProvider())
    registry.register_image_provider(MiniMaxImageProvider())
    registry.register_image_provider(WaveSpeedImageProvider())
    registry.register_image_provider(KieImageProvider())
    registry.register_lipsync_provider(WaveSpeedLipsyncProvider())
    registry.register_lipsync_provider(KieLipsyncProvider())
    registry.register_music_provider(MiniMaxMusicProvider())

register_all()
```

Replace implicit `import * side-effect` in `pipeline_runner.py` with:
```python
from modules.pipeline import providers  # registers on import
```

---

## Priority Order
1. Issue #1 — `optimal_post_time` export fix
2. Issue #2 — bare `except:` replacements
3. Issue #3 — test import fixes
4. Issue #4 — split `db.py`
5. Issue #5 — explicit provider registration

---

## Verification
After each issue is fixed, run relevant tests to confirm:
- `pytest tests/test_content_pipeline.py` — for issues #1, #2
- `pytest tests/test_optimal_post_time.py` — for issues #1, #3
- `pytest tests/test_db.py` — for issue #4
- `pytest tests/test_pipeline_runner.py` — for issue #5

Final: `pytest tests/ -q` should show improved pass rate.
