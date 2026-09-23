// A tiny hash-routed SPA shaped like an EMR: each chart screen fetches JSON to draw itself.
// Synthetic patients only.
const view = document.getElementById("view");

async function api(url, asBlob) {
  const r = await fetch(url);
  if (r.status === 401) {
    location.href = "/login";
    throw new Error("logged out");
  }
  return asBlob ? r.blob() : r.json();
}

async function route() {
  const h = location.hash.slice(1) || "/patients/page/1";
  api("/api/notifications").catch(() => {}); // unrelated traffic the walker must ignore
  let m;
  if ((m = h.match(/^\/patients\/page\/(\d+)$/))) {
    const data = await api(`/api/patients?page=${m[1]}`);
    view.textContent = `patients: ${data.items.length}`;
  } else if ((m = h.match(/^\/patients\/([^/]+)\/summary$/))) {
    const p = await api(`/api/patients/${m[1]}`);
    view.textContent = `summary ${p.patient_id}`;
  } else if ((m = h.match(/^\/patients\/([^/]+)\/labs$/))) {
    const labs = await api(`/api/patients/${m[1]}/labs`);
    view.textContent = `labs: ${labs.results.length}`;
  } else if ((m = h.match(/^\/patients\/([^/]+)\/files$/))) {
    const files = await api(`/api/patients/${m[1]}/files`);
    for (const f of files.files) {
      await api(`/api/files/${f.file_id}/content`, true);
    }
    view.textContent = `files: ${files.files.length}`;
  } else {
    view.textContent = "not found";
  }
}

window.addEventListener("hashchange", route);
route();
