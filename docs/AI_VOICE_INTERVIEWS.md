# Live L1 AI interview

The candidate clicks Start once, allows the microphone, and speaks naturally. OpenAI Realtime streams speech over WebRTC, detects when the candidate finishes speaking, responds aloud and supports interruptions. The candidate has Mute and End controls. An Enable speaker audio button appears only if the browser blocks autoplay.

## Setup

Keep the existing OPENAI_API_KEY private in the backend. Live conversation uses OpenAI even if AI_PROVIDER=groq for other agents. Follow-up summaries still use the shared provider configuration.

```dotenv
AI_VOICE_INTERVIEWS_ENABLED=true
VOICE_REALTIME_MODEL=gpt-realtime-mini
VOICE_REALTIME_MAX_MINUTES=5
VOICE_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
VOICE_NAME=coral
```

The account needs access to the realtime model and available API credits. No new key is necessarily required. Model access and actual speech quality must be tested live. Requests consume API credits; a five-minute cap is not a dollar spending limit.

Run `alembic upgrade head` (migration e633ab05), restart the API and rebuild/restart the frontend. This pilot requires a single continuously running API process: the sideband observer owns the call in memory and writes its transcript to the database. Do not deploy with multiple workers or serverless suspension without adding shared call coordination. After a restart, active calls from the previous process are terminated. Graceful shutdown also closes observed calls.

Use localhost on this laptop for testing. Remote candidates need an HTTPS frontend and internet access to OpenAI WebRTC. The API needs outbound HTTPS and WSS access to OpenAI. Microphone permission is required. If a network blocks WebRTC or UDP, test on another network; no TURN relay or phone integration is included.

## Manual test

1. Open Interviews > existing interview details > L1 > AI voice interview.
2. Review one or two job-related questions and use the five-minute limit. Confirm AI processing, then create and copy a NEW link. Old completed/recorded sessions cannot become new live calls.
3. Open the full link in a private window. Agree to live audio/transcript processing. Click Start live interview and allow the microphone.
4. The interviewer should greet you and ask a question automatically. Answer naturally, then pause. It should respond without Play, Record or Submit actions.
5. Interrupt while it speaks; check it stops and listens. Test Mute/Unmute. Use headphones to reduce echo.
6. Click End interview, or complete the questions. The microphone should stop. Return to the recruiter page and Refresh to review the automatic transcript. Generate a summary if needed.
7. Check a withdrawn link fails, a used link cannot start a second call, and the session ends at its deadline. A failed setup consumes its one connection attempt; create a new link only after addressing the failure.

## Storage and limits

Private three-day links are stored as hashes. Anyone holding a link can use it; it does not verify identity. Call IDs and permanent API keys stay on the backend. Provider transcript events are observed and saved by the server, not uploaded as trusted text from the browser. Transcription is automatic, may arrive slightly out of order, and may contain recognition errors. The recruiter must review it; it is not verified evidence or an audio recording. Hirava does not store raw audio. Provider audio processing/data handling still applies.

There is one live connection attempt per link, a configured duration cap, a per-response output limit and an observer response-count cap. The observer closes calls on withdrawal, completion, deadline, error or shutdown. Call termination failures are shown for follow-up. Abrupt server loss cannot guarantee instant provider termination; keep the API running and check provider usage after failures.

No hiring score, emotion/accent/personality analysis or automatic hiring decision is made. Human-led interviews remain available. The previous recording endpoints are retained for compatibility, but a live session cannot use them. Existing saved recordings/transcripts remain accessible to recruiters.

Automated tests mock provider connections. Live audio latency, account access, interruption quality, speaker autoplay and network behavior require the manual test above. No live paid calls are made by those tests.

Official references: [WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?api=realtime), [server controls](https://developers.openai.com/api/docs/guides/voice-server-controls?api=realtime), [voice activity detection](https://developers.openai.com/api/docs/guides/realtime-vad).
