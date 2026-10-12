import os, json, redis

r = redis.Redis(host=os.environ["REDIS_HOST"], decode_responses=True)

def create_job(job_id, data):
    data["status"] = "PENDENTE"
    r.set(f"job:{job_id}", json.dumps(data))

def get_job(job_id):
    raw = r.get(f"job:{job_id}")
    return json.loads(raw) if raw else None

def update_job(job_id, **fields):
    job = get_job(job_id) or {}
    job.update(fields)
    r.set(f"job:{job_id}", json.dumps(job))
    return job