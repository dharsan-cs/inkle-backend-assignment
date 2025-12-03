Introduction :
  I used MySQL as the primary database and Redis for caching, storing the most recent N events with sorted sets and using HSET for event, post, and user key-value data. Each Docker instance runs a background job to maintain cache size. FastAPI was chosen for high concurrency, and JWT was used for secure session verification. I implemented composite indexes to speed up frequent paired-column searches (is_liked, is_blocked, is_followed), added proper error handling, and Built a social activity feed with proper role-based data handling.


Challenges / Optimizations Performed

    Caching (Redis)
        ->Used Sorted Set to insert and retrieve the most recent events.
        ->Used HSET to store event → event JSON key-value mappings.
        ->Used HSET to store post ID → post JSON key-value mappings (with TTL).
        ->Used HSET to store user ID → user JSON key-value mappings (with TTL).

    Background Task
        ->Implemented a simple background task to ensure only the most recent N events are kept in cache.
        ->The background task wakes up every few seconds and evicts the oldest events when needed.

    Database Connection Pooling
        ->Maintained a pool of open connections with pool size = 10 and overflow = 30.
        ->Reused existing connections efficiently.

    Composite Indexing
        ->Added composite indexes for paired columns such as
        ->follow("follower_id", "followed_id")
        ->block("blocker_id", "blocked_id")
        ->like("user_id", "post_id")

    Permission-Based Access Control
        ->Implemented permission checks for admin creation, user deletion, post deletion, and cache eviction operations.
        ->jwt for session verification

Execution
    
    1. Install dependencies from the requirements.txt file.

    2. Create a database in MySQL and update the connection URL in the .env file.

    3. Run database.py and select Option 2 (this creates and initializes the database/tables).

    4. Start the Redis server (pull the Redis Docker image).

    5. Finally, run python main.py.