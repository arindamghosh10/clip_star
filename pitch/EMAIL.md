# Pitch email

Use this to tell clippers, clip agencies and creators who run many accounts about clip_star.

- **Send it as plain text from your own address.** Cold emails with many images, attachments or links often land in spam.
- **Use one tour link and one demo link.** The screenshots live on the tour page, so the email stays light.
- **Use `email.html`** only when you send through a tool that handles HTML well, or for warm contacts.

Replace everything in `{curly braces}` before sending. The first line must be about *them*. That one line decides whether they keep reading.

---

## Subject lines (pick one, test two)

1. `{First name}, your clips could post themselves`
2. `One long video in, clips live on 9 accounts`
3. `I built a clipping engine you own outright`
4. `Question about how you run {their page / brand}`
5. `Your clipping team, on your own computer`

**Preview text** (the grey line after the subject in most inboxes):
`Finds the moments, edits, captions, posts and replies. Runs on your machine, with your accounts.`

---

## Email 1: the pitch (about 220 words)

> Hi {First name},
>
> {One true, specific line about them, e.g. "Your clips of {creator}'s podcast have been all over my TikTok this month." or "I saw you're running clipping campaigns for {creator}."}
>
> Running that many accounts usually means paying editors, a scheduler, someone on comments and someone on reporting. Every month.
>
> I built **clip_star** to do that whole job in one system you run yourself:
>
> - **Clips:** drop in a long video (or a Drive/Dropbox link). It finds the strongest moments, cuts them to 9:16, and adds word-by-word captions, a hook title, zooms and emojis. It scores every clip and says why it picked it.
> - **Posting:** it writes the caption and hashtags per platform and schedules across all your accounts: Instagram, TikTok, YouTube, Facebook, X, LinkedIn, Threads and Pinterest. It handles A/B versions, posting hours and daily caps, and never posts twice.
> - **After posting:** it pulls in comments, sorts out questions, leads and spam, and drafts replies. Then it tracks views and followers and tells you which kinds of clips to make more of.
>
> Set your rules once and it runs on autopilot. Or keep one "approve" click before anything goes live. Your call.
>
> **It's all yours:** your computer or server, your accounts, your data. It uses only the platforms' official APIs: no bots, no shared logins, no tricks that get accounts flagged. The built-in engines are free and open source. You can plug in Claude, OpenAI, ElevenLabs and others with your own keys only if you want them.
>
> 2-minute tour with screenshots: {TOUR LINK}
> Click around the live demo: {DEMO LINK}
>
> Open to a 20-minute call this week? I'll run one of *your* videos through it live.
>
> {Your name}
>
> P.S. Send me one long video and I'll send back the clips it picks, free. No call needed.

---

## Email 2: follow-up, 3 days later (reply in the same thread)

> Hi {First name}, bumping this in case it got buried.
>
> The short version: one long video in, finished clips posted across all your accounts, comments sorted, and a weekly report on what worked. It runs on your own machine, so there's no per-seat bill and nobody else holds your accounts.
>
> Tour: {TOUR LINK}
>
> Worth 20 minutes? {CALENDAR LINK or "Just reply with a time that suits you."}
>
> {Your name}

## Email 3: last note, 5–7 days later

> Hi {First name}, last one from me.
>
> If clipping and posting isn't a headache for you right now, no worries. If it is, my offer stands: send one long video and I'll send back the clips clip_star picks, with the captions and post text it writes. That's the fastest way to judge it.
>
> {Your name}

---

## Short version (DMs on X, Instagram or LinkedIn)

> Hey {First name}, I built a self-hosted system that turns one long video into captioned clips and posts them across all your accounts (IG, TikTok, YT, X, LinkedIn…) on a schedule. It also sorts comments and reports what's working. Official APIs only, runs on your own machine. 2-min tour: {TOUR LINK}. Want me to run one of your videos through it?

---

## Answers to likely replies

| They ask | Answer |
|---|---|
| "Is it really hands-off?" | Yes, if you want. Automation rules pick approved clips, build the schedule and post it, and replies can auto-send for set categories. Most people keep one approval click per batch at first, then turn it off. |
| "Will my accounts get banned?" | It only uses each platform's official publishing API, with your own developer app and the platform's own login screen. No password sharing, browser bots, proxies or spoofing. The platforms' rules still apply (posting limits, original content), and clip_star enforces daily caps and spacing. |
| "What does it cost to run?" | The software runs on your computer or a small server. The default engines are free. Paid add-ons (Claude, OpenAI, Deepgram, ElevenLabs, Pexels, Klap, Vizard) bill you directly at their own prices, and you can set a monthly budget cap. |
| "How good are the clips?" | Best answered with their own video: offer the free test. The free engine scores hooks, energy, completeness and length; plugging in Claude or OpenAI picks moments with an AI model. |
| "Can my team use it?" | Yes. It has owner, editor, reviewer and viewer roles, invite links, separate workspaces per creator or brand, and notifications by email and phone. |
| "Does it work with n8n / Zapier / my AI assistant?" | Yes. It has a full API, signed webhooks, and an MCP server so Claude and other assistants can drive it. |
| "What are the terms?" | Save it for the call. |

---

## Before you send: check these claims

- [ ] **Demo hosted** and the link works logged out. The demo uses practice accounts, so all numbers are made up (the app says so on screen).
- [ ] **One real platform verified.** Before promising real posting, post one real clip on at least one platform with your own developer app (see `docs/PLATFORM_SETUP.md`). Until then, say "built on the official APIs" rather than "proven on".
- [ ] **Docker install tried once** on a clean machine (`docker compose up --build`), since "run it locally" is part of the pitch.
- [ ] **Licensing / pricing** decided, or at least what you'll say on the call.
- [ ] **Free-test offer:** be ready to run a video through it and send results within a day.
- [ ] **No invented numbers.** Don't quote views or revenue you haven't measured.
