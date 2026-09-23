from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from dotenv import load_dotenv
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import os, json, re, hmac, hashlib, base64, secrets, httpx

# Load .env FIRST before importing any app modules that read os.getenv() at module level.
_BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_BASE_DIR / ".env", override=True)

from app.goal_engine import (
    GoalAnalysisResult, analyze_goal_deterministic, detect_learning_subject,
    get_curriculum_for_subject
)
from app.quiz_engine import (
    generate_quiz_for_quest, mask_quiz_for_client
)
from app.evaluation_engine import evaluate_submission
from app.adaptive_engine import update_topic_skill, decide_adaptive_progression
from app.evidence_engine import (
    evaluate_evidence_with_ai, evaluate_evidence_deterministic, safe_fetch_url,
    extract_text_from_file_data, EvidenceEvaluationResult
)
from app.nlp_engine import (
    parse_natural_language_goal, NaturalLanguageParseResult
)
from app.integrations_engine import (
    get_provider, PROVIDERS, encrypt_token, decrypt_token, FitnessActivityInput, FitnessProvider,
    HealthConnectSyncBatch, normalize_activity, match_activity_to_quests, UnifiedActivity
)
from app.recommendation_engine import (
    generate_personalized_recommendations, RecommendationResponse
)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_URL = f"sqlite:///{BASE_DIR / 'liferpg_final.db'}"
UPLOAD_DIR = BASE_DIR / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True); email=Column(String,unique=True,index=True); password_hash=Column(String); name=Column(String,default='Hero')
    xp=Column(Integer,default=0); level=Column(Integer,default=1); coins=Column(Integer,default=250); streak=Column(Integer,default=0); last_active=Column(String,default='')
    avatar=Column(String,default='knight'); title=Column(String,default='Rookie Adventurer'); age_range=Column(String,default=''); timezone=Column(String,default='Asia/Kolkata')
    difficulty=Column(String,default='Normal'); daily_minutes=Column(Integer,default=30); interests=Column(Text,default=''); priorities=Column(Text,default='')
    notifications=Column(Boolean,default=True); theme=Column(String,default='dark'); sound=Column(Boolean,default=True); onboarding_done=Column(Boolean,default=False); created_at=Column(DateTime,default=datetime.utcnow)

class Goal(Base):
    __tablename__='goals'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); title=Column(String); goal_type=Column(String); category=Column(String,default='Learning'); deadline=Column(String,default=''); priority=Column(String,default='medium'); level=Column(String,default='Beginner'); minutes=Column(Integer,default=30); status=Column(String,default='active'); progress=Column(Float,default=0); created_at=Column(DateTime,default=datetime.utcnow); updated_at=Column(DateTime,default=datetime.utcnow)

class Campaign(Base):
    __tablename__='campaigns'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); goal_id=Column(Integer,ForeignKey('goals.id')); title=Column(String); summary=Column(Text); duration=Column(String,default='12 weeks'); status=Column(String,default='active'); current_milestone=Column(Integer,default=1); boss_name=Column(String,default='Final Boss'); created_at=Column(DateTime,default=datetime.utcnow)

class Milestone(Base):
    __tablename__='milestones'
    id=Column(Integer,primary_key=True); campaign_id=Column(Integer,ForeignKey('campaigns.id')); title=Column(String); description=Column(Text); order_index=Column(Integer); status=Column(String,default='locked'); progress=Column(Float,default=0); reward_xp=Column(Integer,default=150); reward_coins=Column(Integer,default=50); is_boss=Column(Boolean,default=False)

class Skill(Base):
    __tablename__='skills'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); name=Column(String); branch=Column(String,default='Foundations'); progress=Column(Float,default=0); xp=Column(Integer,default=0); level=Column(Integer,default=1); confidence=Column(Float,default=.5); category=Column(String,default='Learning'); description=Column(Text,default=''); prerequisites=Column(Text,default=''); unlocked=Column(Boolean,default=False)
    __table_args__=(UniqueConstraint('user_id','name',name='uq_user_skill'),)

class TopicSkill(Base):
    __tablename__='topic_skills'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); subject=Column(String); topic=Column(String)
    mastery=Column(Float,default=0.0); confidence=Column(Float,default=0.5); attempts=Column(Integer,default=0); last_score=Column(Float,default=0.0)
    last_assessed=Column(DateTime,default=datetime.utcnow); weak_subtopics=Column(Text,default='[]')
    __table_args__=(UniqueConstraint('user_id','subject','topic',name='uq_user_subject_topic'),)

class Quest(Base):
    __tablename__='quests'
    id=Column(Integer,primary_key=True); goal_id=Column(Integer,ForeignKey('goals.id')); milestone_id=Column(Integer,ForeignKey('milestones.id')); title=Column(String); description=Column(Text); quest_type=Column(String,default='challenge'); category=Column(String,default='Learning'); difficulty=Column(Integer,default=1); xp=Column(Integer,default=50); coin_reward=Column(Integer,default=10); status=Column(String,default='locked'); order_index=Column(Integer,default=0); skill=Column(String,default='General'); is_boss=Column(Boolean,default=False); question=Column(Text,default=''); options=Column(Text,default=''); answer=Column(Integer,default=0); due_date=Column(String,default=''); parent_id=Column(Integer,nullable=True); estimated_minutes=Column(Integer,default=30); evidence_required=Column(Boolean,default=False); completed_at=Column(DateTime,nullable=True)
    # Learning Engine extensions
    subject=Column(String,default=''); topic=Column(String,default=''); subtopic=Column(String,default='')
    learning_objective=Column(Text,default=''); assessment_required=Column(Boolean,default=False); assessment_type=Column(String,default='mixed')

class Assessment(Base):
    __tablename__='assessments'
    id=Column(Integer,primary_key=True); quest_id=Column(Integer,ForeignKey('quests.id')); user_id=Column(Integer,ForeignKey('users.id')); score=Column(Float); attempts=Column(Integer,default=1); time_taken=Column(Integer,default=0); feedback=Column(Text,default=''); created_at=Column(DateTime,default=datetime.utcnow)

class Quiz(Base):
    __tablename__='quizzes'
    id=Column(Integer,primary_key=True); quest_id=Column(Integer,ForeignKey('quests.id')); user_id=Column(Integer,ForeignKey('users.id'))
    subject=Column(String,default=''); topic=Column(String,default=''); difficulty=Column(Integer,default=1); status=Column(String,default='pending')
    questions_data=Column(Text,default='[]'); score=Column(Float,default=0.0); percentage=Column(Float,default=0.0); time_taken=Column(Integer,default=0)
    weak_areas=Column(Text,default='[]'); strong_areas=Column(Text,default='[]'); performance_data=Column(Text,default='{}'); feedback=Column(Text,default='')
    created_at=Column(DateTime,default=datetime.utcnow); completed_at=Column(DateTime,nullable=True)

class Evidence(Base):
    __tablename__='evidence'
    id=Column(Integer,primary_key=True); quest_id=Column(Integer,ForeignKey('quests.id')); user_id=Column(Integer,ForeignKey('users.id')); kind=Column(String); value=Column(Text); filename=Column(String,default=''); evaluation=Column(Text,default=''); quality=Column(Float,default=0)
    relevance=Column(Float,default=0.0); confidence=Column(Float,default=0.0); completeness=Column(Float,default=0.0); supports_quest=Column(Boolean,default=False); feedback=Column(Text,default=''); missing_requirements_json=Column(Text,default='[]'); created_at=Column(DateTime,default=datetime.utcnow)

class Inventory(Base):
    __tablename__='inventory'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); item=Column(String); kind=Column(String,default='cosmetic'); cost=Column(Integer,default=0); equipped=Column(Boolean,default=False)

class Mission(Base):
    __tablename__='missions'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); title=Column(String); description=Column(Text); mission_type=Column(String,default='daily'); xp=Column(Integer,default=30); coins=Column(Integer,default=8); status=Column(String,default='available'); day=Column(String); category=Column(String,default='Personal')

class Journal(Base):
    __tablename__='journal'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); quest_id=Column(Integer,nullable=True); learned=Column(Text); difficult=Column(Text); next_step=Column(Text); ai_insight=Column(Text,default=''); created_at=Column(DateTime,default=datetime.utcnow)

class Friend(Base):
    __tablename__='friends'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); name=Column(String); level=Column(Integer,default=1); xp=Column(Integer,default=0); status=Column(String,default='friend')

class Challenge(Base):
    __tablename__='challenges'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); title=Column(String); target=Column(Integer,default=5); progress=Column(Integer,default=0); reward=Column(Integer,default=100); status=Column(String,default='active')

class Integration(Base):
    __tablename__='integrations'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); provider=Column(String); connected=Column(Boolean,default=False)
    status=Column(String,default='disconnected'); external_user_id=Column(String,default=''); scopes=Column(String,default=''); connected_at=Column(DateTime,nullable=True); last_sync_at=Column(DateTime,nullable=True); sync_status=Column(String,default='idle'); error_message=Column(Text,default=''); access_token_enc=Column(Text,default=''); refresh_token_enc=Column(Text,default=''); metadata_json=Column(Text,default='{}'); updated_at=Column(DateTime,default=datetime.utcnow)
    token_expiry=Column(DateTime,nullable=True); is_live=Column(Boolean,default=False); account_name=Column(String,default='')

class UnifiedActivityRecord(Base):
    __tablename__='unified_activities'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id'),index=True); provider=Column(String); activity_type=Column(String)
    title=Column(String); description=Column(Text,default=''); external_id=Column(String,default=''); timestamp=Column(String,default='')
    metadata_json=Column(Text,default='{}'); matched_quest_id=Column(Integer,nullable=True); created_at=Column(DateTime,default=datetime.utcnow)

class Notification(Base):
    __tablename__='notifications'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id')); title=Column(String); body=Column(Text); kind=Column(String,default='system'); read=Column(Boolean,default=False); created_at=Column(DateTime,default=datetime.utcnow)

def ensure_schema():
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        result = conn.exec_driver_sql("PRAGMA table_info(quests)")
        cols = [row[1] for row in result.fetchall()]
        new_cols = [
            ("subject", "VARCHAR DEFAULT ''"),
            ("topic", "VARCHAR DEFAULT ''"),
            ("subtopic", "VARCHAR DEFAULT ''"),
            ("learning_objective", "TEXT DEFAULT ''"),
            ("assessment_required", "BOOLEAN DEFAULT 0"),
            ("assessment_type", "VARCHAR DEFAULT 'mixed'")
        ]
        for col_name, col_def in new_cols:
            if col_name not in cols:
                conn.exec_driver_sql(f"ALTER TABLE quests ADD COLUMN {col_name} {col_def}")

        res_ev = conn.exec_driver_sql("PRAGMA table_info(evidence)")
        ev_cols = [row[1] for row in res_ev.fetchall()]
        new_ev_cols = [
            ("relevance", "FLOAT DEFAULT 0.0"),
            ("confidence", "FLOAT DEFAULT 0.0"),
            ("completeness", "FLOAT DEFAULT 0.0"),
            ("supports_quest", "BOOLEAN DEFAULT 0"),
            ("feedback", "TEXT DEFAULT ''"),
            ("missing_requirements_json", "TEXT DEFAULT '[]'")
        ]
        for col_name, col_def in new_ev_cols:
            if col_name not in ev_cols:
                conn.exec_driver_sql(f"ALTER TABLE evidence ADD COLUMN {col_name} {col_def}")

        res_int = conn.exec_driver_sql("PRAGMA table_info(integrations)")
        int_cols = [row[1] for row in res_int.fetchall()]
        new_int_cols = [
            ("status", "VARCHAR DEFAULT 'disconnected'"),
            ("external_user_id", "VARCHAR DEFAULT ''"),
            ("scopes", "VARCHAR DEFAULT ''"),
            ("connected_at", "DATETIME"),
            ("last_sync_at", "DATETIME"),
            ("sync_status", "VARCHAR DEFAULT 'idle'"),
            ("error_message", "TEXT DEFAULT ''"),
            ("access_token_enc", "TEXT DEFAULT ''"),
            ("refresh_token_enc", "TEXT DEFAULT ''"),
            ("metadata_json", "TEXT DEFAULT '{}'"),
            ("token_expiry", "DATETIME"),
            ("is_live", "BOOLEAN DEFAULT 0"),
            ("account_name", "VARCHAR DEFAULT ''")
        ]
        for col_name, col_def in new_int_cols:
            if col_name not in int_cols:
                conn.exec_driver_sql(f"ALTER TABLE integrations ADD COLUMN {col_name} {col_def}")

        conn.commit()

ensure_schema()

app=FastAPI(title='LIFE RPG API',version='4.1')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
security=HTTPBearer(auto_error=False)
SECRET=os.getenv('LIFE_RPG_SECRET','change-this-secret-in-production')

# ---------- utilities ----------
def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()

def clean(o):
    sensitive_keys = {'_sa_instance_state', 'password_hash', 'access_token_enc', 'refresh_token_enc'}
    return {k:v for k,v in o.__dict__.items() if k not in sensitive_keys} if hasattr(o,'__dict__') else o

def hash_password(p,salt=None):
    salt=salt or secrets.token_hex(16); raw=hashlib.pbkdf2_hmac('sha256',p.encode(),salt.encode(),120000).hex(); return f'{salt}${raw}'

def verify_password(p,stored):
    try: salt,raw=stored.split('$',1); return hmac.compare_digest(hash_password(p,salt).split('$',1)[1],raw)
    except Exception: return False

def token_for(uid):
    payload=base64.urlsafe_b64encode(f'{uid}:{int(datetime.utcnow().timestamp())}'.encode()).decode().rstrip('='); sig=hmac.new(SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest(); return f'{payload}.{sig}'

def uid_from_token(token):
    try:
        payload,sig=token.split('.',1); expected=hmac.new(SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig,expected): return None
        raw=base64.urlsafe_b64decode(payload+'===').decode(); return int(raw.split(':',1)[0])
    except Exception: return None

def current_user(creds:HTTPAuthorizationCredentials=Depends(security),s:Session=Depends(db)):
    if not creds: raise HTTPException(401,'Please log in.')
    uid=uid_from_token(creds.credentials); u=s.get(User,uid) if uid else None
    if not u: raise HTTPException(401,'Session expired. Please log in again.')
    return u

def xp_needed(level): return 500+(max(0,level-1)*100)

def add_xp(u,amount):
    old=u.level; u.xp=max(0,u.xp+int(amount)); u.level=max(1,1+u.xp//500); return old,u.level

def touch(u):
    today=date.today(); last=None
    try: last=date.fromisoformat(u.last_active) if u.last_active else None
    except: last=None
    if last==today: return
    if last==today-timedelta(days=1): u.streak+=1
    elif last is None: u.streak=1
    else: u.streak=1
    u.last_active=today.isoformat()

def cat_for(t):
    x=t.lower(); groups={'Career':['job','career','resume','interview','placement'],'Health':['health','fitness','workout','gym','exercise','sleep','diet'],'Learning':['learn','study','course','exam','python','java','coding','dsa','skill'],'Finance':['money','save','saving','budget','finance','invest'],'Relationships':['friend','family','relationship','communication'],'Creativity':['write','music','art','design','content','creative'],'Personal':['discipline','habit','routine','productivity','focus']}
    for c,words in groups.items():
        if any(w in x for w in words): return c
    return 'Learning'

def type_for(t):
    x=t.lower()
    if any(w in x for w in ['daily','every day','habit','routine','meditate','workout']): return 'habit'
    if any(w in x for w in ['build','develop','create','project','app','website','launch']): return 'project'
    if any(w in x for w in ['exam','certification','pass','interview','demo']): return 'milestone'
    if any(w in x for w in ['learn','study','course','skill','practice']): return 'learning'
    return 'task'

def skill_for(t):
    x=t.lower(); pairs=[('DSA',['dsa','algorithm','data structure','leetcode']),('Python',['python','django','flask','fastapi']),('Coding',['coding','programming','software']),('Career',['career','job','resume','interview']),('Fitness',['fitness','workout','exercise','gym','run']),('Academics',['study','exam','course','learning']),('Projects',['project','build','app','website','hackathon']),('Finance',['money','finance','budget','invest']),('Communication',['relationship','communication','social'])]
    for n,words in pairs:
        if any(w in x for w in words): return n
    return 'Discipline'

def local_analysis(title,deadline,level,minutes,priority,category=''):
    det = analyze_goal_deterministic(title, deadline, level, minutes, priority, category)
    return det.model_dump()

async def ai_json(prompt,fallback):
    key=os.getenv('OPENAI_API_KEY'); model=os.getenv('OPENAI_MODEL','gpt-4o-mini')
    if not key: return fallback
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r=await c.post(os.getenv('OPENAI_BASE_URL','https://api.openai.com/v1')+'/chat/completions',headers={'Authorization':f'Bearer {key}'},json={'model':model,'messages':[{'role':'system','content':'Return valid JSON only.'},{'role':'user','content':prompt}],'temperature':0.2})
            r.raise_for_status(); content=r.json()['choices'][0]['message']['content']; return json.loads(re.sub(r'```json|```','',content).strip())
    except Exception: return fallback

def seed_integrations(s,u):
    for p in ['GitHub','Google Calendar','Outlook Calendar','Focus Timer','Fitness']:
        if not s.query(Integration).filter_by(user_id=u.id,provider=p).first(): s.add(Integration(user_id=u.id,provider=p,connected=False))

def notify(s,u,title,body,kind='system'): s.add(Notification(user_id=u.id,title=title,body=body,kind=kind))

def campaign_plan(goal):
    t=goal.title; skill=skill_for(t); typ=goal.goal_type
    if typ=='project': names=['Define Scope','Foundation Build','Core Implementation','Testing & Polish','Launch & Demo']
    elif typ=='habit': names=['Baseline','Consistency','Environment','Streak Challenge','Habit Boss']
    elif typ=='milestone': names=['Preparation','Practice','Simulation','Final Preparation','Final Boss']
    elif skill=='Coding': names=['Foundations','Problem Solving','Backend/API','Projects','Production Boss']
    else: names=['Foundation','Practice','Application','Challenge','Mastery Boss']
    return names

def ensure_skills(s, u, goal, extra_skills=None):
    primary = skill_for(goal.title)
    names = [primary, 'Discipline', 'Focus']
    if extra_skills:
        names = list(extra_skills) + names
    if goal.category == 'Career':
        names += ['Communication']
    for n in dict.fromkeys(names):
        in_pending = any(isinstance(obj, Skill) and obj.user_id == u.id and obj.name == n for obj in s.new)
        if not in_pending and not s.query(Skill).filter_by(user_id=u.id, name=n).first():
            s.add(Skill(user_id=u.id, name=n, branch='Core' if n in (primary, 'DSA', 'Python') else 'Life', category=goal.category, description=f'{n} mastery built through real-world quests.', prerequisites='', unlocked=(n in (primary, 'DSA', 'Python')), progress=0, xp=0, level=1))
            s.flush()

def quest_specs(goal,milestones):
    specs=[]; base_skill=skill_for(goal.title)
    for m in milestones:
        low=m.title.lower(); boss=m.is_boss
        if boss: qtype='boss'; title=f'{m.title}: {goal.title}'; desc=f'Complete the final real-world proof for {goal.title}.'; xp=250; coins=80; diff=5; evidence=True
        elif 'foundation' in low or 'preparation' in low or 'baseline' in low: qtype='learning'; title=f'{m.title} Quest'; desc=f'Learn and explain the essential ideas behind {goal.title}.'; xp=70; coins=20; diff=1; evidence=False
        elif 'practice' in low or 'problem' in low: qtype='practice'; title=f'{m.title} Run'; desc=f'Practice {base_skill} with a focused, measurable exercise.'; xp=90; coins=25; diff=2; evidence=True
        elif 'build' in low or 'implementation' in low or 'project' in low: qtype='build'; title=f'{m.title} Build'; desc=f'Create a tangible output that advances {goal.title}.'; xp=120; coins=35; diff=3; evidence=True
        elif 'test' in low or 'simulation' in low or 'challenge' in low: qtype='challenge'; title=f'{m.title} Challenge'; desc=f'Push your current skill with a timed or realistic challenge.'; xp=140; coins=40; diff=4; evidence=True
        elif 'launch' in low: qtype='social'; title=f'{m.title} Demo'; desc=f'Share, present or ship the result and collect feedback.'; xp=160; coins=50; diff=4; evidence=True
        else: qtype='habit'; title=f'{m.title} Action'; desc=f'Complete one small repeatable action toward {goal.title}.'; xp=60; coins=18; diff=1; evidence=False
        specs.append((m,qtype,title,desc,xp,coins,diff,evidence,base_skill))
    return specs

# ---------- schemas ----------
class Signup(BaseModel): email:str; password:str=Field(min_length=6); name:str='Hero'
class Login(BaseModel): email:str; password:str
class Profile(BaseModel): name:str='Hero'; age_range:str=''; timezone:str='Asia/Kolkata'; difficulty:str='Normal'; daily_minutes:int=30; interests:str=''; priorities:str=''; notifications:bool=True; theme:str='dark'; sound:bool=True
class GoalIn(BaseModel): title:str; deadline:str=''; level:str='Beginner'; minutes:int=30; priority:str='medium'; category:str=''
class CompleteIn(BaseModel): score:float=1.0; attempts:int=1; time_taken:int=0; answer:Optional[int]=None
class QuizSubmitIn(BaseModel): answers:Dict[str,Any]=Field(default_factory=dict); time_taken:int=0
class MissionIn(BaseModel): mission_id:int
class ShopIn(BaseModel): item:str
class AvatarIn(BaseModel): avatar:str; title:str=''
class FriendIn(BaseModel): name:str
class JournalIn(BaseModel): quest_id:Optional[int]=None; learned:str=''; difficult:str=''; next_step:str=''
class IntegrationIn(BaseModel): provider:str; connected:bool
class GoalStatus(BaseModel): status:str

@app.get('/api/health')
def health(): return {'ok':True,'version':'4.1'}

@app.post('/api/auth/signup')
@app.post('/api/auth/register')
def signup(x:Signup,s:Session=Depends(db)):
    email=x.email.strip().lower()
    if s.query(User).filter_by(email=email).first(): raise HTTPException(400,'An account with that email already exists.')
    u=User(email=email,password_hash=hash_password(x.password),name=x.name.strip() or 'Hero'); s.add(u); s.flush(); seed_integrations(s,u); s.add(Challenge(user_id=u.id,title='Weekly Quest Run',target=5,reward=150)); s.commit(); return {'token':token_for(u.id),'user':clean(u)}

@app.post('/api/auth/login')
def login(x:Login,s:Session=Depends(db)):
    u=s.query(User).filter_by(email=x.email.strip().lower()).first()
    if not u or not verify_password(x.password,u.password_hash): raise HTTPException(401,'Invalid email or password.')
    return {'token':token_for(u.id),'user':clean(u)}

@app.post('/api/auth/logout')
def logout(u:User=Depends(current_user)):
    return {'ok':True,'message':'Logged out successfully'}

@app.post('/api/auth/forgot-password')
def forgot(x:Login,s:Session=Depends(db)): return {'ok':True,'message':'If the account exists, password reset instructions can be sent by the configured email provider.'}

@app.get('/api/me')
def me(u:User=Depends(current_user)): return clean(u)

@app.post('/api/profile')
def profile(x:Profile,s:Session=Depends(db),u:User=Depends(current_user)):
    for k,v in x.model_dump().items(): setattr(u,k,v)
    s.commit(); return clean(u)

@app.post('/api/onboarding/complete')
def onboarding(x:Profile,s:Session=Depends(db),u:User=Depends(current_user)):
    for k,v in x.model_dump().items(): setattr(u,k,v)
    u.onboarding_done=True; touch(u); s.commit(); return clean(u)

# ---------- Goals & Campaigns ----------
@app.post('/api/goals/analyze')
async def analyze(g:GoalIn,u:User=Depends(current_user)):
    det = analyze_goal_deterministic(g.title, g.deadline, g.level, g.minutes, g.priority, g.category)
    fallback = det.model_dump()
    if os.getenv('OPENAI_API_KEY'):
        prompt = f"Analyze this life goal: '{g.title}'. Deadline: '{g.deadline}', Level: '{g.level}', Daily minutes: {g.minutes}. Return JSON with goal_type, category, subject, summary, priority, difficulty, estimated_effort, daily_minutes, required_skills, success_criteria, learning_required, project_required, assessment_required."
        res = await ai_json(prompt, fallback)
        try:
            return GoalAnalysisResult(**{**fallback, **res}).model_dump()
        except Exception:
            return fallback
    return fallback

@app.post('/api/goals')
async def create_goal(g:GoalIn,s:Session=Depends(db),u:User=Depends(current_user)):
    det = analyze_goal_deterministic(g.title, g.deadline, g.level, g.minutes, g.priority, g.category)
    a = det.model_dump()
    if os.getenv('OPENAI_API_KEY'):
        prompt = f"Analyze this goal: {g.title}. Return JSON with goal_type, category, subject, summary, required_skills: {g.title}"
        ai = await ai_json(prompt, a)
        a.update({k:v for k,v in ai.items() if k in a})
        
    goal=Goal(user_id=u.id,title=g.title.strip(),goal_type=a['goal_type'],category=a['category'],deadline=g.deadline,priority=g.priority,level=g.level,minutes=g.minutes); s.add(goal); s.flush()
    
    subject = a.get('subject')
    curriculum = get_curriculum_for_subject(subject) if subject else None
    
    if curriculum:
        # Dynamic curriculum campaign for Python or DSA
        campaign = Campaign(user_id=u.id, goal_id=goal.id, title=g.title.strip(), summary=a.get('summary', f'Adaptive {subject} mastery campaign.'), duration=g.deadline or '8 weeks', boss_name=f'{subject} Boss: Algorithm Trial' if subject=='DSA' else f'{subject} Boss: Architecture Challenge')
        s.add(campaign); s.flush()
        
        milestones = []
        ensure_skills(s, u, goal, extra_skills=[subject])
        
        quest_counter = 0
        for m_idx, m_def in enumerate(curriculum):
            is_boss_m = m_def.get("is_boss", False)
            m = Milestone(
                campaign_id=campaign.id,
                title=m_def["milestone"],
                description=m_def["description"],
                order_index=m_idx + 1,
                status='active' if m_idx == 0 else 'locked',
                progress=0,
                reward_xp=150 + m_idx * 40,
                reward_coins=40 + m_idx * 15,
                is_boss=is_boss_m
            )
            s.add(m); s.flush()
            milestones.append(m)
            
            for q_spec in m_def["quests"]:
                is_first_quest = (quest_counter == 0)
                diff = q_spec.get("diff", 2)
                q = Quest(
                    goal_id=goal.id,
                    milestone_id=m.id,
                    title=q_spec["title"],
                    description=f"{q_spec['obj']}",
                    quest_type="boss" if is_boss_m else "learning",
                    category="Learning",
                    difficulty=diff,
                    xp=250 if is_boss_m else 70 + diff * 20,
                    coin_reward=80 if is_boss_m else 20 + diff * 5,
                    status='available' if is_first_quest else 'locked',
                    order_index=quest_counter,
                    skill=subject,
                    is_boss=is_boss_m,
                    subject=subject,
                    topic=q_spec["topic"],
                    subtopic=q_spec["subtopic"],
                    learning_objective=q_spec["obj"],
                    assessment_required=True,
                    assessment_type=q_spec.get("type", "mixed"),
                    estimated_minutes=max(15, min(120, g.minutes)),
                    evidence_required=is_boss_m
                )
                s.add(q)
                quest_counter += 1
                
                # Pre-initialize TopicSkill entry if not exists
                in_pending_ts = any(isinstance(obj, TopicSkill) and obj.user_id == u.id and obj.subject == subject and obj.topic == q_spec["topic"] for obj in s.new)
                if not in_pending_ts and not s.query(TopicSkill).filter_by(user_id=u.id, subject=subject, topic=q_spec["topic"]).first():
                    s.add(TopicSkill(user_id=u.id, subject=subject, topic=q_spec["topic"], mastery=0.0, confidence=0.5, attempts=0, last_score=0.0))
                    s.flush()
                    
        notify(s, u, 'Adaptive Campaign Created', f'Your AI learning campaign for “{goal.title}” is ready with structured assessments.', 'campaign')
        touch(u); s.commit()
        return {'goal': clean(goal), 'campaign': clean(campaign), 'milestones': [clean(x) for x in milestones], 'analysis': a}
    else:
        campaign=Campaign(user_id=u.id,goal_id=goal.id,title=g.title.strip(),summary=a.get('summary','AI-generated life campaign.'),duration='12 weeks',boss_name=f'{g.title} — Final Boss'); s.add(campaign); s.flush()
        names=campaign_plan(goal); milestones=[]
        for i,n in enumerate(names):
            m=Milestone(campaign_id=campaign.id,title=n,description=f'{n} for {goal.title}',order_index=i+1,status='active' if i==0 else 'locked',progress=0,reward_xp=120+i*35,reward_coins=30+i*10,is_boss=i==len(names)-1); s.add(m); s.flush(); milestones.append(m)
        ensure_skills(s,u,goal)
        for i,(m,qtype,title,desc,xp,coins,diff,evidence,skill) in enumerate(quest_specs(goal,milestones)):
            q=Quest(goal_id=goal.id,milestone_id=m.id,title=title,description=desc,quest_type=qtype,category=goal.category,difficulty=diff,xp=xp,coin_reward=coins,status='available' if i==0 else 'locked',order_index=i,skill=skill,is_boss=m.is_boss,estimated_minutes=max(15,min(120,g.minutes)),evidence_required=evidence)
            if qtype in ('learning','practice'): q.question='What is the strongest way to demonstrate this quest was completed?'; q.options=json.dumps(['Only say I did it','Provide a concrete output or explanation','Skip the result','Wait until next week']); q.answer=1
            s.add(q)
        notify(s,u,'Campaign created',f'Your AI campaign for “{goal.title}” is ready. Your first quest awaits.','campaign'); touch(u); s.commit()
        return {'goal':clean(goal),'campaign':clean(campaign),'milestones':[clean(x) for x in milestones],'analysis':a}

@app.get('/api/goals')
def goals(s:Session=Depends(db),u:User=Depends(current_user)): return [clean(x) for x in s.query(Goal).filter_by(user_id=u.id).order_by(Goal.id.desc()).all()]

@app.patch('/api/goals/{gid}')
def goal_status(gid:int,x:GoalStatus,s:Session=Depends(db),u:User=Depends(current_user)):
    g=s.get(Goal,gid)
    if not g or g.user_id!=u.id: raise HTTPException(404,'Goal not found')
    if x.status not in ['active','paused','completed','archived']: raise HTTPException(400,'Invalid status')
    g.status=x.status; g.updated_at=datetime.utcnow(); s.commit(); return clean(g)

@app.get('/api/campaigns')
def campaigns(s:Session=Depends(db),u:User=Depends(current_user)):
    out=[]
    for c in s.query(Campaign).filter_by(user_id=u.id).order_by(Campaign.id.desc()).all():
        ms=s.query(Milestone).filter_by(campaign_id=c.id).order_by(Milestone.order_index).all(); out.append({**clean(c),'milestones':[clean(m) for m in ms]})
    return out

@app.get('/api/dashboard')
def dashboard(s:Session=Depends(db),u:User=Depends(current_user)):
    quests=[]
    for q in s.query(Quest).join(Goal).filter(Goal.user_id==u.id).order_by(Quest.status.desc(),Quest.id).all():
        d=clean(q); d['options']=json.loads(q.options) if q.options else []; quests.append(d)
    goals_=s.query(Goal).filter_by(user_id=u.id).all(); skills=s.query(Skill).filter_by(user_id=u.id).all(); completed=[q for q in quests if q['status']=='completed']; active=[q for q in quests if q['status'] in ('available','in_progress')]
    cats=[]
    for c in ['Career','Health','Learning','Finance','Relationships','Creativity','Personal']:
        gs=[g for g in goals_ if g.category==c]; cats.append({'name':c,'goals':len(gs),'progress':round(sum(g.progress for g in gs)/len(gs)) if gs else 0})
    campaign=s.query(Campaign).filter_by(user_id=u.id,status='active').order_by(Campaign.id.desc()).first()
    topic_skills=s.query(TopicSkill).filter_by(user_id=u.id).all()
    return {
        'user':clean(u),
        'xp_progress':{'current':u.xp%xp_needed(u.level),'needed':xp_needed(u.level),'percent':round((u.xp%xp_needed(u.level))/xp_needed(u.level)*100)},
        'goals':[clean(g) for g in goals_],
        'campaign':clean(campaign) if campaign else None,
        'quests':quests,
        'skills':[clean(x) for x in skills],
        'topic_skills':[clean(x) for x in topic_skills],
        'active_quests':len(active),
        'completed_quests':len(completed),
        'categories':cats,
        'missions':[clean(x) for x in missions_for(s,u)],
        'achievements':achievement_rows(s,u),
        'unread_notifications':s.query(Notification).filter_by(user_id=u.id,read=False).count()
    }

# ---------- Learning Quests & Quizzes ----------
@app.post('/api/quests/{qid}/start')
def quest_start(qid:int,s:Session=Depends(db),u:User=Depends(current_user)):
    q=s.get(Quest,qid)
    if not q or s.get(Goal,q.goal_id).user_id!=u.id: raise HTTPException(404,'Quest not found')
    if q.status=='locked': raise HTTPException(400,'This quest is locked. Complete the previous quest first.')
    q.status='in_progress'; s.commit(); return {'quest':clean(q),'options':json.loads(q.options) if q.options else []}

@app.get('/api/quests/{qid}/quiz')
async def get_or_create_quiz(qid: int, s: Session = Depends(db), u: User = Depends(current_user)):
    q = s.get(Quest, qid)
    if not q: raise HTTPException(404, 'Quest not found')
    goal = s.get(Goal, q.goal_id)
    if not goal or goal.user_id != u.id: raise HTTPException(403, 'Unauthorized access to quest')
    
    quiz = s.query(Quiz).filter_by(quest_id=q.id, user_id=u.id).first()
    if quiz:
        raw_questions = json.loads(quiz.questions_data)
        if quiz.status == 'completed':
            return {
                'quiz': clean(quiz),
                'questions': raw_questions,
                'is_completed': True,
                'score': quiz.score,
                'percentage': quiz.percentage,
                'weak_areas': json.loads(quiz.weak_areas) if quiz.weak_areas else [],
                'strong_areas': json.loads(quiz.strong_areas) if quiz.strong_areas else [],
                'performance_data': json.loads(quiz.performance_data) if quiz.performance_data else {}
            }
        else:
            return {
                'quiz': clean(quiz),
                'questions': mask_quiz_for_client(raw_questions),
                'is_completed': False
            }
            
    # Determine subject and topic
    subject = q.subject or ("DSA" if "dsa" in q.title.lower() or "dsa" in goal.title.lower() else "Python" if "python" in q.title.lower() or "python" in goal.title.lower() else "DSA")
    topic = q.topic or ("Foundations" if subject == "DSA" else "Basics")
    subtopic = q.subtopic or ""
    diff = q.difficulty or 2
    is_boss = q.is_boss
    is_reinf = (q.quest_type == 'reinforcement')
    
    questions = await generate_quiz_for_quest(
        quest_title=q.title,
        subject=subject,
        topic=topic,
        subtopic=subtopic,
        difficulty=diff,
        learning_objective=q.learning_objective or q.description,
        is_boss=is_boss,
        is_reinforcement=is_reinf,
        ai_json_func=ai_json
    )
    
    quiz = Quiz(
        quest_id=q.id,
        user_id=u.id,
        subject=subject,
        topic=topic,
        difficulty=diff,
        status='pending',
        questions_data=json.dumps(questions),
        score=0.0,
        percentage=0.0
    )
    s.add(quiz); s.commit()
    
    return {
        'quiz': clean(quiz),
        'questions': mask_quiz_for_client(questions),
        'is_completed': False
    }

@app.post('/api/quests/{qid}/quiz/submit')
def submit_quiz(qid: int, x: QuizSubmitIn, s: Session = Depends(db), u: User = Depends(current_user)):
    q = s.get(Quest, qid)
    if not q: raise HTTPException(404, 'Quest not found')
    goal = s.get(Goal, q.goal_id)
    if not goal or goal.user_id != u.id: raise HTTPException(403, 'Unauthorized')
    
    quiz = s.query(Quiz).filter_by(quest_id=q.id, user_id=u.id).first()
    if not quiz: raise HTTPException(400, 'Quiz not initialized. Please load quiz first.')
    
    raw_questions = json.loads(quiz.questions_data)
    eval_result = evaluate_submission(raw_questions, x.answers, time_taken=x.time_taken)
    
    score_pct = eval_result["percentage"]
    normalized_score = max(0.0, min(1.0, score_pct / 100.0))
    
    quiz.score = eval_result["total_score"]
    quiz.percentage = score_pct
    quiz.time_taken = x.time_taken
    quiz.status = 'completed'
    quiz.completed_at = datetime.utcnow()
    quiz.weak_areas = json.dumps(eval_result["weak_areas"])
    quiz.strong_areas = json.dumps(eval_result["strong_areas"])
    quiz.performance_data = json.dumps({
        "question_type_perf": eval_result["question_type_perf"],
        "topic_perf": eval_result["topic_perf"],
        "detailed_results": eval_result["detailed_results"]
    })
    
    # Calculate rewards
    score_ratio = normalized_score
    mult = 0.5 + 0.5 * score_ratio
    earned_xp = round(q.xp * mult)
    earned_coins = round(q.coin_reward * mult)
    old_lvl, new_lvl = add_xp(u, earned_xp)
    u.coins += earned_coins
    touch(u)
    
    q.status = 'completed'
    q.completed_at = datetime.utcnow()
    
    # Update assessment record
    feedback_text = 'Outstanding mastery!' if score_pct >= 85 else 'Good execution with room for polish.' if score_pct >= 65 else 'Reinforcement recommended on weak concepts.'
    s.add(Assessment(
        quest_id=q.id,
        user_id=u.id,
        score=normalized_score,
        attempts=1,
        time_taken=x.time_taken,
        feedback=feedback_text
    ))
    
    # Update Skill model
    sk = s.query(Skill).filter_by(user_id=u.id, name=q.skill).first()
    if sk:
        sk.xp += earned_xp
        sk.progress = min(100.0, round(sk.progress + max(4.0, earned_xp / 8.0), 1))
        sk.level = max(1, 1 + int(sk.xp // 200))
        sk.confidence = round(min(1.0, max(0.2, (sk.confidence * 0.7) + (normalized_score * 0.3))), 2)
        sk.unlocked = True
        
    # Update TopicSkill
    topic_result = {}
    if q.subject and q.topic:
        topic_result = update_topic_skill(
            session=s,
            user_id=u.id,
            subject=q.subject,
            topic=q.topic,
            score_pct=score_pct,
            weak_subtopics=eval_result["weak_areas"],
            TopicSkillModel=TopicSkill
        )
        
    # Goal progress update
    total_q = s.query(Quest).filter_by(goal_id=goal.id).count()
    done_q = s.query(Quest).filter_by(goal_id=goal.id, status='completed').count()
    goal.progress = min(100.0, round((done_q / max(1, total_q)) * 100.0, 1))
    
    # Milestone progress update
    m = s.get(Milestone, q.milestone_id)
    if m:
        m_quests = s.query(Quest).filter_by(milestone_id=m.id).all()
        m_done = sum(1 for z in m_quests if z.status == 'completed')
        m.progress = round((m_done / max(1, len(m_quests))) * 100.0, 1)
        if m.progress >= 100 and m.status != 'completed':
            m.status = 'completed'
            add_xp(u, m.reward_xp)
            u.coins += m.reward_coins
            notify(s, u, 'Milestone Cleared', f'{m.title} completed! Rewards claimed.', 'milestone')
            nxt_m = s.query(Milestone).filter(Milestone.campaign_id == m.campaign_id, Milestone.order_index == m.order_index + 1).first()
            if nxt_m: nxt_m.status = 'active'
            
    # Adaptive decision
    consecutive_reinf = 0
    if q.quest_type == 'reinforcement':
        p = q.parent_id
        while p:
            consecutive_reinf += 1
            pq = s.get(Quest, p)
            p = pq.parent_id if pq else None
            
    adaptive = decide_adaptive_progression(
        score_pct=score_pct,
        subject=q.subject or "DSA",
        topic=q.topic or "Foundations",
        subtopic=q.subtopic or "",
        current_difficulty=q.difficulty or 2,
        consecutive_reinforcements=consecutive_reinf,
        weak_areas=eval_result["weak_areas"]
    )
    
    nxt_quest = None
    if adaptive["needs_reinforcement"]:
        rq = Quest(
            goal_id=q.goal_id,
            milestone_id=q.milestone_id,
            title=adaptive["quest_title"],
            description=adaptive["quest_desc"],
            quest_type="reinforcement",
            category=q.category,
            difficulty=adaptive["next_difficulty"],
            xp=45,
            coin_reward=15,
            status="available",
            order_index=q.order_index + 1000 + consecutive_reinf,
            skill=q.skill,
            subject=q.subject,
            topic=q.topic,
            subtopic=adaptive.get("weak_concept", q.subtopic),
            learning_objective=f"Reinforce understanding of {adaptive.get('weak_concept', q.subtopic)}.",
            assessment_required=True,
            assessment_type="debugging" if "debugging" in adaptive["quest_title"].lower() else "mixed",
            parent_id=q.id,
            estimated_minutes=max(10, q.estimated_minutes // 2),
            evidence_required=False
        )
        s.add(rq); s.flush()
        nxt_quest = rq
        notify(s, u, 'Adaptive Quest Added', adaptive["message"], 'adaptive')
    else:
        nxt = s.query(Quest).filter(Quest.goal_id == q.goal_id, Quest.status == 'locked').order_by(Quest.order_index).first()
        if nxt:
            nxt.status = 'available'
            if adaptive["tier"] == "high" and nxt.difficulty < 5:
                nxt.difficulty = min(5, nxt.difficulty + 1)
            nxt_quest = nxt
            
    if q.is_boss:
        notify(s, u, 'Campaign Victorious!', f'You defeated {q.title}! The boss trial has been conquered.', 'boss')
        
    ch = s.query(Challenge).filter_by(user_id=u.id, status='active').first()
    if ch:
        ch.progress = min(ch.target, ch.progress + 1)
        if ch.progress >= ch.target: ch.status = 'completed'
        
    s.commit()
    
    return {
        'quiz_id': quiz.id,
        'score': eval_result["total_score"],
        'max_score': eval_result["max_score"],
        'percentage': score_pct,
        'earned_xp': earned_xp,
        'earned_coins': earned_coins,
        'level': u.level,
        'leveled_up': new_lvl > old_lvl,
        'total_xp': u.xp,
        'weak_areas': eval_result["weak_areas"],
        'strong_areas': eval_result["strong_areas"],
        'topic_perf': eval_result["topic_perf"],
        'question_type_perf': eval_result["question_type_perf"],
        'detailed_results': eval_result["detailed_results"],
        'adaptive': adaptive,
        'next_quest': clean(nxt_quest) if nxt_quest else None,
        'topic_skill': topic_result
    }

@app.get('/api/quests/{qid}/quiz/result')
def get_quiz_result(qid: int, s: Session = Depends(db), u: User = Depends(current_user)):
    q = s.get(Quest, qid)
    if not q: raise HTTPException(404, 'Quest not found')
    quiz = s.query(Quiz).filter_by(quest_id=q.id, user_id=u.id).first()
    if not quiz or quiz.status != 'completed': raise HTTPException(404, 'No completed assessment found for this quest.')
    
    perf = json.loads(quiz.performance_data) if quiz.performance_data else {}
    return {
        'quiz_id': quiz.id,
        'score': quiz.score,
        'percentage': quiz.percentage,
        'time_taken': quiz.time_taken,
        'weak_areas': json.loads(quiz.weak_areas) if quiz.weak_areas else [],
        'strong_areas': json.loads(quiz.strong_areas) if quiz.strong_areas else [],
        'topic_perf': perf.get('topic_perf', {}),
        'question_type_perf': perf.get('question_type_perf', {}),
        'detailed_results': perf.get('detailed_results', []),
        'completed_at': quiz.completed_at
    }

@app.get('/api/skills/{subject}/topics')
def get_topic_skills(subject: str, s: Session = Depends(db), u: User = Depends(current_user)):
    rows = s.query(TopicSkill).filter_by(user_id=u.id, subject=subject).all()
    return [clean(r) for r in rows]

def complete_quest_progression(s: Session, u: User, q: Quest, score: float = 0.85, feedback: str = "Strong performance.", attempts: int = 1, time_taken: int = 15) -> Dict[str, Any]:
    """Authoritative RPG progression engine for completing a quest."""
    if q.status == 'completed':
        return {'message': 'Already completed', 'earned_xp': 0, 'earned_coins': 0, 'score': score, 'level': u.level, 'leveled_up': False}

    score = max(0.0, min(1.0, float(score)))
    mult = 0.55 + 0.45 * score
    earned = round(q.xp * mult)
    coins = round(q.coin_reward * mult)
    old, new = add_xp(u, earned)
    u.coins += coins
    touch(u)

    q.status = 'completed'
    q.completed_at = datetime.utcnow()
    s.add(Assessment(
        quest_id=q.id,
        user_id=u.id,
        score=score,
        attempts=attempts,
        time_taken=time_taken,
        feedback=feedback
    ))

    sk = s.query(Skill).filter_by(user_id=u.id, name=q.skill).first()
    if sk:
        sk.xp += earned
        sk.progress = min(100.0, round(sk.progress + max(4.0, earned / 8.0), 1))
        sk.level = max(1, 1 + int(sk.xp // 200))
        sk.confidence = min(1.0, 0.4 + sk.progress / 125.0)
        sk.unlocked = True

    goal = s.get(Goal, q.goal_id) if q.goal_id else None
    if goal:
        total_q = s.query(Quest).filter_by(goal_id=goal.id).count()
        done_q = s.query(Quest).filter_by(goal_id=goal.id, status='completed').count()
        goal.progress = min(100.0, round((done_q / max(1, total_q)) * 100.0, 1))

    m = s.get(Milestone, q.milestone_id) if q.milestone_id else None
    if m:
        ms = s.query(Quest).filter_by(milestone_id=m.id).all()
        done = sum(1 for z in ms if z.status == 'completed')
        m.progress = round((done / max(1, len(ms))) * 100.0)
        if m.progress >= 100 and m.status != 'completed':
            m.status = 'completed'
            add_xp(u, m.reward_xp)
            u.coins += m.reward_coins
            notify(s, u, 'Milestone cleared', f'{m.title} is complete. Next milestone unlocked.', 'milestone')
            nxt = s.query(Milestone).filter(Milestone.campaign_id == m.campaign_id, Milestone.order_index == m.order_index + 1).first()
            if nxt:
                nxt.status = 'active'

    nxt = s.query(Quest).filter(Quest.goal_id == q.goal_id, Quest.status == 'locked').order_by(Quest.order_index).first()
    if score < 0.5:
        nxt = None
        rq = Quest(
            goal_id=q.goal_id,
            milestone_id=q.milestone_id,
            title=f'Reinforcement: {q.title}',
            description=f'Rebuild confidence with a smaller version of: {q.description}',
            quest_type='reinforcement',
            category=q.category,
            difficulty=max(1, q.difficulty - 1),
            xp=45,
            coin_reward=12,
            status='available',
            order_index=q.order_index + 1000,
            skill=q.skill,
            evidence_required=False,
            parent_id=q.id,
            estimated_minutes=max(10, q.estimated_minutes // 2)
        )
        s.add(rq)
        notify(s, u, 'Adaptive quest added', f'Your Game Master created reinforcement for {q.skill}.', 'adaptive')
    elif nxt:
        nxt.status = 'available'

    ch = s.query(Challenge).filter_by(user_id=u.id, status='active').first()
    if ch:
        ch.progress = min(ch.target, ch.progress + 1)
        if ch.progress >= ch.target:
            ch.status = 'completed'

    if q.is_boss:
        notify(s, u, 'Boss defeated', f'You defeated {q.title}. Campaign victory is within reach.', 'boss')

    return {
        'earned_xp': earned,
        'earned_coins': coins,
        'score': score,
        'level': u.level,
        'leveled_up': new > old,
        'total_xp': u.xp,
        'next_quest': clean(nxt) if nxt else None,
        'skill': clean(sk) if sk else None,
        'message': 'Reinforcement unlocked. Strengthen the skill before pushing difficulty.' if score < 0.5 else 'Quest cleared. Your next challenge is unlocked.'
    }

def process_github_activity_sync(s: Session, u: User, sync_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingests real GitHub activity items into the Unified Activity layer and links authentic
    commit/repo evidence to matching quests without duplicating evidence or bypassing quiz requirements.
    """
    raw_items = sync_data.get('items', [])
    active_quest_rows = (
        s.query(Quest, Goal)
        .join(Goal, Quest.goal_id == Goal.id)
        .filter(Goal.user_id == u.id, Quest.status.in_(['available', 'in_progress']))
        .all()
    )
    active_quests = []
    for q_obj, g_obj in active_quest_rows:
        qd = clean(q_obj)
        qd['goal_title'] = g_obj.title
        qd['goal_category'] = g_obj.category
        qd['goal_type'] = g_obj.goal_type
        active_quests.append(qd)

    # For every active engineering/coding goal without active quests,
    # generate an iteration build quest so continuous commits continue progressing the campaign
    active_goals = (
        s.query(Goal)
        .filter(Goal.user_id == u.id, Goal.status == 'active')
        .all()
    )
    goal_ids_with_active_quests = {q.get('goal_id') for q in active_quests}
    for g in active_goals:
        g_cat = (g.category or "").lower()
        if g_cat in ('learning', 'career', 'personal', 'creativity', 'coding', 'projects') and g.id not in goal_ids_with_active_quests:
            camp = s.query(Campaign).filter_by(goal_id=g.id).first()
            last_m = s.query(Milestone).filter_by(campaign_id=camp.id).order_by(Milestone.order_index.desc()).first() if camp else None
            m_id = last_m.id if last_m else None
            if camp and not m_id:
                m_obj = Milestone(
                    campaign_id=camp.id,
                    title=f"Continuous Iteration: {g.title}",
                    description=f"Ongoing development for {g.title}",
                    order_index=99,
                    status='active'
                )
                s.add(m_obj)
                s.flush()
                m_id = m_obj.id

            iter_q = Quest(
                milestone_id=m_id,
                goal_id=g.id,
                title=f"Build Iteration: {g.title}",
                description=f"Continuous project implementation, code refactoring and feature delivery for {g.title}.",
                quest_type="build",
                xp=120,
                coin_reward=35,
                estimated_minutes=45,
                difficulty=3,
                evidence_required=True,
                assessment_required=False,
                status="in_progress",
                order_index=999
            )
            s.add(iter_q)
            s.flush()
            qd = clean(iter_q)
            qd['goal_title'] = g.title
            qd['goal_category'] = g.category
            qd['goal_type'] = g.goal_type
            active_quests.append(qd)
            goal_ids_with_active_quests.add(g.id)

    matched_quest_titles = []
    evidence_created_count = 0
    new_records_count = 0
    total_xp_awarded = 0

    for item in raw_items:
        norm = normalize_activity('GitHub', item)
        ext_id = norm.external_id or f"gh_{secrets.token_hex(6)}"

        # 1. Deduplication via UnifiedActivityRecord
        existing = s.query(UnifiedActivityRecord).filter_by(user_id=u.id, external_id=ext_id).first() if ext_id else None
        if existing and existing.matched_quest_id is not None:
            # Already synced and matched: skip to prevent duplicate activity & XP
            continue

        matched = match_activity_to_quests(norm, active_quests)
        matched_id = matched['id'] if matched else None

        if existing:
            if not matched_id:
                # Still unmatched: skip
                continue
            # Previously unmatched activity now matches an active quest!
            existing.matched_quest_id = matched_id
            rec = existing
        else:
            rec = UnifiedActivityRecord(
                user_id=u.id,
                provider="GitHub",
                activity_type=norm.activity_type,
                title=norm.title,
                description=norm.description,
                external_id=ext_id,
                timestamp=norm.timestamp,
                metadata_json=json.dumps(norm.metadata),
                matched_quest_id=matched_id
            )
            s.add(rec)
            new_records_count += 1

        # 2. If matched to an active quest, link authentic evidence
        if matched and matched_id and norm.activity_type in ('github_commit', 'github_repository'):
            q = s.get(Quest, matched_id)
            if q:
                repo = norm.metadata.get('repository') or 'repo'
                sha = norm.metadata.get('sha') or ''
                url = norm.metadata.get('url') or ''

                # Check for duplicate Evidence across this user's github evidence
                existing_ev = s.query(Evidence).filter_by(user_id=u.id, kind='github').all()
                is_duplicate_ev = False
                for ev in existing_ev:
                    if sha:
                        sha_short = sha[:8]
                        if ev.filename in (sha, sha_short) or (ev.filename and (sha.startswith(ev.filename) or ev.filename.startswith(sha))):
                            is_duplicate_ev = True
                            break
                        if ev.value and (sha in ev.value or sha_short in ev.value):
                            is_duplicate_ev = True
                            break
                    if url and (ev.value and url in ev.value):
                        is_duplicate_ev = True
                        break
                    if ext_id and ev.filename == ext_id:
                        is_duplicate_ev = True
                        break

                if not is_duplicate_ev:
                    # Evaluate evidence deterministically
                    eval_text = f"GitHub Commit: {norm.title}\nRepo: {repo}\nDescription: {norm.description}\nURL: {url}"
                    eval_res = evaluate_evidence_deterministic(
                        quest_title=q.title,
                        quest_type=q.quest_type,
                        quest_description=q.description or q.title,
                        evidence_kind='github',
                        evidence_text=eval_text,
                        github_activity={"commits": [{"title": norm.title, "url": url}]}
                    )

                    quality_score = max(80.0, round(eval_res.quality * 100, 1))
                    ev_rec = Evidence(
                        quest_id=q.id,
                        user_id=u.id,
                        kind='github',
                        value=f"{repo}: {norm.title} ({url})" if url else f"{repo}: {norm.title}",
                        filename=sha or ext_id,
                        evaluation=f"Verified authentic GitHub commit from {repo} (SHA: {sha[:8] if sha else 'HEAD'}). Status: Verified.",
                        quality=quality_score,
                        relevance=max(0.85, round(eval_res.relevance, 2)),
                        confidence=max(0.9, round(eval_res.confidence, 2)),
                        completeness=max(0.85, round(eval_res.completeness, 2)),
                        supports_quest=True,
                        feedback=f"Verified GitHub commit '{norm.title}' from {repo} successfully attached.",
                        missing_requirements_json=json.dumps(eval_res.missing_requirements)
                    )
                    s.add(ev_rec)
                    s.flush()
                    evidence_created_count += 1
                    matched_quest_titles.append(q.title)

                    # 3. Update quest progression & rewards if quest is active
                    if q.status in ('available', 'in_progress'):
                        if q.assessment_required:
                            # Award deliverable proof XP & coins while retaining diagnostic quiz for complete mastery
                            if q.status == 'available':
                                q.status = 'in_progress'
                            ev_xp = max(40, round(q.xp * 0.6))
                            ev_coins = max(10, round(q.coin_reward * 0.6))
                            add_xp(u, ev_xp)
                            u.coins += ev_coins
                            total_xp_awarded += ev_xp
                            notify(s, u, 'GitHub Evidence Verified', f"Verified commit from {repo} attached to {q.title}! +{ev_xp} XP, +{ev_coins} coins awarded. Take the diagnostic quiz when ready for full mastery completion.", 'evidence')
                        else:
                            # Tangible coding/project quest: complete using authoritative RPG progression
                            prog_res = complete_quest_progression(
                                s, u, q,
                                score=0.88,
                                feedback=f"Completed with verified GitHub commit '{norm.title}' in repository {repo}."
                            )
                            earned_xp = prog_res.get('earned_xp', 0)
                            total_xp_awarded += earned_xp
                            notify(s, u, 'Quest Cleared via GitHub', f"'{q.title}' completed via real GitHub commit! +{earned_xp} XP, +{prog_res.get('earned_coins', 0)} coins.", 'quest')

                            # Update active_quests list so subsequent distinct items can progress newly unlocked quests
                            active_quests = [aq for aq in active_quests if aq.get('id') != q.id]
                            if prog_res.get('next_quest'):
                                nq = prog_res['next_quest']
                                active_quests.append(nq)

    s.flush()
    return {
        "new_activities": new_records_count,
        "evidence_created": evidence_created_count,
        "matched_quests": matched_quest_titles,
        "total_xp_awarded": total_xp_awarded
    }

# Standard complete for non-learning quests
@app.post('/api/quests/{qid}/complete')
def quest_complete(qid:int,x:CompleteIn,s:Session=Depends(db),u:User=Depends(current_user)):
    q=s.get(Quest,qid); goal=s.get(Goal,q.goal_id) if q else None
    if not q or not goal or goal.user_id!=u.id: raise HTTPException(404,'Quest not found')
    if q.status=='completed': return {'message':'Already completed','earned_xp':0,'earned_coins':0}
    
    # Phase 2 Evidence Check: If quest requires tangible evidence proof
    if q.evidence_required:
        evs = s.query(Evidence).filter_by(quest_id=q.id, user_id=u.id).all()
        if not evs:
            raise HTTPException(400, 'This quest requires evidence submission before completion.')
        valid_ev = any(e.supports_quest or e.quality >= 60.0 for e in evs)
        if not valid_ev:
            raise HTTPException(400, 'Submitted evidence does not sufficiently meet quest criteria. Please review feedback and submit revised deliverables.')

    if q.question and x.answer is not None and x.answer!=q.answer: x.score=min(x.score,.4)
    score = max(0, min(1, x.score))
    fb = 'Strong performance.' if score >= 0.75 else 'Reinforcement recommended.'
    result = complete_quest_progression(s, u, q, score=score, feedback=fb, attempts=x.attempts, time_taken=x.time_taken)
    s.commit()
    return result

# ---------- Evidence ----------
@app.post('/api/evidence/{qid}/text')
async def evidence_text(qid:int,value:str,s:Session=Depends(db),u:User=Depends(current_user)):
    q=s.get(Quest,qid)
    if not q or s.get(Goal,q.goal_id).user_id!=u.id: raise HTTPException(404,'Quest not found')
    eval_res = await evaluate_evidence_with_ai(q.title, q.description or q.title, q.quest_type, 'text', value[:10000])
    e=Evidence(
        quest_id=qid,user_id=u.id,kind='text',value=value[:10000],
        evaluation=eval_res.feedback,
        quality=round(eval_res.quality * 100, 1),
        relevance=round(eval_res.relevance, 2),
        confidence=round(eval_res.confidence, 2),
        completeness=round(eval_res.completeness, 2),
        supports_quest=eval_res.supports_quest,
        feedback=eval_res.feedback,
        missing_requirements_json=json.dumps(eval_res.missing_requirements)
    )
    s.add(e); s.commit()
    res = clean(e)
    res['missing_requirements'] = eval_res.missing_requirements
    return res

@app.post('/api/evidence/{qid}/link')
async def evidence_link(qid:int,value:str,s:Session=Depends(db),u:User=Depends(current_user)):
    if not re.match(r'^https?://',value): raise HTTPException(400,'Enter a valid http(s) link.')
    q=s.get(Quest,qid)
    if not q or s.get(Goal,q.goal_id).user_id!=u.id: raise HTTPException(404,'Quest not found')
    fetched_text = await safe_fetch_url(value)
    eval_res = await evaluate_evidence_with_ai(q.title, q.description or q.title, q.quest_type, 'link', f"URL: {value}\n{fetched_text}")
    e=Evidence(
        quest_id=qid,user_id=u.id,kind='link',value=value,
        evaluation=eval_res.feedback,
        quality=round(eval_res.quality * 100, 1),
        relevance=round(eval_res.relevance, 2),
        confidence=round(eval_res.confidence, 2),
        completeness=round(eval_res.completeness, 2),
        supports_quest=eval_res.supports_quest,
        feedback=eval_res.feedback,
        missing_requirements_json=json.dumps(eval_res.missing_requirements)
    )
    s.add(e); s.commit()
    res = clean(e)
    res['missing_requirements'] = eval_res.missing_requirements
    return res

@app.post('/api/evidence/{qid}/file')
async def evidence_file(qid:int,file:UploadFile=File(...),s:Session=Depends(db),u:User=Depends(current_user)):
    q=s.get(Quest,qid)
    if not q or s.get(Goal,q.goal_id).user_id!=u.id: raise HTTPException(404,'Quest not found')
    safe=re.sub(r'[^A-Za-z0-9_.-]','_',file.filename or 'evidence'); name=f'{u.id}_{qid}_{secrets.token_hex(4)}_{safe}'; path=UPLOAD_DIR/name
    data=await file.read()
    if len(data)>8*1024*1024: raise HTTPException(413,'Evidence file must be under 8 MB.')
    path.write_bytes(data)
    extracted_text = extract_text_from_file_data(data, safe)
    eval_res = await evaluate_evidence_with_ai(q.title, q.description or q.title, q.quest_type, 'file', extracted_text)
    e=Evidence(
        quest_id=qid,user_id=u.id,kind='file',value=f'/uploads/{name}',filename=safe,
        evaluation=eval_res.feedback,
        quality=round(eval_res.quality * 100, 1),
        relevance=round(eval_res.relevance, 2),
        confidence=round(eval_res.confidence, 2),
        completeness=round(eval_res.completeness, 2),
        supports_quest=eval_res.supports_quest,
        feedback=eval_res.feedback,
        missing_requirements_json=json.dumps(eval_res.missing_requirements)
    )
    s.add(e); s.commit()
    res = clean(e)
    res['missing_requirements'] = eval_res.missing_requirements
    return res

class EvaluateEvidenceIn(BaseModel):
    evidence_id: Optional[int] = None
    kind: Optional[str] = None
    value: Optional[str] = None

@app.post('/api/evidence/{qid}/evaluate')
async def evaluate_evidence_endpoint(qid: int, x: Optional[EvaluateEvidenceIn] = None, s: Session=Depends(db), u: User=Depends(current_user)):
    q = s.get(Quest, qid)
    if not q or s.get(Goal, q.goal_id).user_id != u.id:
        raise HTTPException(404, 'Quest not found')
    
    target_ev = None
    if x and x.evidence_id:
        target_ev = s.query(Evidence).filter_by(id=x.evidence_id, user_id=u.id, quest_id=qid).first()
    elif not x or not x.value:
        target_ev = s.query(Evidence).filter_by(quest_id=qid, user_id=u.id).order_by(Evidence.id.desc()).first()
    
    if target_ev:
        kind = target_ev.kind
        val = target_ev.value
    elif x and x.value:
        kind = x.kind or 'text'
        val = x.value
    else:
        raise HTTPException(400, 'No evidence provided to evaluate')
        
    eval_res = await evaluate_evidence_with_ai(q.title, q.description or q.title, q.quest_type, kind, val)
    if target_ev:
        target_ev.quality = round(eval_res.quality * 100, 1)
        target_ev.relevance = round(eval_res.relevance, 2)
        target_ev.confidence = round(eval_res.confidence, 2)
        target_ev.completeness = round(eval_res.completeness, 2)
        target_ev.supports_quest = eval_res.supports_quest
        target_ev.feedback = eval_res.feedback
        target_ev.missing_requirements_json = json.dumps(eval_res.missing_requirements)
        s.commit()
        
    return {
        "relevant": eval_res.relevant,
        "quality": eval_res.quality,
        "confidence": eval_res.confidence,
        "completeness": eval_res.completeness,
        "feedback": eval_res.feedback,
        "missing_requirements": eval_res.missing_requirements,
        "supports_quest": eval_res.supports_quest
    }

@app.post('/api/evidence/{qid}/github-commit')
async def evidence_github_commit(qid: int, commit_data: Dict[str, Any], s: Session=Depends(db), u: User=Depends(current_user)):
    q = s.get(Quest, qid)
    if not q or s.get(Goal, q.goal_id).user_id != u.id:
        raise HTTPException(404, 'Quest not found')
    repo = commit_data.get('repository', 'repo')
    title = commit_data.get('title', '')
    desc = commit_data.get('description', '')
    sha = commit_data.get('sha', '')
    url = commit_data.get('url') or (f"https://github.com/{repo}/commit/{sha}" if sha else "")

    # Prevent duplicate evidence for the same commit
    existing_ev = s.query(Evidence).filter_by(quest_id=qid, user_id=u.id, kind='github').all()
    for ev in existing_ev:
        if (sha and ev.filename == sha) or (url and url in (ev.value or '')):
            res = clean(ev)
            try:
                res['missing_requirements'] = json.loads(ev.missing_requirements_json) if ev.missing_requirements_json else []
            except Exception:
                res['missing_requirements'] = []
            res['earned_xp'] = 0
            res['earned_coins'] = 0
            res['quest_completed'] = (q.status == 'completed')
            res['total_xp'] = u.xp
            res['level'] = u.level
            return res

    combined_text = f"GitHub Commit: {title}\nRepo: {repo}\nDescription: {desc}\nURL: {url}"
    eval_res = await evaluate_evidence_with_ai(q.title, q.description or q.title, q.quest_type, 'github', combined_text)
    e = Evidence(
        quest_id=qid,
        user_id=u.id,
        kind='github',
        value=f"{repo}: {title} ({url})" if url else f"{repo}: {title}",
        filename=sha or commit_data.get('id', ''),
        evaluation=f"Verified GitHub commit from {repo} (SHA: {sha[:8] if sha else 'HEAD'}). {eval_res.feedback}",
        quality=max(80.0, round(eval_res.quality * 100, 1)),
        relevance=max(0.85, round(eval_res.relevance, 2)),
        confidence=max(0.9, round(eval_res.confidence, 2)),
        completeness=max(0.85, round(eval_res.completeness, 2)),
        supports_quest=eval_res.supports_quest,
        feedback=eval_res.feedback,
        missing_requirements_json=json.dumps(eval_res.missing_requirements)
    )
    s.add(e)

    # Link UnifiedActivityRecord if present
    cid = sha or commit_data.get('id', '')
    if cid:
        uar = s.query(UnifiedActivityRecord).filter(
            UnifiedActivityRecord.user_id == u.id,
            UnifiedActivityRecord.external_id.in_([cid, commit_data.get('id', ''), sha])
        ).first()
        if uar:
            uar.matched_quest_id = qid

    earned_xp = 0
    earned_coins = 0
    quest_completed = False
    next_quest_info = None

    if q.status in ('available', 'in_progress'):
        if not q.assessment_required:
            prog_res = complete_quest_progression(
                s, u, q,
                score=0.88,
                feedback=f"Completed with verified GitHub commit '{title}' in repository {repo}."
            )
            earned_xp = prog_res.get('earned_xp', 0)
            earned_coins = prog_res.get('earned_coins', 0)
            quest_completed = True
            next_quest_info = prog_res.get('next_quest')
            notify(s, u, 'Quest Cleared via GitHub', f"'{q.title}' completed via attached GitHub commit! +{earned_xp} XP, +{earned_coins} coins.", 'quest')
        else:
            if q.status == 'available':
                q.status = 'in_progress'
            earned_xp = max(40, round(q.xp * 0.6))
            earned_coins = max(10, round(q.coin_reward * 0.6))
            add_xp(u, earned_xp)
            u.coins += earned_coins
            notify(s, u, 'GitHub Evidence Verified', f"Verified commit attached to {q.title}! +{earned_xp} XP, +{earned_coins} coins awarded.", 'evidence')

    s.commit()
    res = clean(e)
    res['missing_requirements'] = eval_res.missing_requirements
    res['earned_xp'] = earned_xp
    res['earned_coins'] = earned_coins
    res['quest_completed'] = quest_completed
    res['next_quest'] = next_quest_info
    res['total_xp'] = u.xp
    res['level'] = u.level
    return res

@app.get('/api/evidence/{qid}')
def evidence(qid:int,s:Session=Depends(db),u:User=Depends(current_user)):
    rows = s.query(Evidence).filter_by(quest_id=qid,user_id=u.id).order_by(Evidence.id.desc()).all()
    out = []
    for x in rows:
        d = clean(x)
        try:
            d['missing_requirements'] = json.loads(x.missing_requirements_json) if x.missing_requirements_json else []
        except Exception:
            d['missing_requirements'] = []
        out.append(d)
    return out

# ---------- Skills & Trees ----------
@app.get('/api/skill-tree')
def skill_tree(s:Session=Depends(db),u:User=Depends(current_user)):
    skills=s.query(Skill).filter_by(user_id=u.id).all(); lookup={x.name:x for x in skills}
    branches=[
        ('Core',['DSA','Python','Discipline','Focus']),
        ('Career',['Coding','Projects','Communication']),
        ('Life',['Fitness','Finance','Relationships']),
        ('Learning',['Academics'])
    ]
    topic_skills=s.query(TopicSkill).filter_by(user_id=u.id).all()
    topic_map={}
    for ts in topic_skills:
        topic_map.setdefault(ts.subject,[]).append({
            'topic': ts.topic,
            'mastery': ts.mastery,
            'confidence': ts.confidence,
            'attempts': ts.attempts,
            'last_score': ts.last_score
        })
        
    out=[]
    for branch,names in branches:
        nodes=[]
        for i,n in enumerate(names):
            x=lookup.get(n); val=round(x.progress) if x else 0; unlocked=bool(x and x.unlocked) or (i==0 and branch in ('Core','Career','Life','Learning'))
            nodes.append({
                'name':n,
                'progress':val,
                'level':x.level if x else 1,
                'confidence':x.confidence if x else 0.5,
                'unlocked':unlocked,
                'prerequisites':x.prerequisites if x else 'Complete a related quest to unlock.',
                'description':x.description if x else f'Build {n} through real-world quests.',
                'topics': topic_map.get(n, [])
            })
        out.append({'branch':branch,'nodes':nodes})
    return out

# ---------- Avatar & Shop ----------
SHOP=[('Neon Aura','cosmetic',120),('Knight Helm','equipment',180),('Mage Cloak','equipment',220),('Golden Title','title',300),('XP Booster','boost',350),('Phoenix Frame','cosmetic',500)]

@app.get('/api/avatar')
def avatar(s:Session=Depends(db),u:User=Depends(current_user)):
    inv=s.query(Inventory).filter_by(user_id=u.id).all(); return {'user':{'avatar':u.avatar,'title':u.title,'level':u.level},'stats':{'strength':min(100,10+u.xp//80),'intelligence':min(100,10+u.xp//70),'discipline':min(100,10+u.streak*3),'creativity':min(100,10+u.xp//100),'social':min(100,10+len(s.query(Friend).filter_by(user_id=u.id).all())*8)},'inventory':[clean(x) for x in inv]}

@app.post('/api/avatar')
def set_avatar(a:AvatarIn,s:Session=Depends(db),u:User=Depends(current_user)): u.avatar=a.avatar; u.title=a.title or u.title; s.commit(); return {'avatar':u.avatar,'title':u.title}

@app.get('/api/shop')
def shop(s:Session=Depends(db),u:User=Depends(current_user)):
    owned={x.item for x in s.query(Inventory).filter_by(user_id=u.id).all()}; return [{'item':i,'kind':k,'cost':c,'owned':i in owned} for i,k,c in SHOP]

@app.post('/api/shop/buy')
def buy(x:ShopIn,s:Session=Depends(db),u:User=Depends(current_user)):
    item=next((z for z in SHOP if z[0]==x.item),None)
    if not item: raise HTTPException(404,'Item not found')
    if s.query(Inventory).filter_by(user_id=u.id,item=x.item).first(): return {'ok':True,'coins':u.coins}
    if u.coins<item[2]: raise HTTPException(400,'Not enough Life Coins')
    u.coins-=item[2]; s.add(Inventory(user_id=u.id,item=item[0],kind=item[1],cost=item[2])); s.commit(); return {'ok':True,'coins':u.coins}

# ---------- Daily Missions, Analytics & Game Master ----------
def missions_for(s,u):
    today=date.today().isoformat(); rows=s.query(Mission).filter_by(user_id=u.id,day=today).all()
    if rows:return rows
    skill=s.query(Skill).filter_by(user_id=u.id).order_by(Skill.progress).first(); name=skill.name if skill else 'your priority skill'; cat=skill.category if skill else 'Personal'
    defaults=[('Main Quest',f'Complete one focused quest for {name}.','daily',60,18),('Skill Quest',f'Practice {name} for 15 focused minutes.','skill',45,12),('Mind Quest','Write one honest reflection about today.','reflection',30,10)]
    for t,d,typ,x,c in defaults:s.add(Mission(user_id=u.id,title=t,description=d,mission_type=typ,xp=x,coins=c,day=today,category=cat))
    s.commit(); return s.query(Mission).filter_by(user_id=u.id,day=today).all()

def achievement_rows(s,u):
    quests=s.query(Quest).join(Goal).filter(Goal.user_id==u.id).all(); completed=[q for q in quests if q.status=='completed']; bosses=[q for q in completed if q.is_boss]; skills=s.query(Skill).filter_by(user_id=u.id).all(); missions=s.query(Mission).filter_by(user_id=u.id,status='completed').count(); defs=[('first','First Quest','Complete your first quest',len(completed)>=1,'⚔️'),('xp','Rising Hero','Earn 500 XP',u.xp>=500,'⭐'),('streak','7 Day Warrior','Reach a 7-day streak',u.streak>=7,'🔥'),('boss','Boss Slayer','Defeat a boss',len(bosses)>=1,'👑'),('skill','Skill Builder','Reach 75% mastery',any(x.progress>=75 for x in skills),'🧠'),('level','Level 10','Reach level 10',u.level>=10,'🚀'),('daily','Daily Grinder','Complete 10 missions',missions>=10,'📅'),('wealth','Coin Collector','Earn 500 coins',u.coins>=500,'🪙')]; return [{'id':i,'title':t,'description':d,'unlocked':ok,'icon':ic} for i,t,d,ok,ic in defs]

@app.get('/api/missions')
def missions(s:Session=Depends(db),u:User=Depends(current_user)): return [clean(x) for x in missions_for(s,u)]

@app.post('/api/missions/complete')
def mission_complete(x:MissionIn,s:Session=Depends(db),u:User=Depends(current_user)):
    m=s.get(Mission,x.mission_id)
    if not m or m.user_id!=u.id: raise HTTPException(404,'Mission not found')
    if m.status=='completed': return {'ok':True,'xp':0,'coins':0}
    m.status='completed'; add_xp(u,m.xp); u.coins+=m.coins; touch(u); s.commit(); return {'ok':True,'xp':m.xp,'coins':m.coins,'level':u.level}

@app.get('/api/achievements')
def achievements(s:Session=Depends(db),u:User=Depends(current_user)): return achievement_rows(s,u)

@app.get('/api/analytics')
def analytics(s:Session=Depends(db),u:User=Depends(current_user)):
    goals_=s.query(Goal).filter_by(user_id=u.id).all(); quests=s.query(Quest).join(Goal).filter(Goal.user_id==u.id).all(); assessments=s.query(Assessment).filter_by(user_id=u.id).all(); skills=s.query(Skill).filter_by(user_id=u.id).all(); bycat={}
    for q in quests: bycat.setdefault(q.category,[0,0]); bycat[q.category][0]+=1; bycat[q.category][1]+=q.status=='completed'
    return {'xp':u.xp,'level':u.level,'coins':u.coins,'streak':u.streak,'completion_rate':round(sum(q.status=='completed' for q in quests)/len(quests)*100) if quests else 0,'average_score':round(sum(a.score for a in assessments)/len(assessments)*100) if assessments else 0,'goals':len(goals_),'skills':[{'name':x.name,'progress':round(x.progress),'xp':x.xp,'level':x.level} for x in skills],'categories':[{'name':k,'completion':round(v[1]/v[0]*100)} for k,v in bycat.items()],'weekly_xp':sum(a.score*100 for a in assessments if a.created_at>=datetime.utcnow()-timedelta(days=7)),'weekly_quests':sum(a.created_at>=datetime.utcnow()-timedelta(days=7) for a in assessments),'focus_minutes':sum(q.estimated_minutes for q in quests if q.status=='completed')}

@app.get('/api/recap')
def recap(s:Session=Depends(db),u:User=Depends(current_user)):
    since=datetime.utcnow()-timedelta(days=1); rows=s.query(Assessment).filter(Assessment.user_id==u.id,Assessment.created_at>=since).all(); titles=[]
    for a in rows:
        q=s.get(Quest,a.quest_id); titles.append(q.title if q else 'Quest')
    weakest=s.query(Skill).filter_by(user_id=u.id).order_by(Skill.progress).first(); name=weakest.name if weakest else 'your priority skill'
    return {'date':date.today().isoformat(),'quests_completed':len(rows),'xp_earned':round(sum(a.score*100 for a in rows)),'average_score':round(sum(a.score for a in rows)/len(rows)*100) if rows else 0,'streak':u.streak,'next_priority':f'Give extra attention to {name}.','completed_titles':titles,'game_master':f'You moved forward today. Your next priority is {name}.'}

@app.get('/api/weekly-review')
def weekly_review(s:Session=Depends(db),u:User=Depends(current_user)):
    since=datetime.utcnow()-timedelta(days=7); a=s.query(Assessment).filter(Assessment.user_id==u.id,Assessment.created_at>=since).all(); quests=len(a); avg=round(sum(x.score for x in a)/quests*100) if quests else 0; skills=s.query(Skill).filter_by(user_id=u.id).order_by(Skill.progress.desc()).all(); strongest=skills[0].name if skills else 'your first skill'; weakest=skills[-1].name if skills else 'a new skill'; return {'xp':round(sum(x.score*100 for x in a)),'quests':quests,'average':avg,'streak':u.streak,'strongest':strongest,'weakest':weakest,'game_master':f'Your strongest momentum is {strongest}. Give {weakest} extra attention next week.','next_week':f'Choose one focused quest for {weakest} and protect your daily rhythm.'}

@app.post('/api/journal')
def journal(x:JournalIn,s:Session=Depends(db),u:User=Depends(current_user)):
    insight=f'You identified a concrete lesson. Use “{x.next_step[:80]}” as your next action.' if x.next_step else 'Keep the reflection specific and actionable.'; j=Journal(user_id=u.id,quest_id=x.quest_id,learned=x.learned,difficult=x.difficult,next_step=x.next_step,ai_insight=insight); s.add(j); s.commit(); return clean(j)

@app.get('/api/journal')
def journal_list(s:Session=Depends(db),u:User=Depends(current_user)): return [clean(x) for x in s.query(Journal).filter_by(user_id=u.id).order_by(Journal.id.desc()).limit(20).all()]

@app.get('/api/game-master')
async def game_master(s:Session=Depends(db),u:User=Depends(current_user)):
    skills=s.query(Skill).filter_by(user_id=u.id).order_by(Skill.progress).all()
    weakest_skill = skills[0].name if skills else 'Foundations'
    
    # Check topic skills
    weak_topic_obj = s.query(TopicSkill).filter_by(user_id=u.id).order_by(TopicSkill.mastery.asc()).first()
    strong_topic_obj = s.query(TopicSkill).filter_by(user_id=u.id).order_by(TopicSkill.mastery.desc()).first()
    
    # Check recent quiz
    recent_quiz = s.query(Quiz).filter_by(user_id=u.id, status='completed').order_by(Quiz.id.desc()).first()
    active_quest = s.query(Quest).join(Goal).filter(Goal.user_id==u.id,Quest.status.in_(['available','in_progress'])).order_by(Quest.order_index).first()
    recent_assessments = s.query(Assessment).filter_by(user_id=u.id).order_by(Assessment.id.desc()).limit(5).all()
    avg_score = round(sum(a.score for a in recent_assessments)/len(recent_assessments)*100) if recent_assessments else 0
    
    # Specific contextual guidance
    if active_quest and active_quest.quest_type == 'reinforcement':
        headline = f"Reinforcement Focus: {active_quest.topic}"
        msg = f"Your recent assessment in {active_quest.topic} exposed a weak spot in {active_quest.subtopic or 'key concepts'}. Complete this focused drill to strengthen your mastery before advancing."
        tone = "Tactical Mastery"
    elif recent_quiz and recent_quiz.percentage < 60:
        headline = f"Reviewing {recent_quiz.topic}"
        weak_str = ', '.join(json.loads(recent_quiz.weak_areas)) if recent_quiz.weak_areas else recent_quiz.topic
        msg = f"Your last {recent_quiz.subject} assessment showed room for improvement in {weak_str}. The adaptive engine has tailored your next challenge accordingly."
        tone = "Adaptive Coaching"
    elif strong_topic_obj and strong_topic_obj.mastery >= 75:
        headline = f"Strong Momentum in {strong_topic_obj.topic}"
        msg = f"You are demonstrating solid command of {strong_topic_obj.topic} ({int(strong_topic_obj.mastery)}% mastery). Push ahead to the upcoming Boss battle!"
        tone = "High Momentum"
    else:
        headline = f"Next move: {active_quest.title if active_quest else 'a new campaign'}"
        msg = f"Focus on {weakest_skill}. Recent average is {avg_score}%. Every quest assessment adapts the campaign to your actual performance."
        tone = "Adventure Mode"
        
    fallback = {
        'tone': tone,
        'headline': headline,
        'message': msg,
        'next_action': active_quest.title if active_quest else 'Create your first campaign',
        'recent_score': avg_score
    }
    
    if os.getenv('OPENAI_API_KEY'):
        prompt = f"Act as an RPG Game Master. User level {u.level}, streak {u.streak}, weakest skill {weakest_skill}, weak topic {weak_topic_obj.topic if weak_topic_obj else 'None'}, recent assessment score {avg_score}%, active quest {active_quest.title if active_quest else 'None'}. Return JSON with tone, headline, message, next_action, recent_score."
        return await ai_json(prompt, fallback)
    return fallback

@app.get('/api/social')
def social(s:Session=Depends(db),u:User=Depends(current_user)):
    friends=s.query(Friend).filter_by(user_id=u.id).all(); ch=s.query(Challenge).filter_by(user_id=u.id).first()
    if not friends:
        for n,l,x in [('Aarav',18,7420),('Maya',15,6100),('Rohan',12,4860)]: s.add(Friend(user_id=u.id,name=n,level=l,xp=x)); s.commit(); friends=s.query(Friend).filter_by(user_id=u.id).all()
    board=sorted([{'name':u.name,'level':u.level,'xp':u.xp,'you':True}]+[{'name':f.name,'level':f.level,'xp':f.xp,'you':False} for f in friends],key=lambda x:x['xp'],reverse=True); return {'friends':[clean(f) for f in friends],'challenge':clean(ch) if ch else None,'leaderboard':board}

@app.post('/api/social/friends')
def add_friend(x:FriendIn,s:Session=Depends(db),u:User=Depends(current_user)): f=Friend(user_id=u.id,name=x.name.strip() or 'Friend'); s.add(f); s.commit(); return clean(f)

def clean_integration(i: Integration):
    data = clean(i)
    data.pop('access_token_enc', None)
    data.pop('refresh_token_enc', None)
    prov = get_provider(i.provider)
    data['is_configured'] = prov.is_configured() if prov else False
    err_low = (getattr(i, 'error_message', '') or '').lower()
    is_auth_error = 'expired or revoked' in err_low or 'bad credentials' in err_low
    if getattr(i, 'status', '') == 'reauth_required' or is_auth_error:
        data['connected'] = False
        data['status'] = 'reauth_required'
        data['is_live'] = False
    else:
        data['connected'] = bool(getattr(i, 'connected', False))
        data['status'] = getattr(i, 'status', 'disconnected') or ('connected' if data['connected'] else 'disconnected')
        data['is_live'] = bool(getattr(i, 'is_live', False))
    data['account_name'] = getattr(i, 'account_name', '') or getattr(i, 'external_user_id', '')
    data['token_expiry'] = i.token_expiry.isoformat() if getattr(i, 'token_expiry', None) else None
    if 'metadata_json' in data and data['metadata_json']:
        try:
            data['metadata'] = json.loads(data['metadata_json'])
        except Exception:
            data['metadata'] = {}
    else:
        data['metadata'] = {}
    return data

@app.get('/api/integrations')
def list_integrations(s:Session=Depends(db),u:User=Depends(current_user)):
    seed_integrations(s,u)
    rows = s.query(Integration).filter_by(user_id=u.id).all()
    changed = False
    for x in rows:
        err_low = (x.error_message or '').lower()
        if ('expired or revoked' in err_low or 'bad credentials' in err_low) and (x.connected or x.status != 'reauth_required'):
            x.connected = False
            x.status = 'reauth_required'
            x.is_live = False
            x.access_token_enc = ''
            x.refresh_token_enc = ''
            changed = True
    if changed:
        s.commit()
    return [clean_integration(x) for x in rows]

@app.post('/api/integrations')
def set_integration(x:IntegrationIn,s:Session=Depends(db),u:User=Depends(current_user)):
    i=s.query(Integration).filter_by(user_id=u.id,provider=x.provider).first()
    if not i:
        i=Integration(user_id=u.id,provider=x.provider)
        s.add(i)
    i.connected=x.connected
    i.status='connected' if x.connected else 'disconnected'
    if not x.connected:
        i.access_token_enc=''
        i.refresh_token_enc=''
        i.is_live=False
        i.account_name=''
    i.updated_at=datetime.utcnow()
    s.commit()
    return clean_integration(i)

@app.get('/api/integrations/{provider}/auth-url')
def get_auth_url_endpoint(provider: str, redirect_uri: Optional[str] = None, state: Optional[str] = None, u: User=Depends(current_user)):
    prov = get_provider(provider)
    if not prov:
        raise HTTPException(404, f"Provider '{provider}' not supported.")
    # Environment-configured default redirect URI if none explicitly passed
    env_redirect = os.getenv(f"{prov.name.upper().replace(' ', '_')}_REDIRECT_URI")
    effective_redirect = redirect_uri or env_redirect or 'http://localhost:5173/integrations'
    # Whitelist redirect URIs to prevent open-redirect vulnerabilities
    allowed_hosts = ['localhost', '127.0.0.1']
    try:
        from urllib.parse import urlparse
        parsed = urlparse(effective_redirect)
        if parsed.hostname not in allowed_hosts and not parsed.hostname.endswith('.life-rpg.internal'):
            effective_redirect = 'http://localhost:5173/integrations'
    except Exception:
        effective_redirect = 'http://localhost:5173/integrations'

    prov_slug = prov.name.lower().replace(' ', '_')
    state_token = state or f"{u.id}_{prov_slug}_{secrets.token_hex(12)}"
    if not prov.is_configured():
        raise HTTPException(400, f"{prov.name} OAuth credentials are not configured on this server. Add {prov.name.upper().replace(' ', '_')}_CLIENT_ID and _CLIENT_SECRET to your backend .env file.")
    try:
        auth_url = prov.get_auth_url(effective_redirect, state_token)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "provider": prov.name,
        "auth_url": auth_url,
        "state": state_token,
        "is_configured": True
    }


@app.get('/api/integrations/oauth-demo')
def oauth_demo_endpoint(provider: str = 'GitHub', state: str = '', redirect_uri: str = 'http://localhost:5173/integrations'):
    from fastapi.responses import RedirectResponse
    prov_slug = provider.lower().replace(' ', '_')
    code = f"demo_{prov_slug}_token"
    delim = '&' if '?' in redirect_uri else '?'
    target = f"{redirect_uri}{delim}code={code}&state={state}&provider={provider}"
    return RedirectResponse(url=target, status_code=307)


class CallbackIn(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = None

@app.post('/api/integrations/{provider}/callback')
async def oauth_callback_endpoint(provider: str, x: CallbackIn, s: Session=Depends(db), u: User=Depends(current_user)):
    prov = get_provider(provider)
    if not prov:
        raise HTTPException(404, f"Provider '{provider}' not supported.")
    
    prov_slug = prov.name.lower().replace(' ', '_')
    # State ownership & provider match check
    if x.state:
        if not x.state.startswith(f"{u.id}_"):
            raise HTTPException(403, "Invalid OAuth state parameter. Request rejected.")
        # Reject cross-provider state tampering if state specifically contains another known provider's tag
        known_other_slugs = {
            'github': 'GitHub',
            'google_calendar': 'Google Calendar',
            'googlecalendar': 'Google Calendar',
            'outlook_calendar': 'Outlook Calendar',
            'outlookcalendar': 'Outlook Calendar'
        }
        current_clean = prov.name.lower().replace(' ', '').replace('_', '')
        for other_slug, other_name in known_other_slugs.items():
            other_clean = other_name.lower().replace(' ', '').replace('_', '')
            if other_clean != current_clean:
                if f"_{other_slug}_" in f"_{x.state}_" or f"_{other_clean}_" in f"_{x.state}_":
                    raise HTTPException(403, f"OAuth state parameter does not match provider '{prov.name}'.")
        
    env_redirect = os.getenv(f"{prov.name.upper().replace(' ', '_')}_REDIRECT_URI")
    effective_redirect = x.redirect_uri or env_redirect or 'http://localhost:5173/integrations'
    try:
        data = await prov.exchange_code(x.code, effective_redirect)
    except Exception as exc:
        raise HTTPException(400, f"OAuth token exchange failed: {str(exc)}")
        
    it = s.query(Integration).filter_by(user_id=u.id, provider=prov.name).first()
    if not it:
        it = Integration(user_id=u.id, provider=prov.name)
        s.add(it)
    it.connected = True
    it.status = 'connected'
    it.connected_at = datetime.utcnow()
    it.external_user_id = data.get('external_user_id', '')
    it.scopes = data.get('scopes', '')
    it.is_live = bool(data.get('is_live', False))
    it.account_name = data.get('account_name', '')
    if 'expires_in' in data and data['expires_in']:
        it.token_expiry = datetime.utcnow() + timedelta(seconds=int(data['expires_in']))
    if 'access_token' in data:
        it.access_token_enc = encrypt_token(data['access_token'])
    if 'refresh_token' in data and data['refresh_token']:
        it.refresh_token_enc = encrypt_token(data['refresh_token'])
    it.error_message = ''
    it.sync_status = 'idle'
    it.updated_at = datetime.utcnow()
    
    # Run initial sync automatically with deduplication
    try:
        token = data.get('access_token', '')
        sync_data = await prov.sync(token)
        it.last_sync_at = datetime.utcnow()
        it.sync_status = 'synced'
        it.metadata_json = json.dumps(sync_data)
        
        # Save activities to unified activity layer with deduplication & evidence linking
        if prov.name == 'GitHub':
            process_github_activity_sync(s, u, sync_data)
        else:
            active_quests = [clean(q) for q in s.query(Quest).join(Goal).filter(Goal.user_id==u.id, Quest.status.in_(['available','in_progress'])).all()]
            for item in sync_data.get('items', []) + sync_data.get('events', []):
                norm = normalize_activity(prov.name, item)
                existing = s.query(UnifiedActivityRecord).filter_by(user_id=u.id, external_id=norm.external_id).first() if norm.external_id else None
                if not existing:
                    matched = match_activity_to_quests(norm, active_quests)
                    rec = UnifiedActivityRecord(
                        user_id=u.id,
                        provider=prov.name,
                        activity_type=norm.activity_type,
                        title=norm.title,
                        description=norm.description,
                        external_id=norm.external_id or '',
                        timestamp=norm.timestamp,
                        metadata_json=json.dumps(norm.metadata),
                        matched_quest_id=matched['id'] if matched else None
                    )
                    s.add(rec)
    except Exception as e:
        safe_msg = re.sub(r'gh[opurs]_[A-Za-z0-9_]+', '[REDACTED]', str(e))
        safe_msg = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]+', 'Bearer [REDACTED]', safe_msg)
        it.sync_status = 'failed'
        it.error_message = safe_msg
        if "expired or revoked" in safe_msg.lower() or "401" in safe_msg:
            it.connected = False
            it.status = 'reauth_required'
            it.is_live = False
            it.access_token_enc = ''
            it.refresh_token_enc = ''
        
    s.commit()
    mode_label = "Live" if it.is_live else "Demo Simulation"
    notify(s, u, f"{prov.name} Connected ({mode_label})", f"Successfully linked your {prov.name} account to LIFE RPG.", "integration")
    return clean_integration(it)

@app.post('/api/integrations/{provider}/sync')
async def sync_integration_endpoint(provider: str, s: Session=Depends(db), u: User=Depends(current_user)):
    prov = get_provider(provider)
    if not prov:
        raise HTTPException(404, f"Provider '{provider}' not supported.")
    it = s.query(Integration).filter_by(user_id=u.id, provider=prov.name).first()
    if not it or not it.connected:
        raise HTTPException(400, f"{provider} is not connected.")
    if it.status == 'reauth_required':
        raise HTTPException(400, f"{provider} token is expired or revoked. Please reconnect via OAuth.")
        
    token = decrypt_token(it.access_token_enc) if it.access_token_enc else ""
    refresh_token = decrypt_token(it.refresh_token_enc) if it.refresh_token_enc else ""
    
    # Check if token refresh is supported and needed
    if refresh_token:
        try:
            refreshed = await prov.refresh_token_if_needed(refresh_token)
            if refreshed and 'access_token' in refreshed:
                token = refreshed['access_token']
                it.access_token_enc = encrypt_token(token)
                if 'expires_in' in refreshed and refreshed['expires_in']:
                    it.token_expiry = datetime.utcnow() + timedelta(seconds=int(refreshed['expires_in']))
                if 'refresh_token' in refreshed and refreshed['refresh_token']:
                    it.refresh_token_enc = encrypt_token(refreshed['refresh_token'])
        except Exception:
            pass

    try:
        sync_result = await prov.sync(token)
        it.last_sync_at = datetime.utcnow()
        it.sync_status = 'synced'
        it.status = 'connected'
        it.connected = True
        it.error_message = ''
        it.metadata_json = json.dumps(sync_result)
        it.updated_at = datetime.utcnow()
        
        # Ingest into Unified Activity Layer & Quest Evidence
        sync_stats = {}
        if prov.name == 'GitHub':
            sync_stats = process_github_activity_sync(s, u, sync_result)
        else:
            active_quests = [clean(q) for q in s.query(Quest).join(Goal).filter(Goal.user_id==u.id, Quest.status.in_(['available','in_progress'])).all()]
            raw_items = sync_result.get('items', []) + sync_result.get('events', [])
            for item in raw_items:
                norm = normalize_activity(prov.name, item)
                existing = s.query(UnifiedActivityRecord).filter_by(user_id=u.id, external_id=norm.external_id).first() if norm.external_id else None
                if not existing:
                    matched = match_activity_to_quests(norm, active_quests)
                    rec = UnifiedActivityRecord(
                        user_id=u.id,
                        provider=prov.name,
                        activity_type=norm.activity_type,
                        title=norm.title,
                        description=norm.description,
                        external_id=norm.external_id or '',
                        timestamp=norm.timestamp,
                        metadata_json=json.dumps(norm.metadata),
                        matched_quest_id=matched['id'] if matched else None
                    )
                    s.add(rec)
                
        s.commit()
        return {
            "provider": prov.name,
            "status": "synced",
            "is_live": it.is_live,
            "last_sync_at": it.last_sync_at.isoformat() if it.last_sync_at else None,
            "data": sync_result,
            "sync_stats": sync_stats,
            "user": clean(u),
            "total_xp": u.xp,
            "level": u.level,
            "coins": u.coins
        }
    except Exception as exc:
        raw_msg = str(exc)
        safe_msg = re.sub(r'gh[opurs]_[A-Za-z0-9_]+', '[REDACTED]', raw_msg)
        safe_msg = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]+', 'Bearer [REDACTED]', safe_msg)
        it.sync_status = 'failed'
        it.error_message = safe_msg
        it.updated_at = datetime.utcnow()
        
        is_auth_error = (
            "expired or revoked" in safe_msg.lower() or
            "401" in safe_msg or
            "unauthorized" in safe_msg.lower() or
            "bad credentials" in safe_msg.lower() or
            "missing or invalid" in safe_msg.lower()
        )
        if is_auth_error:
            it.connected = False
            it.status = 'reauth_required'
            it.is_live = False
            it.access_token_enc = ''
            it.refresh_token_enc = ''
            
        s.commit()
        raise HTTPException(502, f"Sync error: {safe_msg}")

@app.post('/api/integrations/{provider}/disconnect')
async def disconnect_integration_endpoint(provider: str, s: Session=Depends(db), u: User=Depends(current_user)):
    prov = get_provider(provider)
    prov_name = prov.name if prov else provider
    it = s.query(Integration).filter_by(user_id=u.id, provider=prov_name).first()
    if not it:
        raise HTTPException(404, f"Integration '{provider}' not found.")
        
    token = decrypt_token(it.access_token_enc) if it.access_token_enc else ""
    if prov and token:
        try:
            await prov.revoke_token(token)
        except Exception:
            pass
            
    it.connected = False
    it.status = 'disconnected'
    it.is_live = False
    it.account_name = ''
    it.access_token_enc = ''
    it.refresh_token_enc = ''
    it.token_expiry = None
    it.sync_status = 'idle'
    it.metadata_json = '{}'
    it.updated_at = datetime.utcnow()
    s.commit()
    notify(s, u, f"{prov_name} Disconnected", f"Disconnected {prov_name} from your profile.", "integration")
    return clean_integration(it)

@app.get('/api/integrations/calendar/deadlines')
def get_calendar_deadlines(s: Session=Depends(db), u: User=Depends(current_user)):
    deadlines = []
    for prov_name in ['Google Calendar', 'Outlook Calendar']:
        it = s.query(Integration).filter_by(user_id=u.id, provider=prov_name, connected=True).first()
        if it and it.metadata_json:
            try:
                meta = json.loads(it.metadata_json)
                for dl in meta.get('deadlines', []):
                    dl['provider'] = prov_name
                    deadlines.append(dl)
            except Exception:
                pass
    return deadlines

@app.get('/api/integrations/github/activity')
def get_github_activity(s: Session=Depends(db), u: User=Depends(current_user)):
    it = s.query(Integration).filter_by(user_id=u.id, provider='GitHub', connected=True).first()
    if not it or not it.metadata_json:
        return {"connected": bool(it and it.connected), "items": [], "summary": "No GitHub activity recorded."}
    try:
        meta = json.loads(it.metadata_json)
        return {
            "connected": True,
            "is_live": it.is_live,
            "account_name": it.account_name,
            "items": meta.get("items", []),
            "summary": meta.get("summary", ""),
            "last_active_repo": meta.get("last_active_repo")
        }
    except Exception:
        return {"connected": True, "items": [], "summary": "Error loading activity."}

@app.get('/api/integrations/activities')
def get_unified_activities(s: Session=Depends(db), u: User=Depends(current_user)):
    records = s.query(UnifiedActivityRecord).filter_by(user_id=u.id).order_by(UnifiedActivityRecord.id.desc()).limit(50).all()
    out = []
    for r in records:
        d = clean(r)
        try:
            d['metadata'] = json.loads(r.metadata_json) if r.metadata_json else {}
        except Exception:
            d['metadata'] = {}
        out.append(d)
    return out

@app.get('/api/integrations/fitness/bridge-token')
def get_health_connect_bridge_token(u: User=Depends(current_user)):
    """Generates pairing token for the Android Health Connect companion bridge."""
    return {
        "user_id": u.id,
        "token": token_for(u.id),
        "server_url": "http://localhost:8000",
        "device_pair_code": f"RPG-{u.id}-{secrets.token_hex(3).upper()}",
        "instructions": "Enter this pairing token in the LIFE RPG Android Health Connect Bridge to securely stream activity summaries."
    }

@app.post('/api/integrations/fitness/health-connect/sync')
async def sync_health_connect_batch(batch: HealthConnectSyncBatch, s: Session=Depends(db), u: User=Depends(current_user)):
    """
    Ingests exercise sessions and daily steps from the Android Health Connect companion bridge.
    Normalizes activities, validates against active quests, and awards verified rewards.
    """
    prov = get_provider('Fitness')
    result = await prov.process_health_connect_batch(batch) # type: ignore
    
    # Save Unified Activity records and match quests with deduplication
    active_quests = [clean(q) for q in s.query(Quest).join(Goal).filter(Goal.user_id==u.id, Quest.status.in_(['available','in_progress'])).all()]
    matched_quests_updated = []
    new_sessions = []
    new_xp = 0
    new_coins = 0
    
    for session in result['sessions']:
        norm = normalize_activity("Health Connect", session)
        existing = s.query(UnifiedActivityRecord).filter_by(user_id=u.id, external_id=norm.external_id).first() if norm.external_id else None
        if existing:
            continue
        new_sessions.append(session)
        new_xp += session.get('earned_xp', 0)
        new_coins += session.get('earned_coins', 0)
        matched = match_activity_to_quests(norm, active_quests)
        matched_id = matched['id'] if matched else None
        
        rec = UnifiedActivityRecord(
            user_id=u.id,
            provider="Health Connect",
            activity_type="fitness_activity",
            title=norm.title,
            description=norm.description,
            external_id=norm.external_id or '',
            timestamp=norm.timestamp,
            metadata_json=json.dumps(norm.metadata),
            matched_quest_id=matched_id
        )
        s.add(rec)
        
        # If a matching quest was found, add Evidence
        if matched:
            q_obj = s.get(Quest, matched_id)
            if q_obj:
                e = Evidence(
                    quest_id=q_obj.id,
                    user_id=u.id,
                    kind='fitness',
                    value=session['summary'],
                    evaluation=f"Android Health Connect verified {session['duration_minutes']}m {session['exercise_type']}.",
                    quality=88.0,
                    relevance=0.95,
                    confidence=0.92,
                    completeness=0.9,
                    supports_quest=True,
                    feedback=f"Health Connect recorded: {session['summary']} toward {q_obj.title}."
                )
                s.add(e)
                matched_quests_updated.append(q_obj.title)

    awarded_xp = min(300, new_xp)
    awarded_coins = min(100, new_coins)
    old_lvl, new_lvl = add_xp(u, awarded_xp)
    u.coins += awarded_coins
    touch(u)
    
    # Update Fitness integration status
    it = s.query(Integration).filter_by(user_id=u.id, provider='Fitness').first()
    if not it:
        it = Integration(user_id=u.id, provider='Fitness')
        s.add(it)
    it.connected = True
    it.status = 'connected'
    it.is_live = True
    it.last_sync_at = datetime.utcnow()
    it.metadata_json = json.dumps({"latest_batch": result, "summary": result['summary']})
    
    notify(s, u, 'Health Connect Sync Complete', result['summary'], 'fitness')
    s.commit()
    
    return {
        "ok": True,
        "result": result,
        "matched_quests": matched_quests_updated,
        "earned_xp": awarded_xp,
        "earned_coins": awarded_coins,
        "level": u.level,
        "leveled_up": new_lvl > old_lvl
    }

@app.post('/api/integrations/fitness/activity')
async def record_fitness_activity(activity: FitnessActivityInput, s: Session=Depends(db), u: User=Depends(current_user)):
    prov = get_provider('Fitness')
    result = await prov.record_activity(activity) # type: ignore
    habit_q = s.query(Quest).join(Goal).filter(
        Goal.user_id == u.id,
        Quest.status == 'available',
        (Quest.category == 'Fitness') | (Quest.quest_type == 'habit') | (Quest.title.ilike(f'%{activity.activity_type}%'))
    ).first()
    
    awarded_xp = result['earned_xp']
    awarded_coins = result['earned_coins']
    old_lvl, new_lvl = add_xp(u, awarded_xp)
    u.coins += awarded_coins
    touch(u)
    
    if habit_q:
        e = Evidence(
            quest_id=habit_q.id,
            user_id=u.id,
            kind='fitness',
            value=result['summary'],
            evaluation=f"Fitness tracker verified {activity.duration_minutes}m of {activity.activity_type}.",
            quality=85.0,
            relevance=0.95,
            confidence=0.9,
            completeness=0.85,
            supports_quest=True,
            feedback=f"Fitness logged: {activity.duration_minutes}m activity toward {habit_q.title}."
        )
        s.add(e)
        
    it = s.query(Integration).filter_by(user_id=u.id, provider='Fitness').first()
    if it:
        it.connected = True
        it.status = 'connected'
        it.last_sync_at = datetime.utcnow()
        it.metadata_json = json.dumps({"latest_activity": result})
        
    # Also record into Unified Activity
    norm = normalize_activity("Fitness", result)
    s.add(UnifiedActivityRecord(
        user_id=u.id,
        provider="Fitness",
        activity_type="fitness_activity",
        title=norm.title,
        description=norm.description,
        external_id=norm.external_id or '',
        timestamp=norm.timestamp,
        metadata_json=json.dumps(norm.metadata),
        matched_quest_id=habit_q.id if habit_q else None
    ))
    
    notify(s, u, 'Fitness Activity Recorded', result['summary'], 'fitness')
    s.commit()
    return {
        "ok": True,
        "result": result,
        "quest_updated": clean(habit_q) if habit_q else None,
        "earned_xp": awarded_xp,
        "earned_coins": awarded_coins,
        "level": u.level,
        "leveled_up": new_lvl > old_lvl
    }

class GoalParseIn(BaseModel):
    text: str

@app.post('/api/goals/parse')
def parse_goal_endpoint(x: GoalParseIn, u: User=Depends(current_user)):
    return parse_natural_language_goal(x.text)

@app.get('/api/recommendations')
def get_recommendations_endpoint(s: Session=Depends(db), u: User=Depends(current_user)):
    active_quests = s.query(Quest).join(Goal).filter(Goal.user_id == u.id, Quest.status.in_(['available', 'in_progress'])).order_by(Quest.order_index).limit(10).all()
    deadlines = []
    for prov_name in ['Google Calendar', 'Outlook Calendar']:
        it = s.query(Integration).filter_by(user_id=u.id, provider=prov_name, connected=True).first()
        if it and it.metadata_json:
            try:
                meta = json.loads(it.metadata_json)
                for dl in meta.get('deadlines', []):
                    dl['provider'] = prov_name
                    deadlines.append(dl)
            except Exception:
                pass
    
    weak_skills_rows = s.query(TopicSkill).filter(TopicSkill.user_id == u.id, TopicSkill.mastery < 65.0).order_by(TopicSkill.mastery.asc()).all()
    weak_skills = [w.topic for w in weak_skills_rows]
    
    gh_it = s.query(Integration).filter_by(user_id=u.id, provider='GitHub', connected=True).first()
    gh_repo = None
    if gh_it and gh_it.metadata_json:
        try:
            gh_meta = json.loads(gh_it.metadata_json)
            gh_repo = gh_meta.get('last_active_repo')
        except Exception:
            pass
            
    return generate_personalized_recommendations(
        active_quests=[clean(q) for q in active_quests],
        deadlines=deadlines,
        weak_skills=weak_skills,
        github_active_repo=gh_repo
    )


@app.get('/api/notifications')
def notifications(s:Session=Depends(db),u:User=Depends(current_user)): return [clean(x) for x in s.query(Notification).filter_by(user_id=u.id).order_by(Notification.id.desc()).limit(30).all()]

@app.post('/api/notifications/read-all')
def notifications_read(s:Session=Depends(db),u:User=Depends(current_user)): s.query(Notification).filter_by(user_id=u.id,read=False).update({'read':True}); s.commit(); return {'ok':True}

@app.get('/api/settings')
def settings(u:User=Depends(current_user)): return {'notifications':u.notifications,'theme':u.theme,'sound':u.sound,'difficulty':u.difficulty,'daily_minutes':u.daily_minutes,'timezone':u.timezone}

@app.post('/api/reset')
def reset(s:Session=Depends(db),u:User=Depends(current_user)):
    goal_ids=[x.id for x in s.query(Goal).filter_by(user_id=u.id).all()]
    campaign_ids=[x.id for x in s.query(Campaign).filter_by(user_id=u.id).all()]
    quest_ids=[x.id for x in s.query(Quest).filter(Quest.goal_id.in_(goal_ids)).all()] if goal_ids else []
    if quest_ids:
        s.query(Evidence).filter(Evidence.quest_id.in_(quest_ids),Evidence.user_id==u.id).delete(synchronize_session=False)
        s.query(Assessment).filter(Assessment.quest_id.in_(quest_ids),Assessment.user_id==u.id).delete(synchronize_session=False)
        s.query(Quiz).filter(Quiz.quest_id.in_(quest_ids),Quiz.user_id==u.id).delete(synchronize_session=False)
        s.query(Quest).filter(Quest.id.in_(quest_ids)).delete(synchronize_session=False)
    if campaign_ids:
        s.query(Milestone).filter(Milestone.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        s.query(Campaign).filter(Campaign.id.in_(campaign_ids)).delete(synchronize_session=False)
    s.query(Goal).filter_by(user_id=u.id).delete(synchronize_session=False)
    s.query(TopicSkill).filter_by(user_id=u.id).delete(synchronize_session=False)
    for model in [Notification,Journal,Mission,Skill,Inventory,Friend,Challenge,Integration]:
        s.query(model).filter_by(user_id=u.id).delete(synchronize_session=False)
    u.xp=0;u.level=1;u.coins=250;u.streak=0;u.last_active='';u.onboarding_done=False
    seed_integrations(s,u); s.add(Challenge(user_id=u.id,title='Weekly Quest Run',target=5,reward=150)); s.commit()
    return {'ok':True}
