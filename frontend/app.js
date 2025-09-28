// frontend/app.js
// ===================================================================
// GeoLocate MVP — фронт без JWT
// - Регистрация/Вход (localStorage)
// - Загрузка фото (meta JSON или lat/lon)
// - Поиск по адресу: карта Leaflet + превью
// - Список фото с пагинацией
// - BBox (create/list), Экспорт XLSX
// ===================================================================

const $ = (sel) => document.querySelector(sel);
const val = (sel) => ($(sel)?.value ?? "").trim();

function setText(sel, text) { const el = $(sel); if (el) el.textContent = text; }
function show(el, on = true) { if (typeof el === "string") el = $(el); if (!el) return; el.style.display = on ? "" : "none"; }
function toast(msg, ok = true) { console[ok ? "log" : "warn"](msg); if (!ok) alert(msg); }

// ---------- Auth ----------
function saveUser(user) { localStorage.setItem("user", JSON.stringify(user || null)); }
function getUser() { try { return JSON.parse(localStorage.getItem("user")); } catch { return null; } }
function clearUser() { localStorage.removeItem("user"); }
function renderAuthStatus() {
  const user = getUser();
  const statusEl = $("#authStatus");
  const logoutBtn = $("#logoutBtn");
  if (user && user.name) { statusEl && (statusEl.textContent = `Вы вошли как: ${user.name}`); show(logoutBtn, true); }
  else { statusEl && (statusEl.textContent = "Гость"); show(logoutBtn, false); }
}

async function apiJSON(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  try {
    const data = text ? JSON.parse(text) : {};
    if (!res.ok) throw new Error(data.error || text || `HTTP ${res.status}`);
    return data;
  } catch (e) {
    if (!res.ok) throw new Error(text || e.message);
    return {};
  }
}

async function register() {
  const name = val("#reg_name"); const password = $("#reg_pass")?.value ?? ""; const role = val("#reg_role") || "viewer";
  setText("#reg_out", "..."); try {
    const data = await apiJSON("/api/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, password, role }) });
    setText("#reg_out", JSON.stringify(data, null, 2));
  } catch (e) { setText("#reg_out", e.message); }
}
async function login() {
  const name = val("#login_name"); const password = $("#login_pass")?.value ?? "";
  setText("#login_out", "..."); try {
    const data = await apiJSON("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, password }) });
    if (data.user) saveUser(data.user); renderAuthStatus(); setText("#login_out", JSON.stringify(data, null, 2));
  } catch (e) { setText("#login_out", e.message); }
}
function logout() { clearUser(); renderAuthStatus(); toast("Вы вышли"); }

// ===================================================================
//                          Photos: pagination
// ===================================================================
const PhotosState = {
  page: 1,
  pageSize: 50,
  gotCount: 0, // сколько реально пришло в ответе
};
function updatePhotosPagerUI() {
  setText("#photos_page_info", `стр. ${PhotosState.page}${PhotosState.gotCount ? `, элементов: ${PhotosState.gotCount}` : ""}`);
  const prevBtn = $("#btnPrevPhotos"); const nextBtn = $("#btnNextPhotos");
  prevBtn && (prevBtn.disabled = PhotosState.page <= 1);
  // Если пришло меньше, чем pageSize — предполагаем, что дальше страницы нет
  nextBtn && (nextBtn.disabled = PhotosState.gotCount < PhotosState.pageSize);
}

async function loadPhotos(page = PhotosState.page, limit = PhotosState.pageSize) {
  PhotosState.page = Math.max(1, page);
  PhotosState.pageSize = limit;

  const box = $("#photos");
  if (box) box.textContent = "...";
  try {
    const offset = (PhotosState.page - 1) * PhotosState.pageSize;
    const data = await apiJSON(`/api/photos?limit=${PhotosState.pageSize}&offset=${offset}`);
    const photos = data.photos || [];
    PhotosState.gotCount = photos.length;
    updatePhotosPagerUI();

    if (!photos.length) { box && (box.textContent = "Пусто"); return; }

    const rows = photos.map((p) => {
      const link = `/api/photos/${p.uuid}`;
      const size = p.width && p.height ? `${p.width}×${p.height}` : "-";
      const lat = (p.shot_lat ?? "").toString();
      const lon = (p.shot_lon ?? "").toString();
      return `<tr>
        <td>${p.id}</td>
        <td>${p.name || "-"}</td>
        <td>${size}</td>
        <td>${lat}, ${lon}</td>
        <td><a href="${link}" target="_blank" rel="noopener">open</a></td>
      </tr>`;
    }).join("");

    box && (box.innerHTML = `<table>
      <thead><tr><th>id</th><th>name</th><th>size</th><th>lat/lon</th><th>file</th></tr></thead>
      <tbody>${rows}</tbody></table>`);
  } catch (e) {
    box && (box.textContent = e.message);
  }
}

// ===================================================================
//                          Upload
// ===================================================================
async function upload() {
  const file = $("#file")?.files?.[0];
  const out = $("#upload_out");
  if (!file) { out && (out.textContent = "Выберите файл"); return; }

  const fd = new FormData();
  fd.append("image", file, file.name);
  const type = val("#type"); const subtype = val("#subtype");
  if (type) fd.append("type", type);
  if (subtype) fd.append("subtype", subtype);

  const metaFile = $("#meta")?.files?.[0];
  const lat = val("#shot_lat"); const lon = val("#shot_lon");
  if (metaFile) fd.append("meta", metaFile, metaFile.name);
  else { if (lat) fd.append("shot_lat", lat); if (lon) fd.append("shot_lon", lon); }

  out && (out.textContent = "Загрузка...");
  try {
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const text = await res.text();
    out && (out.textContent = text);
    loadPhotos(1, PhotosState.pageSize);
  } catch (e) {
    out && (out.textContent = e.message);
  }
}

// ===================================================================
//                          Objects (detecs)
// ===================================================================
async function sendDetect() {
  const photo_id = parseInt(val("#ph_id") || "0", 10);
  const x1 = parseInt(val("#x1") || "0", 10);
  const y1 = parseInt(val("#y1") || "0", 10);
  const x2 = parseInt(val("#x2") || "0", 10);
  const y2 = parseInt(val("#y2") || "0", 10);
  const label = val("#label") || "object";
  const confidence = parseFloat(val("#conf") || "0");
  const body = { photo_id, x1, y1, x2, y2, label, confidence };

  try {
    const res = await fetch("/api/detect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const text = await res.text();
    alert(text);
  } catch (e) { alert(e.message); }
}

async function loadObjects() {
  const photo_id = parseInt(val("#ph_id") || "0", 10);
  const box = $("#objects"); box && (box.textContent = "...");
  try {
    const data = await apiJSON(`/api/objects?photo_id=${photo_id}`);
    const arr = data.objects || [];
    if (!arr.length) { box && (box.textContent = "Пусто"); return; }
    const rows = arr.map((o) => {
      const lat = o.lat ?? o.latitude; const lon = o.lon ?? o.longitude;
      const ll = lat != null && lon != null ? `${(+lat).toFixed(6)}, ${(+lon).toFixed(6)}` : "-";
      const bbox = Array.isArray(o.bbox) ? o.bbox.join(", ") : (o.x1 != null ? [o.x1,o.y1,o.x2,o.y2].join(", ") : "-");
      return `<tr>
        <td>${o.id}</td>
        <td>${o.label} (${o.confidence ?? "-"})</td>
        <td>[${bbox}]</td>
        <td>${ll}</td>
        <td>${o.created || "-"}</td>
      </tr>`;
    }).join("");
    box && (box.innerHTML = `<table>
      <thead><tr><th>id</th><th>label</th><th>bbox</th><th>lat/lon</th><th>created</th></tr></thead>
      <tbody>${rows}</tbody></table>`);
  } catch (e) {
    box && (box.textContent = e.message);
  }
}

// ===================================================================
//                          Search + Leaflet Map
// ===================================================================
let _leafletMap = null;
let _leafletMarkers = [];

function ensureMap() {
  if (_leafletMap) return _leafletMap;
  _leafletMap = L.map("map");
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(_leafletMap);
  // дефолтный центр — Москва
  _leafletMap.setView([55.751244, 37.618423], 11);
  return _leafletMap;
}
function clearMarkers() { _leafletMarkers.forEach(m => m.remove()); _leafletMarkers = []; }
function addMarker(lat, lon, html) {
  const marker = L.marker([lat, lon]).addTo(_leafletMap);
  if (html) marker.bindPopup(html);
  _leafletMarkers.push(marker);
  return marker;
}

async function searchAddress() {
  const q = val("#addr");
  const outJson = $("#search_out"); const meta = $("#search_meta"); const grid = $("#search_results");

  if (outJson) outJson.textContent = "..."; if (meta) meta.textContent = ""; if (grid) grid.innerHTML = "";

  try {
    const data = await apiJSON(`/api/search_address?q=${encodeURIComponent(q)}`);
    outJson && (outJson.textContent = JSON.stringify(data, null, 2));

    // подготовка карты
    const map = ensureMap();
    clearMarkers();

    // адресная точка
    if (data.lat != null && data.lon != null) {
      const lat = +data.lat, lon = +data.lon;
      meta && (meta.textContent = `Координаты адреса: ${lat.toFixed(6)}, ${lon.toFixed(6)}. Найдено фото: ${data.results?.length ?? 0}`);
      addMarker(lat, lon, `<b>Адрес</b><br>${lat.toFixed(6)}, ${lon.toFixed(6)}`);
      map.setView([lat, lon], 15);
    }

    // превью карточек
    if (Array.isArray(data.results) && grid) {
      const cards = data.results.map((r) => {
        const href = `/api/photos/${r.uuid}`;
        const title = `${r.name || r.uuid}`;
        const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
        const ll = (r.shot_lat != null && r.shot_lon != null) ? `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}` : "";

        // маркер фото на карте (если есть координаты)
        if (r.shot_lat != null && r.shot_lon != null) {
          addMarker(+r.shot_lat, +r.shot_lon,
            `<div style="max-width:220px">
               <div class="ellipsis" title="${title}"><b>${title}</b></div>
               <div>${dist}${dist && ll ? " · " : ""}${ll}</div>
               <div style="margin-top:6px"><a href="${href}" target="_blank" rel="noopener">open</a></div>
             </div>`
          );
        }

        return `
          <div class="card-photo">
            <a class="thumb" href="${href}" target="_blank" rel="noopener" title="${title}">
              <img src="${href}" alt="${title}">
            </a>
            <div class="meta">
              <div class="ellipsis" title="${title}">${title}</div>
              <div style="color:#666;">${dist}${dist && ll ? " · " : ""}${ll}</div>
              <div><a href="${href}" target="_blank" rel="noopener">open</a></div>
            </div>
          </div>`;
      }).join("");
      grid.innerHTML = cards || `<div style="color:#666">Ничего не найдено</div>`;
    }
  } catch (e) {
    outJson && (outJson.textContent = e.message);
  }
}

// ===================================================================
//                          Calc + Export
// ===================================================================
async function calcForPhoto() {
  const photo_id = parseInt(val("#calc_photo_id") || val("#ph_id") || "0", 10);
  const out = $("#calc_out");
  out && (out.textContent = "...");
  try {
    const data = await apiJSON("/api/calc_for_photo", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ photo_id })
    });
    out && (out.textContent = JSON.stringify(data, null, 2));
    if ($("#ph_id")) $("#ph_id").value = photo_id;
    loadObjects();
  } catch (e) { out && (out.textContent = e.message); }
}

async function exportXlsx() {
  try {
    const res = await fetch("/api/export_xlsx", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    a.href = url; a.download = `export_${ts}.xlsx`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (e) { toast(`Экспорт не удался: ${e.message}`, false); }
}

// ===================================================================
//                          Bind UI
// ===================================================================
document.addEventListener("DOMContentLoaded", () => {
  $("#logoutBtn")?.addEventListener("click", logout);
  renderAuthStatus();

  // Кнопки
  $("#btnRegister")?.addEventListener("click", register);
  $("#btnLogin")?.addEventListener("click", login);
  $("#btnUpload")?.addEventListener("click", upload);
  $("#btnSendDetect")?.addEventListener("click", sendDetect);
  $("#btnLoadObjects")?.addEventListener("click", loadObjects);
  $("#btnSearchAddress")?.addEventListener("click", searchAddress);
  $("#btnCalc")?.addEventListener("click", calcForPhoto);
  $("#btnExportXlsx")?.addEventListener("click", exportXlsx);

  // Пагинация фото
  const pageSizeSel = $("#photos_page_size");
  const prevBtn = $("#btnPrevPhotos");
  const nextBtn = $("#btnNextPhotos");
  const refreshBtn = $("#btnLoadPhotos");

  pageSizeSel?.addEventListener("change", () => {
    PhotosState.pageSize = parseInt(pageSizeSel.value, 10) || 50;
    PhotosState.page = 1;
    loadPhotos(PhotosState.page, PhotosState.pageSize);
  });
  prevBtn?.addEventListener("click", () => {
    if (PhotosState.page > 1) loadPhotos(PhotosState.page - 1, PhotosState.pageSize);
  });
  nextBtn?.addEventListener("click", () => {
    // Разрешаем двигаться вперёд только если предыдущая страница была "полной"
    if (PhotosState.gotCount >= PhotosState.pageSize) {
      loadPhotos(PhotosState.page + 1, PhotosState.pageSize);
    }
  });
  refreshBtn?.addEventListener("click", () => {
    loadPhotos(PhotosState.page, PhotosState.pageSize);
  });

  // Первичная загрузка
  // (Если у тебя фоток много, можешь поставить 25 по умолчанию в select)
  if ($("#photos_page_size")) {
    PhotosState.pageSize = parseInt($("#photos_page_size").value, 10) || 50;
  }
  loadPhotos(1, PhotosState.pageSize);
});
