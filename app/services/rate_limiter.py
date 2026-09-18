from redis import Redis

RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])

if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end

return current
"""


class RateLimiter:
    def __init__(self, redis_url: str):
        self.redis = Redis.from_url(
            redis_url,
            decode_responses=True,
        )

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        current = int(
            self.redis.eval(
                RATE_LIMIT_SCRIPT,
                1,
                key,
                window_seconds,
            )
        )

        return current <= limit, current
