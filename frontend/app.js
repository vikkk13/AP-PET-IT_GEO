// ===================================================================
// GeoLocate MVP — фронт без JWT
// - Регистрация/Вход (localStorage)
// - Загрузка фото (meta JSON формируется автоматически из lat/lon/type/subtype)
// - Поиск по адресу: карта Leaflet + превью
// - Поиск по координатам (топ-N) и по названию файла
// - Список фото с пагинацией (total)
// - Запуск расчёта координат (админ): список загрузок 5/стр + запуск
// - Выгрузка в Excel с выбором полей (админ)
// ===================================================================

const $ = (sel) => document.querySelector(sel);
const val = (sel) => ($(sel)?.value ?? "").trim();

function setText(sel, text) { const el = $(sel); if (el) el.textContent = text; }
function show(el, on = true) { if (typeof el === "string") el = $(el); if (!el) return; el.style.display = on ? "" : "none"; }
function toast(msg, ok = true) { console[ok ? "log" : "warn"](msg); if (!ok) alert(msg); }

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

// ---------- Auth ----------
function saveUser(user) { localStorage.setItem("user", JSON.stringify(user || null)); }
function getUser() { try { return JSON.parse(localStorage.getItem("user")); } catch { return null; } }
function clearUser() { localStorage.removeItem("user"); }
function isAdminUser(user) { return !!(user && ["admin","Админ","administrator"].includes(user.role)); }

function renderAuthStatus() {
  const user = getUser();
  const statusEl = $("#authStatus");
  const logoutBtn = $("#logoutBtn");
  const isAdmin = isAdminUser(user);

  if (user && user.name) {
    statusEl && (statusEl.textContent = `Вы вошли как: ${user.name}${user.role ? ` (${user.role})` : ""}`);
    show(logoutBtn, true);
  } else {
    statusEl && (statusEl.textContent = "Гость");
    show(logoutBtn, false);
  }

  // показать/скрыть админ-блоки
  show("#cardRegister", isAdmin);
  show("#cardUsers", isAdmin);
  show("#cardCalc", isAdmin);
  show("#cardExport", isAdmin);
}

async function register() {
  const name = val("#reg_name");
  const password = $("#reg_pass")?.value ?? "";
  const allowedRoles = ["admin","uploader","runner","viewer","exporter"];
  const chosen = val("#reg_role") || "viewer";
  const role = allowedRoles.includes(chosen) ? chosen : "viewer";

  setText("#reg_out", "...");
  try {
    const data = await apiJSON("/api/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, password, role })
    });
    setText("#reg_out", JSON.stringify(data, null, 2));
  } catch (e) { setText("#reg_out", e.message); }
}

async function login() {
  const name = val("#login_name"); const password = $("#login_pass")?.value ?? "";
  setText("#login_out", "...");
  try {
    const data = await apiJSON("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, password })
    });
    if (data.user) saveUser(data.user);
    renderAuthStatus();
    if (isAdminUser(getUser())) loadUploads(1); // админ — подгружаем список загрузок
    setText("#login_out", JSON.stringify(data, null, 2));
  } catch (e) { setText("#login_out", e.message); }
}
function logout() { clearUser(); renderAuthStatus(); toast("Вы вышли"); }

// ===================================================================
//                          Photos: pagination
// ===================================================================
const PhotosState = { page: 1, pageSize: 5, gotCount: 0, total: 0 };

function updatePhotosPagerUI() {
  const totalPages = Math.max(1, Math.ceil((PhotosState.total || 0) / PhotosState.pageSize));
  setText("#photos_page_info",
    `стр. ${PhotosState.page} из ${totalPages}` +
    (PhotosState.total ? `, всего: ${PhotosState.total}` : "") +
    (PhotosState.gotCount ? `, на странице: ${PhotosState.gotCount}` : "")
  );
  $("#btnPrevPhotos") && ($("#btnPrevPhotos").disabled = PhotosState.page <= 1);
  $("#btnNextPhotos") && ($("#btnNextPhotos").disabled = PhotosState.page >= totalPages);
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
    PhotosState.total = Number(data.total || 0);
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
        <td class="ellipsis" title="${p.name || "-"}">${p.name || "-"}</td>
        <td>${size}</td>
        <td>${lat}, ${lon}</td>
        <td><a href="${link}" target="_blank" rel="noopener">open</a></td>
      </tr>`;
    }).join("");

    box && (box.innerHTML = `<table>
      <thead><tr><th>id</th><th>name</th><th>size</th><th>lat/lon</th><th>file</th></tr></thead>
      <tbody>${rows}</tbody></table>`);
  } catch (e) { box && (box.textContent = e.message); }
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

  const type = val("#type");
  const subtype = val("#subtype");
  if (type) fd.append("type", type);
  if (subtype) fd.append("subtype", subtype);

  const lat = val("#shot_lat");
  const lon = val("#shot_lon");

  // meta.json из заполненных полей
  const meta = {};
  if (lat) meta.lat = parseFloat(lat);
  if (lon) meta.lon = parseFloat(lon);
  if (type) meta.type = type;
  if (subtype) meta.subtype = subtype;
  if (Object.keys(meta).length) {
    const blob = new Blob([JSON.stringify(meta)], { type: "application/json" });
    fd.append("meta", blob, "meta.json");
  }

  out && (out.textContent = "Загрузка...");
  try {
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const text = await res.text();

    let msg = text;
    try { const data = text ? JSON.parse(text) : null; if (data?.photo) msg = `✅ Загружено: ${data.photo.name} (id=${data.photo.id})`; } catch {}
    out && (out.textContent = msg);

    const f = $("#file")?.files?.[0];
    if (f) setText("#file_info", `Фото: ${f.name} (${(f.size/1024).toFixed(1)} KB) — загружено`);

    loadPhotos(1, PhotosState.pageSize);
  } catch (e) { out && (out.textContent = `Ошибка: ${e.message}`); }
}

// ===================================================================
//                          Users (admin)
// ===================================================================
async function loadUsers() {
  const box = $("#users_out");
  if (box) box.textContent = "...";
  try {
    const data = await apiJSON("/api/users");
    const arr = data.users || data || [];
    if (!Array.isArray(arr) || !arr.length) { box && (box.textContent = "Пусто"); return; }
    const rows = arr.map((u) => {
      const id = u.id ?? u.user_id ?? "-";
      const name = u.name ?? u.username ?? "-";
      const role = u.role ?? "-";
      const created = u.created ?? u.created_at ?? "-";
      return `<tr><td>${id}</td><td class="ellipsis" title="${name}">${name}</td><td>${role}</td><td>${created}</td></tr>`;
    }).join("");
    box && (box.innerHTML = `<table>
      <thead><tr><th>id</th><th>name</th><th>role</th><th>created</th></tr></thead>
      <tbody>${rows}</tbody></table>`);
  } catch (e) {
    const msg = (e.message || "").includes("404") ? "Эндпоинт /api/users не найден (нужна поддержка в auth-service)" : e.message;
    box && (box.textContent = msg);
  }
}

// ===================================================================
//                Search + Leaflet Map (address / coords / name)
// ===================================================================
let _leafletMap = null;
let _leafletMarkers = [];

function ensureMap() {
  if (_leafletMap) return _leafletMap;
  _leafletMap = L.map('map', { attributionControl: false });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '' }).addTo(_leafletMap);
  L.control.attribution({ prefix: false }).addAttribution('© OpenStreetMap contributors').addTo(_leafletMap);
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

// --- поиск по адресу ---
async function searchAddress() {
  const q = val("#addr");
  const outJson = $("#search_out"); const meta = $("#search_meta"); const grid = $("#search_results");
  if (outJson) outJson.textContent = "..."; if (meta) meta.textContent = ""; if (grid) grid.innerHTML = "";

  try {
    const data = await apiJSON(`/api/search_address?q=${encodeURIComponent(q)}`);
    outJson && (outJson.textContent = JSON.stringify(data, null, 2));

    const map = ensureMap();
    clearMarkers();

    if (data.lat != null && data.lon != null) {
      const lat = +data.lat, lon = +data.lon;
      meta && (meta.textContent = `Координаты адреса: ${lat.toFixed(6)}, ${lon.toFixed(6)}. Найдено фото: ${data.results?.length ?? 0}`);
      addMarker(lat, lon, `<b>Адрес</b><br>${lat.toFixed(6)}, ${lon.toFixed(6)}`);
      map.setView([lat, lon], 15);
    }

    if (Array.isArray(data.results) && grid) {
      const cards = data.results.map((r) => {
        const href = `/api/photos/${r.uuid}`;
        const title = `${r.name || r.uuid}`;
        const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
        const ll = (r.shot_lat != null && r.shot_lon != null) ? `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}` : "";
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
  } catch (e) { outJson && (outJson.textContent = e.message); }
}

// --- поиск по координатам (без радиуса, топ-N ближайших) ---
async function searchCoords() {
  const lat = parseFloat(val("#coord_lat"));
  const lon = parseFloat(val("#coord_lon"));
  const limit = parseInt(val("#coord_limit") || "12", 10);

  const meta = $("#coords_meta");
  const grid = $("#coords_results");
  if (meta) meta.textContent = "";
  if (grid) grid.innerHTML = "";

  if (Number.isNaN(lat) || Number.isNaN(lon)) { meta && (meta.textContent = "Укажи корректные lat/lon"); return; }

  try {
    const url = `/api/search_coords?lat=${lat}&lon=${lon}&limit=${limit}`;
    const data = await apiJSON(url);

    meta && (meta.textContent = `Найдено: ${data.results?.length ?? 0} (топ-${limit} ближайших)`);

    const map = ensureMap();
    clearMarkers();
    addMarker(lat, lon, `<b>Центр</b><br>${lat.toFixed(6)}, ${lon.toFixed(6)}`);
    map.setView([lat, lon], 15);

    if (Array.isArray(data.results) && grid) {
      const cards = data.results.map((r) => {
        const href = `/api/photos/${r.uuid}`;
        const title = `${r.name || r.uuid}`;
        const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
        const ll = (r.shot_lat != null && r.shot_lon != null) ? `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}` : "";
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
  } catch (e) { meta && (meta.textContent = e.message); }
}

// --- поиск по названию файла ---
async function searchByName() {
  const q = val("#name_q");
  const limit = parseInt(val("#name_limit") || "25", 10);
  const meta = $("#name_meta");
  const box = $("#name_results");
  if (meta) meta.textContent = "...";
  if (box) box.textContent = "";

  try {
    const data = await apiJSON(`/api/search_name?q=${encodeURIComponent(q)}&limit=${limit}&offset=0`);
    const photos = data.photos || [];
    meta && (meta.textContent = `Всего по фильтру: ${data.total ?? 0}, показано: ${photos.length}`);

    if (!photos.length) { box && (box.textContent = "Пусто"); return; }

    const rows = photos.map((p) => {
      const link = `/api/photos/${p.uuid}`;
      const size = p.width && p.height ? `${p.width}×${p.height}` : "-";
      const lat = (p.shot_lat ?? "").toString();
      const lon = (p.shot_lon ?? "").toString();
      return `<tr>
        <td>${p.id}</td>
        <td class="ellipsis" title="${p.name || "-"}">${p.name || "-"}</td>
        <td>${size}</td>
        <td>${lat}, ${lon}</td>
        <td><a href="${link}" target="_blank" rel="noopener">open</a></td>
      </tr>`;
    }).join("");

    box && (box.innerHTML = `<table>
      <thead><tr><th>id</th><th>name</th><th>size</th><th>lat/lon</th><th>file</th></tr></thead>
      <tbody>${rows}</tbody></table>`);
  } catch (e) { meta && (meta.textContent = e.message); }
}

// ===================================================================
//                 Admin: список загрузок + запуск расчёта
// ===================================================================
const UploadsState = { page: 1, pageSize: 5, gotCount: 0, total: 0, selectedId: null };

function updateUploadsPagerUI() {
  const totalPages = Math.max(1, Math.ceil((UploadsState.total || 0) / UploadsState.pageSize));
  setText("#uploads_page_info", `стр. ${UploadsState.page} из ${totalPages}`);
  $("#btnPrevUploads") && ($("#btnPrevUploads").disabled = UploadsState.page <= 1);
  $("#btnNextUploads") && ($("#btnNextUploads").disabled = UploadsState.page >= totalPages);
}

function selectUpload(id) {
  UploadsState.selectedId = id;
  const btn = $("#btnRunCalc");
  if (btn) btn.disabled = !id;
  document.querySelectorAll('input[name="upload_pick"]').forEach(r => { r.checked = (String(r.value) === String(id)); });
}

async function loadUploads(page = UploadsState.page) {
  UploadsState.page = Math.max(1, page);
  const box = $("#uploads");
  if (box) box.textContent = "...";
  try {
    const offset = (UploadsState.page - 1) * UploadsState.pageSize;
    const data = await apiJSON(`/api/photos?limit=${UploadsState.pageSize}&offset=${offset}`);
    const arr = data.photos || [];
    UploadsState.total = Number(data.total || 0);
    UploadsState.gotCount = arr.length;
    updateUploadsPagerUI();

    if (!arr.length) { box && (box.textContent = "Пусто"); return; }

    const rows = arr.map((p, idx) => {
      const created = p.created || "-";
      const size = (p.width && p.height) ? `${p.width}×${p.height}` : "-";
      const radioId = `u_${p.id}`;
      return `<tr>
        <td style="width:34px;text-align:center;">
          <input type="radio" name="upload_pick" id="${radioId}" value="${p.id}" ${idx===0 && UploadsState.page===1 ? "checked" : ""} />
        </td>
        <td><label for="${radioId}" class="ellipsis" title="${p.name || "-"}">${p.name || "-"}</label></td>
        <td>${size}</td>
        <td>${created}</td>
        <td><a href="/api/photos/${p.uuid}" target="_blank" rel="noopener">open</a></td>
      </tr>`;
    }).join("");

    box && (box.innerHTML = `<table>
      <thead><tr><th></th><th>name</th><th>size</th><th>created</th><th>file</th></tr></thead>
      <tbody>${rows}</tbody></table>`);

    document.querySelectorAll('input[name="upload_pick"]').forEach(r => {
      r.addEventListener("change", (e) => selectUpload(e.target.value));
    });

    if (UploadsState.page === 1 && arr[0]) selectUpload(arr[0].id);
  } catch (e) { box && (box.textContent = e.message); }
}

async function runCalcForSelected() {
  const id = UploadsState.selectedId;
  const out = $("#calc_out");
  if (!id) { out && (out.textContent = "Выберите загрузку"); return; }
  out && (out.textContent = "Выполняю расчёт...");

  try {
    const data = await apiJSON("/api/calc_for_photo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ photo_id: Number(id) })
    });
    out && (out.textContent = data?.message || "Готово");
  } catch (e) { out && (out.textContent = e.message); }
}

// ===================================================================
//                          Export (админ, выбор полей)
// ===================================================================
function getExportFields() {
  return Array.from(document.querySelectorAll('input[name="export_field"]:checked')).map(i => i.value);
}
function setExportFields(checked) {
  document.querySelectorAll('input[name="export_field"]').forEach(i => { i.checked = !!checked; });
}
async function exportXlsx() {
  const out = $("#export_status");
  const fields = getExportFields();
  const onlyHouses = $("#export_only_houses")?.checked || false;

  if (!fields.length) { out && (out.textContent = "Выберите хотя бы одно поле"); return; }

  out && (out.textContent = "Готовлю файл...");
  try {
    const res = await fetch("/api/export_xlsx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, filter: { label: onlyHouses ? "house" : null } })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    a.href = url; a.download = `export_${ts}.xlsx`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);

    out && (out.textContent = `✅ Готово (${fields.length} полей)`);
  } catch (e) { out && (out.textContent = `Ошибка: ${e.message}`); }
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
  $("#btnLoadUsers")?.addEventListener("click", loadUsers);
  $("#btnSearchAddress")?.addEventListener("click", searchAddress);
  $("#btnSearchCoords")?.addEventListener("click", searchCoords);
  $("#btnSearchName")?.addEventListener("click", searchByName);

  // Export (с выбором полей)
  $("#btnExportSelectAll")?.addEventListener("click", () => setExportFields(true));
  $("#btnExportClear")?.addEventListener("click", () => setExportFields(false));
  $("#btnExportXlsx")?.addEventListener("click", exportXlsx);

  // Admin: загрузки + запуск
  $("#btnPrevUploads")?.addEventListener("click", () => { if (UploadsState.page > 1) loadUploads(UploadsState.page - 1); });
  $("#btnNextUploads")?.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil((UploadsState.total || 0) / UploadsState.pageSize));
    if (UploadsState.page < totalPages) loadUploads(UploadsState.page + 1);
  });
  $("#btnLoadUploads")?.addEventListener("click", () => loadUploads(UploadsState.page));
  $("#btnRunCalc")?.addEventListener("click", runCalcForSelected);

  // Пагинация фото
  const pageSizeSel = $("#photos_page_size");
  $("#btnPrevPhotos")?.addEventListener("click", () => { if (PhotosState.page > 1) loadPhotos(PhotosState.page - 1, PhotosState.pageSize); });
  $("#btnNextPhotos")?.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil((PhotosState.total || 0) / PhotosState.pageSize));
    if (PhotosState.page < totalPages) loadPhotos(PhotosState.page + 1, PhotosState.pageSize);
  });
  $("#btnLoadPhotos")?.addEventListener("click", () => loadPhotos(PhotosState.page, PhotosState.pageSize));
  pageSizeSel?.addEventListener("change", () => {
    PhotosState.pageSize = parseInt(pageSizeSel.value, 10) || 50;
    PhotosState.page = 1;
    loadPhotos(PhotosState.page, PhotosState.pageSize);
  });

  // Имя/размер выбранного фото
  $("#file")?.addEventListener("change", () => {
    const f = $("#file")?.files?.[0];
    const info = f ? `Фото: ${f.name} (${(f.size/1024).toFixed(1)} KB)` : "Фото не выбрано";
    setText("#file_info", info);
  });

  // Первичная загрузка
  if ($("#photos_page_size")) PhotosState.pageSize = parseInt($("#photos_page_size").value, 10) || 50;
  loadPhotos(1, PhotosState.pageSize);

  // Если уже авторизован админ — подгрузим список загрузок
  if (isAdminUser(getUser())) loadUploads(1);
});
