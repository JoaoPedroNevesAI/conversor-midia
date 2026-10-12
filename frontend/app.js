const API = "http://localhost:8000";

document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData();
  fd.append("file", document.getElementById("file").files[0]);
  fd.append("target_format", document.getElementById("target").value);
  fd.append("email", document.getElementById("email").value);

  const res = await fetch(`${API}/jobs`, { method: "POST", body: fd });
  const { jobId } = await res.json();
  document.getElementById("status").textContent = `Job criado: ${jobId}`;

  const poll = setInterval(async () => {
    const r = await fetch(`${API}/jobs/${jobId}`);
    const job = await r.json();
    document.getElementById("status").textContent = `Status: ${job.status}`;
    if (job.status === "CONCLUIDO" || job.status === "ERRO") clearInterval(poll);
  }, 2000);
});