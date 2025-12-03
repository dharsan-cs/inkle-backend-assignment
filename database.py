from sqlalchemy.ext.asyncio import AsyncSession ,create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Index ,Column ,Integer ,DateTime ,String ,Text ,ForeignKey ,func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import mysql
from dotenv import load_dotenv
import sqlalchemy
import asyncio
import os 

Base = declarative_base()
load_dotenv()

def get_db_url(exe_env = os.getenv("EXECUTION_ENV")):
    if exe_env == "local":
        return os.getenv("DEV_DB_URL")

    socket_path = f"/cloudsql/{os.getenv('CLOUD_SQL_CONNECTION_NAME')}"
    url = sqlalchemy.engine.url.URL.create(
        drivername = os.getenv('DRIVER_NAME'),
        username = os.getenv('DB_USERNAME'),
        password = os.getenv('DB_PASSWORD'),
        database = os.getenv('DB_NAME'), 
        query = {
            "unix_socket" : socket_path
        }
    )
    return url

##db connection url  
DATABASE_URL = get_db_url()

##connection factory (maitaining a pool of open connections)
engine = create_async_engine(
    DATABASE_URL ,
    echo = False ,
    pool_size = 10,
    max_overflow = 20,
    pool_timeout = 30,
    pool_recycle = 1800,
)

##async session factory  
async_session_maker = sessionmaker( 
    bind = engine ,
    class_ = AsyncSession ,
    expire_on_commit = False
)

#User Roles :- Owner(auto-created at startup if needed) ,Admin(created by Owner) ,User(public signup)
class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True)
    name = Column(String(255) ,nullable = False ,unique = True ,index = True) 
    email = Column(String(255) ,nullable = False ,unique = True ,index = True)
    password = Column(String(255))
    role = Column(String(255))
    created_on = Column(DateTime(timezone=True), server_default=func.now())

#Composite unique indexed follower-followed relationship
class UserFollow(Base):
    __tablename__ = "user_follow"
    id = Column(Integer, primary_key=True)
    follower_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    followed_id = Column(Integer, ForeignKey('user.id'), nullable=False ,index = True) 

    __table_args__ = (
        Index("ix_user_follow", "follower_id", "followed_id", unique=True),
    )

#Composite unique indexed blocker-blocked relationship
class UserBlock(Base):
    __tablename__ = "user_block"
    id = Column(Integer, primary_key=True)
    blocker_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    blocked_id = Column(Integer, ForeignKey('user.id'), nullable=False) 

    __table_args__ = (
        Index("ix_user_block", "blocker_id", "blocked_id", unique=True),
    )

class Post(Base):
    __tablename__ = "post"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False ,index = True) 
    title = Column(String(1020) ,nullable = True) 
    content = Column(Text ,nullable = False) 
    created_on = Column(DateTime(timezone=True), server_default=func.now())
    post_likes = Column(Integer ,default=0)

#Composite unique indexed user-post relationship && index on post_id for faster lookups
class PostLike(Base):
    __tablename__ = "post_like"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    post_id = Column(Integer, ForeignKey('post.id'), nullable=False ,index = True)

    __table_args__ = (
        Index("ix_post_like", "user_id", "post_id", unique=True),
    )

class EventLog(Base):
    __tablename__ = "event_log"
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey('user.id'), nullable=False) 
    actor_name = Column(String(255), nullable = False)
    actor_role = Column(String(255), nullable = False)
    action = Column(String(255) ,nullable = False ,index = True) 
    target_type = Column(String(255))
    target_id = Column(Integer)
    target_user_name = Column(String(255)) 
    created_on = Column(DateTime(timezone=True), server_default=func.now(), index=True)

##create tables function 
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

##generate and save SQL CREATE TABLE queries to a file
def get_table_creation_query():
    with open("create_tables.txt", "w") as f:
        for table in Base.metadata.sorted_tables:
            create_sql = str(CreateTable(table).compile(dialect=mysql.dialect()))
            f.write(create_sql)

if __name__ == "__main__": 
    print("Choose an option:")
    print("1: Generate SQL CREATE TABLE queries and save to file")
    print("2: Create tables in the database")
    option = input("Enter 1 or 2: ").strip()
    if option == "1":
        get_table_creation_query()
    elif option == "2":
        asyncio.run(init_db())
    else:
        print("❌ Invalid option. Please enter 1 or 2.")