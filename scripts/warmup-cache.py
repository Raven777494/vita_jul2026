# scripts/warmup-cache.py
import redis
r = redis.Redis(host='redis', port=6379)
# 預載常用查詢
r.set('common:greeting', '你好')