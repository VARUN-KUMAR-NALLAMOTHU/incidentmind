"""Demo history: resolved incidents retained into memory before the live demo starts.

Kafka is intentionally NOT seeded here, so it can be the live "empty memory -> learn -> recall" moment
in the demo script (see README). Everything else spans Redis, PostgreSQL, Kubernetes and Nginx, with a
deliberate mix of outcomes:
  - a straightforward success (payment-api)
  - a failed attempt followed by the fix that actually worked (payment-api, checkout-api)
  - a CONFLICT: the same fix worked once and failed once for the same service (redis-cache), to exercise
    the "mixed evidence" handling in the prompt and UI
  - an entry older than STALE_DAYS (orders-db) to exercise the staleness flag
Each attempt carries `days_ago` so retained memories get realistic, spread-out dates.
"""

SEED = [
    {
        "service": "payment-api", "environment": "Production", "days_ago": 12,
        "symptoms": "Redis connection timeout, HTTP 504 responses on checkout",
        "logs": "ERROR Redis connection pool exhausted (active=50/50, waiting=214)\n"
                "HTTP 504 Gateway Timeout on POST /charge\nRedisConnectionError: timeout acquiring connection",
        "attempts": [
            ("Restart payment-api only", "failed", "504s returned within 10 minutes", 12, 8),
            ("Increase Redis connection pool from 50 to 100 and restart", "success",
             "Errors stopped immediately, pool usage settled around 40%", 12, 22),
        ],
    },
    {
        "service": "checkout-api", "environment": "Production", "days_ago": 34,
        "symptoms": "Intermittent 502s during flash sale traffic",
        "logs": "upstream prematurely closed connection while reading response header from upstream\n"
                "worker_connections 1024 exceeded",
        "attempts": [
            ("Scale checkout-api replicas from 3 to 4", "failed", "502 rate barely dropped", 34, 6),
            ("Raise nginx worker_connections to 4096 and enable keepalive upstream", "success",
             "502s dropped to near zero within 5 minutes", 34, 19),
        ],
    },
    {
        "service": "orders-db", "environment": "Production", "days_ago": 118,
        "symptoms": "PostgreSQL too many connections, requests failing",
        "logs": "FATAL: sorry, too many clients already\nremaining connection slots are reserved "
                "for non-replication superuser connections",
        "attempts": [
            ("Add PgBouncer in transaction pooling mode and lower app pool size to 20", "success",
             "Active connections dropped 70%, no recurrence since", 118, 15),
        ],
    },
    {
        "service": "redis-cache", "environment": "Production", "days_ago": 60,
        "symptoms": "Redis OOM killer triggered, cache evictions spiking",
        "logs": "Out of memory: Kill process (redis-server)\nWARNING maxmemory-policy is noeviction",
        "attempts": [
            ("Restart Redis with maxmemory unchanged", "failed", "OOM recurred within 2 hours", 60, 3),
            ("Set maxmemory-policy to allkeys-lru and raise maxmemory to 4gb", "success",
             "No further OOM kills in a week of monitoring", 60, 20),
        ],
    },
    {
        # Deliberate conflict: the SAME fix ("restart the pod") recorded once as working, once as failing,
        # for the same service - so the UI's conflict badge and the prompt's "mixed evidence" rule fire.
        "service": "redis-cache", "environment": "Production", "days_ago": 45,
        "symptoms": "Redis replica falling behind, stale reads reported",
        "logs": "MASTER <-> REPLICA sync: receiving RDB from master\nrepl_backlog_size too small, "
                "partial resync failed",
        "attempts": [
            ("Restart the replica pod", "success", "Resync completed cleanly this time", 45, 10),
        ],
    },
    {
        "service": "redis-cache", "environment": "Production", "days_ago": 20,
        "symptoms": "Redis replica lag alert firing again",
        "logs": "MASTER <-> REPLICA sync: Full resync requested\nreplica lag 340s and climbing",
        "attempts": [
            ("Restart the replica pod", "failed",
             "Lag returned within an hour, root cause was network jitter not the pod", 20, 5),
            ("Increase repl-backlog-size to 256mb and pin replica to a dedicated node", "success",
             "Lag stayed under 2s for the following week", 20, 30),
        ],
    },
    {
        "service": "auth-service", "environment": "Production", "days_ago": 9,
        "symptoms": "Kubernetes pods stuck in CrashLoopBackOff after deploy",
        "logs": "Back-off restarting failed container\nliveness probe failed: HTTP probe failed with "
                "statuscode: 503\nOOMKilled",
        "attempts": [
            ("Roll back to the previous image tag", "success",
             "Pods stabilized within 2 minutes, root cause was a memory leak in the new build", 9, 7),
        ],
    },
    {
        "service": "auth-service", "environment": "Production", "days_ago": 5,
        "symptoms": "Pods stuck in Pending, insufficient CPU",
        "logs": "0/6 nodes are available: 6 Insufficient cpu\nFailedScheduling",
        "attempts": [
            ("Lower CPU requests from 1 core to 500m and add a cluster-autoscaler node group", "success",
             "Scheduling succeeded, autoscaler added 1 node under load", 5, 12),
        ],
    },
    {
        "service": "search-api", "environment": "Production", "days_ago": 27,
        "symptoms": "Nginx returning 413 Request Entity Too Large on bulk upload",
        "logs": "client intended to send too large body: 12582912 bytes\n413 Request Entity Too Large",
        "attempts": [
            ("Raise client_max_body_size to 20m in the nginx config", "success",
             "Uploads up to 15MB now succeed", 27, 4),
        ],
    },
    {
        "service": "search-api", "environment": "Staging", "days_ago": 15,
        "symptoms": "Elasticsearch queries timing out under load test",
        "logs": "SearchPhaseExecutionException: all shards failed\nEsRejectedExecutionException: "
                "rejected execution of processing",
        "attempts": [
            ("Increase thread_pool.search.queue_size", "failed",
             "Rejections continued, thread pool was not actually the bottleneck", 15, 9),
            ("Add 2 more data nodes and increase shard count from 1 to 3", "success",
             "P99 query latency dropped from 4.2s to 380ms", 15, 26),
        ],
    },
    {
        "service": "notifications-worker", "environment": "Production", "days_ago": 3,
        "symptoms": "Queue backlog growing, notifications delayed by 20+ minutes",
        "logs": "consumer lag: 48213 messages\nWorker pool saturated, all 10 workers busy",
        "attempts": [
            ("Scale worker pool from 10 to 25", "success",
             "Backlog cleared in 12 minutes and stayed near zero", 3, 11),
        ],
    },
    {
        "service": "billing-service", "environment": "Production", "days_ago": 71,
        "symptoms": "PostgreSQL deadlocks on invoice generation",
        "logs": "deadlock detected\nProcess 4821 waits for ShareLock on transaction; blocked by process 4790",
        "attempts": [
            ("Add a retry with exponential backoff around the invoice transaction", "success",
             "Deadlock errors dropped to near zero, occasional single retries succeed silently", 71, 14),
        ],
    },
]
