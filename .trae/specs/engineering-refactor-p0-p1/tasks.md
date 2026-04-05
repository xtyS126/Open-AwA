# Tasks

- [x] Task 1: Fix Frontend Auto-Login & Request Interceptor Consistency
  - [x] SubTask 1.1: In `frontend/src/App.tsx`, wrap the `test_user_default` registration and auto-login logic in `if (import.meta.env.DEV)`.
  - [x] SubTask 1.2: In `frontend/src/shared/api/api.ts`, refactor `chatAPI.sendMessageStream` to generate and send an `X-Request-Id` header, log start/success/failure events, and align headers with `axios` requests.

- [x] Task 2: Refactor Backend Database Models to use JSON
  - [x] SubTask 2.1: In `backend/db/models.py`, change structured `Text` fields to `JSON` type. This includes fields like `Skill.config`, `Skill.tags`, `Skill.dependencies`, `Plugin.config`, `Plugin.dependencies`, `ExperienceMemory.trigger_conditions`, `ExperienceMemory.experience_metadata`, `ConversationRecord.llm_input`, `ConversationRecord.llm_output`, and `BehaviorLog.details`.
  - [x] SubTask 2.2: Ensure backward compatibility or graceful serialization if needed (SQLite uses text under the hood for JSON, so SQLAlchemy's `JSON` type is sufficient).

- [x] Task 3: Eliminate Global Singleton AIAgent and Long-lived DB Session
  - [x] SubTask 3.1: In `backend/core/agent.py`, modify `AIAgent.__init__` to accept `db_session` as a parameter instead of creating `SessionLocal()` internally. Remove the `close()` / `__del__` logic since the caller should manage the session lifecycle.
  - [x] SubTask 3.2: In `backend/api/routes/chat.py`, remove the global `agent = AIAgent()` instance.
  - [x] SubTask 3.3: In `backend/api/routes/chat.py` endpoints (`chat`, `confirm_operation`, `websocket_endpoint`), instantiate a local `AIAgent(db_session=db)` for the duration of the request/connection.
  - [x] SubTask 3.4: In `backend/api/routes/chat.py`'s `websocket_endpoint`, keep the `db` session open for the duration of the websocket connection instead of closing it early, and pass it to the local `AIAgent`.

- [ ] Task 4: Decouple Protocol Logic from Routing Layer
  - [ ] SubTask 4.1: Create `backend/api/services/chat_protocol.py` (or similar) to handle SSE stream processing, WebSocket protocol chunking (`_send_chunked_websocket_message`, `_build_chunk_checksum`), and token decoding.
  - [ ] SubTask 4.2: Move the `active_connections` state and connection lifecycle logic to a dedicated service layer `backend/api/services/ws_manager.py`.
  - [ ] SubTask 4.3: Refactor `chat.py` to call these new services, drastically reducing the size of the router functions to focus only on parameters, auth, and response formatting.

# Task Dependencies
- [Task 1] depends on nothing.
- [Task 2] depends on nothing.
- [Task 3] depends on [Task 2].
- [Task 4] depends on [Task 3].