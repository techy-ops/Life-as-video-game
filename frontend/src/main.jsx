import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowRight, BarChart3, Bell, BookOpen, Briefcase, CalendarDays, Check, ChevronRight, Coins, Crown, Dumbbell, Flame, Gift, Gamepad2, Heart, Home, Link2, Lock, LogOut, Medal, Menu, MessageCircle, Plus, RefreshCw, ScrollText, Settings, Shield, Sparkles, Swords, Target, Trophy, TrendingUp, UserRound, Users, X, Zap, Brain, ShoppingBag, Upload, FileText, Play, Pause, CircleCheck, Layers, Flag, Clock, Send, Mic, MicOff, AlertTriangle, GitCommit } from 'lucide-react';
import './styles.css';
const API = import.meta.env.VITE_API_URL;
const request = async (path, opt = {}) => {
  const headers = { ...(opt.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(opt.headers || {}) };
  const token = localStorage.getItem('liferpg_token');
  if (token) headers.Authorization = `Bearer ${token}`;
  let r;
  try {
    r = await fetch(API + path, { ...opt, headers });
  } catch (netErr) {
    throw new Error('Backend unavailable. Please verify the LIFE RPG backend is running.');
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401) {
      throw new Error(d.detail || 'Invalid credentials. Please check your email and password.');
    }
    if (r.status === 400) {
      throw new Error(d.detail || 'Request rejected. Please check your details.');
    }
    if (r.status === 422) {
      const msg = Array.isArray(d.detail) ? d.detail.map(e => e.msg || 'Validation failed').join('; ') : (d.detail || 'Validation error. Please check your inputs.');
      throw new Error(msg);
    }
    if (r.status >= 500) {
      throw new Error('Server error. Please try again later.');
    }
    throw new Error(d.detail || 'Something went wrong');
  }
  return d;
};
const icons = { Career: Briefcase, Health: Dumbbell, Learning: BookOpen, Finance: Coins, Relationships: Heart, Creativity: Sparkles, Personal: Target };
const avatarEmoji = a => ({ knight: '🛡️', mage: '🧙', rogue: '🗡️', healer: '🧝', hero: '⚔️' })[a] || '⚔️';
function App() {
  const [auth, setAuth] = useState(!!localStorage.getItem('liferpg_token')), [me, setMe] = useState(null), [page, setPage] = useState('home'), [dash, setDash] = useState(null), [toast, setToast] = useState(''), [loading, setLoading] = useState(false), [showAuth, setShowAuth] = useState(false), [showWorldEntry, setShowWorldEntry] = useState(false);
  const load = async () => { if (!auth) return; try { const u = await request('/me'); setMe(u); const d = await request('/dashboard'); setDash(d); if (!u.onboarding_done) setPage('onboarding') } catch (e) { localStorage.removeItem('liferpg_token'); setAuth(false) } };
  useEffect(() => { load() }, [auth]);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    const error = params.get('error');
    const errDesc = params.get('error_description');
    if (error) {
      setToast(`OAuth denied: ${errDesc || error}`);
      window.history.replaceState({}, document.title, window.location.pathname);
      setPage('integrations');
      return;
    }
    if (code && state && auth) {
      const handleOAuthCallback = async () => {
        setLoading(true);
        try {
          let provider = sessionStorage.getItem('pending_oauth_provider');
          if (!provider) {
            const parts = state.split('_');
            if (parts.length >= 2) {
              const slug = parts[1].toLowerCase();
              if (slug.includes('git')) provider = 'GitHub';
              else if (slug.includes('google') || slug.includes('cal')) provider = 'Google Calendar';
              else if (slug.includes('outlook')) provider = 'Outlook Calendar';
            }
          }
          if (!provider) {
            provider = params.get('provider') || (code.startsWith('ya29') ? 'Google Calendar' : 'GitHub');
          }
          const redirectUri = window.location.origin + window.location.pathname;
          await request(`/integrations/${provider}/callback`, {
            method: 'POST',
            body: JSON.stringify({ code, state, redirect_uri: redirectUri })
          });
          sessionStorage.removeItem('pending_oauth_provider');
          setToast(`🎉 ${provider} successfully connected!`);
          await load();
          setPage('integrations');
        } catch (err) {
          setToast(`OAuth connection error: ${err.message}`);
        } finally {
          window.history.replaceState({}, document.title, window.location.pathname);
          setLoading(false);
        }
      };
      handleOAuthCallback();
    }
  }, [auth]);
  const logout = () => { localStorage.removeItem('liferpg_token'); setAuth(false); setMe(null); setDash(null); setPage('home') };
  const enterWorld = () => {
    if (showWorldEntry || showAuth) return;
    setShowWorldEntry(true);
    window.setTimeout(() => {
      setShowWorldEntry(false);
      setShowAuth(true);
    }, 1900);
  };
  if (!auth) {
    if (showWorldEntry) return <WorldEntry />;
    if (showAuth) return <Auth onLogin={() => setAuth(true)} onBack={() => setShowAuth(false)} />;
    return <Landing onEnter={enterWorld} />;
  }
  if (!dash || !me) return <div className="boot"><Gamepad2 /><b>Loading your world…</b><span>Syncing your campaign</span></div>;
  if (!me.onboarding_done) return <Onboarding me={me} onDone={async () => { await load(); setPage('home') }} />;
  const refresh = async () => { setLoading(true); try { await load() } finally { setLoading(false) } };
  return <><Shell page={page} setPage={setPage} dash={dash} me={me} logout={logout} refresh={refresh} loading={loading}>{page === 'home' && <Dashboard dash={dash} setPage={setPage} refresh={refresh} />} {page === 'goals' && <Goals setPage={setPage} refresh={refresh} />} {page === 'campaign' && <Campaign />} {page === 'quests' && <QuestBoard dash={dash} refresh={refresh} />} {page === 'skills' && <SkillTree />} {page === 'hero' && <Hero />} {page === 'boss' && <Bosses />} {page === 'analytics' && <Analytics />} {page === 'journal' && <Journal />} {page === 'review' && <Weekly />} {page === 'achievements' && <Achievements />} {page === 'social' && <Social />} {page === 'integrations' && <Integrations refresh={refresh} />} {page === 'notifications' && <Notifications />} {page === 'settings' && <SettingsPage me={me} refresh={refresh} />}</Shell>{toast && <div className="toast">{toast}<button onClick={() => setToast('')}><X /></button></div>}</>;
}
function WorldEntry() {
  return <div className="worldEntry" aria-label="Entering LIFE RPG">
    <div className="worldEntryGlow" />
    <div className="worldEntryStars"><span>✦</span><span>·</span><span>✧</span><span>·</span><span>✦</span></div>
    <div className="worldEntryAvatar">
      <div className="entryAvatarCircle">⚔️</div>
      <div className="entryAvatarRing ringOne" /><div className="entryAvatarRing ringTwo" />
    </div>
    <div className="worldEntryMessage">
      <span className="entrySmall">NEW CAMPAIGN DETECTED</span>
      <h1>Hi, <em>Hero.</em></h1>
      <p>Your world is waiting.</p>
    </div>
    <div className="worldEntryProgress"><span /></div>
  </div>;
}
function Landing({ onEnter }) {
  const [menu, setMenu] = useState(false);
  const [faqOpen, setFaqOpen] = useState(0);

  const go = id => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setMenu(false);
  };

  const faqs = [
    ['What is LIFE RPG?', 'LIFE RPG turns meaningful real-world goals into campaigns, quests, evidence-based progress, XP, skills and milestones.'],
    ['How does the AI create quests?', 'The AI uses the goal and campaign context to break a larger ambition into structured, actionable quests and progression.'],
    ['How is progress evaluated?', 'Users can submit supported evidence such as text, links, files and GitHub activity. The system can evaluate evidence before awarding quest progress.'],
    ['What do XP and skills mean?', 'Completed quests can award XP and coins while contributing to skill progression, levels, achievements and future quests.'],
    ['Can I use it for different goals?', 'Yes. LIFE RPG is designed around personal goals across areas such as career, learning, health, creativity and personal growth.']
  ];

  return (
    <div className="blockLanding">
      <div className="blockNoise" />
      <div className="blockGrid" />
      <div className="blockGlow blockGlowOrange" />
      <div className="blockGlow blockGlowPurple" />

      <header className="blockNav">
        <button className="blockLogo" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
          <span className="blockLogoMark"><Gamepad2 /></span>
          <span>LIFE<span>RPG</span></span>
        </button>

        <nav className={menu ? 'open' : ''}>
          <button onClick={() => go('blockHow')}>HOW IT WORKS</button>
          <button onClick={() => go('blockCampaign')}>CAMPAIGN</button>
          <button onClick={() => go('blockSkills')}>SKILLS</button>
          <button onClick={() => go('blockQuests')}>QUESTS</button>
          <button onClick={() => go('blockAI')}>AI MASTER</button>
        </nav>

        <button className="blockEnter" onClick={onEnter}>
          ENTER THE WORLD <ArrowRight />
        </button>
        <button className="blockMenu" onClick={() => setMenu(!menu)} aria-label="Open menu"><Menu /></button>
      </header>

      <main>
        {/* HERO */}
        <section className="blockHero" id="blockTop">
          <div className="blockHeroCopy">
            <div className="blockKicker"><span /> PERSONAL AI LIFE CAMPAIGN</div>
            <h1>TURN YOUR<br />LIFE INTO<br /><em>A GAME.</em></h1>
            <p>
              Turn meaningful goals into adaptive quests, real-world evidence,
              visible progress and RPG-style growth.
            </p>
            <div className="blockActions">
              <button className="blockPrimary" onClick={onEnter}>START YOUR CAMPAIGN <ArrowRight /></button>
              <button className="blockSecondary" onClick={() => go('blockHow')}>EXPLORE THE SYSTEM <ChevronRight /></button>
            </div>
            <div className="blockMeta">
              <span><i /> AI-GENERATED CAMPAIGNS</span>
              <span><i /> REAL-WORLD PROGRESSION</span>
              <span><i /> XP + SKILLS + MILESTONES</span>
            </div>
          </div>

          <div className="blockHeroVisual">
            <div className="blockOrbit orbitA" />
            <div className="blockOrbit orbitB" />
            <div className="blockHeroGlow" />
            <div className="blockLevelTag"><b>01</b> LEVEL UP YOUR LIFE</div>

            <button className="blockAvatar" onClick={onEnter} aria-label="Enter LIFE RPG">
              <div className="blockAvatarScan" />
              <div className="blockAvatarHead">⚔</div>
              <div className="blockAvatarBody"><span>XP</span><b>∞</b><span>QUEST</span></div>
              <div className="blockAvatarCore" />
              <small>CLICK TO ENTER</small>
            </button>

            <div className="blockFloat floatA"><span>QUEST COMPLETE</span><b>+150 XP</b><small>REAL WORLD ACTION</small></div>
            <div className="blockFloat floatB"><span>SKILL UNLOCKED</span><b>Focus +1</b><small>LEVEL 07 → 08</small></div>
            <div className="blockFloat floatC"><span>AI GAME MASTER</span><b>Next quest ready</b><small>ADAPTIVE CAMPAIGN</small></div>
          </div>
        </section>

        {/* STATS */}
        <section className="blockStats">
          {[
            [Activity, 'GOALS', 'TURNED INTO QUESTS'],
            [Swords, 'QUESTS', 'BUILT AROUND ACTION'],
            [Zap, 'XP', 'EARNED THROUGH PROGRESS'],
            [Brain, 'SKILLS', 'GROWN OVER TIME']
          ].map(([Icon, title, sub]) => (
            <div className="blockStat" key={title}>
              <Icon />
              <small>{title}</small>
              <b>{sub}</b>
            </div>
          ))}
        </section>

        {/* HOW IT WORKS */}
        <section className="blockSection" id="blockHow">
          <div className="blockSectionHead">
            <span className="blockEyebrow">✦ THE CORE LOOP</span>
            <h2>HOW LIFE RPG<br /><em>WORKS.</em></h2>
            <p>Your real-world ambition becomes a playable progression system.</p>
          </div>

          <div className="blockHowGrid">
            {[
              [Target, '01', 'SET YOUR GOAL', 'Tell LIFE RPG what you want to achieve.'],
              [Sparkles, '02', 'BUILD YOUR CAMPAIGN', 'AI structures milestones, skills and quests around the goal.'],
              [Swords, '03', 'COMPLETE REAL QUESTS', 'Take action in the real world and submit evidence.'],
              [Zap, '04', 'LEVEL UP', 'Earn XP, coins, skills and unlock your next challenge.']
            ].map(([Icon, n, title, text]) => (
              <article className="blockHowCard" key={n}>
                <div className="blockStep"><span>/// {n}</span><Icon /></div>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>

        {/* PROMO */}
        <section className="blockPromo">
          <div>
            <span>✦ PLAY YOUR PROGRESS</span>
            <h2>READY TO TURN<br />YOUR NEXT GOAL<br />INTO A QUEST?</h2>
            <p>Start with one meaningful goal and let the campaign grow from there.</p>
          </div>
          <button onClick={onEnter}>START PLAYING NOW <ArrowRight /></button>
        </section>

        {/* SYSTEM */}
        <section className="blockSplit" id="blockSystem">
          <div className="blockArtifact">
            <div className="blockCube">
              <div>XP</div><div>+</div><div>LVL</div><div>⚔</div>
            </div>
            <span>PROGRESS ENGINE</span>
          </div>
          <div className="blockSplitCopy">
            <span className="blockEyebrow">✦ BUILT FOR REAL LIFE</span>
            <h2>YOUR LIFE.<br />YOUR QUESTS.<br /><em>YOUR WORLD.</em></h2>
            <p>LIFE RPG connects goals, action, evidence and progression into one game-like loop.</p>
            <div className="blockFeatureList">
              <div><Check /><span><b>Evidence-Based Progress</b><small>Connect real work to quest completion.</small></span></div>
              <div><TrendingUp /><span><b>Adaptive Progression</b><small>Quest difficulty and sequencing can evolve with your progress.</small></span></div>
              <div><Shield /><span><b>Meaningful Rewards</b><small>XP, skills, milestones and achievements reflect your journey.</small></span></div>
            </div>
          </div>
        </section>

        {/* CAMPAIGN */}
        <section className="blockSection blockCampaignSection" id="blockCampaign">
          <div className="blockSectionHead rowHead">
            <div><span className="blockEyebrow">✦ YOUR CAMPAIGN</span><h2>FROM GOAL TO<br /><em>VICTORY.</em></h2></div>
            <span className="blockStage">CAMPAIGN // ACTIVE</span>
          </div>

          <div className="blockCampaignCard">
            <div className="blockCampaignTop">
              <div><span>CURRENT FOCUS</span><h3>Build a stronger future</h3></div>
              <div className="blockProgress"><div><span>PROGRESSION</span><b>68%</b></div><i><em /></i></div>
            </div>
            <div className="blockPipeline">
              {[
                ['01', 'GOAL', 'Your ambition', 'DONE'],
                ['02', 'MILESTONE', 'Major checkpoint', 'DONE'],
                ['03', 'SKILL', 'Capability growth', 'ACTIVE'],
                ['04', 'QUESTS', 'Real actions', 'NEXT'],
                ['05', 'BOSS', 'Big challenge', 'LOCKED']
              ].map(([n, label, value, state]) => (
                <div className={'pipelineItem ' + state.toLowerCase()} key={n}>
                  <small>{n}. {label}</small><b>{value}</b><span>{state}</span>
                </div>
              ))}
            </div>
            <div className="blockObjective">
              <span><Swords /> PRACTICE TODAY'S CORE SKILL</span><b>+150 XP</b><em>READY FOR PROOF</em>
            </div>
          </div>
        </section>

        {/* SKILLS */}
        <section className="blockSection" id="blockSkills">
          <div className="blockSectionHead centered">
            <span className="blockEyebrow">✦ CHARACTER PROGRESSION</span>
            <h2>BUILD YOUR<br /><em>SKILL TREE.</em></h2>
            <p>Every meaningful quest can contribute to a visible constellation of skills.</p>
          </div>
          <div className="blockSkillTree">
            <div className="skillBranch">
              <span>BRANCH 01</span>
              <div><b>CORE SKILL</b><em>MASTERED</em><small>Foundation unlocked</small></div>
              <div><b>ADVANCED SKILL</b><em>72%</em><small>Progressing</small></div>
              <div className="locked"><b>EXPERT SKILL</b><em>LOCKED</em><small>Complete prerequisites</small></div>
            </div>
            <div className="skillCore"><Brain /><small>CHARACTER CORE</small><b>YOUR BUILD</b><span>12 / 16 NODES</span></div>
            <div className="skillBranch">
              <span>BRANCH 02</span>
              <div><b>APPLIED SKILL</b><em>MASTERED</em><small>Real-world practice</small></div>
              <div><b>SPECIALIZATION</b><em>45%</em><small>Current focus</small></div>
              <div className="locked"><b>LEGENDARY NODE</b><em>LOCKED</em><small>Reach the next milestone</small></div>
            </div>
          </div>
        </section>

        {/* QUESTS */}
        <section className="blockSection blockDarkSection" id="blockQuests">
          <div className="blockSectionHead rowHead">
            <div><span className="blockEyebrow">✦ DAILY BOUNTIES</span><h2>TACTICAL<br /><em>QUEST BOARD.</em></h2></div>
            <span className="blockStage">ROTATION // ACTIVE</span>
          </div>
          <div className="blockQuestGrid">
            {[
              [Target, 'DAILY MISSION', 'Deep work session', '+100 XP'],
              [Swords, 'CHALLENGE', 'Build & ship a project', '+250 XP'],
              [Check, 'REAL WORLD', 'Complete your next milestone', '+200 XP'],
              [Crown, 'EPIC BOSS', 'Conquer a major goal', '+1,200 XP']
            ].map(([Icon, type, title, xp], i) => (
              <article className={'blockQuestCard ' + (i === 3 ? 'epic' : '')} key={title}>
                <div className="questCardTop"><span>{type}</span><b>{'★'.repeat(i + 1)}</b></div>
                <Icon />
                <h3>{title}</h3>
                <p>Complete the action, submit proof and move your campaign forward.</p>
                <div><strong>{xp}</strong><button onClick={onEnter}>{i === 3 ? 'ENTER BOSS' : 'VIEW QUEST'} <ArrowRight /></button></div>
              </article>
            ))}
          </div>
        </section>

        {/* AI MASTER */}
        <section className="blockSection" id="blockAI">
          <div className="blockConsole">
            <div className="consoleTop"><span>● ● ●</span><b>AI_GAME_MASTER // ACTIVE</b><em>● SYNCHRONIZED</em></div>
            <div className="consoleBody">
              <p><small>[01]</small> Goal analyzed → campaign structure generated.</p>
              <p><small>[02]</small> Quest completed → <strong>+150 XP</strong> awarded.</p>
              <p><small>[03]</small> Evidence evaluated → progress recorded.</p>
              <p><small>[04]</small> Next objective assigned → <strong>READY</strong>.</p>
            </div>
            <div className="consoleStats">
              <span>GAME MASTER <b>ACTIVE</b></span>
              <span>EVIDENCE <b>EVALUATED</b></span>
              <span>PROGRESSION <b>ADAPTIVE</b></span>
              <span>NEXT QUEST <b>READY</b></span>
            </div>
          </div>
        </section>

        {/* BOSS */}
        <section className="blockBoss">
          <div>
            <span>✦ CRITICAL ENCOUNTER</span>
            <h2>FACE THE<br /><em>HARD DAYS.</em></h2>
            <p>Big goals are made of difficult moments. LIFE RPG turns milestones into encounters you can work toward defeating.</p>
            <div className="bossBar"><span><b>BOSS PROGRESS</b><em>42%</em></span><i><b /></i></div>
          </div>
          <div className="bossLoot">
            <small>VICTORY REWARDS</small>
            <p><Zap /> XP & experience</p>
            <p><Coins /> Coins & rewards</p>
            <p><Trophy /> Achievements</p>
            <button onClick={onEnter}>ENTER THE WORLD <ArrowRight /></button>
          </div>
        </section>

        {/* FAQ */}
        <section className="blockSection blockFaq" id="blockFaq">
          <div className="blockSectionHead centered">
            <span className="blockEyebrow">✦ INTEL</span>
            <h2>FREQUENTLY ASKED<br /><em>QUESTIONS.</em></h2>
          </div>
          <div className="faqList">
            {faqs.map(([q, a], i) => (
              <div className="faqItem" key={q}>
                <button onClick={() => setFaqOpen(faqOpen === i ? -1 : i)}>
                  <span>{q}</span>{faqOpen === i ? <X /> : <Plus />}
                </button>
                {faqOpen === i && <p>{a}</p>}
              </div>
            ))}
          </div>
        </section>

        {/* CTA */}
        <section className="blockCTA">
          <span>✦ THE ADVENTURE COMMENCES</span>
          <h2>STOP PLANNING.<br /><em>START PLAYING.</em></h2>
          <p>Your next level starts with a single meaningful goal.</p>
          <button onClick={onEnter}>ENTER LIFE RPG <ArrowRight /></button>
        </section>
      </main>

      <footer className="blockFooter">
        <div><button className="blockLogo"><span className="blockLogoMark"><Gamepad2 /></span>LIFE<span>RPG</span></button><p>Make your real life worth playing.</p></div>
        <div><b>EXPLORE</b><button onClick={() => go('blockHow')}>How it works</button><button onClick={() => go('blockCampaign')}>Campaign</button><button onClick={() => go('blockQuests')}>Quests</button></div>
        <div><b>ACCOUNT</b><button onClick={onEnter}>Enter the world</button><button onClick={onEnter}>Create your hero</button></div>
        <div><b>LIFE RPG</b><span>Real goals. Real actions. Visible growth.</span></div>
      </footer>
    </div>
  );
}

function FeaturePanel({ tag, title, text, visual }) { return <article className="featurePanel"><div className="featureCopy"><span className="pill">✦ {tag}</span><h3>{title}</h3><p>{text}</p></div><div className={'featureVisual ' + visual}>{visual === 'character' && <><div className="paperAvatar">⚔️</div><b>STEP 02</b><span>SETUP YOUR CHARACTER IDENTITY</span><div className="paperLine"></div><div className="paperLine short"></div></>}{visual === 'stats' && <><div className="statAvatar">🛡️</div><div className="radar">◈</div><b>LEVEL 07 · 2,450 XP</b><small>FOCUS 72 · DISCIPLINE 64 · CREATIVITY 81</small></>}{visual === 'quests' && <><div className="questWindow"><b>TODAY</b><span>☑ Ship project</span><span>☑ 30 min deep work</span><span>☐ Read 20 pages</span><strong>+150 XP</strong></div></>}{visual === 'boss' && <><div className="bossVisual"><Crown /><b>PROCRASTINATION</b><div><i /><i /><i /><i /></div><small>42% HP REMAINING</small></div></>}</div></article> }
function LoopStep({ n, title, icon }) { return <div className="loopStep"><span>{n}</span><div className="loopIcon">{icon}</div><h3>{title}</h3></div> }
function MockQuest({ title, xp }) { return <div className="mockQuest"><div><span>QUEST</span><b>{title}</b></div><strong>{xp}</strong></div> }
function PriceCard({ label, title, text, features, featured, onClick }) { return <article className={'priceCard ' + (featured ? 'featured' : '')}><span className="priceLabel">{label}</span><h3>{title}</h3><p>{text}</p><ul>{features.map(f => <li key={f}><Check />{f}</li>)}</ul><button onClick={onClick}>{featured ? 'ENTER LIFE RPG' : 'GET STARTED'} <ArrowRight /></button></article> }

function Auth({ onLogin, onBack }) { const [mode, setMode] = useState('login'), [email, setEmail] = useState(''), [password, setPassword] = useState(''), [name, setName] = useState('Hero'), [busy, setBusy] = useState(false), [err, setErr] = useState(''); const submit = async e => { e.preventDefault(); setBusy(true); setErr(''); try { const d = await request(mode === 'login' ? '/auth/login' : '/auth/signup', { method: 'POST', body: JSON.stringify(mode === 'login' ? { email, password } : { email, password, name }) }); localStorage.setItem('liferpg_token', d.token); onLogin() } catch (x) { setErr(x.message) } finally { setBusy(false) } }; return <div className="authPage rpgLoginPage"><button className="authBack" onClick={onBack}><ArrowRight /> Back to landing</button><div className="authBrand"><Gamepad2 />LIFE<span>RPG</span></div><div className="authCard"><div className="eyebrow"><Sparkles /> PERSONAL AI LIFE CAMPAIGN</div><h1>{mode === 'login' ? 'Welcome back, Hero.' : 'Build your character.'}</h1><p>{mode === 'login' ? 'Your campaign is waiting.' : 'Turn a real-life goal into an adaptive RPG journey.'}</p><form onSubmit={submit}>{mode === 'signup' && <label>Name<input value={name} onChange={e => setName(e.target.value)} placeholder="Your hero name" /></label>}<label>Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} required placeholder="hero@example.com" /></label><label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} minLength="6" required placeholder="At least 6 characters" /></label>{err && <div className="error">{err}</div>}<button className="primary full" disabled={busy}>{busy ? 'Entering…' : mode === 'login' ? 'Enter the world' : 'Create my hero'} <ArrowRight /></button></form><button className="textBtn" onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}>{mode === 'login' ? "New here? Create an account" : "Already have an account? Log in"}</button><small className="privacy"><Shield /> Your AI key stays on your server; the browser never receives it.</small></div></div> }
function Onboarding({ me, onDone }) { const [form, setForm] = useState({ name: me.name, age_range: '18-24', timezone: 'Asia/Kolkata', difficulty: 'Normal', daily_minutes: 30, interests: '', priorities: '', notifications: true, theme: 'dark', sound: true }); const [busy, setBusy] = useState(false); const save = async () => { setBusy(true); try { await request('/onboarding/complete', { method: 'POST', body: JSON.stringify(form) }); onDone() } catch (e) { alert(e.message) } finally { setBusy(false) } }; return <div className="onboarding"><div className="onboardCard"><div className="avatarBig">{avatarEmoji('hero')}</div><div className="eyebrow">CHARACTER CREATION</div><h1>Welcome, {me.name}.<br /><em>Let's build your world.</em></h1><p>These settings help the Game Master shape realistic quests around your time, interests and difficulty.</p><div className="formGrid"><label>Hero name<input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label><label>Age range<select value={form.age_range} onChange={e => setForm({ ...form, age_range: e.target.value })}><option>Under 18</option><option>18-24</option><option>25-34</option><option>35-44</option><option>45+</option></select></label><label>Daily time<select value={form.daily_minutes} onChange={e => setForm({ ...form, daily_minutes: +e.target.value })}><option value="15">15 min</option><option value="30">30 min</option><option value="60">1 hour</option><option value="120">2+ hours</option></select></label><label>Difficulty<select value={form.difficulty} onChange={e => setForm({ ...form, difficulty: e.target.value })}><option>Gentle</option><option>Normal</option><option>Hard</option><option>Elite</option></select></label><label className="wide">Interests<input value={form.interests} onChange={e => setForm({ ...form, interests: e.target.value })} placeholder="coding, fitness, writing…" /></label><label className="wide">Main priorities<input value={form.priorities} onChange={e => setForm({ ...form, priorities: e.target.value })} placeholder="career, health, learning…" /></label></div><button className="primary full" disabled={busy} onClick={save}>{busy ? 'Creating your character…' : 'Enter my adventure'} <ArrowRight /></button></div></div> }
function Shell({ children, page, setPage, dash, me, logout, refresh, loading }) { const nav = [['home', 'Home', Home], ['goals', 'Goals', Target], ['campaign', 'Campaign', Flag], ['quests', 'Quests', Swords], ['skills', 'Skill Tree', Brain], ['hero', 'Hero', UserRound], ['boss', 'Boss Battles', Crown], ['analytics', 'Analytics', TrendingUp], ['journal', 'Journal', BookOpen], ['review', 'Weekly Review', ScrollText], ['achievements', 'Achievements', Trophy], ['social', 'Community', Users], ['integrations', 'Integrations', Link2], ['notifications', 'Notifications', Bell], ['settings', 'Settings', Settings]]; return <div className={`app ${page === 'home' ? 'rpgWorldApp' : ''}`}><aside><div className="brand" onClick={() => setPage('home')}><Gamepad2 />LIFE<span>RPG</span></div><div className="sideHero"><div className="miniAvatar">{avatarEmoji(me.avatar)}</div><div><b>{me.name}</b><span>LVL {me.level} · {me.title}</span></div></div><nav>{nav.map(([id, label, I]) => <button className={page === id ? 'active' : ''} key={id} onClick={() => setPage(id)}><I />{label}{id === 'notifications' && dash.unread_notifications > 0 && <i className="dot" />}</button>)}</nav><button className="newGoal" onClick={() => setPage('goals')}><Plus /> New Goal</button><div className="sideBottom"><button onClick={refresh}><RefreshCw className={loading ? 'spin' : ''} /> Sync</button><button onClick={logout}><LogOut /> Log out</button></div></aside><main><header><div><small>YOUR ADVENTURE · {page.toUpperCase()}</small><h3>Good day, {me.name} 👋</h3></div><div className="headerStats"><span><Flame /> {me.streak}</span><span><Coins /> {me.coins}</span><span><Zap /> {me.xp} XP</span><b>LVL {me.level}</b></div></header>{children}</main></div> }
function PageTitle({ eyebrow, title, text, action }) { return <div className="pageTitle"><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{text}</p>{action}</div> }
function Dashboard({ dash, setPage, refresh }) {
  const q = dash.quests.find(x => x.status === 'available' || x.status === 'in_progress');
  const quests = dash.quests.filter(x => x.status === 'available' || x.status === 'in_progress').slice(0, 3);
  const [gm, setGm] = useState(null), [rec, setRec] = useState(null), [deadlines, setDeadlines] = useState([]);
  useEffect(() => { request('/game-master').then(setGm).catch(() => { }); request('/recommendations').then(setRec).catch(() => { }); request('/integrations/calendar/deadlines').then(setDeadlines).catch(() => { }) }, [dash.user.xp, dash.user.streak]);
  const urgentDeadline = deadlines.find(d => d.is_deadline || d.urgency === 'urgent');
  const focus = [
    { name: 'Health', icon: Heart },
    { name: 'Learning', icon: BookOpen },
    { name: 'Career', icon: Briefcase },
    { name: 'Relationships', icon: Users },
    { name: 'Finance', icon: Coins }
  ];
  return <div className="page rpgDashboard">
    {urgentDeadline && <div className="deadlineBanner rpgHudPanel"><div className="deadlineIcon"><AlertTriangle /></div><div className="grow"><div className="eyebrow" style={{ color: 'var(--gold)' }}>CALENDAR DEADLINE DETECTED · {urgentDeadline.provider?.toUpperCase() || 'CALENDAR'}</div><h3>{urgentDeadline.summary}</h3><p>{urgentDeadline.description || 'Approaching deadline detected from connected calendar. Prioritize your related quest deliverables.'}</p></div><div className="deadlineTime"><Clock size={13} /><span>{new Date(urgentDeadline.start_time).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span></div></div>}
    {rec?.top_recommendation && <div className="recommendationHero rpgHudPanel"><div className="recIconBox"><Sparkles /></div><div className="grow"><div className="eyebrow">{rec.headline}</div><h3>{rec.top_recommendation.title}</h3><p>{rec.top_recommendation.reason} <b>{rec.top_recommendation.suggested_action}</b></p></div><button className="primary" onClick={() => setPage('quests')}>Take Action <ArrowRight size={14} /></button></div>}
    <section className="commandHero rpgHeroWorld">
      <div className="rpgHeroCopy"><div className="eyebrow">YOUR ADVENTURE CONTINUES</div><h1>Turn real life<br />into <em>progress.</em></h1><p>{gm?.message || 'You are not just managing tasks. You are building a stronger you.'}</p><div className="actions"><button className="primary rpgPrimary" onClick={() => q ? setPage('quests') : setPage('goals')}><Swords /> {q ? 'Today’s Quests' : 'Create campaign'} <ArrowRight /></button></div></div>
      <HeroSnapshot dash={dash} />
      <div className="rpgHeroTag">A SMALL STEP TODAY<br /><span>A LEGEND TOMORROW</span></div>
    </section>

    <div className="statGrid rpgStats"><Stat icon={Flame} label="Streak" value={`${dash.user.streak} day${dash.user.streak === 1 ? '' : 's'}`} sub="Keep it going!" /><Stat icon={Coins} label="Coins" value={dash.user.coins} sub="Earn more!" /><Stat icon={Zap} label="Experience" value={`${dash.user.xp} XP`} sub="Complete quests!" /><Stat icon={Trophy} label="Achievements" value={`${dash.achievements.filter(a => a.unlocked).length}/${dash.achievements.length}`} sub="Milestones unlocked" /></div>

    <div className="rpgHomeGrid">
      <section className="panel rpgQuestPanel">
        <div className="panelHead"><h2><Swords /> TODAY'S QUESTS</h2><button onClick={() => setPage('quests')}>View All <ArrowRight /></button></div>
        <div className="rpgQuestList">{quests.length ? quests.map((quest, i) => <button className="rpgQuestRow" key={quest.id || i} onClick={() => setPage('quests')}><span className="rpgQuestIcon">{i === 0 ? <Swords /> : i === 1 ? <BookOpen /> : <Dumbbell />}</span><span className="grow"><b>{quest.title}</b><small>{quest.description || `${quest.estimated_minutes || 30} min · Build your consistency`}</small></span><strong>+{quest.reward || quest.reward_xp || 25} XP</strong><ChevronRight /></button>) : <button className="rpgQuestRow" onClick={() => setPage('goals')}><span className="rpgQuestIcon"><Swords /></span><span className="grow"><b>Create your first campaign</b><small>Set your long-term goal</small></span><strong>+50 XP</strong><ChevronRight /></button>}</div>
      </section>

      <section className="rpgJourney panel"><div className="rpgJourneyOverlay" /><div className="panelHead"><h2><Flag /> YOUR JOURNEY</h2><button onClick={() => setPage('campaign')}>Open <ArrowRight /></button></div><div className="journeyPath"><div className="journeyNode current"><span>⚑</span><b>Lv {dash.user.level}</b><small>You are here</small></div><div className="journeyNode"><span>⚔</span><b>Lv 5</b><small>The Disciplined</small></div><div className="journeyNode"><span>✦</span><b>Lv 10</b><small>The Focused</small></div><div className="journeyNode"><span>♛</span><b>Lv 20</b><small>The Unstoppable</small></div></div><div className="journeyCaption">SAME YOU. <b>HIGHER LEVEL.</b></div></section>

      <section className="panel rpgFocusPanel"><div className="panelHead"><h2><Sparkles /> DAILY FOCUS</h2><button onClick={() => setPage('analytics')}>Edit</button></div>{focus.map(({ name, icon: Icon }) => { const c = dash.categories.find(x => x.name.toLowerCase() === name.toLowerCase()); const value = c?.progress || 0; return <div className="rpgFocusRow" key={name}><Icon /><span>{name}</span><div><i style={{ width: `${value}%` }} /></div><b>{value}%</b></div> })}<div className="rpgQuote"><span>✦</span><em>“Progress, not perfection.”</em></div></section>
    </div>

    <div className="sectionHead rpgCommandHead"><div><small>YOUR COMMAND CENTER</small><h2>What should I do now?</h2></div><button onClick={() => setPage('quests')}>All quests <ArrowRight /></button></div>
    <div className="focusGrid rpgFocusCards"><FocusCard icon={Swords} title="Main Quest" text={q?.title || 'Create your first campaign'} meta={q ? `${q.estimated_minutes || 30} min · ${q.difficulty || 1}/5 difficulty` : 'Start with one goal'} onClick={() => setPage(q ? 'quests' : 'goals')} /><FocusCard icon={Brain} title="Skill Quest" text={dash.skills.sort((a, b) => a.progress - b.progress)[0]?.name || 'Your priority skill'} meta="Strengthen your weakest skill" onClick={() => setPage('skills')} /><FocusCard icon={Crown} title="Next Boss" text={dash.campaign?.boss_name || 'Final Boss'} meta="Build toward your campaign victory" onClick={() => setPage('boss')} /></div>
    <div className="twoCol rpgBottomPanels"><div className="panel"><PanelHead title="Life map" icon={Activity} action="Analytics" onClick={() => setPage('analytics')} />{dash.categories.map(c => <div className="meter" key={c.name}><span>{c.name}</span><div><i style={{ width: `${c.progress}%` }} /></div><b>{c.progress}%</b></div>)}</div><div className="panel gm"><PanelHead title="AI Game Master" icon={Sparkles} /><div className="gmMessage"><div className="gmAvatar"><BotIcon /></div><div><strong>{gm?.headline || 'Your next level is built one quest at a time.'}</strong><p>{gm?.next_action || 'Choose one focused action today.'}</p><small>{gm?.tone || 'Adventure mode'} · Recent score {gm?.recent_score || 0}%</small></div></div></div></div>
  </div>
}
function BotIcon() { return <span className="botEmoji">🤖</span> }
function HeroSnapshot({ dash }) { return <div className="heroSnapshot"><div className="heroTop"><div className="avatarLarge">{avatarEmoji(dash.user.avatar)}</div><div><small>YOUR HERO</small><h2>{dash.user.title}</h2><span>Level {dash.user.level}</span></div></div><div className="xpLine"><span>XP TO NEXT LEVEL</span><b>{dash.xp_progress.current}/{dash.xp_progress.needed}</b></div><div className="bar"><i style={{ width: `${dash.xp_progress.percent}%` }} /></div><div className="heroNums"><div><b>{dash.user.coins}</b><span>Coins</span></div><div><b>{dash.active_quests}</b><span>Active quests</span></div><div><b>{dash.skills.length}</b><span>Skills</span></div></div></div> }
function Stat({ icon: Icon, label, value, sub }) { return <div className="stat"><Icon /><div><small>{label}</small><strong>{value}</strong><span>{sub}</span></div></div> }
function FocusCard({ icon: Icon, title, text, meta, onClick }) { return <button className="focusCard" onClick={onClick}><div className="iconBox"><Icon /></div><small>{title}</small><h3>{text}</h3><span>{meta}</span><ArrowRight /></button> }
function PanelHead({ title, icon: Icon, action, onClick }) { return <div className="panelHead"><h2><Icon /> {title}</h2>{action && <button onClick={onClick}>{action} <ArrowRight /></button>}</div> }
function Goals({ setPage, refresh }) { const [rows, setRows] = useState([]), [title, setTitle] = useState(''), [category, setCategory] = useState('Learning'), [minutes, setMinutes] = useState(30), [priority, setPriority] = useState('medium'), [analysis, setAnalysis] = useState(null), [busy, setBusy] = useState(false); const [nlpInput, setNlpInput] = useState(''), [nlpResult, setNlpResult] = useState(null), [nlpBusy, setNlpBusy] = useState(false), [listening, setListening] = useState(false), [voiceNotice, setVoiceNotice] = useState(''); const load = () => request('/goals').then(setRows); useEffect(() => { load() }, []); const parseNlp = async (txtToParse) => { const txt = txtToParse || nlpInput; if (!txt.trim()) return; setNlpBusy(true); try { const res = await request('/goals/parse', { method: 'POST', body: JSON.stringify({ text: txt }) }); setNlpResult(res); setTitle(res.title); const matchedCat = Object.keys(icons).find(c => c.toLowerCase() === res.category.toLowerCase()) || 'Learning'; setCategory(matchedCat); setMinutes(res.estimated_effort_minutes); setPriority(res.priority) } catch (e) { alert(e.message) } finally { setNlpBusy(false) } }; const toggleVoice = () => { const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (!SR) { setVoiceNotice("Speech recognition is not supported in this browser. You can type your goal in the box."); setTimeout(() => setVoiceNotice(''), 4000); return } if (listening) { setListening(false); return } try { const r = new SR(); r.lang = 'en-US'; r.interimResults = false; r.onstart = () => { setListening(true); setVoiceNotice("Listening... speak your goal now!") }; r.onresult = e => { const t = e.results[0][0].transcript; setNlpInput(t); setListening(false); setVoiceNotice(`Heard: "${t}"`); parseNlp(t) }; r.onerror = e => { setListening(false); setVoiceNotice(`Speech error: ${e.error}`); setTimeout(() => setVoiceNotice(''), 3000) }; r.onend = () => setListening(false); r.start() } catch (err) { setListening(false); setVoiceNotice("Unable to access microphone.") } }; const analyze = async () => { if (!title.trim()) return; setBusy(true); try { setAnalysis(await request('/goals/analyze', { method: 'POST', body: JSON.stringify({ title, category, minutes, priority }) })) } catch (e) { alert(e.message) } finally { setBusy(false) } }; const create = async () => { setBusy(true); try { await request('/goals', { method: 'POST', body: JSON.stringify({ title, category, minutes, priority, level: 'Beginner' }) }); setTitle(''); setAnalysis(null); setNlpResult(null); setNlpInput(''); await load(); await refresh(); setPage('campaign') } catch (e) { alert(e.message) } finally { setBusy(false) } }; const status = async (id, s) => { await request(`/goals/${id}`, { method: 'PATCH', body: JSON.stringify({ status: s }) }); load(); refresh() }; return <div className="page"><PageTitle eyebrow="LIFE GOALS & AI INGESTION" title={<>Give your ambition a <em>campaign.</em></>} text="Speak or type naturally. The AI extracts deadlines, skills and categories, then generates your milestones and quests." /><div className="nlGoalBar panel"><div className="nlTop"><div className="eyebrow"><Sparkles size={12} /> NATURAL LANGUAGE & VOICE PARSER</div><span className="nlSub">Type or speak your goal or deadline</span></div><div className="nlInputRow"><input value={nlpInput} onChange={e => setNlpInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') parseNlp() }} placeholder="e.g. 'I need to build a Python REST API by Friday 6 PM' or 'Study DSA 1 hour every day'…" /><button className={`voiceBtn ${listening ? 'listening' : ''}`} onClick={toggleVoice} title={listening ? 'Stop Listening' : 'Speak Goal (Microphone)'}>{listening ? <MicOff size={16} /> : <Mic size={16} />}</button><button className="primary" disabled={nlpBusy || !nlpInput.trim()} onClick={() => parseNlp()}>{nlpBusy ? <RefreshCw className="spin" size={14} /> : <Sparkles size={14} />} Parse Goal</button></div>{voiceNotice && <div className="voiceNotice">{voiceNotice}</div>}{nlpResult && <div className="nlpCard"><div className="nlpHead"><div><small>STRUCTURED INTERPRETATION</small><h4>{nlpResult.title}</h4></div><span className="nlpBadge">{nlpResult.suggested_quest_type?.toUpperCase()}</span></div><p>{nlpResult.explanation}</p><div className="nlpTags"><span><b>Category:</b> {nlpResult.category}</span><span><b>Priority:</b> {nlpResult.priority}</span><span><b>Effort:</b> {nlpResult.estimated_effort_minutes}m</span>{nlpResult.deadline_human && <span className="urgentTag"><b>Deadline:</b> {nlpResult.deadline_human}</span>}{nlpResult.recurrence && <span><b>Recurrence:</b> {nlpResult.recurrence}</span>}{nlpResult.related_skills?.map((s, i) => <span key={i} className="skillTag">⚡ {s}</span>)}</div></div>}</div><div className="goalBuilder"><div><div className="formGrid"><label className="wide">What do you want to achieve?<textarea rows="4" value={title} onChange={e => setTitle(e.target.value)} placeholder="I want to become a full-stack developer…" /></label><label>Life category<select value={category} onChange={e => setCategory(e.target.value)}>{Object.keys(icons).map(x => <option key={x}>{x}</option>)}</select></label><label>Daily time<select value={minutes} onChange={e => setMinutes(+e.target.value)}><option value="15">15 minutes</option><option value="30">30 minutes</option><option value="60">1 hour</option><option value="120">2+ hours</option></select></label><label>Priority<select value={priority} onChange={e => setPriority(e.target.value)}><option>low</option><option>medium</option><option>high</option></select></label></div><div className="actions"><button className="secondary" disabled={busy} onClick={analyze}><Sparkles /> Understand my goal</button><button className="primary" disabled={busy || !title.trim()} onClick={create}>{busy ? 'Building…' : 'Create Life Campaign'} <ArrowRight /></button></div></div>{analysis ? <div className="analysisCard"><div className="eyebrow">AI READ</div><h3>{analysis.quest_style || analysis.goal_type}</h3><p>{analysis.summary}</p><div className="tags"><span>{analysis.category}</span><span>{analysis.skill}</span><span>{analysis.difficulty}</span></div><small>{analysis.estimated_effort}</small></div> : <div className="emptyGoal"><Sparkles /><h3>AI campaign preview</h3><p>Understand your goal first and we'll show how the Game Master sees it.</p></div>}</div><div className="sectionHead"><div><small>GOAL LIFECYCLE</small><h2>Your campaigns</h2></div></div><div className="goalList">{rows.length ? rows.map(g => <div className="goalRow" key={g.id}><div className="goalIcon"><Target /></div><div className="grow"><small>{g.category} · {g.priority}</small><h3>{g.title}</h3><div className="bar"><i style={{ width: `${g.progress}%` }} /></div></div><b>{Math.round(g.progress)}%</b><select value={g.status} onChange={e => status(g.id, e.target.value)}><option>active</option><option>paused</option><option>completed</option><option>archived</option></select></div>) : <EmptyState text="Your first goal becomes your first campaign." />}</div></div> }

function Campaign() { const [rows, setRows] = useState([]); useEffect(() => { request('/campaigns').then(setRows) }, []); return <div className="page"><PageTitle eyebrow="LIFE CAMPAIGN" title={<>Your goal has become a <em>world.</em></>} text="Milestones are the map. Quests are the moves. The final boss is the real-world outcome." />{rows.length ? rows.map(c => <div className="campaignCard" key={c.id}><div className="campaignHeader"><div><small>ACTIVE CAMPAIGN</small><h2>{c.title}</h2><p>{c.summary}</p></div><div className="bossBadge"><Crown /> {c.boss_name}</div></div><div className="timeline">{c.milestones.map((m, i) => <div className={`milestone ${m.status}`} key={m.id}><div className="timelineDot">{m.status === 'completed' ? <Check /> : m.is_boss ? <Crown /> : <span>{i + 1}</span>}</div><div className="milestoneBody"><div><small>{m.is_boss ? 'FINAL BOSS' : `MILESTONE ${i + 1}`}</small><h3>{m.title}</h3><p>{m.description}</p></div><div className="milestoneReward">+{m.reward_xp} XP<br />+{m.reward_coins} 🪙</div></div><div className="bar"><i style={{ width: `${m.progress}%` }} /></div></div>)}</div></div>) : <EmptyState text="Create a goal to generate your campaign." />}</div> }
function QuestBoard({ dash, refresh }) { const [selected, setSelected] = useState(null); const active = dash.quests.filter(q => q.status !== 'locked'); return <div className="page"><PageTitle eyebrow="QUEST BOARD" title={<>Choose your <em>next move.</em></>} text="Every quest connects to a goal, skill, and milestone. Learning quests feature AI assessments that adapt your campaign." /><div className="questBoard">{active.map(q => <QuestCard q={q} onOpen={() => setSelected(q)} key={q.id} />)}</div>{!active.length && <EmptyState text="Create a campaign to unlock quests." />}{selected && <QuestModal q={selected} close={() => setSelected(null)} refresh={refresh} />}</div> }
function QuestCard({ q, onOpen }) { const isLearning = q.assessment_required || q.quest_type === 'learning' || !!q.subject; const isReinf = q.quest_type === 'reinforcement'; const type = q.is_boss ? 'BOSS TRIAL' : isReinf ? 'REINFORCEMENT' : isLearning ? 'LEARNING QUEST' : q.quest_type?.toUpperCase(); return <button className={`questCard ${q.is_boss ? 'bossCard' : isReinf ? 'reinforceCard' : ''}`} onClick={onOpen}><div className="questTop"><span>{q.is_boss ? <Crown /> : isReinf ? <Flame /> : isLearning ? <Brain /> : <Swords />} {type}</span><b>+{q.xp} XP</b></div><h3>{q.title}</h3><p>{q.description}</p><div className="questMeta">{q.topic && <span className="badgeLearning"><Brain size={11} /> {q.topic}</span>}{isReinf && <span className="badgeReinforce"><Flame size={11} /> Focus Drill</span>}<span><Clock size={11} /> {q.estimated_minutes} min</span><span>Difficulty {q.difficulty}/5</span>{isLearning && <span><Sparkles size={11} /> Assessment</span>}{q.evidence_required && <span><Shield size={11} /> Proof</span>}</div><ArrowRight /></button> }
function QuestModal({ q, close, refresh }) { const isLearning = q.assessment_required || q.quest_type === 'learning' || !!q.subject; const [started, setStarted] = useState(false), [inQuiz, setInQuiz] = useState(false), [score, setScore] = useState(1), [evidence, setEvidence] = useState(''), [link, setLink] = useState(''), [file, setFile] = useState(null), [result, setResult] = useState(null), [busy, setBusy] = useState(false); const [evalResult, setEvalResult] = useState(null), [ghCommits, setGhCommits] = useState([]), [attachedEvList, setAttachedEvList] = useState([]), [evaluating, setEvaluating] = useState(false); const loadEv = () => { request(`/evidence/${q.id}`).then(rows => { setAttachedEvList(rows || []); if (rows && rows.length > 0) { const l = rows[0]; setEvalResult({ quality: (l.quality || 70) / 100, relevance: l.relevance || .75, confidence: l.confidence || .85, completeness: l.completeness || .75, supports_quest: l.supports_quest !== false, feedback: l.feedback || l.evaluation, missing_requirements: l.missing_requirements || [] }) } }).catch(() => { }) }; useEffect(() => { request('/integrations/github/activity').then(d => { if (d.connected && d.items) setGhCommits(d.items.filter(x => x.type === 'commit')) }).catch(() => { }); loadEv() }, [q.id]); const start = async () => { await request(`/quests/${q.id}/start`, { method: 'POST' }); setStarted(true); if (isLearning) setInQuiz(true) }; const evaluateNow = async () => { if (!evidence.trim() && !link.trim() && !file) return alert('Provide text, a link, or a file to evaluate.'); setEvaluating(true); try { let lastEv = null; if (evidence.trim()) lastEv = await request(`/evidence/${q.id}/text?value=${encodeURIComponent(evidence)}`, { method: 'POST' }); if (link.trim()) lastEv = await request(`/evidence/${q.id}/link?value=${encodeURIComponent(link)}`, { method: 'POST' }); if (file) { const fd = new FormData(); fd.append('file', file); lastEv = await request(`/evidence/${q.id}/file`, { method: 'POST', body: fd }) } if (lastEv) { setEvalResult({ quality: (lastEv.quality || 70) / 100, relevance: lastEv.relevance || .75, confidence: lastEv.confidence || .85, completeness: lastEv.completeness || .75, supports_quest: lastEv.supports_quest !== false, feedback: lastEv.feedback || lastEv.evaluation, missing_requirements: lastEv.missing_requirements || [] }); loadEv() } } catch (e) { alert(e.message) } finally { setEvaluating(false) } }; const attachCommit = async commit => { try { const r = await request(`/evidence/${q.id}/github-commit`, { method: 'POST', body: JSON.stringify(commit) }); setEvidence(`GitHub Commit: ${commit.title} (${commit.repository})`); setEvalResult({ quality: (r.quality || 80) / 100, relevance: r.relevance || .85, confidence: r.confidence || .9, completeness: r.completeness || .8, supports_quest: r.supports_quest !== false, feedback: r.feedback, missing_requirements: r.missing_requirements || [] }); loadEv() } catch (e) { alert(e.message) } }; const completeStandard = async () => { setBusy(true); try { if (evidence.trim() && !evalResult) await request(`/evidence/${q.id}/text?value=${encodeURIComponent(evidence)}`, { method: 'POST' }); if (link.trim() && !evalResult) await request(`/evidence/${q.id}/link?value=${encodeURIComponent(link)}`, { method: 'POST' }); if (file && !evalResult) { const fd = new FormData(); fd.append('file', file); await request(`/evidence/${q.id}/file`, { method: 'POST', body: fd }) } const res = await request(`/quests/${q.id}/complete`, { method: 'POST', body: JSON.stringify({ score }) }); setResult(res); await refresh() } catch (e) { alert(e.message) } finally { setBusy(false) } }; if (inQuiz) return <QuizRunner q={q} close={close} refresh={refresh} />; return <div className="modalBackdrop"><div className="questModal"><button className="close" onClick={close}><X /></button><div className="eyebrow">{q.is_boss ? 'BOSS CHALLENGE' : q.quest_type === 'reinforcement' ? 'REINFORCEMENT DRILL' : isLearning ? 'LEARNING QUEST' : q.quest_type?.toUpperCase()}</div><h2>{q.title}</h2><p>{q.description}</p>{isLearning && <div className="learningMetaBox"><h4><Brain size={14} /> Learning Objective & Assessment</h4><p>{q.learning_objective || 'Master the core algorithmic and architectural principles of this topic through an interactive diagnostic evaluation.'}</p></div>}{!started && !result && <button className="primary full" onClick={start}><Play /> {isLearning ? 'Start Learning & Assessment' : 'Begin Quest'}</button>}{started && !result && !isLearning && <div className="questWork"><label>Self-assessed performance<select value={score} onChange={e => setScore(+e.target.value)}><option value="1">Excellent</option><option value=".8">Strong</option><option value=".6">Partial</option><option value=".4">Struggled</option></select></label>{q.evidence_required && <div className="evidenceBox"><h3><Shield /> Real-World Evidence Proof</h3><textarea value={evidence} onChange={e => setEvidence(e.target.value)} placeholder="Describe your concrete deliverables, architecture, or lesson learned…" /><input value={link} onChange={e => setLink(e.target.value)} placeholder="GitHub repository, commit, or live deployment link…" /><label className="fileInput"><Upload /> {file ? file.name : 'Attach documentation, PDF, code file, or visual proof'}<input type="file" onChange={e => setFile(e.target.files?.[0] || null)} /></label>{ghCommits.length > 0 && <div className="ghCommitPicker"><h4><GitCommit size={13} /> Quick Attach from Connected GitHub</h4>{ghCommits.slice(0, 2).map((c, i) => <div className="commitItem" key={i}><div><span>{c.title}</span><small>{c.repository} · {new Date(c.timestamp).toLocaleDateString()}</small></div><button type="button" onClick={() => attachCommit(c)}>Attach Proof</button></div>)}</div>}{attachedEvList.length > 0 && <div className="attachedEvidenceList"><h4><Shield size={13} /> Verified Deliverables ({attachedEvList.length})</h4>{attachedEvList.map((ev, i) => <div className="evidenceItemCard" key={i}><div className="evidenceItemTop"><span>{ev.kind === 'github' ? <GitCommit size={13} /> : <FileText size={13} />} <b>{ev.kind?.toUpperCase() || 'EVIDENCE'} PROOF</b></span><span className={`evalStatusBadge ${ev.supports_quest ? 'pass' : 'warn'}`}>{ev.supports_quest ? `Verified (${Math.round(ev.quality || 85)}%)` : 'Pending'}</span></div><div className="evidenceValue">{ev.value}</div>{ev.feedback && <small className="evidenceFeedback">💡 {ev.feedback}</small>}<div className="evidenceTime">{new Date(ev.created_at).toLocaleString()}</div></div>)}</div>}<button type="button" className="secondary full" style={{ marginTop: 8 }} disabled={evaluating} onClick={evaluateNow}>{evaluating ? <><RefreshCw className="spin" size={13} /> Evaluating Evidence…</> : <><Sparkles size={13} /> Run AI Evidence Evaluation</>}</button>{evalResult && <div className={`evalScorecard ${evalResult.supports_quest ? 'evalPass' : 'evalFail'}`}><div className="evalTop"><div className="eyebrow">{evalResult.supports_quest ? <Check size={13} /> : <AlertTriangle size={13} />} EVIDENCE AUDIT RESULT</div><span className={`evalStatusBadge ${evalResult.supports_quest ? 'pass' : 'warn'}`}>{evalResult.supports_quest ? 'SUFFICIENT PROOF VERIFIED' : 'REVISED PROOF REQUIRED'}</span></div><div className="evalMetrics"><div className="metric"><span>Quality</span><b>{Math.round(evalResult.quality * 100)}%</b></div><div className="metric"><span>Relevance</span><b>{Math.round(evalResult.relevance * 100)}%</b></div><div className="metric"><span>Completeness</span><b>{Math.round(evalResult.completeness * 100)}%</b></div><div className="metric"><span>Confidence</span><b>{Math.round(evalResult.confidence * 100)}%</b></div></div><p className="evalFeedback">💡 {evalResult.feedback}</p>{evalResult.missing_requirements?.length > 0 && <div className="missingReqs"><small>MISSING REQUIREMENTS:</small><div className="tags">{evalResult.missing_requirements.map((m, i) => <span key={i} style={{ borderColor: 'var(--danger)', color: '#ff9aaa' }}>{m}</span>)}</div></div>}</div>}</div>}<button className="primary full" disabled={busy} onClick={completeStandard}>{busy ? 'Validating requirements…' : 'Complete Quest'} <Check /></button></div>}{result && <div className="resultCard"><div className="resultIcon"><CircleCheck /></div><div className="eyebrow">QUEST COMPLETE</div><h2>+{result.earned_xp} XP · +{result.earned_coins} 🪙</h2><p>{result.message}</p><div className="resultGrid"><span>Score <b>{Math.round(result.score * 100)}%</b></span><span>Level <b>{result.level}</b></span><span>Next <b>{result.next_quest?.title || 'Milestone progress'}</b></span></div><button className="secondary full" onClick={close}>Continue adventure</button></div>}</div></div> }

function QuizRunner({ q, close, refresh }) { const [data, setData] = useState(null), [curr, setCurr] = useState(0), [answers, setAnswers] = useState({}), [seconds, setSeconds] = useState(0), [busy, setBusy] = useState(false), [result, setResult] = useState(null); useEffect(() => { request(`/quests/${q.id}/quiz`).then(d => { setData(d); if (d.is_completed) { setResult(d) } }).catch(e => alert(e.message)) }, [q.id]); useEffect(() => { if (result) return; const t = setInterval(() => setSeconds(s => s + 1), 1000); return () => clearInterval(t) }, [result]); const submit = async () => { setBusy(true); try { const r = await request(`/quests/${q.id}/quiz/submit`, { method: 'POST', body: JSON.stringify({ answers, time_taken: seconds }) }); setResult(r); await refresh() } catch (e) { alert(e.message) } finally { setBusy(false) } }; const formatTimer = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; if (!data) return <div className="modalBackdrop"><div className="assessmentModal"><Loading /></div></div>; if (result) return <QuizResultView result={result} q={q} close={close} />; const questions = data.questions || []; const question = questions[curr]; const renderFormatted = t => { if (!t) return null; const parts = t.split('```'); return parts.map((p, i) => i % 2 === 1 ? <pre className="codeBlock" key={i}><code>{p.replace(/^(python|py)\n/, '')}</code></pre> : <p className="questionText" key={i}>{p}</p>) }; return <div className="modalBackdrop"><div className="assessmentModal"><div className="quizTopBar"><div className="eyebrow"><Brain size={13} /> {q.subject || 'CODING'} · {q.topic || 'TOPIC'} ASSESSMENT</div><div className="timerBox"><Clock size={13} /> {formatTimer(seconds)}</div><button className="close" onClick={close}><X /></button></div><div className="quizProgressBar"><i style={{ width: `${Math.round(((curr + 1) / Math.max(1, questions.length)) * 100)}%` }} /></div>{question && <div className="quizQuestionBox"><div className="questionTypeHeader"><span className="typePill">{question.question_type.toUpperCase()}</span><span className="pointsPill">+{question.points} PTS</span></div>{renderFormatted(question.question)}{question.question_type === 'mcq' && <div className="optionsGrid">{question.options?.map((opt, idx) => <button className={`optionBtn ${answers[question.id] === idx ? 'selected' : ''}`} key={idx} onClick={() => setAnswers({ ...answers, [question.id]: idx })}><span className="optionIndicator">{String.fromCharCode(65 + idx)}</span><span>{opt}</span></button>)}</div>}{question.question_type === 'output_prediction' && <input value={answers[question.id] || ''} onChange={e => setAnswers({ ...answers, [question.id]: e.target.value })} placeholder="Type expected output (e.g. [1, 2] or 4)…" />}{question.question_type === 'debugging' && <textarea rows="4" className="codeAnswerInput" value={answers[question.id] || ''} onChange={e => setAnswers({ ...answers, [question.id]: e.target.value })} placeholder="Describe bug or write corrected code line…" />}{question.question_type === 'short_answer' && <textarea rows="4" value={answers[question.id] || ''} onChange={e => setAnswers({ ...answers, [question.id]: e.target.value })} placeholder="Explain key concept and algorithmic reasoning…" />}{question.question_type === 'coding_problem' && <textarea rows="5" className="codeAnswerInput" value={answers[question.id] || ''} onChange={e => setAnswers({ ...answers, [question.id]: e.target.value })} placeholder="# Write your implementation here..." />}</div>}<div className="quizNav"><button className="secondary" disabled={curr === 0} onClick={() => setCurr(c => Math.max(0, c - 1))}>Previous</button><span className="quizProgressNum">Question {curr + 1} of {questions.length}</span>{curr < questions.length - 1 ? <button className="primary" onClick={() => setCurr(c => c + 1)}>Next <ArrowRight size={14} /></button> : <button className="primary" disabled={busy} onClick={submit}>{busy ? 'Evaluating…' : 'Submit Assessment'} <Check size={14} /></button>}</div></div></div> }
function QuizResultView({ result, q, close }) { const isReinf = result.adaptive?.needs_reinforcement; return <div className="modalBackdrop"><div className="assessmentModal"><button className="close" onClick={close}><X /></button><div className="resultScoreHeader"><div className="bigScoreCircle"><strong>{Math.round(result.percentage)}%</strong><small>{result.percentage >= 80 ? 'MASTERED' : result.percentage >= 60 ? 'PROFICIENT' : 'NEEDS DRILL'}</small></div><div className="eyebrow">DIAGNOSTIC EVALUATION COMPLETE</div><h2>+{result.earned_xp} XP · +{result.earned_coins} 🪙</h2><p>{result.adaptive?.message || 'Performance evaluated. Topic skills updated.'}</p></div><div className={`adaptiveCallout ${isReinf ? 'reinforceCallout' : ''}`}>{isReinf ? <Flame /> : <Sparkles />}<div><h4>{isReinf ? 'Adaptive Reinforcement Activated' : 'Campaign Progression Unlocked'}</h4><p>{isReinf ? `The AI Game Master detected a weak spot in ${result.adaptive?.weak_concept || q.topic}. A focused reinforcement drill has been generated to reinforce this concept.` : 'Outstanding mastery! Difficulty has been increased for your upcoming challenges along the campaign path.'}</p></div></div><div className="resultGrid"><span>Score <b>{result.score}/{result.max_score || 100}</b></span><span>Level <b>{result.level || 1}</b></span><span>Next <b>{result.next_quest?.title || 'Campaign Progress'}</b></span></div>{result.weak_areas?.length > 0 && <div style={{ margin: '14px 0' }}><small style={{ color: 'var(--danger)', fontWeight: 800, fontSize: 10, letterSpacing: '.1em' }}>WEAK CONCEPTS DETECTED</small><div className="tags" style={{ marginTop: 6 }}>{result.weak_areas.map((w, i) => <span key={i} style={{ borderColor: '#ff657a55', color: '#ff9aaa' }}>{w}</span>)}</div></div>}{result.detailed_results?.length > 0 && <div className="reviewContainer"><h3><Check size={15} /> Question Review & Explanations</h3>{result.detailed_results.map((rev, i) => <div className={`reviewItem ${rev.is_correct ? 'correct' : 'incorrect'}`} key={i}><div className="reviewHeader"><span>QUESTION {i + 1} · {rev.question_type?.toUpperCase()}</span><b>{rev.earned_points}/{rev.points} PTS</b></div><div style={{ fontWeight: 600, color: '#f0f4fa', fontSize: 13 }}>{rev.question}</div><div className="reviewAnswerRow userAns">Your answer: <b>{String(rev.user_answer ?? '—')}</b></div>{!rev.is_correct && <div className="reviewAnswerRow correctAns">Correct: {String(rev.correct_answer)}</div>}<div className="reviewExplanation">💡 {rev.explanation || rev.feedback}</div></div>)}</div>}<button className="primary full" style={{ marginTop: 20 }} onClick={close}>Continue Campaign <ArrowRight size={15} /></button></div></div> }
function SkillTree() { const [tree, setTree] = useState([]); useEffect(() => { request('/skill-tree').then(setTree) }, []); return <div className="page"><PageTitle eyebrow="SKILL TREE & TOPIC INTELLIGENCE" title={<>Turn effort into <em>mastery.</em></>} text="Skills grow from real quest evaluations. Explore topic-level mastery, confidence, and attempts." /><div className="tree">{tree.map(b => <div className="branch" key={b.branch}><div className="branchTitle"><Brain /><h2>{b.branch}</h2></div><div className="nodes">{b.nodes.map(n => <div className={`skillNode ${n.unlocked ? 'unlocked' : 'locked'}`} key={n.name}><div className="nodeIcon">{n.unlocked ? <Brain /> : <Lock />}</div><h3>{n.name}</h3><span>LVL {n.level} · {Math.round((n.confidence || .5) * 100)}% Confidence</span><div className="bar"><i style={{ width: `${n.progress}%` }} /></div><small>{n.progress}% mastery</small><p>{n.description}</p>{n.topics?.length > 0 && <div className="topicDrawer"><h4><Sparkles size={12} /> TOPIC MASTERY BREAKDOWN ({n.topics.length} TOPICS)</h4>{n.topics.map(t => <div className="topicCardMini" key={t.topic}><div className="topicCardTop"><span>{t.topic}</span><b>{Math.round(t.mastery)}%</b></div><div className="bar" style={{ height: 4, margin: '5px 0' }}><i style={{ width: `${t.mastery}%` }} /></div><div className="topicCardMeta"><span>{Math.round((t.confidence || .5) * 100)}% confidence</span><span>{t.attempts} attempts</span></div></div>)}</div>}</div>)}</div></div>)}</div></div> }
function Hero() { const [a, setA] = useState(null), [shop, setShop] = useState([]), [msg, setMsg] = useState(''); const load = () => Promise.all([request('/avatar'), request('/shop')]).then(([x, y]) => { setA(x); setShop(y) }); useEffect(() => { load() }, []); if (!a) return <Loading />; const buy = async item => { try { await request('/shop/buy', { method: 'POST', body: JSON.stringify({ item }) }); setMsg(`${item} unlocked.`); load() } catch (e) { setMsg(e.message) } }; return <div className="page"><PageTitle eyebrow="YOUR HERO" title={<>Build a character your <em>life can power.</em></>} text="Your real-world consistency shapes stats, titles and inventory." /><div className="heroLayout"><div className="character panel"><div className="characterAvatar">{avatarEmoji(a.user.avatar)}</div><h2>{a.user.title}</h2><p>Level {a.user.level} Hero</p><div className="avatarChoices">{['knight', 'mage', 'rogue', 'healer'].map(x => <button className={a.user.avatar === x ? 'chosen' : ''} key={x} onClick={async () => { await request('/avatar', { method: 'POST', body: JSON.stringify({ avatar: x, title: a.user.title }) }); load() }}>{avatarEmoji(x)}</button>)}</div></div><div><div className="panel"><PanelHead title="Hero attributes" icon={Activity} />{Object.entries(a.stats).map(([k, v]) => <div className="meter" key={k}><span>{k}</span><div><i style={{ width: `${v}%` }} /></div><b>{v}</b></div>)}</div><div className="panel shop"><PanelHead title="Life Shop" icon={ShoppingBag} />{shop.map(x => <div className="shopRow" key={x.item}><div><Gift /><span><b>{x.item}</b><small>{x.kind}</small></span></div><button disabled={x.owned} onClick={() => buy(x.item)}>{x.owned ? 'OWNED' : `${x.cost} 🪙`}</button></div>)}</div>{msg && <div className="notice">{msg}</div>}</div></div></div> }
function Bosses() {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    request('/campaigns').then(cs => {
      const bosses = cs.flatMap(c => c.milestones.filter(m => m.is_boss).map(m => ({ ...m, campaign: c.title, boss: c.boss_name })));
      setRows(bosses);
    });
  }, []);
  return <div className="page"><PageTitle eyebrow="BOSS BATTLES" title={<>Face the <em>real outcome.</em></>} text="Bosses are multi-stage proof that you can execute, not just plan." /><div className="bossGrid">{rows.length ? rows.map(b => <div className="bossPanel" key={b.id}><div className="bossIcon"><Crown /></div><small>FINAL BOSS · {b.campaign}</small><h2>{b.boss}</h2><p>{b.description}</p><div className="bossHp"><span>PROGRESS</span><b>{b.progress}%</b><div className="bar"><i style={{ width: `${b.progress}%` }} /></div></div><div className="bossSteps"><span>✓ Foundations</span><span>⚔ Execution</span><span>🔒 Final proof</span></div></div>) : <EmptyState text="Create a campaign and its final boss will appear here." />}</div></div>;
}
function Analytics() { const [a, setA] = useState(null); useEffect(() => { request('/analytics').then(setA) }, []); if (!a) return <Loading />; return <div className="page"><PageTitle eyebrow="PROGRESS INTELLIGENCE" title={<>See the pattern behind your <em>progress.</em></>} text="Time-series signals help the Game Master choose what to emphasize next." /><div className="statGrid"><Stat icon={Zap} label="Weekly XP" value={`+${Math.round(a.weekly_xp)}`} sub="last 7 days" /><Stat icon={Swords} label="Weekly quests" value={a.weekly_quests} sub="assessed" /><Stat icon={Target} label="Completion" value={`${a.completion_rate}%`} sub="all quests" /><Stat icon={Clock} label="Focus time" value={`${a.focus_minutes}m`} sub="completed quest time" /></div><div className="twoCol"><div className="panel"><PanelHead title="Skill growth" icon={Brain} />{a.skills.map(s => <div className="meter" key={s.name}><span>{s.name} · Lv {s.level}</span><div><i style={{ width: `${s.progress}%` }} /></div><b>{s.progress}%</b></div>)}</div><div className="panel"><PanelHead title="Life balance" icon={Activity} />{a.categories.map(c => <div className="meter" key={c.name}><span>{c.name}</span><div><i style={{ width: `${c.completion}%` }} /></div><b>{c.completion}%</b></div>)}</div></div></div> }
function Journal() { const [rows, setRows] = useState([]), [form, setForm] = useState({ learned: '', difficult: '', next_step: '' }); const load = () => request('/journal').then(setRows); useEffect(() => { load() }, []); const save = async () => { await request('/journal', { method: 'POST', body: JSON.stringify(form) }); setForm({ learned: '', difficult: '', next_step: '' }); load() }; return <div className="page"><PageTitle eyebrow="JOURNAL" title={<>Turn experience into <em>insight.</em></>} text="Reflection gives the Game Master context that raw XP cannot provide." /><div className="journalEditor panel"><div className="formGrid"><label>What did you learn?<textarea value={form.learned} onChange={e => setForm({ ...form, learned: e.target.value })} /></label><label>What was difficult?<textarea value={form.difficult} onChange={e => setForm({ ...form, difficult: e.target.value })} /></label><label>What will you do next?<textarea value={form.next_step} onChange={e => setForm({ ...form, next_step: e.target.value })} /></label></div><button className="primary" onClick={save}><Send /> Save reflection</button></div><div className="journalList">{rows.map(r => <div className="panel journalEntry" key={r.id}><small>{new Date(r.created_at).toLocaleString()}</small><h3>{r.learned || 'Reflection'}</h3><p><b>Hard:</b> {r.difficult || '—'}</p><p><b>Next:</b> {r.next_step || '—'}</p><div className="aiInsight"><Sparkles /> {r.ai_insight}</div></div>)}</div></div> }
function Weekly() { const [r, setR] = useState(null); useEffect(() => { request('/weekly-review').then(setR) }, []); if (!r) return <Loading />; return <div className="page"><PageTitle eyebrow="WEEKLY REVIEW" title={<>Your week, <em>decoded.</em></>} text="The Game Master summarizes the last seven days and sets a focused next-week priority." /><div className="reviewHero"><Sparkles /><div><small>GAME MASTER</small><h2>{r.game_master}</h2><p>{r.next_week}</p></div></div><div className="statGrid"><Stat icon={Zap} label="XP" value={`+${r.xp}`} sub="this week" /><Stat icon={Swords} label="Quests" value={r.quests} sub="assessed" /><Stat icon={Target} label="Average" value={`${r.average}%`} sub="performance" /><Stat icon={Flame} label="Streak" value={r.streak} sub="days" /></div><div className="twoCol"><div className="panel"><small>STRONGEST</small><h2>{r.strongest}</h2><p>Keep using this strength as a bridge into harder quests.</p></div><div className="panel"><small>NEEDS ATTENTION</small><h2>{r.weakest}</h2><p>Give this skill one focused quest next week.</p></div></div></div> }
function Achievements() { const [rows, setRows] = useState([]); useEffect(() => { request('/achievements').then(setRows) }, []); return <div className="page"><PageTitle eyebrow="ACHIEVEMENTS" title={<>Make progress <em>visible.</em></>} text="Badges celebrate meaningful milestones without replacing the real-world outcome." /><div className="achievementGrid">{rows.map(a => <div className={`achievement ${a.unlocked ? 'unlocked' : ''}`} key={a.id}><div className="achievementIcon">{a.icon}</div><div><h3>{a.title}</h3><p>{a.description}</p></div>{a.unlocked ? <Check /> : <Lock />}</div>)}</div></div> }
function Social() { const [d, setD] = useState(null), [name, setName] = useState(''); const load = () => request('/social').then(setD); useEffect(() => { load() }, []); if (!d) return <Loading />; const add = async () => { if (name.trim()) { await request('/social/friends', { method: 'POST', body: JSON.stringify({ name }) }); setName(''); load() } }; return <div className="page"><PageTitle eyebrow="COMMUNITY" title={<>Accountability without the <em>noise.</em></>} text="Friends, shared challenges and leaderboards sit around the solo campaign rather than replacing it." /><div className="twoCol"><div className="panel"><PanelHead title="Leaderboard" icon={Users} />{d.leaderboard.map((x, i) => <div className={`leader ${x.you ? 'you' : ''}`} key={x.name}><b>#{i + 1}</b><span className="miniAvatar">{avatarEmoji(i === 0 ? 'mage' : 'knight')}</span><strong>{x.name}</strong><span>LVL {x.level}</span><b>{x.xp.toLocaleString()} XP</b></div>)}</div><div><div className="panel"><PanelHead title="Weekly challenge" icon={Trophy} /><h3>{d.challenge?.title}</h3><div className="bar"><i style={{ width: `${Math.round((d.challenge?.progress || 0) / (d.challenge?.target || 1) * 100)}%` }} /></div><p>{d.challenge?.progress}/{d.challenge?.target} quests · +{d.challenge?.reward} XP</p></div><div className="panel"><h3>Add accountability friend</h3><div className="inline"><input value={name} onChange={e => setName(e.target.value)} placeholder="Friend name" /><button className="primary" onClick={add}><Plus /></button></div></div></div></div></div> }
function Integrations({ refresh }) {
  const [rows, setRows] = useState([]), [syncing, setSyncing] = useState({}), [activities, setActivities] = useState([]);
  const [fitType, setFitType] = useState('walk'), [fitMins, setFitMins] = useState(30), [fitSteps, setFitSteps] = useState(3500), [fitMsg, setFitMsg] = useState('');
  const [bridgeData, setBridgeData] = useState(null), [showBridge, setShowBridge] = useState(false), [copied, setCopied] = useState(false);

  const load = async () => {
    try {
      const data = await request('/integrations');
      setRows(data);
      const acts = await request('/integrations/activities').catch(() => []);
      setActivities(acts);
    } catch (e) { }
  };

  useEffect(() => { load() }, []);

  const connectProvider = async (p) => {
    if (!p.is_configured) {
      alert(`${p.provider} is not configured on this server.\n\nAdd ${p.provider.toUpperCase().replace(/ /g, '_')}_CLIENT_ID and ${p.provider.toUpperCase().replace(/ /g, '_')}_CLIENT_SECRET to your backend .env file, then restart the server.`);
      return;
    }
    try {
      sessionStorage.setItem('pending_oauth_provider', p.provider);
      const redirectUri = window.location.origin + '/integrations';
      const authData = await request(`/integrations/${p.provider}/auth-url?redirect_uri=${encodeURIComponent(redirectUri)}`);
      if (!authData.auth_url || !authData.auth_url.startsWith('http')) {
        alert(`${p.provider} returned an invalid auth URL. Check your OAuth credentials in the backend .env.`);
        sessionStorage.removeItem('pending_oauth_provider');
        return;
      }
      window.location.href = authData.auth_url;
    } catch (e) {
      sessionStorage.removeItem('pending_oauth_provider');
      alert(`OAuth error: ${e.message}`);
    }
  };

  const disconnectProvider = async p => {
    try {
      await request(`/integrations/${p.provider}/disconnect`, { method: 'POST' });
      await load();
      if (refresh) await refresh();
    } catch (e) {
      alert(`Disconnect error: ${e.message}`);
    }
  };

  const syncProvider = async p => {
    setSyncing(s => ({ ...s, [p.provider]: true }));
    try {
      const res = await request(`/integrations/${p.provider}/sync`, { method: 'POST' });
      await load();
      if (refresh) await refresh();
      const awarded = res?.sync_stats?.total_xp_awarded || 0;
      if (awarded > 0) {
        const quests = res?.sync_stats?.matched_quests?.join(', ') || 'Active Quest';
        alert(`🎉 ${p.provider} Sync Complete!\n\n+${awarded} XP Awarded!\nQuests Cleared: ${quests}`);
      }
    } catch (e) {
      alert(`Sync error: ${e.message}`);
    } finally {
      setSyncing(s => ({ ...s, [p.provider]: false }));
    }
  };

  const loadBridgeToken = async () => {
    try {
      const d = await request('/integrations/fitness/bridge-token');
      setBridgeData(d);
      setShowBridge(true);
    } catch (e) {
      alert(e.message);
    }
  };

  const copyToken = () => {
    if (bridgeData?.token) {
      navigator.clipboard.writeText(bridgeData.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  };

  const logFitness = async e => {
    e.preventDefault();
    try {
      const res = await request('/integrations/fitness/activity', {
        method: 'POST',
        body: JSON.stringify({ activity_type: fitType, duration_minutes: +fitMins, steps: +fitSteps })
      });
      setFitMsg(`Logged! +${res.earned_xp} XP and +${res.earned_coins} coins awarded.`);
      setTimeout(() => setFitMsg(''), 5000);
      await load();
      if (refresh) await refresh();
    } catch (err) {
      alert(err.message);
    }
  };

  const getDesc = name => {
    if (name === 'GitHub') return 'Sync real repositories and commits to attach verifiable code evidence to engineering quests.';
    if (name.includes('Google Calendar')) return 'Detect real-world deadlines, exams, and deliverables within upcoming weeks to adapt quest priorities.';
    if (name.includes('Outlook Calendar')) return 'Extract assignment submission windows and meetings directly into your RPG schedule.';
    if (name === 'Fitness') return 'Connect Android Health Connect companion bridge to ingest verified workouts, steps, and activity.';
    return 'Feed focus sessions and real-world milestones into your progress.';
  };

  return <div className="page">
    <PageTitle
      eyebrow="REAL-WORLD INTEGRATIONS (PHASE 3)"
      title={<>Connect the RPG to your <em>real world.</em></>}
      text="Link external providers. The intelligence layer converts real GitHub commits, Google Calendar deadlines, and Android Health Connect workouts into verified RPG quest progress."
    />

    <div className="integrationGrid">
      {rows.map(x => {
        const isConn = !!x.connected;
        const isLive = !!x.is_live;
        const isConfigured = !!x.is_configured;
        const meta = x.metadata || {};
        const items = meta.items || [];
        const events = meta.events || [];

        return <div className="intCard panel" key={x.provider}>
          <div className="intTop">
            <div className="intInfo">
              <div className="intIconBox">
                {x.provider === 'GitHub' ? <GitCommit /> : x.provider.includes('Calendar') ? <CalendarDays /> : x.provider === 'Fitness' ? <Dumbbell /> : <Link2 />}
              </div>
              <div className="intTitle">
                <h3>{x.provider}</h3>
                <div>
                  <span className={`intStatusPill ${isConn ? 'live' : 'disconnected'}`}>
                    {isConn ? '● LIVE CONNECTED' : '○ NOT CONNECTED'}
                  </span>
                </div>
                <div>
                  <span className={`configBadge ${isConfigured ? 'ready' : 'unconfigured'}`}>
                    {isConfigured ? '⚡ Live OAuth Ready' : '⚠️ Not Configured'}
                  </span>
                </div>
                {x.account_name && <div className="accountPill">@{x.account_name}</div>}
              </div>
            </div>
            {isConn && <button className="syncBtn" disabled={syncing[x.provider]} onClick={() => syncProvider(x)}>
              <RefreshCw className={syncing[x.provider] ? 'spin' : ''} size={12} /> {syncing[x.provider] ? 'Syncing…' : 'Sync Now'}
            </button>}
          </div>

          <div className="intDesc">{getDesc(x.provider)}</div>

          {isConn && <div className="intMeta">
            <div><b>Last sync:</b> {x.last_sync_at ? new Date(x.last_sync_at).toLocaleString() : 'Just now'}</div>
            {meta.summary && <div style={{ marginTop: 4, color: 'var(--accent)' }}>ℹ️ {meta.summary}</div>}
            {x.error_message && <div style={{ marginTop: 4, color: 'var(--danger)' }}>⚠️ {x.error_message}</div>}

            {/* GitHub synced preview */}
            {x.provider === 'GitHub' && items.length > 0 && <div className="activityMiniList">
              <h5>Recent Synced Commits & Repos</h5>
              {items.slice(0, 3).map((it, i) => <div className="miniActivityItem" key={i}>
                <span>{it.type === 'commit' ? `Commit: ${it.title}` : `Repo: ${it.title}`}</span>
                <small>{it.repository}</small>
              </div>)}
            </div>}

            {/* Google Calendar deadlines preview */}
            {x.provider.includes('Calendar') && events.length > 0 && <div className="activityMiniList">
              <h5>Upcoming Events & Deadlines</h5>
              {events.slice(0, 3).map((ev, i) => <div className="miniActivityItem" key={i}>
                <span>{ev.summary}</span>
                <span className={`urgencyPill ${ev.urgency || 'normal'}`}>{ev.urgency || 'normal'}</span>
              </div>)}
            </div>}
          </div>}

          {/* Fitness & Android Health Connect Bridge */}
          {x.provider === 'Fitness' && <div className="fitnessQuickLog">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <small style={{ fontWeight: 800, color: 'var(--accent)', letterSpacing: '.1em' }}>ANDROID HEALTH CONNECT</small>
              <button type="button" style={{ fontSize: 10, background: 'none', border: 'none', color: 'var(--accent2)', cursor: 'pointer', textDecoration: 'underline' }} onClick={loadBridgeToken}>
                {showBridge ? 'Hide Bridge Pairing' : 'Pair Android App'}
              </button>
            </div>

            {showBridge && bridgeData && <div className="bridgeTokenBox">
              <div className="tokenHeader">
                <h4><Shield size={12} /> Android Bridge Pairing Token</h4>
                <small>{bridgeData.device_pair_code}</small>
              </div>
              <p style={{ fontSize: 11, color: 'var(--muted)', margin: '0 0 8px' }}>{bridgeData.instructions}</p>
              <div className="bridgeCodeRow">
                <code>{bridgeData.token}</code>
                <button type="button" onClick={copyToken}>{copied ? 'Copied!' : 'Copy Token'}</button>
              </div>
            </div>}

            {isConn && <form className="fitnessForm" onSubmit={logFitness}>
              <input value={fitType} onChange={e => setFitType(e.target.value)} placeholder="Activity (e.g. walk, run)" />
              <input type="number" value={fitMins} onChange={e => setFitMins(e.target.value)} placeholder="Mins" />
              <input type="number" value={fitSteps} onChange={e => setFitSteps(e.target.value)} placeholder="Steps" />
              <button className="primary" type="submit"><Plus size={13} /> Log</button>
            </form>}
            {fitMsg && <div className="notice" style={{ marginTop: 6 }}>{fitMsg}</div>}
          </div>}

          <div className="intActions" style={{ marginTop: 16 }}>
            {isConn ? (
              <button className="secondary" onClick={() => disconnectProvider(x)}>Disconnect Provider</button>
            ) : (
              <button className="primary" style={{ width: '100%' }} onClick={() => connectProvider(x)}>
                {isConfigured ? `Connect ${x.provider}` : `Configure ${x.provider} First`} <ArrowRight size={14} />
              </button>
            )}
          </div>
        </div>
      })}
    </div>

    {/* Unified Activity Feed Section */}
    {activities.length > 0 && <div className="feedSection panel">
      <div className="sectionHead">
        <div>
          <small>REAL ACTIVITY STREAM</small>
          <h2>Unified Activity Feed</h2>
        </div>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>{activities.length} total events ingested</span>
      </div>
      <div className="activityFeedGrid">
        {activities.slice(0, 6).map((act, idx) => <div className="feedCard" key={idx}>
          <div className="feedCardTop">
            <b>{act.provider} · {act.activity_type.replace('_', ' ').toUpperCase()}</b>
            <small>{new Date(act.timestamp).toLocaleDateString()}</small>
          </div>
          <h4>{act.title}</h4>
          <p>{act.description || 'Normalized external activity record.'}</p>
          {act.matched_quest_id && <div style={{ marginTop: 6, display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, color: '#38bdf8', background: '#0369a122', padding: '2px 7px', borderRadius: 4, border: '1px solid #0284c744' }}>
            <Check size={11} /> Linked as Quest Evidence
          </div>}
        </div>)}
      </div>
    </div>}

    <div className="privacyBlock">
      <Shield />
      <div>
        <h3>Zero-Knowledge Security Architecture</h3>
        <p>OAuth tokens are encrypted on the backend with authenticated AES/HMAC keystream cryptography. Access tokens and provider secrets are strictly protected and never exposed to the frontend browser.</p>
      </div>
    </div>
  </div>;
}


function Notifications() { const [rows, setRows] = useState([]); const load = () => request('/notifications').then(setRows); useEffect(() => { load() }, []); const read = async () => { await request('/notifications/read-all', { method: 'POST' }); load() }; return <div className="page"><PageTitle eyebrow="NOTIFICATIONS" title={<>Your world <em>speaks back.</em></>} text="Campaign events, adaptive recommendations and milestones appear here." action={<button className="secondary" onClick={read}><Check /> Mark all read</button>} /><div className="notificationList">{rows.length ? rows.map(n => <div className={`notification panel ${n.read ? 'read' : ''}`} key={n.id}><Bell /><div><small>{new Date(n.created_at).toLocaleString()}</small><h3>{n.title}</h3><p>{n.body}</p></div></div>) : <EmptyState text="No notifications yet. Your first campaign will create them." />}</div></div> }
function SettingsPage({ me, refresh }) { const [form, setForm] = useState({ name: me.name, age_range: me.age_range, timezone: me.timezone, difficulty: me.difficulty, daily_minutes: me.daily_minutes, interests: me.interests, priorities: me.priorities, notifications: me.notifications, theme: me.theme, sound: me.sound }); const save = async () => { await request('/profile', { method: 'POST', body: JSON.stringify(form) }); refresh(); alert('Settings saved.') }; const reset = async () => { if (confirm('Reset your RPG progress?')) { await request('/reset', { method: 'POST' }); location.reload() } }; return <div className="page"><PageTitle eyebrow="SETTINGS" title={<>Control your <em>world.</em></>} text="Profile, AI preferences, notifications and privacy controls." /><div className="settingsGrid"><div className="panel"><PanelHead title="Profile" icon={UserRound} /><div className="formGrid"><label>Name<input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label><label>Timezone<input value={form.timezone} onChange={e => setForm({ ...form, timezone: e.target.value })} /></label><label>Difficulty<select value={form.difficulty} onChange={e => setForm({ ...form, difficulty: e.target.value })}><option>Gentle</option><option>Normal</option><option>Hard</option><option>Elite</option></select></label><label>Daily minutes<input type="number" value={form.daily_minutes} onChange={e => setForm({ ...form, daily_minutes: +e.target.value })} /></label><label className="wide">Interests<input value={form.interests} onChange={e => setForm({ ...form, interests: e.target.value })} /></label><label className="wide">Priorities<input value={form.priorities} onChange={e => setForm({ ...form, priorities: e.target.value })} /></label></div><button className="primary" onClick={save}>Save settings</button></div><div className="panel"><PanelHead title="Privacy & controls" icon={Shield} /><div className="settingToggle"><span><b>Notifications</b><small>Quest reminders and campaign events</small></span><input type="checkbox" checked={form.notifications} onChange={e => setForm({ ...form, notifications: e.target.checked })} /></div><div className="settingToggle"><span><b>Sound</b><small>Interface and quest feedback</small></span><input type="checkbox" checked={form.sound} onChange={e => setForm({ ...form, sound: e.target.checked })} /></div><div className="danger"><h3>Reset demo progress</h3><p>This clears goals, quests, skills, inventory, journal and social demo data for your account.</p><button onClick={reset}><RefreshCw /> Reset progress</button></div></div></div></div> }
function Loading() { return <div className="loadingPage"><Gamepad2 /><b>Loading…</b></div> }
function EmptyState({ text }) { return <div className="empty"><Sparkles /><h3>Nothing here yet</h3><p>{text}</p></div> }

createRoot(document.getElementById('root')).render(<App />);
