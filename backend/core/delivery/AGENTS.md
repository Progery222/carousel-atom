<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# delivery

## Purpose
Output adapters that push a rendered carousel to an external channel. The pipeline calls into this package only when `deliver=...` is requested. Currently the one implemented adapter is Telegram; the package is structured as a registry so more channels can be added behind a common protocol.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Adapter registry — `get_adapter(name)` returns a protocol implementation (e.g. the Telegram adapter). |
| `telegram.py` | `send()` posts a carousel to a chat as a media group (10-photo limit) followed by the caption; needs `TELEGRAM_BOT_TOKEN` + the topic's resolved `delivery.telegram_chat`. |

## For AI Agents

### Working In This Directory
- **Adding an adapter**: implement the send protocol and register it in `__init__.py`; the API exposes it via `GET /deliveries` and `POST /deliver/{run_id}` once registered.
- Telegram's media-group cap is 10 photos — split or truncate larger carousels rather than failing.
- The chat target comes from the topic config (`delivery.telegram_chat`, often an `env:CHAT_<TOPIC>` reference resolved by `topic_loader`); the bot token comes from the environment. Missing credentials should degrade gracefully (log + return a non-fatal result), not raise.
- Use `core.http` / `requests` consistently with the rest of the backend and log under `carousel.delivery.*`.

### Testing Requirements
- No dedicated unit test; verify against a real bot token + chat id in a scratch environment, or mock the HTTP layer.

### Common Patterns
- A frozen `DeliveryResult`-style return shape; graceful degradation on missing config.

## Dependencies

### Internal
- `core.topic_loader` (`TopicConfig` for the chat target), `core.log`.

### External
- requests (Telegram Bot API).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
