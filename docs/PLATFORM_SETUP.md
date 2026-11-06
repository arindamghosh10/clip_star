# Connecting real social accounts

clip_star posts through each platform's **official API**, so whoever runs clip_star registers one developer app per platform. You do this once; every account on that platform then connects through its own login.

**Before you start**

1. clip_star must be reachable at a stable address. For one computer, `http://localhost:8000` works for most platforms. Some platforms (Meta, TikTok) only accept **https** redirect addresses; then run clip_star behind HTTPS (for example a reverse proxy with a certificate, or a tunnel) and set:
   - `CLIPSTAR_PUBLIC_API_URL` – the address the browser uses for the API (OAuth redirects come back here)
   - `CLIPSTAR_WEB_URL` – the address of the web app
2. In clip_star go to **Settings → Platform apps**. Each platform shows the exact **redirect address** to paste into its developer console, and the permissions to request.
3. Back up the encryption key: `CLIPSTAR_SECRET_KEY`, or the file `.secret_key` in the storage folder. Without it, saved connections can't be read and accounts must be reconnected.

**Try it first without any of this:** add a *practice account* on the Accounts screen. It goes through scheduling, approval and publishing exactly like a real one, but nothing is posted. You can also make it fail on purpose (account page → Practice behaviour) to see retries, verification and reconnect prompts.

Platform rules, approval processes and console menus change often. Each section links to the official docs; follow those where they differ from this page.

---

## YouTube (Shorts)
- **Where:** Google Cloud Console → create a project → enable **YouTube Data API v3** → OAuth consent screen → Credentials → *OAuth client ID* (type: Web application).
- **Redirect address:** add the one shown in clip_star.
- **Permissions:** `youtube.upload`, `youtube.readonly`.
- **Keys in clip_star:** Client ID and Client secret.
- **Good to know:** each upload uses API quota from your project's daily allowance; request more in the console if you post a lot. Apps in "testing" mode only work for listed test users, and Google may require verification before public use. Videos are posted as Shorts when they are vertical and under 3 minutes.
- Docs: https://developers.google.com/youtube/v3/guides/uploading_a_video

## Instagram (Reels) and Facebook (Page Reels)
- **Where:** Meta for Developers → create an app (Business type) → add **Facebook Login** → add the Instagram/Pages products your app needs.
- **Redirect address:** add both clip_star addresses (Instagram and Facebook) under Facebook Login → *Valid OAuth Redirect URIs*. Meta requires https.
- **Permissions:** Instagram: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`. Facebook: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `business_management`.
- **Keys:** App ID and App secret (the same app can be saved for both Instagram and Facebook).
- **Good to know:** Instagram accounts must be **professional** (Business or Creator) and linked to a Facebook Page. One login can add several Pages and Instagram accounts at once. Using these permissions for accounts you don't own needs Meta **App Review**. Instagram allows about 50 API posts per account per day.
- Docs: https://developers.facebook.com/docs/instagram-platform/content-publishing · https://developers.facebook.com/docs/video-api/guides/reels-publishing

## Threads
- **Where:** Meta for Developers → create an app with the **Threads API** use case.
- **Permissions:** `threads_basic`, `threads_content_publish`. **Keys:** Threads App ID and secret.
- **Extra requirement:** Threads downloads the video from a public web address. Set `CLIPSTAR_PUBLIC_MEDIA_URL` to the public https address of this server; clip_star gives Threads a signed link that expires after a few hours.
- Docs: https://developers.facebook.com/docs/threads/posts

## TikTok
- **Where:** TikTok for Developers → create an app → add **Login Kit** and **Content Posting API** (Direct Post).
- **Permissions:** `user.info.basic`, `video.publish`. **Keys:** Client key and Client secret.
- **Good to know:** until TikTok **audits** your app, posts are private (only visible to the account owner) and only a few accounts can post per day. clip_star picks the visibility TikTok allows and marks private posts on the post. Apply for the audit in the developer portal.
- Docs: https://developers.tiktok.com/doc/content-posting-api-get-started

## X
- **Where:** X Developer Portal → project and app → **User authentication settings**: OAuth 2.0, type *Web App*, add the redirect address.
- **Permissions:** `tweet.read`, `tweet.write`, `users.read`, `media.write`, `offline.access`. **Keys:** OAuth 2.0 Client ID and Client secret.
- **Good to know:** posting video needs a **paid X API plan**; posts are limited to 280 characters.
- Docs: https://docs.x.com/x-api/media/quickstart/media-upload-chunked

## LinkedIn
- **Where:** LinkedIn Developer Portal → create an app → add **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**.
- **Permissions:** `openid`, `profile`, `w_member_social`. **Keys:** Client ID and Client secret.
- **Good to know:** posts go to the member's own feed. Logins last about 60 days; clip_star marks the account *Reconnect* when it expires. LinkedIn retires API versions after about a year: if posting starts failing with a version error, set `CLIPSTAR_LINKEDIN_VERSION` to a current `YYYYMM` value.
- Docs: https://learn.microsoft.com/linkedin/marketing/community-management/shares/videos-api

## Pinterest
- **Where:** Pinterest Developers → create an app.
- **Permissions:** `boards:read`, `pins:read`, `pins:write`, `user_accounts:read`. **Keys:** App ID and App secret.
- **Good to know:** pick the board to pin to on the account's page in clip_star (it needs at least one board). New apps start with *Trial* access; request Standard access for public posting.
- Docs: https://developers.pinterest.com/docs/api-features/creating-boards-and-pins/

---

## How clip_star keeps posting safe
- A post is sent only when its batch is approved and running, and its account is connected.
- Every attempt is recorded before the platform is called. If the platform doesn't answer in time, the post is marked **Checking** and clip_star looks for it on the account instead of posting again. If it can't confirm after three checks, it stops and asks you.
- Temporary problems (rate limits, outages) retry after 2, 6, 18 and 54 minutes. Permanent problems (rejected video, missing permission) stop and show the reason.
- Expired logins mark the account **Reconnect**; posts wait instead of failing silently.
