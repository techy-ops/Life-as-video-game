import unittest
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import (
    app, SessionLocal, User, Goal, Campaign, Milestone, Quest, Integration,
    Evidence, Assessment, Skill, UnifiedActivityRecord, hash_password, token_for
)
from app.integrations_engine import get_provider, encrypt_token

class TestGitHubEvidenceAndProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = SessionLocal()

        # Clean up existing test user (full, ordered cleanup)
        old_u = cls.db.query(User).filter_by(email="github_progress_tester@test.com").first()
        if old_u:
            cls.cleanup_user(old_u.id)

        # Create fresh test user
        cls.user = User(
            email="github_progress_tester@test.com",
            password_hash=hash_password("testpass123"),
            name="Code Hero",
            level=1,
            xp=0,
            coins=100,
            onboarding_done=True
        )
        cls.db.add(cls.user)
        cls.db.commit()
        cls.db.refresh(cls.user)
        cls.token = token_for(cls.user.id)

        # Pre-create a connected GitHub integration so all tests that need it work
        # even when run out of sequence or in full suite context.
        it = Integration(
            user_id=cls.user.id,
            provider="GitHub",
            connected=True,
            status="connected",
            is_live=True,
            access_token_enc=encrypt_token("gho_test_valid_access_token_123"),
            account_name="hero_dev"
        )
        cls.db.add(it)
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'user') and cls.user:
            cls.cleanup_user(cls.user.id)
        cls.db.close()

    @classmethod
    def cleanup_user(cls, uid):
        """Safely removes all data for a user in the correct FK order."""
        s = cls.db
        # Get all goals for this user
        gids = [g.id for g in s.query(Goal).filter_by(user_id=uid).all()]
        # Get all quests for those goals
        qids = [q.id for q in s.query(Quest).filter(Quest.goal_id.in_(gids)).all()] if gids else []
        # Delete in FK dependency order
        if qids:
            s.query(Evidence).filter(Evidence.quest_id.in_(qids)).delete(synchronize_session=False)
            s.query(Assessment).filter(Assessment.quest_id.in_(qids)).delete(synchronize_session=False)
            s.query(Quest).filter(Quest.id.in_(qids)).delete(synchronize_session=False)
        if gids:
            # Get campaign IDs for this user's goals to scope milestone deletion correctly
            camp_ids = [c.id for c in s.query(Campaign).filter_by(user_id=uid).all()]
            if camp_ids:
                s.query(Milestone).filter(Milestone.campaign_id.in_(camp_ids)).delete(synchronize_session=False)
            s.query(Campaign).filter_by(user_id=uid).delete(synchronize_session=False)
            s.query(Goal).filter_by(user_id=uid).delete(synchronize_session=False)
        s.query(Skill).filter_by(user_id=uid).delete(synchronize_session=False)
        s.query(UnifiedActivityRecord).filter_by(user_id=uid).delete(synchronize_session=False)
        s.query(Integration).filter_by(user_id=uid).delete(synchronize_session=False)
        s.query(User).filter_by(id=uid).delete(synchronize_session=False)
        s.commit()

    def setUp(self):
        it = self.db.query(Integration).filter_by(user_id=self.user.id, provider="GitHub").first()
        if not it:
            it = Integration(
                user_id=self.user.id,
                provider="GitHub",
                connected=True,
                status="connected",
                is_live=True,
                access_token_enc=encrypt_token("gho_test_valid_access_token_123"),
                account_name="hero_dev"
            )
            self.db.add(it)
        else:
            it.connected = True
            it.status = "connected"
            it.is_live = True
            it.access_token_enc = encrypt_token("gho_test_valid_access_token_123")
        self.db.commit()

    def auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _setup_coding_campaign(self):
        """Sets up a goal, campaign, milestone, skill, and an active coding project quest."""
        # Skill
        sk = self.db.query(Skill).filter_by(user_id=self.user.id, name="Coding").first()
        if not sk:
            sk = Skill(user_id=self.user.id, name="Coding", branch="Career", progress=10.0, xp=50, level=1, unlocked=True)
            self.db.add(sk)

        goal = Goal(user_id=self.user.id, title="Build Full Stack Web App", category="Coding", goal_type="project", progress=0.0)
        self.db.add(goal)
        self.db.commit()

        camp = Campaign(user_id=self.user.id, goal_id=goal.id, title="Full Stack Web App Campaign", summary="Real world software engineering")
        self.db.add(camp)
        self.db.commit()

        ms = Milestone(campaign_id=camp.id, title="Core API Backend", description="Build REST API", order_index=1, status="active", progress=0.0, reward_xp=100, reward_coins=30)
        self.db.add(ms)
        self.db.commit()

        q1 = Quest(
            goal_id=goal.id,
            milestone_id=ms.id,
            title="Implement FastAPI Auth Router",
            description="Create JWT authentication router in repo life-rpg-api",
            quest_type="build",
            category="Coding",
            difficulty=2,
            xp=100,
            coin_reward=25,
            status="available",
            order_index=1,
            skill="Coding",
            evidence_required=True,
            assessment_required=False
        )
        q2 = Quest(
            goal_id=goal.id,
            milestone_id=ms.id,
            title="Implement User Profile Endpoint",
            description="Second endpoint",
            quest_type="build",
            category="Coding",
            difficulty=2,
            xp=80,
            coin_reward=20,
            status="locked",
            order_index=2,
            skill="Coding",
            evidence_required=True,
            assessment_required=False
        )
        self.db.add(q1)
        self.db.add(q2)
        self.db.commit()

        return goal, ms, q1, q2

    @patch("httpx.AsyncClient")
    def test_a_real_github_commit_creates_verified_evidence_and_progress(self, mock_client_cls):
        """
        Scenario A:
        Real GitHub commit is synced -> matched to active quest -> creates authentic Evidence
        record with repository, commit title, URL, sha, and updates quest status & user XP.
        """
        goal, ms, q1, q2 = self._setup_coding_campaign()
        # Refresh user to get current (clean) XP/coins from DB
        self.db.refresh(self.user)
        initial_xp = self.user.xp
        initial_coins = self.user.coins

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        # Mock GitHub /user/repos
        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = [
            {
                "id": 5001,
                "name": "life-rpg-api",
                "description": "FastAPI engine",
                "html_url": "https://github.com/hero_dev/life-rpg-api",
                "updated_at": "2026-09-20T12:00:00Z",
                "owner": {"login": "hero_dev"}
            }
        ]

        # Mock GitHub /repos/owner/repo/commits
        mock_commits_resp = MagicMock()
        mock_commits_resp.status_code = 200
        commit_sha = "f7e8d9c0b1a2"
        commit_url = f"https://github.com/hero_dev/life-rpg-api/commit/{commit_sha}"
        mock_commits_resp.json.return_value = [
            {
                "sha": commit_sha,
                "commit": {
                    "message": "feat: implement FastAPI Auth Router with JWT verification\n\nFull security layer added.",
                    "author": {"name": "Hero Dev", "date": "2026-09-20T11:45:00Z"}
                },
                "html_url": commit_url
            }
        ]
        mock_client.get.side_effect = [mock_repos_resp, mock_commits_resp]

        # Trigger sync
        sync_resp = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(sync_resp.status_code, 200)
        res_json = sync_resp.json()
        self.assertEqual(res_json["status"], "synced")
        self.assertIn("Implement FastAPI Auth Router", res_json["sync_stats"]["matched_quests"])
        self.assertGreater(res_json["sync_stats"]["evidence_created"], 0)

        # Verify Evidence record in DB
        ev = self.db.query(Evidence).filter_by(quest_id=q1.id, user_id=self.user.id, kind="github").first()
        self.assertIsNotNone(ev, "Verified GitHub Evidence was not created in DB")
        self.assertTrue(ev.supports_quest)
        self.assertGreaterEqual(ev.quality, 80.0)
        self.assertIn("life-rpg-api", ev.value)
        self.assertIn(commit_url, ev.value)
        self.assertEqual(ev.filename, commit_sha[:12])
        self.assertIn("Verified", ev.evaluation)

        # Verify UnifiedActivityRecord
        act = self.db.query(UnifiedActivityRecord).filter_by(user_id=self.user.id, external_id=f"commit_{commit_sha[:8]}").first()
        self.assertIsNotNone(act, "UnifiedActivityRecord was not created")
        self.assertEqual(act.matched_quest_id, q1.id)
        meta = json.loads(act.metadata_json)
        self.assertEqual(meta["repository"], "life-rpg-api")
        self.assertEqual(meta["url"], commit_url)

        # Verify Quest completion & RPG progression
        self.db.refresh(q1)
        self.assertEqual(q1.status, "completed")
        self.assertIsNotNone(q1.completed_at)

        # Verify Assessment — use the most recent Assessment for this quest to be robust
        # against stale data from previous runs in the same DB
        from sqlalchemy import desc
        assess = (
            self.db.query(Assessment)
            .filter_by(quest_id=q1.id, user_id=self.user.id)
            .order_by(desc(Assessment.id))
            .first()
        )
        self.assertIsNotNone(assess)
        self.assertGreaterEqual(assess.score, 0.8)

        # Verify User XP and coins increased via existing progression logic
        self.db.refresh(self.user)
        self.assertGreater(self.user.xp, initial_xp)
        self.assertGreater(self.user.coins, initial_coins)

        # Verify next quest unlocked
        self.db.refresh(q2)
        self.assertEqual(q2.status, "available")

    @patch("httpx.AsyncClient")
    def test_b_duplicate_commit_does_not_create_duplicate_evidence(self, mock_client_cls):
        """
        Scenario B:
        Syncing the exact same GitHub commit a second time must NOT create duplicate Evidence,
        must NOT create duplicate UnifiedActivityRecords, and must NOT award double XP.
        """
        # User state before second sync
        self.db.refresh(self.user)
        xp_before = self.user.xp
        coins_before = self.user.coins

        # Count evidence before
        commit_sha = "f7e8d9c0b1a2"
        commit_url = f"https://github.com/hero_dev/life-rpg-api/commit/{commit_sha}"
        ev_count_before = self.db.query(Evidence).filter(Evidence.value.contains(commit_url)).count()
        self.assertEqual(ev_count_before, 1)

        # Mock identical sync response
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = [
            {"id": 5001, "name": "life-rpg-api", "description": "FastAPI engine", "html_url": "https://github.com/hero_dev/life-rpg-api", "owner": {"login": "hero_dev"}}
        ]
        mock_commits_resp = MagicMock()
        mock_commits_resp.status_code = 200
        mock_commits_resp.json.return_value = [
            {"sha": commit_sha, "commit": {"message": "feat: implement FastAPI Auth Router", "author": {"name": "Hero Dev", "date": "2026-09-20T11:45:00Z"}}, "html_url": commit_url}
        ]
        mock_client.get.side_effect = [mock_repos_resp, mock_commits_resp]

        # Trigger second sync
        sync_resp = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(sync_resp.status_code, 200)
        res_json = sync_resp.json()
        self.assertEqual(res_json["sync_stats"]["evidence_created"], 0)
        self.assertEqual(res_json["sync_stats"]["new_activities"], 0)

        # Verify Evidence count is STILL 1
        ev_count_after = self.db.query(Evidence).filter(Evidence.value.contains(commit_url)).count()
        self.assertEqual(ev_count_after, 1, "Duplicate Evidence was created on repeated sync!")

        # Verify user XP and coins did not increase (no double-awarding)
        self.db.refresh(self.user)
        self.assertEqual(self.user.xp, xp_before)
        self.assertEqual(self.user.coins, coins_before)

    @patch("httpx.AsyncClient")
    def test_c_unmatched_commit_does_not_corrupt_quest_progress(self, mock_client_cls):
        """
        Scenario C:
        A commit that does not match any active quest (e.g. unrelated project, or user only has fitness quests)
        must ingest cleanly into the activity layer without corrupting, modifying, or completing unrelated quests.
        """
        # Create an unrelated health quest
        goal_health = Goal(user_id=self.user.id, title="Fitness Transformation", category="Health", goal_type="habit", progress=0.0)
        self.db.add(goal_health)
        self.db.commit()

        q_health = Quest(
            goal_id=goal_health.id,
            title="Morning 5km Run",
            description="Run 5km outdoor intervals",
            quest_type="habit",
            category="Health",
            status="available",
            evidence_required=True,
            xp=50,
            coin_reward=15
        )
        self.db.add(q_health)
        self.db.commit()

        self.db.refresh(self.user)
        xp_before = self.user.xp

        # Mock an unrelated commit on an unrelated repository
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = [
            {"id": 8888, "name": "random-sandbox-scripts", "description": "Just scratchpad", "html_url": "https://github.com/hero_dev/random-sandbox-scripts", "owner": {"login": "hero_dev"}}
        ]
        mock_commits_resp = MagicMock()
        mock_commits_resp.status_code = 200
        unmatched_sha = "112233445566"
        unmatched_url = f"https://github.com/hero_dev/random-sandbox-scripts/commit/{unmatched_sha}"
        mock_commits_resp.json.return_value = [
            {"sha": unmatched_sha, "commit": {"message": "docs: update personal scratchpad notes", "author": {"name": "Hero Dev", "date": "2026-09-20T12:30:00Z"}}, "html_url": unmatched_url}
        ]
        mock_client.get.side_effect = [mock_repos_resp, mock_commits_resp]

        sync_resp = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(sync_resp.status_code, 200)
        res_json = sync_resp.json()
        self.assertEqual(res_json["sync_stats"]["evidence_created"], 0)

        # Verify activity was recorded with matched_quest_id = None
        act = self.db.query(UnifiedActivityRecord).filter_by(user_id=self.user.id, external_id=f"commit_{unmatched_sha[:8]}").first()
        self.assertIsNotNone(act)
        self.assertIsNone(act.matched_quest_id)

        # Health quest must remain available and untouched
        self.db.refresh(q_health)
        self.assertEqual(q_health.status, "available")
        ev_health = self.db.query(Evidence).filter_by(quest_id=q_health.id).all()
        self.assertEqual(len(ev_health), 0)

        # User XP must be untouched
        self.db.refresh(self.user)
        self.assertEqual(self.user.xp, xp_before)

    @patch("httpx.AsyncClient")
    def test_d_github_api_and_token_failures_handled_safely(self, mock_client_cls):
        """
        Scenario D:
        1. Expired/revoked token (401 from GitHub API) -> integration marked failed, returns 502 with clean message.
        2. API rate limit / forbidden (403 from GitHub API) -> handled safely.
        3. Missing access token -> raises clean error, no simulation demo data returned.
        """
        # Ensure there is a connected GitHub integration for this user (idempotent upsert)
        it = self.db.query(Integration).filter_by(user_id=self.user.id, provider="GitHub").first()
        if not it:
            it = Integration(
                user_id=self.user.id,
                provider="GitHub",
                connected=True,
                status="connected",
                is_live=True,
                access_token_enc=encrypt_token("gho_test_valid_access_token_123"),
                account_name="hero_dev"
            )
            self.db.add(it)
        else:
            # Re-set to connected state in case a previous test left it in 'failed'
            it.connected = True
            it.status = "connected"
            it.access_token_enc = encrypt_token("gho_test_valid_access_token_123")
        self.db.commit()
        self.db.refresh(it)

        # 1. Test expired token (HTTP 401)
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        mock_client.get.return_value = mock_resp_401

        resp = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(resp.status_code, 502)
        self.assertIn("expired or revoked", resp.json()["detail"])

        # Check DB status was safely updated to failed and reauth_required
        self.db.refresh(it)
        self.assertEqual(it.sync_status, "failed")
        self.assertIn("expired or revoked", it.error_message)
        self.assertFalse(it.connected)
        self.assertEqual(it.status, "reauth_required")
        self.assertEqual(it.access_token_enc, "")

        # Re-connect for the 403 test
        it.connected = True
        it.status = "connected"
        it.sync_status = "idle"
        it.error_message = ""
        it.access_token_enc = encrypt_token("gho_test_valid_access_token_123")
        self.db.commit()

        # 2. Test rate limit (HTTP 403)
        mock_resp_403 = MagicMock()
        mock_resp_403.status_code = 403
        mock_client.get.return_value = mock_resp_403

        resp2 = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(resp2.status_code, 502)
        self.assertIn("rate limit", resp2.json()["detail"])

        # 3. Direct provider check with empty token
        gh_prov = get_provider("GitHub")
        import asyncio
        with self.assertRaises(ValueError) as cm:
            asyncio.run(gh_prov.sync(""))
        self.assertIn("missing or invalid", str(cm.exception))

    @patch("httpx.AsyncClient")
    def test_e_regression_real_browser_flow_with_two_sum_project_and_commits(self, mock_client_cls):
        """
        Regression Test reproducing the REAL user flow:
        - User creates a project goal ('Add two_sum project in github') via natural flow.
        - Has active quest ('Define Scope Action', habit/project type, category Learning, assessment_required=False).
        - Connects real GitHub and syncs commit ('Two sum testing updates' in repo 'life-rpg-python-test').
        - Asserts XP_AFTER > XP_BEFORE.
        - Asserts authentic Evidence created and verified.
        - Asserts quest completed and next quest unlocked.
        - Asserts re-sync does NOT award duplicate XP.
        """
        # Ensure integration is live and connected
        it = self.db.query(Integration).filter_by(user_id=self.user.id, provider="GitHub").first()
        it.connected = True
        it.status = "connected"
        it.is_live = True
        it.access_token_enc = encrypt_token("gho_real_user_flow_token_123")
        it.account_name = "techy-ops"
        self.db.commit()

        # Create the real user's goal and campaign
        goal = Goal(
            user_id=self.user.id,
            title="Add two_sum project in github",
            category="Learning",
            goal_type="project",
            progress=0.0
        )
        self.db.add(goal)
        self.db.commit()

        camp = Campaign(
            user_id=self.user.id,
            goal_id=goal.id,
            title="Add two_sum project in github",
            summary="Two sum coding project campaign"
        )
        self.db.add(camp)
        self.db.commit()

        m1 = Milestone(
            campaign_id=camp.id,
            title="Define Scope",
            description="Define Scope for two_sum project",
            order_index=1,
            status="active",
            reward_xp=120,
            reward_coins=30
        )
        m2 = Milestone(
            campaign_id=camp.id,
            title="Foundation Build",
            description="Foundation Build for two_sum project",
            order_index=2,
            status="locked",
            reward_xp=150,
            reward_coins=40
        )
        self.db.add(m1)
        self.db.add(m2)
        self.db.commit()

        q1 = Quest(
            goal_id=goal.id,
            milestone_id=m1.id,
            title="Define Scope Action",
            description="Complete one small repeatable action toward Add two_sum project in github.",
            quest_type="habit",
            category="Learning",
            difficulty=1,
            xp=60,
            coin_reward=18,
            status="available",
            order_index=0,
            skill="Projects",
            evidence_required=False,
            assessment_required=False
        )
        q2 = Quest(
            goal_id=goal.id,
            milestone_id=m2.id,
            title="Foundation Build Quest",
            description="Learn and explain the essential ideas behind Add two_sum project in github.",
            quest_type="learning",
            category="Learning",
            difficulty=1,
            xp=70,
            coin_reward=20,
            status="locked",
            order_index=1,
            skill="Projects",
            evidence_required=False,
            assessment_required=False
        )
        self.db.add(q1)
        self.db.add(q2)
        self.db.commit()

        # Record XP before sync
        self.db.refresh(self.user)
        xp_before = self.user.xp
        coins_before = self.user.coins

        # Mock GitHub API response with real commit data
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = [
            {
                "id": 9901,
                "name": "life-rpg-python-test",
                "description": "Python test repo",
                "html_url": "https://github.com/techy-ops/life-rpg-python-test",
                "updated_at": "2026-09-21T16:32:00Z",
                "owner": {"login": "techy-ops"}
            }
        ]

        commit_sha = "f179a2c610007d46a0fbeeb"
        mock_commits_resp = MagicMock()
        mock_commits_resp.status_code = 200
        mock_commits_resp.json.return_value = [
            {
                "sha": commit_sha,
                "commit": {
                    "message": "Two sum testing updates",
                    "author": {"name": "Krishna Keerthana", "date": "2026-09-21T16:30:00Z"}
                },
                "html_url": f"https://github.com/techy-ops/life-rpg-python-test/commit/{commit_sha}"
            }
        ]
        mock_client.get.side_effect = [mock_repos_resp, mock_commits_resp]

        # Call POST /api/integrations/GitHub/sync (exact browser endpoint)
        resp = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Assertions on sync_stats
        self.assertEqual(data["sync_stats"]["evidence_created"], 1)
        self.assertGreater(data["sync_stats"]["total_xp_awarded"], 0)
        self.assertIn("Define Scope Action", data["sync_stats"]["matched_quests"])

        # Check DB user XP updated
        self.db.refresh(self.user)
        xp_after = self.user.xp
        self.assertGreater(xp_after, xp_before, "REAL BUG ASSERTION: XP_AFTER must be greater than XP_BEFORE")
        self.assertEqual(xp_after - xp_before, data["sync_stats"]["total_xp_awarded"])
        self.assertGreater(self.user.coins, coins_before)

        # Check Evidence created in DB
        ev = self.db.query(Evidence).filter_by(quest_id=q1.id, user_id=self.user.id, kind="github").first()
        self.assertIsNotNone(ev)
        self.assertTrue(ev.supports_quest)
        self.assertGreaterEqual(ev.quality, 80.0)
        self.assertIn("f179a2c6", ev.filename)

        # Check quest1 completed and quest2 unlocked
        self.db.refresh(q1)
        self.assertEqual(q1.status, "completed")
        self.db.refresh(q2)
        self.assertEqual(q2.status, "available")

        # Duplicate Sync Check: Resync must NOT award XP twice
        mock_client.get.side_effect = [mock_repos_resp, mock_commits_resp]
        resp2 = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2["sync_stats"]["evidence_created"], 0)
        self.assertEqual(data2["sync_stats"]["total_xp_awarded"], 0)

        self.db.refresh(self.user)
        self.assertEqual(self.user.xp, xp_after, "Duplicate sync must NOT increase XP twice")

    @patch("httpx.AsyncClient")
    def test_f_github_expired_token_marks_reauth_and_reconnect_flow(self, mock_client_cls):
        """
        Scenario F:
        1. Connected GitHub encounters 401 Unauthorized during sync.
        2. Backend immediately transitions integration to connected=False, status='reauth_required', and clears token.
        3. GET /api/integrations reflects reauth_required and connected=False without token leakage.
        4. Re-sync while reauth_required is cleanly rejected with 400.
        5. User initiates reconnect via OAuth callback: integration restored to connected=True, status='connected'.
        """
        it = self.db.query(Integration).filter_by(user_id=self.user.id, provider="GitHub").first()
        if not it:
            it = Integration(user_id=self.user.id, provider="GitHub")
            self.db.add(it)
        it.connected = True
        it.status = "connected"
        it.is_live = True
        it.sync_status = "idle"
        it.error_message = ""
        it.access_token_enc = encrypt_token("gho_old_token_to_expire_123")
        self.db.commit()

        # 1. Trigger sync that fails with 401
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        mock_client.get.return_value = mock_resp_401

        resp = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(resp.status_code, 502)
        self.assertIn("expired or revoked", resp.json()["detail"])

        # 2. Check DB status
        self.db.refresh(it)
        self.assertFalse(it.connected)
        self.assertEqual(it.status, "reauth_required")
        self.assertEqual(it.sync_status, "failed")
        self.assertEqual(it.access_token_enc, "")

        # 3. Check GET /api/integrations
        list_resp = self.client.get("/api/integrations", headers=self.auth_headers())
        self.assertEqual(list_resp.status_code, 200)
        gh_item = next((x for x in list_resp.json() if x["provider"] == "GitHub"), None)
        self.assertIsNotNone(gh_item)
        self.assertFalse(gh_item["connected"])
        self.assertEqual(gh_item["status"], "reauth_required")
        self.assertNotIn("access_token", gh_item)
        self.assertNotIn("access_token_enc", gh_item)

        # 4. Attempting sync while reauth_required returns 400
        sync_while_reauth = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(sync_while_reauth.status_code, 400)
        self.assertIn("reconnect", sync_while_reauth.json()["detail"].lower())

        # 5. Reconnect via OAuth callback
        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {
            "access_token": "gho_new_fresh_reconnected_token_456",
            "scope": "read:user,repo"
        }
        mock_client.post.return_value = mock_post_resp

        mock_user_resp = MagicMock()
        mock_user_resp.status_code = 200
        mock_user_resp.json.return_value = {"login": "hero_dev", "name": "Hero Developer"}

        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = []

        mock_client.get.side_effect = [mock_user_resp, mock_repos_resp]

        state = f"{self.user.id}_github_reconnect_123"
        cb_resp = self.client.post(
            "/api/integrations/GitHub/callback",
            json={"code": "live_reconnect_code_789", "state": state, "redirect_uri": "http://localhost:5173/integrations"},
            headers=self.auth_headers()
        )
        self.assertEqual(cb_resp.status_code, 200)
        cb_data = cb_resp.json()
        self.assertTrue(cb_data["connected"])
        self.assertEqual(cb_data["status"], "connected")

        self.db.refresh(it)
        self.assertTrue(it.connected)
        self.assertEqual(it.status, "connected")
        self.assertNotEqual(it.access_token_enc, "")

    @patch("httpx.AsyncClient")
    def test_g_github_empty_repo_and_rate_limit_resilience(self, mock_client_cls):
        """
        Scenario G:
        - Handle empty git repositories (409 Conflict) without crashing sync.
        - Handle rate limit headers (403 with x-ratelimit-remaining: 0).
        """
        it = self.db.query(Integration).filter_by(user_id=self.user.id, provider="GitHub").first()
        it.connected = True
        it.status = "connected"
        it.sync_status = "idle"
        it.error_message = ""
        it.access_token_enc = encrypt_token("gho_test_valid_access_token_123")
        self.db.commit()

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        # 1. Test empty repo (409) along with active repo
        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = [
            {"id": 1, "name": "empty-repo", "owner": {"login": "hero_dev"}, "html_url": "https://github.com/hero_dev/empty-repo"},
            {"id": 2, "name": "active-repo", "owner": {"login": "hero_dev"}, "html_url": "https://github.com/hero_dev/active-repo"}
        ]

        mock_409_commits = MagicMock()
        mock_409_commits.status_code = 409
        mock_409_commits.json.return_value = {"message": "Git Repository is empty."}

        mock_active_commits = MagicMock()
        mock_active_commits.status_code = 200
        mock_active_commits.json.return_value = [
            {
                "sha": "123456789abc",
                "commit": {"message": "feat: init active repo", "author": {"name": "Hero Dev", "date": "2026-09-20T10:00:00Z"}},
                "html_url": "https://github.com/hero_dev/active-repo/commit/123456789abc"
            }
        ]

        mock_client.get.side_effect = [mock_repos_resp, mock_409_commits, mock_active_commits]

        sync_resp = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(sync_resp.status_code, 200)
        items = sync_resp.json()["data"]["items"]
        # Empty repo was recorded, but skipped on commits; active repo synced commits
        self.assertTrue(any(i["id"] == "commit_12345678" for i in items))

        # 2. Test rate limit on commit call
        mock_client.get.side_effect = None
        mock_rate_limit_resp = MagicMock()
        mock_rate_limit_resp.status_code = 403
        mock_rate_limit_resp.headers = {"x-ratelimit-remaining": "0"}
        mock_client.get.side_effect = [mock_repos_resp, mock_rate_limit_resp]

        rl_resp = self.client.post("/api/integrations/GitHub/sync", headers=self.auth_headers())
        self.assertEqual(rl_resp.status_code, 502)
        self.assertIn("rate limit", rl_resp.json()["detail"].lower())
