import os, json, tempfile
from common.object_store import ensure_buckets, upload_file, download_file, delete_object, public_url, BUCKET_UPLOADS, BUCKET_CONVERTED
from common.job_store import update_job, get_job
from common.queue_client import get_channel, publish_conversion, publish_notification
from .converters import video, audio, image

MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", 3))
CONVERTERS = {"video": video.convert, "audio": audio.convert, "image": image.convert}

def process(ch, method, properties, body):
    payload = json.loads(body)
    job_id = payload["jobId"]
    print(f"[{job_id}] recebido (tentativa {payload.get('attempt', 1)})", flush=True)

    # idempotência: se já concluído, só confirma a mensagem e sai
    current = get_job(job_id)
    if current and current.get("status") == "CONCLUIDO":
        print(f"[{job_id}] já concluído, ignorando (idempotência)", flush=True)
        ch.basic_ack(method.delivery_tag)
        return

    update_job(job_id, status="PROCESSANDO")
    print(f"[{job_id}] convertendo {payload['sourceFormat']} -> {payload['targetFormat']}", flush=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src_path = f"{tmp}/source.{payload['sourceFormat']}"
            out_path = f"{tmp}/result.{payload['targetFormat']}"

            download_file(BUCKET_UPLOADS, payload["sourceObject"], src_path)
            CONVERTERS[payload["sourceType"]](src_path, out_path)

            result_object = f"{job_id}.{payload['targetFormat']}"
            upload_file(BUCKET_CONVERTED, result_object, out_path)
            result_url = public_url(BUCKET_CONVERTED, result_object)

            delete_object(BUCKET_UPLOADS, payload["sourceObject"])

        update_job(job_id, status="CONCLUIDO", resultUrl=result_url)
        print(f"[{job_id}] concluído", flush=True)
        publish_notification(ch, {
            "jobId": job_id, "status": "CONCLUIDO",
            "resultUrl": result_url, "notifyEmail": payload["notifyEmail"],
        })
        ch.basic_ack(method.delivery_tag)

    except Exception as e:
        print(f"[{job_id}] falhou: {e}", flush=True)
        attempt = payload.get("attempt", 1)
        if attempt >= MAX_ATTEMPTS:
            update_job(job_id, status="ERRO", error=str(e))
            publish_notification(ch, {
                "jobId": job_id, "status": "ERRO",
                "error": str(e), "notifyEmail": payload["notifyEmail"],
            })
            ch.basic_nack(method.delivery_tag, requeue=False)  # vai para a DLQ
        else:
            payload["attempt"] = attempt + 1
            publish_conversion(ch, payload)
            ch.basic_ack(method.delivery_tag)  # a cópia reenviada assume o trabalho

def main():
    ensure_buckets()
    conn, ch = get_channel()
    ch.basic_qos(prefetch_count=1)  # 1 mensagem por worker por vez -> competing consumers de verdade
    ch.basic_consume("conversao", process)
    print("Worker aguardando mensagens...", flush=True)
    ch.start_consuming()

if __name__ == "__main__":
    main()