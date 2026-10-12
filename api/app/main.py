import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from common.object_store import upload_bytes, ensure_buckets, BUCKET_UPLOADS
from common.job_store import create_job, get_job
from common.queue_client import get_channel, publish_conversion

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],  # origem do frontend
    allow_methods=["*"],
    allow_headers=["*"],
)
ensure_buckets()

EXT_TO_TYPE = {"mp4": "video", "avi": "video", "mov": "video",
               "mp3": "audio", "wav": "audio",
               "png": "image", "jpg": "image", "jpeg": "image"}

@app.post("/jobs")
async def create_conversion_job(file: UploadFile, target_format: str = Form(...), email: str = Form(...)):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    source_type = EXT_TO_TYPE.get(ext)
    if not source_type:
        raise HTTPException(400, f"Formato de origem não suportado: {ext}")

    job_id = str(uuid.uuid4())
    object_name = f"{job_id}.{ext}"
    data = await file.read()
    upload_bytes(BUCKET_UPLOADS, object_name, data)

    payload = {
        "jobId": job_id,
        "sourceObject": object_name,
        "sourceType": source_type,
        "sourceFormat": ext,
        "targetFormat": target_format,
        "notifyEmail": email,
        "requestedAt": datetime.now(timezone.utc).isoformat(),
        "attempt": 1,
    }
    create_job(job_id, payload)

    conn, ch = get_channel()
    publish_conversion(ch, payload)
    conn.close()

    return {"jobId": job_id}

@app.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return job