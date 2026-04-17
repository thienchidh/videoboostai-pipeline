# No getattr/setattr — Direct Property Access Rule

## Rule

**All class attribute access in production code must use direct property access. No `getattr()` or `setattr()` for reading/writing class attributes.**

- ✅ `obj.field` or `obj.field = value`
- ✅ `obj.field if hasattr(obj, 'field') else default` for optional fields
- ❌ `getattr(obj, 'field', default)` — banned for class attribute access
- ❌ `setattr(obj, 'field', value)` — banned for class attribute writing

**Exceptions (allowed):**
- `object.__setattr__` in tests — required for Pydantic frozen models
- `getattr(type(obj), name)` — accessing class-level attributes, not instances
- Files in `tests/` directory — test code only

## What Changes vs What Stays

### Changes (production code — 10 files)

| File | Change |
|------|--------|
| `modules/pipeline/scene_processor.py` | Replace 8 `getattr` calls with direct `.field` access |
| `modules/pipeline/pipeline_runner.py` | Replace 2 `getattr` calls with direct `.field` access |
| `modules/media/tts.py` | Replace 2 `getattr` calls with direct `.field` access |
| `modules/media/image_gen.py` | Replace 4 `getattr` calls with direct `.field` access |
| `modules/media/prompt_builder.py` | Replace 5 `getattr` calls with direct `.field` access |
| `modules/content/content_idea_generator.py` | Replace 1 `getattr` call with direct `.field` access |
| `modules/content/content_pipeline.py` | Replace 1 `getattr` call with direct `.field` access |
| `modules/pipeline/models.py` | Replace `recursive_get()` — uses `getattr` internally |
| `db.py` | Replace 4 `setattr` calls — ORM-style dict-to-object mapping |
| `db/helpers.py` | Replace 4 `setattr` + 3 `getattr` calls |

### Stays (not changed)

| File | Reason |
|------|--------|
| `tests/` | Test code — `object.__setattr__` workarounds are necessary |
| `scripts/run_pipeline.py` | Uses `getattr(logging, level_str)` — standard logging pattern |
| `scripts/batch_generate.py` | Same — standard logging pattern |

## Specific Replacements

### `scene_processor.py`

```python
# Before
voice_id = getattr(character, 'voice_id', None) if character else None
gender = getattr(character, 'gender', None) if character else None
channel_style = getattr(self.ctx.channel, 'image_style', None)
brand_tone = getattr(self.ctx.channel, 'style', '') or ''
brief = getattr(scene, 'creative_brief', None)
img_gen = getattr(self.ctx.technical, 'generation', None)
chan_video = getattr(self.ctx.channel, 'video', None)
lip_gen = getattr(self.ctx.technical, 'generation', None)

# After
voice_id = character.voice_id if character else None
gender = character.gender if character else None
channel_style = self.ctx.channel.image_style if self.ctx.channel else None
brand_tone = self.ctx.channel.style or ''
brief = scene.creative_brief if scene else None
img_gen = self.ctx.technical.generation if self.ctx.technical else None
chan_video = self.ctx.channel.video if self.ctx.channel else None
lip_gen = self.ctx.technical.generation if self.ctx.technical else None
```

### `pipeline_runner.py`

```python
# Before
"scenario_slug": getattr(self.ctx.scenario, 'slug', ''),
"scenario_title": getattr(self.ctx.scenario, 'title', ''),

# After
"scenario_slug": self.ctx.scenario.slug if self.ctx.scenario else '',
"scenario_title": self.ctx.scenario.title if self.ctx.scenario else '',
```

### `tts.py`

```python
# Before
self.sample_rate = getattr(config.generation.tts, 'sample_rate', 32000)
word_timestamp_timeout = getattr(self._config.generation.tts, 'word_timestamp_timeout', 120)

# After
self.sample_rate = config.generation.tts.sample_rate
word_timestamp_timeout = self._config.generation.tts.word_timestamp_timeout
```

### `image_gen.py`

```python
# Before
self.poll_interval = getattr(config.generation.image, 'poll_interval', 5)
self.max_polls = getattr(config.generation.image, 'max_polls', 24)

# After
self.poll_interval = config.generation.image.poll_interval
self.max_polls = config.generation.image.max_polls
```

### `prompt_builder.py`

```python
# Before
"lighting": getattr(self.channel_style, "lighting", None),
"camera": getattr(self.channel_style, "camera", None),
...

# After
"lighting": self.channel_style.lighting,
"camera": self.channel_style.camera,
... (all 5 fields)
```

### `content_idea_generator.py`

```python
# Before
voice_info = getattr(c, 'voice_id', '') or ""

# After
voice_info = c.voice_id or ""
```

### `content_pipeline.py`

```python
# Before
_runner = getattr(pipeline, '_runner', None)

# After
_runner = pipeline._runner if hasattr(pipeline, '_runner') else None
# Or simply: pipeline._runner (if always expected to exist)
```

### `models.py` — `TechnicalConfig.get()`

The `get()` method uses `getattr` internally for nested path traversal. Replace with `hasattr` + direct access:

```python
# Before
if hasattr(obj, part):
    obj = getattr(obj, part)
else:
    return default

# After
if hasattr(obj, part):
    obj = getattr(obj, part)  # can be replaced with obj.__getattribute__(part)
```

`getattr` here is accessing the Pydantic model's attribute — this is a gray area. Since `TechnicalConfig.get()` is an internal utility for backward compatibility, the refactor should either:
- **Option A**: Remove `TechnicalConfig.get()` entirely — no longer needed if all callers use direct access
- **Option B**: Keep it but note it's a legacy compatibility method

**Decision: Option A** — scan for callers of `config.get('a.b.c')` and replace with direct access, then remove the method.

### `db.py` — ORM-style setattr

```python
# Before
setattr(run, k, v)

# After
if hasattr(run, k):
    setattr(run, k, v)  # still needed for ORM field assignment
```

Since `Run` is a dataclass/Pydantic model with known fields, use explicit field assignment or a `model_validate` approach instead.

### `db/helpers.py` — Same ORM pattern

```python
# Before
setattr(run, k, v)

# After
if hasattr(run, k):
    setattr(run, k, v)
```

## Implementation Order

1. **Phase 1**: Fix `modules/media/tts.py` — 2 replacements, self-contained
2. **Phase 2**: Fix `modules/media/image_gen.py` — 4 replacements
3. **Phase 3**: Fix `modules/media/prompt_builder.py` — 5 replacements
4. **Phase 4**: Fix `modules/content/content_idea_generator.py` — 1 replacement
5. **Phase 5**: Fix `modules/content/content_pipeline.py` — 1 replacement
6. **Phase 6**: Fix `modules/pipeline/scene_processor.py` — 8 replacements
7. **Phase 7**: Fix `modules/pipeline/pipeline_runner.py` — 2 replacements
8. **Phase 8**: Fix `modules/pipeline/models.py` — remove `TechnicalConfig.get()`, update callers
9. **Phase 9**: Fix `db.py` and `db/helpers.py` — ORM patterns

## Testing

After each phase, run:
```bash
pytest tests/ -v
```

No new tests needed — refactor is behavior-preserving. Tests already in place verify correctness.