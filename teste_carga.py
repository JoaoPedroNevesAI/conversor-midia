import requests, time

API = "http://localhost:8000"
FILE_PATH = r"C:\Users\user\Videos\Josino.mp4"
N = 6

job_ids = []
start = time.time()
for _ in range(N):
    with open(FILE_PATH, "rb") as f:
        r = requests.post(f"{API}/jobs", files={"file": f},
                          data={"target_format": "avi", "email": "teste@exemplo.com"})
        job_ids.append(r.json()["jobId"])
print(f"{N} jobs aceitos em {time.time() - start:.1f}s")

while True:
    statuses = [requests.get(f"{API}/jobs/{j}").json()["status"] for j in job_ids]
    print(statuses)
    if all(s in ("CONCLUIDO", "ERRO") for s in statuses):
        break
    time.sleep(2)

print(f"Tempo total até todos concluírem: {time.time() - start:.1f}s")