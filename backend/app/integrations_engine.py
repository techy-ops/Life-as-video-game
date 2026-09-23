"""
Integrations Engine for LIFE RPG (Phase 2 & Phase 3).
Handles OAuth architecture, secure token storage (AES-style authenticated keystream),
token lifecycle & refresh, activity syncing, deadline extraction, Android Health Connect
bridge ingestion, unified activity normalization, and quest matching for:
- GitHub (Real OAuth + Repo/Commit Sync)
- Google Calendar (Real OAuth + Events/Deadlines + Token Refresh)
- Fitness (Android Health Connect Bridge + Manual Logging)
- Outlook Calendar (Optional Phase 2 compatibility)
"""

from __future__ import annotations
import os
import json
import base64
import hashlib
import hmac
import secrets
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from pathlib import Path
import httpx
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env before reading any environment variables.
# Use the absolute path to backend/.env so this works regardless of working directory.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=True)

SECRET = os.getenv("LIFE_RPG_SECRET", "change-this-secret-in-production")

# ---------- Authenticated Token Encryption (Pure Python, Zero-Dependency) ----------

def encrypt_token(plain_token: str) -> str:
    """Encrypts an OAuth token using PBKDF2-derived keystream + HMAC-SHA256 authenticated container."""
    if not plain_token:
        return ""
    salt = secrets.token_bytes(16)
    # Derive 64 bytes: 32 bytes for CTR keystream, 32 bytes for HMAC
    derived = hashlib.pbkdf2_hmac("sha256", SECRET.encode(), salt, 100000, dklen=64)
    enc_key = derived[:32]
    mac_key = derived[32:]

    data = plain_token.encode("utf-8")
    ciphertext = bytearray()
    # SHA-256 counter-mode stream cipher
    block_idx = 0
    for i in range(0, len(data), 32):
        block_counter = block_idx.to_bytes(4, "big")
        keystream_block = hmac.new(enc_key, salt + block_counter, hashlib.sha256).digest()
        chunk = data[i:i + 32]
        for c_byte, k_byte in zip(chunk, keystream_block):
            ciphertext.append(c_byte ^ k_byte)
        block_idx += 1

    # Authenticate salt + ciphertext
    tag = hmac.new(mac_key, salt + ciphertext, hashlib.sha256).digest()
    packed = salt + tag + ciphertext
    return base64.urlsafe_b64encode(packed).decode("utf-8")

def decrypt_token(cipher_token_b64: str) -> str:
    """Decrypts and verifies an OAuth token container."""
    if not cipher_token_b64:
        return ""
    try:
        packed = base64.urlsafe_b64decode(cipher_token_b64.encode("utf-8"))
        if len(packed) < 48:
            return ""
        salt = packed[:16]
        tag = packed[16:48]
        ciphertext = packed[48:]

        derived = hashlib.pbkdf2_hmac("sha256", SECRET.encode(), salt, 100000, dklen=64)
        enc_key = derived[:32]
        mac_key = derived[32:]

        expected_tag = hmac.new(mac_key, salt + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            return ""

        plaintext = bytearray()
        block_idx = 0
        for i in range(0, len(ciphertext), 32):
            block_counter = block_idx.to_bytes(4, "big")
            keystream_block = hmac.new(enc_key, salt + block_counter, hashlib.sha256).digest()
            chunk = ciphertext[i:i + 32]
            for c_byte, k_byte in zip(chunk, keystream_block):
                plaintext.append(c_byte ^ k_byte)
            block_idx += 1

        return plaintext.decode("utf-8")
    except Exception:
        return ""

# ---------- Schemas ----------

class CalendarEvent(BaseModel):
    id: str
    summary: str
    description: Optional[str] = ""
    start_time: str
    end_time: Optional[str] = None
    is_deadline: bool = False
    suggested_quest_title: Optional[str] = None
    urgency: str = "normal"  # low, normal, urgent
    remaining_hours: Optional[float] = None

class GitHubActivityItem(BaseModel):
    id: str
    type: str  # commit, repo, pr, issue
    title: str
    description: str
    url: Optional[str] = None
    timestamp: str
    repository: str
    sha: Optional[str] = None
    author: Optional[str] = None

class FitnessActivityInput(BaseModel):
    activity_type: str = Field(..., description="e.g. walk, run, cycling, workout, gym")
    duration_minutes: int = Field(..., ge=1, le=1440)
    steps: Optional[int] = Field(None, ge=0)
    calories: Optional[int] = Field(None, ge=0)
    distance_meters: Optional[float] = Field(None, ge=0)
    date: Optional[str] = Field(None)
    notes: Optional[str] = Field("")

class HealthConnectSession(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = "Exercise Session"
    exercise_type: str = Field(default="workout", description="e.g. walking, running, biking, gym, yoga")
    start_time: str
    end_time: str
    duration_minutes: int = Field(..., ge=1, le=1440)
    steps: Optional[int] = Field(None, ge=0)
    calories: Optional[int] = Field(None, ge=0)
    distance_meters: Optional[float] = Field(None, ge=0)
    source_app: Optional[str] = "Health Connect"

class HealthConnectSyncBatch(BaseModel):
    sessions: List[HealthConnectSession] = Field(default_factory=list)
    daily_steps: Optional[int] = None
    date: Optional[str] = None
    device_name: Optional[str] = "Android Device"

class UnifiedActivity(BaseModel):
    id: str
    provider: str  # 'GitHub', 'Google Calendar', 'Fitness', 'Health Connect'
    activity_type: str  # 'github_commit', 'github_repository', 'calendar_event', 'fitness_activity'
    title: str
    description: str
    timestamp: str
    external_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    matched_quest_id: Optional[int] = None
    matched_quest_title: Optional[str] = None

# ---------- Provider Implementations ----------

class BaseProvider:
    name: str = "base"

    def is_configured(self) -> bool:
        return False

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        raise NotImplementedError

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def sync(self, access_token: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def refresh_token_if_needed(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        return None

    async def revoke_token(self, access_token: str) -> bool:
        return True



class GitHubProvider(BaseProvider):
    name = "GitHub"

    def is_configured(self) -> bool:
        return bool(os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET"))

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        client_id = os.getenv("GITHUB_CLIENT_ID", "")
        if not self.is_configured():
            return f"/api/integrations/oauth-demo?provider=GitHub&state={state}&redirect_uri={redirect_uri}"
        return (
            f"https://github.com/login/oauth/authorize?"
            f"client_id={client_id}&redirect_uri={redirect_uri}&"
            f"scope=read:user,repo&state={state}"
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not self.is_configured() or code.startswith("demo_") or "mock" in code:
            return {
                "access_token": f"gh_demo_{secrets.token_hex(16)}",
                "external_user_id": "demo_coder",
                "scopes": "read:user,repo",
                "account_name": "Demo Coder",
                "is_live": False
            }
        client_id = os.getenv("GITHUB_CLIENT_ID", "")
        client_secret = os.getenv("GITHUB_CLIENT_SECRET", "")
        if not (client_id and client_secret):
            raise ValueError("GitHub OAuth credentials are not configured on this server.")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri
                }
            )
            data = resp.json()
            if "error" in data:
                raise ValueError(data.get("error_description", f"GitHub OAuth failed: {data.get('error')}"))

            token = data.get("access_token")
            if not token:
                raise ValueError("No access token returned by GitHub.")

            # Fetch authenticated user profile
            user_resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}", "User-Agent": "LIFE-RPG-Platform"}
            )
            user_info = user_resp.json() if user_resp.status_code == 200 else {}
            login = user_info.get("login") or "github_user"
            name = user_info.get("name") or login

            return {
                "access_token": token,
                "external_user_id": str(login),
                "scopes": data.get("scope", "read:user,repo"),
                "account_name": name,
                "is_live": True
            }


    async def sync(self, access_token: str) -> Dict[str, Any]:
        """Fetches live repositories and recent commits using access token."""
        if not access_token:
            raise ValueError("GitHub access token is missing or invalid. Please connect your GitHub account via OAuth.")

        if "demo" in access_token:
            items = [
                {
                    "id": "commit_d3adb33f",
                    "type": "commit",
                    "title": "feat: implement game master adaptive loop",
                    "description": "feat: implement game master adaptive loop\n\nFull verification and tests",
                    "url": "https://github.com/demo/repo/commit/d3adb33f",
                    "timestamp": datetime.now().isoformat(),
                    "repository": "life-rpg-core",
                    "sha": "d3adb33f1234",
                    "author": "Demo Coder"
                },
                {
                    "id": "repo_101",
                    "type": "repo",
                    "title": "life-rpg-core",
                    "description": "Core RPG engine repository",
                    "url": "https://github.com/demo/life-rpg-core",
                    "timestamp": datetime.now().isoformat(),
                    "repository": "life-rpg-core"
                }
            ]
            return {
                "items": items,
                "summary": f"Successfully synced {len(items)} items from Demo GitHub",
                "repositories_count": 1,
                "last_active_repo": "life-rpg-core",
                "is_live": False
            }

        async with httpx.AsyncClient(timeout=20.0) as client:
            headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "LIFE-RPG-Platform"}
            # Fetch user repositories
            repos_resp = await client.get(
                "https://api.github.com/user/repos?sort=updated&per_page=6&type=owner",
                headers=headers
            )
            if repos_resp.status_code == 401:
                raise ValueError("GitHub access token expired or revoked. Please reconnect.")
            if repos_resp.status_code == 403:
                raise ValueError("GitHub API rate limit exceeded or access forbidden.")
            if repos_resp.status_code != 200:
                raise ValueError(f"GitHub API error: HTTP {repos_resp.status_code}")

            repos = repos_resp.json()
            items = []

            for r in repos:
                repo_name = r.get("name", "")
                owner_login = r.get("owner", {}).get("login", "")
                items.append({
                    "id": f"repo_{r.get('id')}",
                    "type": "repo",
                    "title": repo_name,
                    "description": r.get("description") or "Repository",
                    "url": r.get("html_url", ""),
                    "timestamp": r.get("updated_at", ""),
                    "repository": repo_name
                })

                # Fetch recent commits for the active repo
                if owner_login and repo_name and len(items) < 15:
                    try:
                        commits_resp = await client.get(
                            f"https://api.github.com/repos/{owner_login}/{repo_name}/commits?per_page=3",
                            headers=headers
                        )
                        if commits_resp.status_code == 200:
                            for c in commits_resp.json():
                                sha = c.get("sha", "")
                                commit_msg = c.get("commit", {}).get("message", "Commit")
                                first_line = commit_msg.split("\n")[0][:100]
                                author_name = c.get("commit", {}).get("author", {}).get("name", "Author")
                                commit_date = c.get("commit", {}).get("author", {}).get("date", "")
                                items.append({
                                    "id": f"commit_{sha[:8]}",
                                    "type": "commit",
                                    "title": first_line,
                                    "description": commit_msg,
                                    "url": c.get("html_url", ""),
                                    "timestamp": commit_date,
                                    "repository": repo_name,
                                    "sha": sha[:12],
                                    "author": author_name
                                })
                    except Exception:
                        pass

            last_repo = repos[0].get("name") if repos else "None"
            return {
                "items": items,
                "summary": f"Successfully synced {len(items)} items ({len(repos)} repos) from Live GitHub",
                "repositories_count": len(repos),
                "last_active_repo": last_repo,
                "is_live": True
            }


class GoogleCalendarProvider(BaseProvider):
    name = "Google Calendar"

    def is_configured(self) -> bool:
        return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        if not self.is_configured():
            return f"/api/integrations/oauth-demo?provider=Google+Calendar&state={state}&redirect_uri={redirect_uri}"
        return (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&"
            "scope=https://www.googleapis.com/auth/calendar.events.readonly%20https://www.googleapis.com/auth/userinfo.email&"
            "access_type=offline&prompt=consent&"
            f"state={state}"
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not self.is_configured() or code.startswith("demo_"):
            return {
                "access_token": f"gcal_demo_{secrets.token_hex(16)}",
                "refresh_token": f"gcal_refresh_demo_{secrets.token_hex(16)}",
                "external_user_id": "demo_google_user@gmail.com",
                "scopes": "https://www.googleapis.com/auth/calendar.events.readonly",
                "account_name": "Demo Google User",
                "expires_in": 3600,
                "is_live": False
            }
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        if not (client_id and client_secret):
            raise ValueError("Google Calendar OAuth credentials are not configured on this server.")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri
                }
            )
            data = resp.json()
            if "error" in data:
                raise ValueError(data.get("error_description", f"Google OAuth failed: {data.get('error')}"))

            access_token = data.get("access_token")
            # Fetch user email
            user_email = "google_user"
            try:
                u_resp = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                if u_resp.status_code == 200:
                    user_email = u_resp.json().get("email", "google_user")
            except Exception:
                pass

            return {
                "access_token": access_token,
                "refresh_token": data.get("refresh_token"),
                "scopes": data.get("scope", "calendar.events.readonly"),
                "external_user_id": user_email,
                "account_name": user_email,
                "expires_in": data.get("expires_in", 3600),
                "is_live": True
            }

    async def refresh_token_if_needed(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Refreshes expired access token using refresh_token."""
        if not self.is_configured() or not refresh_token:
            return None
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token"
                }
            )
            data = resp.json()
            if "access_token" in data:
                return {
                    "access_token": data["access_token"],
                    "expires_in": data.get("expires_in", 3600)
                }
        return None

    async def sync(self, access_token: str) -> Dict[str, Any]:
        """Fetches calendar events and identifies deadlines with urgency within next 14 days."""
        now = datetime.now()
        if not access_token or "demo" in access_token:
            events = [
                {
                    "id": "gcal_1",
                    "summary": "Project Submission: REST API & DB",
                    "description": "Upload code repository and walkthrough report",
                    "start_time": (now + timedelta(days=1, hours=4)).replace(minute=0, second=0).isoformat(),
                    "is_deadline": True,
                    "suggested_quest_title": "Submit Project Report & API Code",
                    "urgency": "urgent",
                    "remaining_hours": 28.0
                },
                {
                    "id": "gcal_2",
                    "summary": "Technical Interview — Python & Algorithms",
                    "description": "Live coding and system design review",
                    "start_time": (now + timedelta(days=3, hours=2)).replace(minute=0, second=0).isoformat(),
                    "is_deadline": True,
                    "suggested_quest_title": "Prepare Python & Algorithms Interview",
                    "urgency": "urgent",
                    "remaining_hours": 74.0
                },
                {
                    "id": "gcal_3",
                    "summary": "Weekly Team Standup",
                    "description": "Routine weekly sync meeting",
                    "start_time": (now + timedelta(days=2)).isoformat(),
                    "is_deadline": False,
                    "suggested_quest_title": None,
                    "urgency": "normal",
                    "remaining_hours": 48.0
                }
            ]
            deadlines = [e for e in events if e["is_deadline"]]
            return {
                "events": events,
                "deadlines": deadlines,
                "summary": f"{len(events)} events synced. {len(deadlines)} active deadlines detected (Demo Mode).",
                "is_live": False
            }

        async with httpx.AsyncClient(timeout=20.0) as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            time_min = now.isoformat() + "Z"
            time_max = (now + timedelta(days=21)).isoformat() + "Z"
            resp = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin={time_min}&timeMax={time_max}&singleEvents=true&orderBy=startTime",
                headers=headers
            )
            if resp.status_code == 401:
                raise ValueError("Google Calendar access token expired. Re-authentication or refresh required.")
            if resp.status_code != 200:
                raise ValueError(f"Google Calendar API returned HTTP {resp.status_code}")

            raw = resp.json()
            events = []
            deadline_keywords = ["deadline", "submit", "submission", "due", "interview", "exam", "presentation", "report", "deliverable", "milestone", "test", "assignment"]

            for item in raw.get("items", []):
                summary = item.get("summary", "Untitled")
                start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
                desc = item.get("description", "")
                text_corpus = f"{summary} {desc}".lower()

                is_dl = any(k in text_corpus for k in deadline_keywords)

                # Calculate remaining time
                rem_hours = None
                urgency = "normal"
                if start:
                    try:
                        clean_start = start.replace("Z", "+00:00")
                        ev_time = datetime.fromisoformat(clean_start)
                        if ev_time.tzinfo is not None:
                            now_tz = datetime.now(timezone.utc)
                            diff = (ev_time - now_tz).total_seconds() / 3600.0
                        else:
                            diff = (ev_time - now).total_seconds() / 3600.0
                        rem_hours = round(max(0.0, diff), 1)

                        if is_dl:
                            if rem_hours <= 48:
                                urgency = "urgent"
                            elif rem_hours <= 168: # 7 days
                                urgency = "high"
                            else:
                                urgency = "normal"
                    except Exception:
                        pass

                events.append({
                    "id": item.get("id"),
                    "summary": summary,
                    "description": desc,
                    "start_time": start,
                    "is_deadline": is_dl,
                    "suggested_quest_title": f"Deliverable: {summary}" if is_dl else None,
                    "urgency": urgency,
                    "remaining_hours": rem_hours
                })

            deadlines = [e for e in events if e["is_deadline"]]
            return {
                "events": events,
                "deadlines": deadlines,
                "summary": f"{len(events)} Google Calendar events synced. {len(deadlines)} deadlines detected.",
                "is_live": True
            }


class OutlookCalendarProvider(BaseProvider):
    name = "Outlook Calendar"

    def __init__(self):
        self.client_id = os.getenv("AZURE_CLIENT_ID", "")
        self.client_secret = os.getenv("AZURE_CLIENT_SECRET", "")

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        if not self.is_configured():
            return f"/api/integrations/oauth-demo?provider=Outlook+Calendar&state={state}&redirect_uri={redirect_uri}"
        return (
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
            f"client_id={self.client_id}&response_type=code&redirect_uri={redirect_uri}&"
            f"response_mode=query&scope=Calendars.Read&state={state}"
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not self.is_configured() or code.startswith("demo_"):
            return {
                "access_token": f"ms_demo_{secrets.token_hex(16)}",
                "external_user_id": "outlook_hero@outlook.com",
                "scopes": "Calendars.Read",
                "account_name": "Outlook Hero",
                "is_live": False
            }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri
                }
            )
            data = resp.json()
            if "error" in data:
                raise ValueError(data.get("error_description", "Outlook OAuth failed"))
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "scopes": data.get("scope", ""),
                "external_user_id": "outlook_user",
                "is_live": True
            }

    async def sync(self, access_token: str) -> Dict[str, Any]:
        now = datetime.now()
        events = [
            {
                "id": "ms_cal_1",
                "summary": "Final Term Assignment Due",
                "description": "Submit code review report and unit test suites",
                "start_time": (now + timedelta(days=2, hours=6)).replace(minute=0, second=0).isoformat(),
                "is_deadline": True,
                "suggested_quest_title": "Final Term Assignment Submission",
                "urgency": "urgent",
                "remaining_hours": 54.0
            }
        ]
        deadlines = [e for e in events if e["is_deadline"]]
        return {
            "events": events,
            "deadlines": deadlines,
            "summary": f"{len(events)} Outlook events synced. {len(deadlines)} deadlines found.",
            "is_live": False
        }


class FitnessProvider(BaseProvider):
    name = "Fitness"

    def is_configured(self) -> bool:
        # Health Connect companion bridge is enabled by default
        return True

    async def record_activity(self, activity: FitnessActivityInput) -> Dict[str, Any]:
        """Validates and processes fitness activity into real-world activity log."""
        # Sanity check activity duration and values
        duration = min(1440, max(1, activity.duration_minutes))
        earned_xp = min(150, max(15, duration * 2))
        earned_coins = min(50, max(5, duration // 2))

        return {
            "activity_type": activity.activity_type.lower().strip(),
            "duration_minutes": duration,
            "steps": activity.steps,
            "calories": activity.calories,
            "distance_meters": activity.distance_meters,
            "date": activity.date or datetime.now().isoformat(),
            "earned_xp": earned_xp,
            "earned_coins": earned_coins,
            "verified": True,
            "source": "Manual / Health Connect Bridge",
            "summary": f"Completed {duration}m of {activity.activity_type}" + (f" ({activity.steps} steps)" if activity.steps else "")
        }

    async def process_health_connect_batch(self, batch: HealthConnectSyncBatch) -> Dict[str, Any]:
        """
        Processes real workout sessions and steps synced from Android Health Connect bridge.
        """
        processed_sessions = []
        total_xp = 0
        total_coins = 0

        for session in batch.sessions:
            duration = min(1440, max(1, session.duration_minutes))
            xp = min(150, max(15, duration * 2))
            coins = min(50, max(5, duration // 2))
            total_xp += xp
            total_coins += coins

            summary = f"Health Connect: {duration}m {session.exercise_type}"
            if session.steps:
                summary += f", {session.steps} steps"
            if session.distance_meters:
                summary += f", {round(session.distance_meters / 1000, 2)} km"

            processed_sessions.append({
                "id": session.id or f"hc_{secrets.token_hex(6)}",
                "exercise_type": session.exercise_type.lower(),
                "title": session.title or f"{session.exercise_type.capitalize()} Workout",
                "start_time": session.start_time,
                "end_time": session.end_time,
                "duration_minutes": duration,
                "steps": session.steps,
                "calories": session.calories,
                "distance_meters": session.distance_meters,
                "earned_xp": xp,
                "earned_coins": coins,
                "source_app": session.source_app or "Health Connect",
                "summary": summary
            })

        # Cap total batch reward to prevent abuse
        total_xp = min(300, total_xp)
        total_coins = min(100, total_coins)

        return {
            "sessions": processed_sessions,
            "daily_steps": batch.daily_steps,
            "total_xp": total_xp,
            "total_coins": total_coins,
            "sessions_count": len(processed_sessions),
            "summary": f"Successfully ingested {len(processed_sessions)} Health Connect sessions ({batch.daily_steps or 0} daily steps)."
        }


# ---------- Unified Activity Layer ----------

def normalize_activity(
    provider: str,
    raw_item: Dict[str, Any]
) -> UnifiedActivity:
    """Normalizes provider raw records into standard unified activity format."""
    now_iso = datetime.now().isoformat()
    prov_clean = provider.strip()

    if prov_clean == "GitHub":
        item_type = raw_item.get("type", "commit")
        sha = raw_item.get("sha", "")
        repo = raw_item.get("repository", "")
        title = raw_item.get("title", f"GitHub {item_type}")
        desc = raw_item.get("description", "")
        time = raw_item.get("timestamp") or now_iso
        ext_id = raw_item.get("id") or f"gh_{sha or secrets.token_hex(4)}"
        return UnifiedActivity(
            id=f"act_{secrets.token_hex(8)}",
            provider="GitHub",
            activity_type="github_commit" if item_type == "commit" else "github_repository",
            title=title,
            description=desc,
            timestamp=time,
            external_id=ext_id,
            metadata={"repository": repo, "sha": sha, "url": raw_item.get("url")}
        )

    elif prov_clean in ("Google Calendar", "Outlook Calendar"):
        title = raw_item.get("summary", "Calendar Event")
        desc = raw_item.get("description", "")
        time = raw_item.get("start_time") or now_iso
        ext_id = raw_item.get("id") or f"cal_{secrets.token_hex(4)}"
        is_dl = raw_item.get("is_deadline", False)
        return UnifiedActivity(
            id=f"act_{secrets.token_hex(8)}",
            provider=prov_clean,
            activity_type="calendar_event",
            title=title,
            description=desc,
            timestamp=time,
            external_id=ext_id,
            metadata={
                "is_deadline": is_dl,
                "urgency": raw_item.get("urgency", "normal"),
                "remaining_hours": raw_item.get("remaining_hours")
            }
        )

    elif prov_clean in ("Fitness", "Health Connect"):
        act_type = raw_item.get("activity_type") or raw_item.get("exercise_type") or "workout"
        dur = raw_item.get("duration_minutes", 30)
        steps = raw_item.get("steps")
        title = raw_item.get("title") or f"{dur}m {act_type.capitalize()} Activity"
        desc = raw_item.get("summary") or f"Completed {dur}m of {act_type}"
        time = raw_item.get("date") or raw_item.get("start_time") or now_iso
        ext_id = raw_item.get("id") or f"fit_{secrets.token_hex(4)}"
        return UnifiedActivity(
            id=f"act_{secrets.token_hex(8)}",
            provider="Health Connect",
            activity_type="fitness_activity",
            title=title,
            description=desc,
            timestamp=time,
            external_id=ext_id,
            metadata={"duration_minutes": dur, "steps": steps, "activity_type": act_type}
        )

    else:
        return UnifiedActivity(
            id=f"act_{secrets.token_hex(8)}",
            provider=prov_clean,
            activity_type="manual_evidence",
            title=raw_item.get("title", "Activity"),
            description=raw_item.get("description", ""),
            timestamp=now_iso,
            external_id=secrets.token_hex(6),
            metadata=raw_item
        )


def match_activity_to_quests(
    activity: UnifiedActivity,
    quests: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Finds the most relevant active quest for a normalized activity.
    Ensures strict validation (e.g. learning quests cannot be auto-completed by commit alone).
    """
    if not quests:
        return None

    act_type = activity.activity_type
    act_title_lower = activity.title.lower()
    act_meta = activity.metadata

    # 1. Fitness matching
    if act_type == "fitness_activity":
        fit_kind = str(act_meta.get("activity_type", "")).lower()
        for q in quests:
            q_cat = str(q.get("category", "")).lower()
            q_type = str(q.get("quest_type", "")).lower()
            q_title = str(q.get("title", "")).lower()
            # Strict protection: Learning quests, coding quests, or assessment-required quests must NEVER match fitness
            if q.get("assessment_required") or q_type == "learning" or q_cat in ("learning", "coding", "career"):
                continue
            if q_cat in ("fitness", "health", "wellness") or q_type == "habit" or fit_kind in q_title or any(w in q_title for w in ["walk", "run", "workout", "gym", "cardio", "swim", "cycling", "steps"]):
                return q

    # 2. GitHub commit / repository matching
    elif act_type in ("github_commit", "github_repository"):
        stop_words = {'the', 'and', 'for', 'with', 'from', 'this', 'that', 'into', 'your', 'have', 'action', 'quest', 'complete', 'toward', 'small', 'repeatable'}
        def _tokens(text: str) -> set:
            if not text:
                return set()
            cleaned = re.sub(r'[^a-zA-Z0-9]+', ' ', str(text)).lower()
            return {w for w in cleaned.split() if len(w) >= 2 and w not in stop_words}

        raw_repo = str(act_meta.get("repository", "")).lower()
        repo_clean = re.sub(r'[-_./\s]+', ' ', raw_repo)
        repo_tokens = _tokens(raw_repo)
        raw_commit_words = _tokens(act_title_lower)
        commit_words_longer = {w for w in raw_commit_words if len(w) >= 3 and w not in ('feat', 'fix', 'test', 'update', 'add', 'refactor', 'changes', 'commit', 'code')}

        # Filter eligible quests for coding/projects/engineering
        eligible = []
        for q in quests:
            q_cat = str(q.get("category", "")).lower()
            q_type = str(q.get("quest_type", "")).lower()
            q_skill = str(q.get("skill", "")).lower()
            q_subject = str(q.get("subject", "")).lower()
            goal_cat = str(q.get("goal_category", "")).lower()
            goal_type = str(q.get("goal_type", "")).lower()

            # Strictly reject non-engineering domains (Fitness, Health, Wellness, Relationships, Finance)
            if q_cat in ("fitness", "health", "wellness", "finance", "relationships") or q_skill in ("fitness", "health", "wellness"):
                continue

            # Must be linked to code/project/learning/technical activity
            is_coding_domain = (
                q_cat in ("coding", "projects", "learning", "career", "personal") or
                goal_cat in ("coding", "projects", "learning", "career", "personal")
            )
            is_coding_skill = (
                any(k in q_skill for k in ["coding", "project", "python", "dsa", "software", "dev", "engineer", "fastapi", "web", "api"]) or
                any(k in q_subject for k in ["python", "dsa", "coding"]) or
                goal_type in ("project", "learning") or
                q_type in ("build", "project", "challenge", "practice", "habit", "boss", "learning")
            )
            if is_coding_domain and is_coding_skill:
                eligible.append(q)

        if not eligible:
            return None

        if act_type == "github_commit":
            best_match = None
            best_score = 0

            for q in eligible:
                score = 0
                q_title = str(q.get("title", "")).lower()
                q_desc = str(q.get("description", "")).lower()
                goal_title = str(q.get("goal_title", "")).lower()
                q_skill = str(q.get("skill", "")).lower()
                q_subject = str(q.get("subject", "")).lower()
                q_topic = str(q.get("topic", "")).lower()

                q_title_tokens = _tokens(q_title)
                q_desc_tokens = _tokens(q_desc)
                goal_tokens = _tokens(goal_title)
                skill_tokens = _tokens(f"{q_skill} {q_subject} {q_topic}")

                quest_all_tokens = q_title_tokens | q_desc_tokens | goal_tokens | skill_tokens

                # Check repo match
                repo_in_text = bool(
                    raw_repo and (raw_repo in q_title or raw_repo in q_desc or raw_repo in goal_title)
                ) or bool(
                    repo_clean and (repo_clean in q_title or repo_clean in q_desc or repo_clean in goal_title)
                )

                # Meaningful repo token overlap (e.g. 'python', 'api', 'two', 'sum', 'fastapi', 'rpg')
                meaningful_repo_tokens = {w for w in repo_tokens if w not in ('the', 'test', 'demo', 'app', 'new')}
                repo_token_overlap = meaningful_repo_tokens & quest_all_tokens

                # Check commit keyword overlap
                overlap_title = raw_commit_words & q_title_tokens
                overlap_desc = raw_commit_words & q_desc_tokens
                overlap_goal = raw_commit_words & goal_tokens
                overlap_skill = raw_commit_words & skill_tokens
                all_keyword_overlap = commit_words_longer & quest_all_tokens

                # Direct task match
                if repo_in_text and (overlap_title or overlap_goal or all_keyword_overlap):
                    score += 10
                elif repo_token_overlap and (overlap_title or overlap_goal or all_keyword_overlap):
                    score += 7
                elif repo_in_text:
                    # Direct commit to the specific repository linked to this goal / quest!
                    score += 6
                elif repo_token_overlap and any(w in act_title_lower for w in ["api", "router", "endpoint", "feat", "fix", "crud", "test", "build", "refactor", "changes", "update"]):
                    score += 5
                elif all_keyword_overlap:
                    score += 5 + len(all_keyword_overlap)
                elif (overlap_title or overlap_goal):
                    score += 4
                elif repo_token_overlap:
                    score += 3

                # Prefer active coding/project quests over generic when committing real code
                if not q.get("assessment_required") and q.get("quest_type") in ("build", "project", "challenge", "practice", "habit"):
                    score += 1

                if score > best_score:
                    best_score = score
                    best_match = q

            if best_score >= 3:
                return best_match

        elif act_type == "github_repository":
            for q in eligible:
                q_title = str(q.get("title", "")).lower()
                q_desc = str(q.get("description", "")).lower()
                goal_title = str(q.get("goal_title", "")).lower()
                if raw_repo and (raw_repo in q_title or raw_repo in q_desc or raw_repo in goal_title):
                    if any(w in q_title for w in ["repo", "repository", "setup", "initialize", "init", "scaffold", "build"]):
                        return q

    # 3. Calendar deadline matching
    elif act_type == "calendar_event":
        for q in quests:
            q_title = str(q.get("title", "")).lower()
            if any(w in act_title_lower for w in q_title.split() if len(w) > 3):
                return q

    return None


# Provider Registry
PROVIDERS: Dict[str, BaseProvider] = {
    "GitHub": GitHubProvider(),
    "Google Calendar": GoogleCalendarProvider(),
    "Outlook Calendar": OutlookCalendarProvider(),
    "Fitness": FitnessProvider()
}

def get_provider(name: str) -> Optional[BaseProvider]:
    """Case-insensitive and whitespace-tolerant provider lookup."""
    clean_target = name.lower().replace(" ", "").replace("_", "").replace("-", "")
    for key, prov in PROVIDERS.items():
        clean_key = key.lower().replace(" ", "").replace("_", "").replace("-", "")
        if clean_key == clean_target:
            return prov
    return None
