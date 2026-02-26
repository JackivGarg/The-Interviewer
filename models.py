from sqlalchemy import Column, Integer, String
from database import Base


class CEO(Base):
    __tablename__ = "ceo"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, default="Jackiv Garg")
    password = Column(String)


class HR(Base):
    __tablename__ = "hr"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    skills = Column(String, nullable=True)
    experience = Column(String, nullable=True)
