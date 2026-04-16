# Design: Giảm Verbose Logging

## Mục tiêu
Chuyển các log payload/API response từ `INFO` → `DEBUG`. Log ở `INFO` chỉ dùng cho progress và kết quả quan trọng. Khi cần trace API, chạy với `--debug`.

## Nguyên tắc
| Level | Nên log |
|-------|---------|
| `INFO` | Progress chính, kết quả cuối cùng, lỗi |
| `DEBUG` | Payload/request-response/API chi tiết |

## Thay đổi

### `modules/llm/minimax.py`
- Line 68-93: `logger.info` (request/response payload) → `logger.debug`

### `modules/media/tts.py`
- Line 88-98: `logger.info` (TTS payload/response) → `logger.debug`

### `modules/media/image_gen.py`
- `MiniMaxImageProvider.generate`: line 53, 56, 58, 61, 63 → `logger.debug`
- `KieImageProvider.generate`: line 223, 225, 227, 228, 238, 246, 261 → `logger.debug`

### `modules/media/kie_ai_client.py`
- Line 49 (init): → `logger.debug`
- Line 85, 89, 93 (request/response): → `logger.debug`

### `modules/media/lipsync.py`
- `KieAIInfinitalkProvider.generate`: line 357, 382 → `logger.debug`

### `scripts/run_pipeline.py`
- Thêm `--debug` flag: set DEBUG level khi có flag

## Giữ nguyên
- `content_pipeline.py` — progress log (Step 1, Step 2...) → hữu ích cho biết pipeline đang chạy đâu
- `topic_researcher.py` — research step log → hữu ích
- `logger.warning/error` — luôn giữ nguyên
