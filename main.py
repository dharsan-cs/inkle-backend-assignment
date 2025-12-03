from database import User ,UserFollow ,UserBlock ,Post ,PostLike ,EventLog ,async_session_maker
from authentication import Authentication ,TokenData ,OWNER_ROLE ,ADMIN_ROLE ,USER_ROLE
from sqlalchemy import select ,update ,delete ,desc ,or_
from fastapi import FastAPI ,Request ,HTTPException
from contextlib import asynccontextmanager
from sqlalchemy.exc import TimeoutError
from datetime import datetime ,timezone
from pydantic import BaseModel
from typing import List
from cache import Cache 
from dotenv import load_dotenv
import asyncio
import uvicorn
import os  

load_dotenv()

Auth = Authentication()
CacheInstance = Cache()

# Event action constants
POST_CREATION_EVENT = "created_post"
POST_LIKE_EVENT = "liked_post"
POST_DELETE_EVENT = "deleted_post"
USER_FOLLOW_EVENT = "followed_user"
USER_BLOCK_EVENT = "blocked_user"
USER_DELETE_EVENT = "deleted_user"
LIKE_DELETE_EVENT = "deleted_like"

# target_type constants
TARGET_TYPE_POST = "post"
TARGET_TYPE_USER = "user"
TARGET_TYPE_LIKE = "like"

async def create_owner():
    name = os.getenv("OWNER_NAME")
    email = os.getenv("OWNER_EMAIL")
    password = os.getenv("OWNER_PASSWORD")

    try:
        async with async_session_maker() as session:
            existing_user = await session.scalar(
                select(User).where(
                    or_(
                        User.name == name ,
                        User.email == email
                    )
                )
            )

            if existing_user:
                print("Owner Already Exist")
                return
            
            hashed_password = Auth.hash_password(password)

            new_user = User(
                name = name,
                email = email,
                password = hashed_password,
                role = OWNER_ROLE
            )

            session.add(new_user)
            await session.commit()
            print("Owner Created")
    
    except Exception as e:
        print("Owner-Createion-Error : " ,e)
        return

@asynccontextmanager
async def lifespan(app: FastAPI):

    await create_owner()

    await CacheInstance.connect()

    if not await CacheInstance.is_cache_populated():
        
        async with async_session_maker() as session:
            stmt = select(EventLog).order_by(EventLog.id.desc()).limit(CacheInstance.event_max_logs)
            result =  await session.execute(stmt)
            events = result.scalars().all()
            
            await CacheInstance.populate_cache(events)

    task = asyncio.create_task(CacheInstance.evict_background_task())

    try:
        yield
    finally:
        # Shutdown
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            print("Scheduler stopped.")


app = FastAPI(lifespan=lifespan)

class SignupPayload(BaseModel):
    name:str
    email:str
    password:str


async def get_user_helper(user_id:int ,sesssion):
    user:User = await CacheInstance.get_user(user_id)
    if user:
        return user 

    user = await sesssion.get(User ,user_id)
    if not user:
        raise HTTPException(status_code=400 ,detail="user not found")
    
    await CacheInstance.add_user(user)
    return user


@app.post("/signup")
async def signup(req:Request ,payload:SignupPayload):

    try:
        async with async_session_maker() as session:

            if payload.name.strip() == "" or payload.email.strip() == "" or payload.password.strip() == "":
                raise HTTPException(status_code=400 ,detail="name/email/password connot be empty")
            
            existing_user = await session.scalar(
                select(User).where(
                    or_(
                        User.name == payload.name ,
                        User.email == payload.email
                    )
                )
            )

            if existing_user:
                raise HTTPException(status_code=400 ,detail="User with given name or email already exists")
            
            hashed_password = Auth.hash_password(payload.password)

            new_user = User(
                name = payload.name,
                email = payload.email,
                password = hashed_password,
                role = USER_ROLE
            )

            session.add(new_user)
            await session.commit()

            return {"login_token" : Auth.generate_login_token(new_user)}
    
    except HTTPException:
        raise

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")


class LoginPayload(BaseModel):
    name_or_email:str
    password:str

@app.post("/login")
async def login( req:Request ,payload:LoginPayload):
    try:
        async with async_session_maker() as session:
            user:User = await session.scalar(
                select(User).where(
                    or_(
                        User.name == payload.name_or_email ,
                        User.email == payload.name_or_email
                    )
                )
            )

            if not user:
                raise HTTPException(status_code=404 ,detail="user not found")
            
            if not Auth.verify_password(payload.password ,user.password):
                raise HTTPException(status_code=401 ,detail="incorrect password")
            
            return {"login_token" : Auth.generate_login_token(user)}
    
    except HTTPException:
        raise

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")

class PostCreatePayload(BaseModel):
    title:str | None = None
    content:str

@app.post("/create_post")
async def create_post(req:Request ,payload:PostCreatePayload):
    token_data:TokenData = Auth.session_verify(req)

    if payload.content.strip() == "":
        raise HTTPException(status_code=400 ,detail="Post content cannot be empty")
    
    if len(payload.content.strip()) > 5000:
        raise HTTPException(status_code=400 ,detail="Post content exceeds maximum length of 5000 characters")

    try:
        async with async_session_maker() as session:

            user:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)

            new_post = Post(
                user_id = user.id,
                title = payload.title,
                content = payload.content,
                created_on = datetime.now(tz = timezone.utc)
            )

            session.add(new_post)
            await session.flush()

            new_event = EventLog(
                actor_id = user.id,
                actor_name = user.name,
                actor_role = user.role,
                action = POST_CREATION_EVENT,
                target_type = TARGET_TYPE_POST,
                target_id = new_post.id,
                target_user_name = user.name,
                created_on = datetime.now(tz = timezone.utc)
            )

            session.add(new_event)
            await session.commit()

            await CacheInstance.add_event_log(new_event)
            await CacheInstance.add_post(new_post)

            return {"post_id": new_post.id} 
    
    except HTTPException:
        raise

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")


async def post_fetch_helper(user:User ,post_id:int ,session):
    post:Post = await CacheInstance.get_post(post_id)
            
    if not post:    
        post = await session.get(Post, post_id)
        if not post:
            raise HTTPException(status_code=404 ,detail="Post not found") 
        
        await CacheInstance.add_post(post)
    
    block_relation = await session.scalar(
        select(UserBlock).where(
            UserBlock.blocker_id == post.user_id,
            UserBlock.blocked_id == user.id
        )
    )

    if block_relation:
        raise HTTPException(status_code=403 ,detail="You are blocked by the post owner")
            
    return post

@app.get("/posts/{post_id}")
async def get_post(req:Request ,post_id:int):
    token_data:TokenData = Auth.session_verify(req)

    try:
        async with async_session_maker() as session:
            
            user:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)
            
            return await post_fetch_helper(user ,post_id ,session)
    
    except HTTPException:
        raise
          
    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")

@app.post("/like_post/{post_id}")
async def like_post(req:Request ,post_id:int):
    token_data:TokenData = Auth.session_verify(req)

    try:
        async with async_session_maker() as session:

            user:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)
            post:Post = await post_fetch_helper(user ,post_id ,session)

            existing_like = await session.scalar(
                select(PostLike).where(
                    PostLike.user_id == user.id,
                    PostLike.post_id == post.id
                )
            )

            if existing_like:
                raise HTTPException(status_code=400 ,detail="Post already liked")

            new_like = PostLike(
                user_id = user.id,
                post_id = post.id
            )
            session.add(new_like)
            await session.flush()

            post_owner:User = await CacheInstance.get_user(post.user_id)
            if not post_owner:
                post_owner = await session.get(User ,post.user_id)
                await CacheInstance.add_user(post_owner)

            new_event = EventLog(
                actor_id = user.id,
                actor_name = user.name,
                actor_role = user.role,
                action = POST_LIKE_EVENT,
                target_type = TARGET_TYPE_POST,
                target_id = post.id,
                target_user_name = post_owner.name,
                created_on = datetime.now(tz = timezone.utc)
            )
            session.add(new_event)
          
            await session.execute(update(Post).where(Post.id == post.id).values(post_likes = Post.post_likes + 1))
            
            await session.commit()
            
            await CacheInstance.increment_post_post_likes(post.id)
            await CacheInstance.add_event_log(new_event)

            return {"message":"Post liked successfully"}

    except HTTPException:
        raise 

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")

@app.post("/block_user/{target_user_id}")
async def block_user(req:Request ,target_user_id:int):
    token_data:TokenData = Auth.session_verify(req)
     
    try:
        async with async_session_maker() as session:

            user:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)

            if user.id == target_user_id:
                raise HTTPException(status_code=400 ,detail="You cannot block yourself")

            blocked_user:User = await get_user_helper(user_id = target_user_id ,sesssion = session)
            if blocked_user.role == OWNER_ROLE or blocked_user.role == ADMIN_ROLE:
                raise HTTPException(status_code=403 ,detail="You cannot block owner/admin")

            
            existing_block = await session.scalar(
                select(UserBlock).where(
                    UserBlock.blocker_id == user.id,
                    UserBlock.blocked_id == blocked_user.id
                )
            )

            if existing_block:
                raise HTTPException(status_code=400 ,detail="User already blocked")

            new_block = UserBlock(
                blocker_id = user.id,
                blocked_id = blocked_user.id
            )
            session.add(new_block)

            new_event = EventLog(
                actor_id = user.id,
                actor_name = user.name,
                actor_role =user.role,
                action = USER_BLOCK_EVENT,
                target_type = TARGET_TYPE_USER,
                target_id = blocked_user.id,
                target_user_name = blocked_user.name,
                created_on = datetime.now(tz = timezone.utc)
            )
            session.add(new_event)

            await session.commit()
            await CacheInstance.add_event_log(new_event)

            return {"message":"User blocked successfully"}
    
    except HTTPException:
        raise 

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")

@app.post("/follow_user/{target_user_id}")
async def follow_user(req:Request ,target_user_id:int):
    token_data:TokenData = Auth.session_verify(req)

    try:
        async with async_session_maker() as session:

            user:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)

            if user.id == target_user_id:
                raise HTTPException(status_code=400 ,detail="You cannot follow yourself")
            
            followed_user:User = await get_user_helper(user_id = target_user_id ,sesssion = session)
        
            existing_follow = await session.scalar(
                select(UserFollow).where(
                    UserFollow.follower_id == user.id,
                    UserFollow.followed_id == followed_user.id
                )
            )

            if existing_follow:
                raise HTTPException(status_code=400 ,detail="User already followed")

            new_follow = UserFollow(
                follower_id = user.id,
                followed_id = followed_user.id
            )
            session.add(new_follow)

            new_event = EventLog(
                actor_id = user.id,
                actor_name = user.name,
                actor_role = user.role,
                action = USER_FOLLOW_EVENT,
                target_type = TARGET_TYPE_USER,
                target_id = followed_user.id,
                target_user_name = followed_user.name,
                created_on = datetime.now(tz = timezone.utc)
            )
            session.add(new_event)

            await session.commit()
            await CacheInstance.add_event_log(new_event)

            return {"message":"User followed successfully"}
    
    except HTTPException:
        raise 

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")


@app.get("/event_logs")
async def get_event_logs(req:Request ,limit:int = 100 ,offset:int = 0):
    token_data:TokenData = Auth.session_verify(req)
   
    try:
        async with async_session_maker() as session:

            _:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)

            if limit <= 0 or limit > 100:
                raise HTTPException(status_code=400 ,detail="Limit must be between 1 and 100")
            
            if offset < 0:
                raise HTTPException(status_code=400 ,detail="Offset cannot be negative")
            
            ##fetch from cache only if entire data is available in cache
            events:List[EventLog] = await CacheInstance.get_event_logs(offset ,limit)
            if events:
                return events

            events:List[EventLog] = (await session.scalars(select(EventLog).order_by(desc(EventLog.id)).offset(offset).limit(limit))).all()   
            
            return events
    
    except HTTPException:
        raise

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")

class AdminCreatePayload(BaseModel):
    admin_name:str
    admin_email:str
    admin_password:str

@app.post("/create_admin")
async def create_admin(req:Request ,payload:AdminCreatePayload):
    token_data:TokenData = Auth.session_verify(req)
    
    try:
        async with async_session_maker() as session:

            if payload.admin_name.strip() == "" or payload.admin_email.strip() == "" or payload.admin_password.strip() == "":
                raise HTTPException(status_code=400 ,detail="name/email/password connot be empty")

            user:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)

            if not Auth.is_owner(user = user):
                raise HTTPException(status_code=403 ,detail="Forbidden")

            existing_user = await session.scalar(
                select(User).where(
                    or_(
                        User.name == payload.admin_name ,
                        User.email == payload.admin_email
                    )
                )
            )

            if existing_user:
                raise HTTPException(status_code=400 ,detail="User with given name or email already exists")
            
            hashed_password = Auth.hash_password(payload.admin_password)

            new_user = User(
                name = payload.admin_name,
                email = payload.admin_email,
                password = hashed_password,
                role = ADMIN_ROLE
            )

            session.add(new_user)
            await session.commit()
            return {"message" : "Admin created succesfully"}
    
    except HTTPException:
        raise

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")

async def delete_user_helper(target_user_id: int, session):

    await CacheInstance.delete_user(user_id=target_user_id)

    del_post_stmt = delete(Post).where(Post.user_id == target_user_id)
    del_post_like_stmt = delete(PostLike).where(PostLike.user_id == target_user_id)

    del_user_follow_stmt = delete(UserFollow).where(
        or_(
            UserFollow.follower_id == target_user_id,
            UserFollow.followed_id == target_user_id,
        )
    )

    del_user_block_stmt = delete(UserBlock).where(
        or_(
            UserBlock.blocker_id == target_user_id,
            UserBlock.blocked_id == target_user_id,
        )
    )

    del_event_log_stmt = delete(EventLog).where(EventLog.actor_id == target_user_id)
    del_user_stmt = delete(User).where(User.id == target_user_id)

    await session.execute(del_post_stmt)
    await session.execute(del_post_like_stmt)
    await session.execute(del_user_follow_stmt)
    await session.execute(del_user_block_stmt)
    await session.execute(del_event_log_stmt)
    await session.execute(del_user_stmt)


@app.post("/delete_user/{target_user_id}")
async def delete_admin(req:Request ,target_user_id:int):
    token_data:TokenData = Auth.session_verify(req)
    
    try:
        async with async_session_maker() as session:
            
            user:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)

            if user.role != ADMIN_ROLE and user.role != OWNER_ROLE:
                raise HTTPException(status_code=403 ,detail="Forbidden")

            target_user:User = await session.get(User ,target_user_id)
            if not target_user:
                raise HTTPException(status_code=404 ,detail="user not found")
            
            if target_user.role == OWNER_ROLE:
                raise HTTPException(status_code=403 ,detail="Forbidden")
            
            if target_user.role == ADMIN_ROLE and user.role != OWNER_ROLE:
                raise HTTPException(status_code=403 ,detail="Forbidden")
            
            await delete_user_helper(target_user_id = target_user.id ,session = session)            

            new_event = EventLog(
                actor_id = user.id,
                actor_name = user.name,
                actor_role = user.role,
                action = USER_DELETE_EVENT,
                target_type = TARGET_TYPE_USER,
                target_id = target_user.id,
                target_user_name = target_user.role,
                created_on = datetime.now(tz = timezone.utc)
            )

            session.add(new_event)

            await session.commit()

            await CacheInstance.add_event_log(new_event)

            return {"message" : "User deleted succesfully"}
        
    except HTTPException:
        raise

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")
    
@app.post("/delete_post/{post_id}")
async def delete_post(req:Request ,post_id:int):
    token_data:TokenData = Auth.session_verify(req)
    
    try:
        async with async_session_maker() as session:

            user:User = await get_user_helper(user_id = token_data.user_id ,sesssion = session)
            if user.role != ADMIN_ROLE and user.role != OWNER_ROLE:
                raise HTTPException(status_code=403 ,detail="Forbidden")

            post:Post = await session.get(Post ,post_id)
            if not post:
                raise HTTPException(status_code=404 ,detail="Post not found")
            
            post_owner:User = await get_user_helper(user_id = post.user_id ,sesssion = session)
            
            await CacheInstance.delete_post(post_id = post.id)

            post_like_del_stmt = delete(PostLike).where(PostLike.post_id == post.id)
            post_del_stmt = delete(Post).where(Post.id == post.id)

            await session.execute(post_like_del_stmt)
            await session.execute(post_del_stmt)

            new_event = EventLog(
                actor_id = user.id,
                actor_name = user.name,
                actor_role = user.role,
                action = POST_DELETE_EVENT,
                target_type = TARGET_TYPE_POST,
                target_id = post.id,
                target_user_name = post_owner.name,
                created_on = datetime.now(tz = timezone.utc)
            )
            session.add(new_event)

            await session.commit()

            await CacheInstance.add_event_log(new_event)

            return {"message" : "Post deleted succesfully"}
    
    except HTTPException:
        raise

    except TimeoutError:
        raise HTTPException(status_code=503 ,detail="Database timeout , please try again later")
    
    except Exception as e:
        print("Error :" ,e)
        raise HTTPException(status_code=500 ,detail="Internal server error")
                

if __name__ == "__main__":
    port = int(os.environ.get("PORT"))
    uvicorn.run("main:app", host="0.0.0.0", port=port ,reload = True)