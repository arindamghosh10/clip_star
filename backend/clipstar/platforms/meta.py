"""Instagram Reels, Facebook Page Reels and Threads (Meta).

Instagram and Facebook use Facebook Login and the Graph API; one login can give access to
several Pages and their linked Instagram professional accounts, each becoming an account here.
Threads uses its own login and API, and needs the video at a public URL.
"""

from __future__ import annotations

from ..config import get_settings
from ..errors import PermanentError
from datetime import datetime

from .base import App, Identity, Provider, PublishRequest, PublishResult, RemoteComment, Tokens, num
from .http import call, json_of
from .util import text_matches, url, wait_until


def graph() -> str:
    return f"https://graph.facebook.com/{get_settings().meta_graph_version}"


def rupload(kind: str) -> str:
    return f"https://rupload.facebook.com/{kind}/{get_settings().meta_graph_version}"


class _FacebookLogin(Provider):
    client_id_label = "App ID"

    def auth_url(self, app, state, redirect_uri, code_challenge):
        return url(f"https://www.facebook.com/{get_settings().meta_graph_version}/dialog/oauth", client_id=app.client_id, redirect_uri=redirect_uri, state=state, scope=",".join(self.scopes), response_type="code")

    def exchange(self, app, code, redirect_uri, verifier):
        r = call("GET", url(f"{graph()}/oauth/access_token", client_id=app.client_id, client_secret=app.client_secret, redirect_uri=redirect_uri, code=code), label=self.label)
        short = json_of(r, self.label)["access_token"]
        # swap for a long-lived user token (about 60 days); Page tokens derived from it don't expire
        r = call("GET", url(f"{graph()}/oauth/access_token", grant_type="fb_exchange_token", client_id=app.client_id, client_secret=app.client_secret, fb_exchange_token=short), label=self.label)
        return Tokens.from_oauth(json_of(r, self.label))

    def _pages(self, tokens: Tokens) -> list[dict]:
        r = call("GET", url(f"{graph()}/me/accounts", fields="id,name,access_token,instagram_business_account{id,username}", limit="100", access_token=tokens.access_token), label=self.label)
        return json_of(r, self.label).get("data", [])


class Instagram(_FacebookLogin):
    platform = "instagram"
    label = "Instagram"
    scopes = ["instagram_basic", "instagram_content_publish", "instagram_manage_comments", "instagram_manage_insights", "pages_show_list", "pages_read_engagement", "business_management"]
    metrics_supported = True
    comments_supported = True
    reply_max_chars = 2200
    docs_url = "https://developers.facebook.com/docs/instagram-platform/content-publishing"

    def identities(self, app, tokens):
        out = []
        for p in self._pages(tokens):
            ig = p.get("instagram_business_account")
            if ig and p.get("access_token"):
                out.append(Identity(remote_id=ig["id"], handle=f"@{ig.get('username') or ig['id']}", tokens=Tokens(p["access_token"], extra={"username": ig.get("username")}), options={"page_id": p["id"]}))
        if not out:
            raise PermanentError("no ig", user_message="No Instagram professional account is linked to the Facebook Pages you shared. Link one in Instagram settings, then connect again.")
        return out

    def publish(self, app, tokens, remote_id, req):
        tok = tokens.access_token
        r = call("POST", f"{graph()}/{remote_id}/media", label=self.label, data={"media_type": "REELS", "upload_type": "resumable", "caption": req.caption[:2200], "share_to_feed": "true", "access_token": tok})
        container = json_of(r, self.label)["id"]
        size = req.video.stat().st_size
        call("POST", f"{rupload('ig-api-upload')}/{container}", label=self.label, headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)}, content=req.video.read_bytes())

        def ready():
            d = json_of(call("GET", url(f"{graph()}/{container}", fields="status_code,status", access_token=tok), label=self.label), self.label)
            code = d.get("status_code")
            if code == "FINISHED":
                return "ok"
            if code in ("ERROR", "EXPIRED"):
                raise PermanentError(str(d), user_message=f"Instagram couldn't process the video: {d.get('status') or code}")
            return None

        wait_until(ready, label=self.label)
        r = call("POST", f"{graph()}/{remote_id}/media_publish", label=self.label, commit=True, data={"creation_id": container, "access_token": tok})
        mid = json_of(r, self.label)["id"]
        link = None
        try:
            link = json_of(call("GET", url(f"{graph()}/{mid}", fields="permalink", access_token=tok), label=self.label), self.label).get("permalink")
        except Exception:
            pass  # the post exists; a missing link isn't worth failing over
        return PublishResult(mid, link)

    def find(self, app, tokens, remote_id, req, since):
        d = json_of(call("GET", url(f"{graph()}/{remote_id}/media", fields="id,caption,timestamp,permalink", limit="10", access_token=tokens.access_token), label=self.label), self.label)
        for m in d.get("data", []):
            if text_matches(m.get("caption"), req.caption):
                return PublishResult(m["id"], m.get("permalink"))
        return None


def _iso(v):
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00").replace("+0000", "+00:00")) if v else None
    except ValueError:
        return None


def _ig_comments(self, app, tokens, remote_id, post_remote_id):
    d = json_of(call("GET", url(f"{graph()}/{post_remote_id}/comments", fields="id,text,username,timestamp", limit="50", access_token=tokens.access_token), label=self.label), self.label)
    own = (tokens.extra or {}).get("username")
    return [RemoteComment(c["id"], c.get("username", ""), c.get("text", ""), _iso(c.get("timestamp")), is_own=bool(own) and c.get("username") == own) for c in d.get("data", [])]


def _ig_reply(self, app, tokens, remote_id, post_remote_id, comment_remote_id, text):
    r = call("POST", f"{graph()}/{comment_remote_id}/replies", label=self.label, commit=True, data={"message": text, "access_token": tokens.access_token})
    return json_of(r, self.label)["id"]


def _ig_hide(self, app, tokens, remote_id, comment_remote_id, hidden=True):
    call("POST", f"{graph()}/{comment_remote_id}", label=self.label, data={"hide": "true" if hidden else "false", "access_token": tokens.access_token})


def _insight_values(d: dict) -> dict:
    out = {}
    for m in d.get("data", []):
        v = (m.get("total_value") or {}).get("value")
        if v is None and m.get("values"):
            v = m["values"][-1].get("value")
        out[m.get("name")] = v
    return out


def _ig_metrics(self, app, tokens, remote_id, post_remote_id, published_at, hints=None):
    d = json_of(call("GET", url(f"{graph()}/{post_remote_id}/insights", metric="views,likes,comments,shares,saved,ig_reels_avg_watch_time", access_token=tokens.access_token), label=self.label), self.label)
    v = _insight_values(d)
    avg_ms = v.get("ig_reels_avg_watch_time")
    return {"views": num(v.get("views")), "likes": num(v.get("likes")), "comments": num(v.get("comments")), "shares": num(v.get("shares")), "saves": num(v.get("saved")), "avg_watch_s": (avg_ms / 1000) if isinstance(avg_ms, (int, float)) else None}


def _ig_followers(self, app, tokens, remote_id):
    return num(json_of(call("GET", url(f"{graph()}/{remote_id}", fields="followers_count", access_token=tokens.access_token), label=self.label), self.label).get("followers_count"))


Instagram.post_metrics = _ig_metrics
Instagram.account_followers = _ig_followers
Instagram.list_comments = _ig_comments
Instagram.reply = _ig_reply
Instagram.hide = _ig_hide


class Facebook(_FacebookLogin):
    platform = "facebook"
    label = "Facebook"
    scopes = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "pages_manage_engagement", "pages_read_user_content", "read_insights", "business_management"]
    metrics_supported = True
    comments_supported = True
    reply_max_chars = 8000
    docs_url = "https://developers.facebook.com/docs/video-api/guides/reels-publishing"

    def identities(self, app, tokens):
        out = [Identity(remote_id=p["id"], handle=p.get("name") or p["id"], tokens=Tokens(p["access_token"])) for p in self._pages(tokens) if p.get("access_token")]
        if not out:
            raise PermanentError("no pages", user_message="No Facebook Pages were shared. Connect again and select at least one Page.")
        return out

    def publish(self, app, tokens, remote_id, req):
        tok = tokens.access_token
        d = json_of(call("POST", f"{graph()}/{remote_id}/video_reels", label=self.label, data={"upload_phase": "start", "access_token": tok}), self.label)
        video_id, upload_url = d["video_id"], d.get("upload_url") or f"{rupload('video-upload')}/{d['video_id']}"
        size = req.video.stat().st_size
        call("POST", upload_url, label=self.label, headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)}, content=req.video.read_bytes())
        call("POST", f"{graph()}/{remote_id}/video_reels", label=self.label, commit=True, data={"upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED", "description": req.caption, "access_token": tok})
        return PublishResult(video_id, f"https://www.facebook.com/reel/{video_id}")

    def find(self, app, tokens, remote_id, req, since):
        d = json_of(call("GET", url(f"{graph()}/{remote_id}/video_reels", fields="id,description,created_time", limit="10", access_token=tokens.access_token), label=self.label), self.label)
        for v in d.get("data", []):
            if text_matches(v.get("description"), req.caption):
                return PublishResult(v["id"], f"https://www.facebook.com/reel/{v['id']}")
        return None


def _fb_comments(self, app, tokens, remote_id, post_remote_id):
    d = json_of(call("GET", url(f"{graph()}/{post_remote_id}/comments", fields="id,message,from,created_time", limit="50", access_token=tokens.access_token), label=self.label), self.label)
    return [RemoteComment(c["id"], (c.get("from") or {}).get("name", ""), c.get("message", ""), _iso(c.get("created_time")), is_own=(c.get("from") or {}).get("id") == remote_id) for c in d.get("data", [])]


def _fb_reply(self, app, tokens, remote_id, post_remote_id, comment_remote_id, text):
    r = call("POST", f"{graph()}/{comment_remote_id}/comments", label=self.label, commit=True, data={"message": text, "access_token": tokens.access_token})
    return json_of(r, self.label)["id"]


def _fb_hide(self, app, tokens, remote_id, comment_remote_id, hidden=True):
    call("POST", f"{graph()}/{comment_remote_id}", label=self.label, data={"is_hidden": "true" if hidden else "false", "access_token": tokens.access_token})


def _fb_metrics(self, app, tokens, remote_id, post_remote_id, published_at, hints=None):
    tok = tokens.access_token
    out: dict = {}
    try:
        v = _insight_values(json_of(call("GET", url(f"{graph()}/{post_remote_id}/video_insights", metric="blue_reels_play_count,post_video_avg_time_watched", access_token=tok), label=self.label), self.label))
        out["views"] = num(v.get("blue_reels_play_count"))
        if isinstance(v.get("post_video_avg_time_watched"), (int, float)):
            out["avg_watch_s"] = v["post_video_avg_time_watched"] / 1000
    except Exception:
        pass  # insights can lag or be unavailable for new Pages; likes/comments still help
    d = json_of(call("GET", url(f"{graph()}/{post_remote_id}", fields="likes.summary(true).limit(0),comments.summary(true).limit(0)", access_token=tok), label=self.label), self.label)
    out["likes"] = num(((d.get("likes") or {}).get("summary") or {}).get("total_count"))
    out["comments"] = num(((d.get("comments") or {}).get("summary") or {}).get("total_count"))
    return out


def _fb_followers(self, app, tokens, remote_id):
    return num(json_of(call("GET", url(f"{graph()}/{remote_id}", fields="followers_count", access_token=tokens.access_token), label=self.label), self.label).get("followers_count"))


Facebook.post_metrics = _fb_metrics
Facebook.account_followers = _fb_followers
Facebook.list_comments = _fb_comments
Facebook.reply = _fb_reply
Facebook.hide = _fb_hide

THREADS = "https://graph.threads.net"


class Threads(Provider):
    platform = "threads"
    label = "Threads"
    scopes = ["threads_basic", "threads_content_publish", "threads_read_replies", "threads_manage_replies", "threads_manage_insights"]
    metrics_supported = True
    comments_supported = True
    reply_max_chars = 500
    docs_url = "https://developers.facebook.com/docs/threads/posts"
    client_id_label = "Threads App ID"

    def auth_url(self, app, state, redirect_uri, code_challenge):
        return url("https://threads.net/oauth/authorize", client_id=app.client_id, redirect_uri=redirect_uri, scope=",".join(self.scopes), response_type="code", state=state)

    def exchange(self, app, code, redirect_uri, verifier):
        d = json_of(call("POST", f"{THREADS}/oauth/access_token", label=self.label, data={"client_id": app.client_id, "client_secret": app.client_secret, "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code": code}), self.label)
        r = call("GET", url(f"{THREADS}/access_token", grant_type="th_exchange_token", client_secret=app.client_secret, access_token=d["access_token"]), label=self.label)
        return Tokens.from_oauth(json_of(r, self.label))

    def refresh(self, app, tokens):
        r = call("GET", url(f"{THREADS}/refresh_access_token", grant_type="th_refresh_token", access_token=tokens.access_token), label=self.label)
        return Tokens.from_oauth(json_of(r, self.label))

    def identities(self, app, tokens):
        d = json_of(call("GET", url(f"{THREADS}/v1.0/me", fields="id,username", access_token=tokens.access_token), label=self.label), self.label)
        tokens.extra = {**(tokens.extra or {}), "username": d.get("username")}  # to recognise our own replies
        return [Identity(remote_id=d["id"], handle=f"@{d.get('username') or d['id']}", tokens=tokens)]

    def publish(self, app, tokens, remote_id, req):
        public = req.account_options.get("_public_video_url")
        if not public:
            raise PermanentError("no public url", user_message="Threads needs the video at a public web address. Set CLIPSTAR_PUBLIC_MEDIA_URL to an address where this server is reachable from the internet.")
        tok = tokens.access_token
        d = json_of(call("POST", f"{THREADS}/v1.0/{remote_id}/threads", label=self.label, data={"media_type": "VIDEO", "video_url": public, "text": req.caption[:500], "access_token": tok}), self.label)
        cid = d["id"]

        def ready():
            s = json_of(call("GET", url(f"{THREADS}/v1.0/{cid}", fields="status,error_message", access_token=tok), label=self.label), self.label)
            if s.get("status") == "FINISHED":
                return "ok"
            if s.get("status") in ("ERROR", "EXPIRED"):
                raise PermanentError(str(s), user_message=f"Threads couldn't process the video: {s.get('error_message') or s.get('status')}")
            return None

        wait_until(ready, label=self.label)
        pid = json_of(call("POST", f"{THREADS}/v1.0/{remote_id}/threads_publish", label=self.label, commit=True, data={"creation_id": cid, "access_token": tok}), self.label)["id"]
        link = None
        try:
            link = json_of(call("GET", url(f"{THREADS}/v1.0/{pid}", fields="permalink", access_token=tok), label=self.label), self.label).get("permalink")
        except Exception:
            pass
        return PublishResult(pid, link)

    def find(self, app, tokens, remote_id, req, since):
        d = json_of(call("GET", url(f"{THREADS}/v1.0/{remote_id}/threads", fields="id,text,timestamp,permalink", limit="10", access_token=tokens.access_token), label=self.label), self.label)
        for t in d.get("data", []):
            if text_matches(t.get("text"), req.caption):
                return PublishResult(t["id"], t.get("permalink"))
        return None


def _th_comments(self, app, tokens, remote_id, post_remote_id):
    d = json_of(call("GET", url(f"{THREADS}/v1.0/{post_remote_id}/replies", fields="id,text,username,timestamp", access_token=tokens.access_token), label=self.label), self.label)
    own = (tokens.extra or {}).get("username")
    return [RemoteComment(c["id"], c.get("username", ""), c.get("text", ""), _iso(c.get("timestamp")), is_own=bool(own) and c.get("username") == own) for c in d.get("data", [])]


def _th_reply(self, app, tokens, remote_id, post_remote_id, comment_remote_id, text):
    tok = tokens.access_token
    cid = json_of(call("POST", f"{THREADS}/v1.0/{remote_id}/threads", label=self.label, data={"media_type": "TEXT", "text": text, "reply_to_id": comment_remote_id, "access_token": tok}), self.label)["id"]
    return json_of(call("POST", f"{THREADS}/v1.0/{remote_id}/threads_publish", label=self.label, commit=True, data={"creation_id": cid, "access_token": tok}), self.label)["id"]


def _th_hide(self, app, tokens, remote_id, comment_remote_id, hidden=True):
    call("POST", f"{THREADS}/v1.0/{comment_remote_id}/manage_reply", label=self.label, data={"hide": "true" if hidden else "false", "access_token": tokens.access_token})


Threads.list_comments = _th_comments
Threads.reply = _th_reply
Threads.hide = _th_hide


def _th_metrics(self, app, tokens, remote_id, post_remote_id, published_at, hints=None):
    v = _insight_values(json_of(call("GET", url(f"{THREADS}/v1.0/{post_remote_id}/insights", metric="views,likes,replies,reposts,quotes,shares", access_token=tokens.access_token), label=self.label), self.label))
    shares = sum(x for x in (num(v.get("reposts")), num(v.get("quotes")), num(v.get("shares"))) if x)
    return {"views": num(v.get("views")), "likes": num(v.get("likes")), "comments": num(v.get("replies")), "shares": shares}


def _th_followers(self, app, tokens, remote_id):
    v = _insight_values(json_of(call("GET", url(f"{THREADS}/v1.0/{remote_id}/threads_insights", metric="followers_count", access_token=tokens.access_token), label=self.label), self.label))
    return num(v.get("followers_count"))


Threads.post_metrics = _th_metrics
Threads.account_followers = _th_followers
