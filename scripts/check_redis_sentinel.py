import redis
from redis.sentinel import Sentinel

SENTINELS = [("host1", 26379), ("host2", 26379), ("host3", 26379)]
MASTER = "mymaster"
USER = None              # 계정 있으면 "user"
REDIS_PW = "Redis비번"
SENTINEL_PW = "Sentinel비번"   # 없으면 None

for h, p in SENTINELS:
    for label, pw in [("인증O", SENTINEL_PW), ("인증X", None)]:
        try:
            r = redis.Redis(host=h, port=p, username=USER if pw else None, password=pw, socket_timeout=3)
            print(h, p, label, "addr:", r.sentinel_get_master_addr_by_name(MASTER),
                  "masters:", list(r.sentinel_masters().keys()))
        except Exception as e:
            print(h, p, label, "실패:", type(e).__name__, e)

try:
    s = Sentinel(SENTINELS, socket_timeout=3,
                 sentinel_kwargs={"username": USER, "password": SENTINEL_PW},
                 username=USER, password=REDIS_PW)
    print("master:", s.discover_master(MASTER))
    print("ping:", s.master_for(MASTER, db=0, socket_timeout=3).ping())
except Exception as e:
    print("master 접속 실패:", type(e).__name__, e)
