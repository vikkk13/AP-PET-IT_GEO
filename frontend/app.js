// ===================================================================
// GeoLocate MVP — фронт без JWT
// - Регистрация/Вход (localStorage)
// - Загрузка фото (meta JSON формируется автоматически из lat/lon/type/subtype)
// - Предпросмотр выбранного файла до загрузки
// - Импорт ZIP-архивом (/api/upload_zip) + ПРЕДПРОСМОТР с пагинацией
// - Поиск по адресу: карта Leaflet + превью (показывать только при данных)
// - Поиск по координатам (топ-N)
// - Список фото с пагинацией (total)
// - Запуск расчёта координат (админ): список загрузок 5/стр + запуск
// - Выгрузка в Excel с выбором полей (админ)
// ===================================================================

const $ = (sel) => document.querySelector(sel);
const val = (sel) => ($(sel)?.value ?? "").trim();

function setText(sel, text) { const el = $(sel); if (el) el.textContent = text; }
function show(el, on = true) { if (typeof el === "string") el = $(el); if (!el) return; el.style.display = on ? "" : "none"; }
function toast(msg, ok = true) { console[ok ? "log" : "warn"](msg); if (!ok) alert(msg); }

// ===================================================================
// Предпросмотр выбранного изображения
// ===================================================================
let _filePreviewURL = null;
function updatePreview(file) {
  const wrap = $("#file_preview_wrap");
  const img  = $("#file_preview");

  if (_filePreviewURL) { try { URL.revokeObjectURL(_filePreviewURL); } catch {} _filePreviewURL = null; }

  if (!file || !file.type?.startsWith("image/")) {
    img?.removeAttribute("src");
    show(wrap, false);
    return;
  }

  _filePreviewURL = URL.createObjectURL(file);
  if (img) img.src = _filePreviewURL;
  show(wrap, true);

  img?.addEventListener("load", () => { try { URL.revokeObjectURL(_filePreviewURL); } catch {} _filePreviewURL = null; }, { once: true });
}

// ===================================================================
// ZIP preview state + автозагрузка JSZip
// ===================================================================
const ZipState = {
  zipFile: null,
  entries: [],   // [{name,size,index,entry}]
  page: 1,
  pageSize: 12,
  total: 0,
  urls: {},      // {index: objectURL}
};

function resetZipPreview() {
  Object.values(ZipState.urls).forEach(u => { try { URL.revokeObjectURL(u); } catch {} });
  ZipState.urls = {};
  ZipState.zipFile = null;
  ZipState.entries = [];
  ZipState.page = 1;
  ZipState.total = 0;
  setText("#zip_parse_status", "");
  setText("#zip_page_info", "стр. 1");
  setText("#zip_count_info", "");
  const grid = $("#zip_grid"); if (grid) grid.innerHTML = "";
  show("#zip_preview_wrap", false);
}

function isImageName(name) {
  if (!name) return false;
  return /\.(jpe?g|png|webp|bmp|gif|tiff?)$/i.test(name);
}

// --- автоподгрузка JSZip из CDN при первом использовании ---
let _jszipPromise = null;
function ensureJSZip() {
  if (window.JSZip) return Promise.resolve(window.JSZip);
  if (_jszipPromise) return _jszipPromise;
  _jszipPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js";
    s.async = true;
    s.onload = () => window.JSZip ? resolve(window.JSZip) : reject(new Error("JSZip не инициализировался"));
    s.onerror = () => reject(new Error("Не удалось загрузить JSZip с CDN"));
    document.head.appendChild(s);
  });
  return _jszipPromise;
}

// ленивое создание blob-URL для миниатюры
async function getEntryObjectURL(entry) {
  const key = entry.__idx;
  if (ZipState.urls[key]) return ZipState.urls[key];
  const blob = await entry.async("blob");
  const url = URL.createObjectURL(blob);
  ZipState.urls[key] = url;
  return url;
}

function updateZipPagerUI() {
  const totalPages = Math.max(1, Math.ceil((ZipState.total || 0) / ZipState.pageSize));
  setText("#zip_page_info", `стр. ${ZipState.page} из ${totalPages}`);
  $("#btnPrevZip") && ($("#btnPrevZip").disabled = ZipState.page <= 1);
  $("#btnNextZip") && ($("#btnNextZip").disabled = ZipState.page >= totalPages);
  setText("#zip_count_info", `Изображений: ${ZipState.total}`);
}

async function renderZipPage(page = ZipState.page) {
  ZipState.page = Math.max(1, page);
  const start = (ZipState.page - 1) * ZipState.pageSize;
  const end = Math.min(start + ZipState.pageSize, ZipState.total);
  const slice = ZipState.entries.slice(start, end);

  const grid = $("#zip_grid");
  if (!grid) return;

  grid.innerHTML = "";
  setText("#zip_parse_status", slice.length ? "" : "Пусто");

  for (const item of slice) {
    const card = document.createElement("div");
    card.className = "zip-thumb";

    const img = document.createElement("img");
    img.alt = item.name;

    try {
      const url = await getEntryObjectURL(item.entry);
      img.src = url;
    } catch {
      continue;
    }

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.title = `${item.name} (${(item.size/1024).toFixed(1)} KB)`;
    meta.textContent = item.name;

    card.appendChild(img);
    card.appendChild(meta);
    grid.appendChild(card);
  }

  updateZipPagerUI();
}

async function loadZipPreview(file) {
  resetZipPreview();
  if (!file) return;
  ZipState.zipFile = file;

  setText("#zip_parse_status", "Читаю ZIP…");
  show("#zip_preview_wrap", true);

  try {
    await ensureJSZip(); // гарантируем наличие JSZip
    const zip = await JSZip.loadAsync(file);

    const entries = [];
    let idx = 0;
    zip.forEach((relativePath, entry) => {
      if (entry.dir) return;
      if (!isImageName(entry.name)) return;
      entry.__idx = idx;
      entries.push({
        name: entry.name.split("/").pop(),
        size: (entry._data && (entry._data.uncompressedSize || entry._data.compressedSize)) || 0,
        index: idx++,
        entry
      });
    });

    entries.sort((a,b) => a.name.localeCompare(b.name, "ru"));
    ZipState.entries = entries;
    ZipState.total = entries.length;

    if (!ZipState.total) {
      setText("#zip_parse_status", "В ZIP не найдено изображений");
      updateZipPagerUI();
      return;
    }

    setText("#zip_parse_status", "");
    await renderZipPage(1);
  } catch (e) {
    setText("#zip_parse_status", `Ошибка чтения ZIP: ${e.message || e}`);
  }
}

// ===================================================================
// Fetch helper
// ===================================================================
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

// ===================================================================
// Auth
// ===================================================================
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
    if (isAdminUser(getUser())) loadUploads(1);
    setText("#login_out", JSON.stringify(data, null, 2));
  } catch (e) { setText("#login_out", e.message); }
}
function logout() { clearUser(); renderAuthStatus(); toast("Вы вышли"); }

// ===================================================================
// Photos: pagination
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
// Upload (single file)
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
    try {
      const data = text ? JSON.parse(text) : null;
      if (data?.photo) msg = `✅ Загружено: ${data.photo.name} (id=${data.photo.id})`;
    } catch {}
    out && (out.textContent = msg);

    const f = $("#file")?.files?.[0];
    if (f) setText("#file_info", `Фото: ${f.name} (${(f.size/1024).toFixed(1)} KB) — загружено`);

    loadPhotos(1, PhotosState.pageSize);
  } catch (e) {
    out && (out.textContent = `Ошибка: ${e.message}`);
  }

  updatePreview(null);
}

// ===================================================================
// Upload ZIP (bulk)
// ===================================================================
async function uploadZip() {
  const zf = $("#zip")?.files?.[0];
  const out = $("#zip_out");
  if (!zf) { out && (out.textContent = "Выберите ZIP-архив"); return; }

  const fd = new FormData();
  fd.append("archive", zf, zf.name);
  fd.append("zip", zf, zf.name);

  const type = val("#type");
  const subtype = val("#subtype");
  if (type)   fd.append("type", type);
  if (subtype) fd.append("subtype", subtype);

  out && (out.textContent = "Импортирую ZIP...");
  try {
    const res = await fetch("/api/upload_zip", { method: "POST", body: fd });
    const text = await res.text();

    let msg = text;
    try {
      const data = text ? JSON.parse(text) : null;
      if (data?.imported != null) {
        msg = `✅ Импортировано файлов: ${data.imported}` + (data.skipped ? `, пропущено: ${data.skipped}` : "");
      }
    } catch {}

    out && (out.textContent = msg);
    loadPhotos(1, PhotosState.pageSize);

    $("#zip").value = "";
    setText("#zip_info", "ZIP не выбран");
    resetZipPreview();
  } catch (e) {
    out && (out.textContent = `Ошибка: ${e.message}`);
  }
}

// ===================================================================
// Users (admin)
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
// Search + Leaflet Map (address / coords)
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
function showMap(on) {
  show("#map", on);
  if (on) setTimeout(() => ensureMap().invalidateSize(), 0);
}

async function searchAddress() {
  const q = val("#addr");
  const outJson = $("#search_out");
  const meta = $("#search_meta");
  const grid = $("#search_results");

  setText("#search_out", "...");
  setText("#search_meta", "");
  if (grid) { grid.innerHTML = ""; show("#search_results", false); }
  showMap(false);

  try {
    const data = await apiJSON(`/api/search_address?q=${encodeURIComponent(q)}`);
    outJson && (outJson.textContent = JSON.stringify(data, null, 2));

    const results = Array.isArray(data.results) ? data.results : [];
    const hasCards = results.length > 0;
    const hasAddr = (data.lat != null && data.lon != null);

    if (hasAddr || hasCards) {
      clearMarkers();
      if (hasAddr) {
        const lat = +data.lat, lon = +data.lon;
        setText("#search_meta", `Координаты адреса: ${lat.toFixed(6)}, ${lon.toFixed(6)}. Найдено фото: ${results.length}`);
        addMarker(lat, lon, `<b>Адрес</b><br>${lat.toFixed(6)}, ${lon.toFixed(6)}`);
        ensureMap().setView([lat, lon], 15);
      } else {
        setText("#search_meta", `Найдено фото: ${results.length}`);
      }
      showMap(true);
    }

    if (hasCards && grid) {
      const map = ensureMap();
      results.forEach((r) => {
        if (r.shot_lat != null && r.shot_lon != null) {
          const href = `/api/photos/${r.uuid}`;
          const title = `${r.name || r.uuid}`;
          const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
          const ll = `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}`;
          addMarker(+r.shot_lat, +r.shot_lon,
            `<div style="max-width:220px">
               <div class="ellipsis" title="${title}"><b>${title}</b></div>
               <div>${dist}${dist && ll ? " · " : ""}${ll}</div>
               <div style="margin-top:6px"><a href="${href}" target="_blank" rel="noopener">open</a></div>
             </div>`
          );
        }
      });

      const cards = results.map((r) => {
        const href = `/api/photos/${r.uuid}`;
        const title = `${r.name || r.uuid}`;
        const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
        const ll = (r.shot_lat != null && r.shot_lon != null) ? `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}` : "";
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

      grid.innerHTML = cards;
      show("#search_results", true);
    } else {
      show("#search_results", false);
    }
  } catch (e) {
    outJson && (outJson.textContent = e.message);
    showMap(false);
    show("#search_results", false);
  }
}

async function searchCoords() {
  const lat = parseFloat(val("#coord_lat"));
  const lon = parseFloat(val("#coord_lon"));
  const limit = parseInt(val("#coord_limit") || "12", 10);

  const meta = $("#coords_meta");
  const grid = $("#coords_results");

  setText("#coords_meta", "");
  if (grid) { grid.innerHTML = ""; show("#coords_results", false); }
  showMap(false);

  if (Number.isNaN(lat) || Number.isNaN(lon)) { setText("#coords_meta", "Укажи корректные lat/lon"); return; }

  try {
    const data = await apiJSON(`/api/search_coords?lat=${lat}&lon=${lon}&limit=${limit}`);
    const results = Array.isArray(data.results) ? data.results : [];
    setText("#coords_meta", `Найдено: ${results.length} (топ-${limit} ближайших)`);

    if (results.length > 0) {
      clearMarkers();
      addMarker(lat, lon, `<b>Центр</b><br>${lat.toFixed(6)}, ${lon.toFixed(6)}`);
      ensureMap().setView([lat, lon], 15);
      showMap(true);
    }

    if (results.length > 0 && grid) {
      const map = ensureMap();
      results.forEach((r) => {
        if (r.shot_lat != null && r.shot_lon != null) {
          const href = `/api/photos/${r.uuid}`;
          const title = `${r.name || r.uuid}`;
          const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
          const ll = `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}`;
          addMarker(+r.shot_lat, +r.shot_lon,
            `<div style="max-width:220px">
               <div class="ellipsis" title="${title}"><b>${title}</b></div>
               <div>${dist}${dist && ll ? " · " : ""}${ll}</div>
               <div style="margin-top:6px"><a href="${href}" target="_blank" rel="noopener">open</a></div>
             </div>`
          );
        }
      });

      const cards = results.map((r) => {
        const href = `/api/photos/${r.uuid}`;
        const title = `${r.name || r.uuid}`;
        const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
        const ll = (r.shot_lat != null && r.shot_lon != null)
          ? `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}`
          : "";
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

      grid.innerHTML = cards;
      show("#coords_results", true);
    } else {
      show("#coords_results", false);
    }
  } catch (e) {
    setText("#coords_meta", e.message);
    showMap(false);
    show("#coords_results", false);
  }
}

// ===================================================================
// Admin: список загрузок + запуск расчёта
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

    const wrap = $("#calc_preview_wrap");
    const img  = $("#calc_preview");
    const thumbs = $("#calc_preview_thumbs");

    if (data?.preview?.processed_image_url) {
      img.src = data.preview.processed_image_url;
      if (thumbs) {
        const singles = (data.preview.single_photos || []).filter(Boolean);
        thumbs.innerHTML = singles.map(u => `
          <a href="${u}" target="_blank" rel="noopener" style="display:block;border:1px solid #eee;border-radius:6px;overflow:hidden">
            <img src="${u}" alt="bbox" style="width:100%;display:block">
          </a>
        `).join("");
      }
      show(wrap, true);
    } else {
      show(wrap, false);
    }
  } catch (e) {
    out && (out.textContent = e.message);
    show("#calc_preview_wrap", false);
  }
}

// ===================================================================
// Export (админ, выбор полей)
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
// Bind UI
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
  $("#btnPickPhoto")?.addEventListener("click", () => $("#file")?.click());
  $("#btnPickZip")?.addEventListener("click",   () => $("#zip")?.click());

  // ZIP импорт + предпросмотр
  $("#btnUploadZip")?.addEventListener("click", uploadZip);
  $("#zip")?.addEventListener("change", () => {
    const f = $("#zip")?.files?.[0];
    const info = f ? `ZIP: ${f.name} (${(f.size/1024/1024).toFixed(2)} MB)` : "ZIP не выбран";
    setText("#zip_info", info);
    loadZipPreview(f);
  });
  $("#btnPrevZip")?.addEventListener("click", () => { if (ZipState.page > 1) renderZipPage(ZipState.page - 1); });
  $("#btnNextZip")?.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil((ZipState.total || 0) / ZipState.pageSize));
    if (ZipState.page < totalPages) renderZipPage(ZipState.page + 1);
  });

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
  pageSizeSel?.addEventListener("change", () => {
    PhotosState.pageSize = parseInt(pageSizeSel.value, 10) || 5;
    PhotosState.page = 1;
    loadPhotos(PhotosState.page, PhotosState.pageSize);
  });
  $("#btnPrevPhotos")?.addEventListener("click", () => { if (PhotosState.page > 1) loadPhotos(PhotosState.page - 1, PhotosState.pageSize); });
  $("#btnNextPhotos")?.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil((PhotosState.total || 0) / PhotosState.pageSize));
    if (PhotosState.page < totalPages) loadPhotos(PhotosState.page + 1, PhotosState.pageSize);
  });

  // Имя/размер выбранного фото + превью
  $("#file")?.addEventListener("change", () => {
    const f = $("#file")?.files?.[0];
    const info = f ? `Фото: ${f.name} (${(f.size/1024).toFixed(1)} KB)` : "Фото не выбрано";
    setText("#file_info", info);
    updatePreview(f);
  });

  // Первичная загрузка
  if (pageSizeSel) PhotosState.pageSize = parseInt(pageSizeSel.value, 10) || 5;
  loadPhotos(1, PhotosState.pageSize);

  // Если уже авторизован админ — подгрузим список загрузок
  if (isAdminUser(getUser())) loadUploads(1);

  // Спрятать карту/превью до первых результатов
  show("#map", false);
  show("#search_results", false);
  show("#coords_results", false);
  show("#file_preview_wrap", false);
  show("#zip_preview_wrap", false);
});
