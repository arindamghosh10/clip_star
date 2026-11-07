# Paid connectors (your own keys)

Every connector is optional. clip_star works end to end with its free engines. A connector uses **your** account with the provider: you sign up, you pay them, and you put the key on the server (environment variable, or `.env` next to `docker-compose.yml`). Turn a connector on per stage in **Engines & connectors**. Spending on metered connectors counts toward the monthly budget set there.

If a connector fails or the budget runs out, the free engine takes over where one exists, and a note on the video says so.

| Connector | What it does | Set | Notes |
|---|---|---|---|
| **Claude** (Anthropic) | Picks moments, writes post text, sorts comments and drafts replies | `CLIPSTAR_ANTHROPIC_API_KEY` | Model `CLIPSTAR_CLAUDE_MODEL` (default `claude-opus-5-5`) |
| **OpenAI** | Same three jobs | `CLIPSTAR_OPENAI_API_KEY`, `CLIPSTAR_OPENAI_MODEL` | No model is assumed: pick one your key can use that supports structured outputs. `CLIPSTAR_OPENAI_BASE_URL` points it at any OpenAI-compatible service. For budgets, set `CLIPSTAR_OPENAI_PRICE_INPUT_PER_MTOK` / `…_OUTPUT_PER_MTOK`. |
| **Deepgram** | Transcription with speaker labels | `CLIPSTAR_DEEPGRAM_API_KEY` | Model `CLIPSTAR_DEEPGRAM_MODEL` (default `nova-3`); `CLIPSTAR_DEEPGRAM_PRICE_PER_MIN` for budgets |
| **AssemblyAI** | Transcription with speaker labels | `CLIPSTAR_ASSEMBLYAI_API_KEY` | `CLIPSTAR_ASSEMBLYAI_SPEECH_MODEL` (default `universal`; AssemblyAI requires one); `CLIPSTAR_ASSEMBLYAI_PRICE_PER_MIN` |
| **ElevenLabs** | Dubs a clip version into another language (voice + captions) | `CLIPSTAR_ELEVENLABS_API_KEY` | Clip editor → "Dub into other languages". Accounts whose language matches post the dub. Dubbed clips are always labelled AI-altered. `CLIPSTAR_ELEVENLABS_PRICE_PER_MIN` for budgets |
| **Pexels** | B-roll cutaways (free stock video) | `CLIPSTAR_PEXELS_API_KEY` (free) | Turn on in Settings → Clips or per clip version; up to two 2-second cutaways per clip, never during the hook. Pexels videos are free to use; credits are stored with each render. |
| **Klap**, **Vizard** | Their own AI clipping; their finished clips arrive in Clips for review | `CLIPSTAR_KLAP_API_KEY`, `CLIPSTAR_VIZARD_API_KEY` | Video page → "Also clip with …". They download the video themselves, so `CLIPSTAR_PUBLIC_MEDIA_URL` must be this server's public address. Their clips can't be re-cut in clip_star; text, approval, scheduling and stats work as usual. |
| **YouTube upload alerts** | Tells you when a new long video appears on a connected channel | (uses the YouTube connection) | Checked hourly. YouTube doesn't let apps download videos, so the alert asks for the original file or a Drive/Dropbox link. |

**Not connected:** OpusClip, Submagic, Reap, Lumiclip and ScaleReach had no public clipping API we could confirm. They can be added when one is available.

**Verification status:** request shapes come from each provider's public docs. They were tested against simulated providers, not live accounts. The first real run with each key is the real check; see `docs/PROJECT_STATUS.md` §4.
