from sqlalchemy import Column, BigInteger, Integer, String, ForeignKey, Text, DECIMAL, Boolean, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

# Users
class Users(Base):
    __tablename__ = "Users"

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    email = Column(String(100), nullable=False, unique=True)
    provider_id = Column(String(100), nullable=False, unique=True)
    nickname = Column(String(200), nullable=False)
    provider_name = Column(String(100))
    profile_image_url = Column(Text)
    status = Column(String(40), default="active")
    has_completed_survey = Column(Boolean, default=False)

    # 관계 설정
    groups = relationship("UserGroups", back_populates="user")

# Groups
class Groups(Base):
    __tablename__ = "Groups"

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    invite_code = Column(String(6), unique=True, nullable=False)
    image_url = Column(Text)

    # 관계 설정
    users = relationship("UserGroups", back_populates="group")
    
# Manittos
class Manittos(Base):
    __tablename__ = "Manittos"

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    group_id = Column(BigInteger, ForeignKey("Groups.id", ondelete="CASCADE"), index=True, nullable=False)
    manitto_id = Column(BigInteger, ForeignKey("Users.id", ondelete="CASCADE"), nullable=False)
    manittee_id = Column(BigInteger, ForeignKey("Users.id", ondelete="CASCADE"), nullable=False)
    week = Column(Integer, nullable=False)