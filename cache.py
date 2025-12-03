from database import User ,EventLog ,Post ,async_session_maker
import redis.asyncio as aioredis
from dotenv import load_dotenv
from datetime import datetime
from typing import List
import asyncio
import os 

load_dotenv()

class Cache:

    def __init__(self):
        self.event_set_key = "EventLogs"
        self.event_max_logs = 1000
        self.post_expiry_seconds = 3600
        self.user_expirey_seconds = 3600
        self.is_populated = False
        self.evict_time_interval_seconds = 5
        self.__r = None
    
    async def connect(self):
        if self.__r is not None:
            return
        try:
            host = os.getenv("REDISHOST" ,"locahost")
            port = os.getenv("REDISPORT" ,6379)
            self.__r = aioredis.Redis(host=host, port=port, db=0)
            await self.__r.ping() 
        
        except Exception as e:
            self.__r = None
            raise ConnectionError(f"Failed to connect to Redis: {e}")
    
    async def close(self):
        if self.__r:
            await self.__r.close()

    def event_key(self, event_id: int) -> str:
        return f"Event:{event_id}"

    def post_key(self, post_id: int) -> str:
        return f"Post:{post_id}"
    
    def user_key(self, user_id: int) -> str:
        return f"User:{user_id}"

    async def add_event_log(self ,event:EventLog):
        assert self.__r is not None , "Redis connection not established"
        
        score = event.id
        await self.__r.zadd(self.event_set_key ,{self.event_key(event.id): score})

        await self.__r.hset(self.event_key(event.id) ,mapping={
            "id":event.id,
            "actor_id": event.actor_id,
            "actor_name": event.actor_name,
            "actor_role": event.actor_role,
            "action": event.action,
            "target_type": event.target_type or "",
            "target_id": event.target_id or -1,
            "target_user_name": event.target_user_name or "",
            "created_on": event.created_on.timestamp()
        })
    
    async def is_cache_populated(self) -> bool:
        assert self.__r is not None , "Redis connection not established"

        if self.is_populated:
            return True

        total = await self.__r.zcard(self.event_set_key)
        if total > 0 :
            self.is_populated = True
            return True

        return False 

    async def populate_cache(self ,events:List[EventLog]):
        assert self.__r is not None , "Redis connection not established"

        if len(events) == 0:
            return
        
        events = events[0 : self.event_max_logs]
        for event in events:
            await self.add_event_log(event)
        
        self.is_populated = True    

        
    async def get_event_logs(self ,offset:int = 0 ,limit:int = 100):
        assert self.__r is not None , "Redis connection not established"

        if offset + limit > self.event_max_logs:
            return []

        event_keys = await self.__r.zrevrange(self.event_set_key ,offset ,offset + limit - 1)
        if len(event_keys) == 0:
            return []
        
        pipe  = self.__r.pipeline()
        for key in event_keys:
            pipe.hgetall(key)
        
        event_dicts = await pipe.execute()
        
        events = []
        for event_dict in event_dicts:
            if event_dict:
                decoded = {k.decode(): v.decode() for k, v in event_dict.items()}
                decoded["id"] = int(decoded["id"])
                decoded["actor_id"] = int(decoded["actor_id"])
                decoded["target_id"] = int(decoded["target_id"])
                decoded["created_on"] = datetime.fromtimestamp(float(decoded["created_on"]))
                events.append( EventLog(**decoded) )
                
        return events        
    
    ##background task to evict oldest event logs when max limit exceeded
    async def evict_background_task(self):
        while True:
            try:
                await self.evict_oldest_event()
                await asyncio.sleep(self.evict_time_interval_seconds)
            except asyncio.CancelledError:
                break

    async def evict_oldest_event(self):
        assert self.__r is not None , "Redis connection not established"

        total = await self.__r.zcard(self.event_set_key)
        excess = total - self.event_max_logs
        if excess <= 0:
            return 
        
        popped = await self.__r.zpopmin(self.event_set_key, excess)
        
        pipe = self.__r.pipeline()
        for key, _ in popped:
            pipe.delete(key)    
        
        await pipe.execute()
        

    async def add_post(self ,post:Post):       
        assert self.__r is not None , "Redis connection not established"

        await self.__r.hset(self.post_key(post.id) ,mapping={
            "id": post.id,
            "user_id": post.user_id,
            "title": post.title or "",
            "content": post.content,
            "created_on": post.created_on.timestamp(),
            "post_likes": post.post_likes
        })
        
        await self.__r.expire(self.post_key(post.id) ,self.post_expiry_seconds)

    async def get_post(self ,post_id:int):
        assert self.__r is not None , "Redis connection not established"

        post_dict = await self.__r.hgetall(self.post_key(post_id))
        if not post_dict:
            return None
        
        decoded = {k.decode(): v.decode() for k, v in post_dict.items()}
        decoded["id"] = int(decoded["id"])
        decoded["user_id"] = int(decoded["user_id"]) 
        decoded["created_on"] = datetime.fromtimestamp(float(decoded["created_on"]))
        decoded["post_likes"] = int(decoded["post_likes"])

        return Post(**decoded)

    async def increment_post_post_likes(self ,post_id:int):
        assert self.__r is not None , "Redis connection not established"

        exists = await self.__r.exists(self.post_key(post_id))
        if not exists:
            return

        await self.__r.hincrby(self.post_key(post_id) ,"post_likes" ,1)
    
    async def decrement_post_post_likes(self ,post_id:int):
        assert self.__r is not None , "Redis connection not established"

        exists = await self.__r.exists(self.post_key(post_id))
        if not exists:
            return
        
        await self.__r.hincrby(self.post_key(post_id) ,"post_likes" ,-1)
    
    async def add_user(self ,user:User):
        assert self.__r is not None , "Redis connection not established"

        await self.__r.hset(self.user_key(user.id) ,mapping={
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "created_on": user.created_on.timestamp()
        })

        await self.__r.expire(self.user_key(user.id) ,self.user_expirey_seconds)
    
    async def get_user(self ,user_id:int):
        assert self.__r is not None , "Redis connection not established"

        user_dict = await self.__r.hgetall(self.user_key(user_id))
        if not user_dict:
            return None
        
        decoded = {k.decode(): v.decode() for k, v in user_dict.items()}
        decoded["id"] = int(decoded["id"])
        decoded["created_on"] = datetime.fromtimestamp(float(decoded["created_on"]))

        return User(**decoded)
    

    async def delete_event(self, event_id: int):
        assert self.__r is not None, "Redis connection not established"
        
        key = self.event_key(event_id)
        await self.__r.zrem(self.event_set_key, key)
        await self.__r.delete(key)
    
    async def delete_post(self, post_id: int):
        assert self.__r is not None, "Redis connection not established"

        key = self.post_key(post_id)
        await self.__r.delete(key)
    
    async def delete_user(self, user_id: int):
        assert self.__r is not None, "Redis connection not established"

        key = self.user_key(user_id)
        await self.__r.delete(key)


    

