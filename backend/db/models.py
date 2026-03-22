from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config.settings import settings


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Skill(Base):
    __tablename__ = "skills"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    version = Column(String)
    description = Column(Text)
    config = Column(Text)
    enabled = Column(Boolean, default=True)
    installed_at = Column(DateTime, default=datetime.utcnow)


class Plugin(Base):
    __tablename__ = "plugins"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    version = Column(String)
    enabled = Column(Boolean, default=True)
    config = Column(Text)
    installed_at = Column(DateTime, default=datetime.utcnow)


class ShortTermMemory(Base):
    __tablename__ = "short_term_memory"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True)
    role = Column(String)
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class LongTermMemory(Base):
    __tablename__ = "long_term_memory"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text)
    embedding = Column(Text)
    importance = Column(Float, default=0.5)
    created_at = Column(DateTime, default=datetime.utcnow)
    access_count = Column(Integer, default=0)
    last_access = Column(DateTime, default=datetime.utcnow)


class BehaviorLog(Base):
    __tablename__ = "behavior_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True)
    action_type = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class ExperienceMemory(Base):
    __tablename__ = "experience_memory"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    experience_type = Column(String, index=True)
    title = Column(String(200))
    content = Column(Text)
    trigger_conditions = Column(Text)
    success_metrics = Column(Float, default=0.0)
    usage_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    source_task = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_access = Column(DateTime, default=datetime.utcnow)
    confidence = Column(Float, default=0.5, index=True)
    metadata = Column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True)
    action = Column(String)
    resource = Column(String)
    result = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)


class ExperienceExtractionLog(Base):
    __tablename__ = "experience_extraction_log"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True)
    task_summary = Column(Text)
    extracted_experience = Column(Text)
    extraction_trigger = Column(String)
    extraction_quality = Column(Float, default=0.0)
    reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PromptConfig(Base):
    __tablename__ = "prompt_configs"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    content = Column(Text)
    variables = Column(Text)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
