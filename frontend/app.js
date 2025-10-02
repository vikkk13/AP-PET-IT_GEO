// ===================================================================
// GeoLocate MVP — фронт без JWT (исправленная версия)
// ===================================================================

/* ------------------------ Базовая конфигурация -------------------- */
// Можно переопределить в index.html через <script>window.API_BASE=...</script>
const API_BASE = (typeof window !== "undefined" && window.API_BASE) || "/api";

/* ------------------------ Утилиты ------------------------ */
const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const val = (sel) => ($(sel)?.value ?? "").trim();

function setText(target, text) {
  const el = typeof target === "string" ? $(target) : target;
  if (!el) return;
  el.textContent = text;
}
function show(target, on = true) {
  const el = typeof target === "string" ? $(target) : target;
  if (!el) return;
  el.style.display = on ? "" : "none";
}
function toast(msg, ok = true) {
  console[ok ? "log" : "warn"](msg);
  if (!ok) alert(msg);
}
function ymd(d) {
  if (!d) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function setDefault3YearsRangeIn(containerSel, fromSel, toSel) {
  const scope = typeof containerSel === "string" ? $(containerSel) : containerSel;
  if (!scope) return;
  const fromEl = scope.querySelector(fromSel);
  const toEl   = scope.querySelector(toSel);
  const to = new Date();
  const from = new Date(); from.setFullYear(to.getFullYear() - 3);
  if (fromEl && !fromEl.value) fromEl.value = ymd(from);
  if (toEl   && !toEl.value)   toEl.value   = ymd(to);
}
function buildQuery(params) {
  const p = Object.entries(params)
    .filter(([, v]) => !(v === undefined || v === null || v === "" || v === "all"))
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  return p ? `?${p}` : "";
}
function hasLatLon(p) { return p && p.shot_lat != null && p.shot_lon != null; }
function inDateRange(p, fromISO, toISO) {
  if (!fromISO && !toISO) return true;
  const created = p.created || p.created_at || p.uploaded_at;
  if (!created) return false;
  const ts = new Date(created).getTime();
  if (Number.isNaN(ts)) return false;
  if (fromISO && ts < new Date(fromISO).getTime()) return false;
  if (toISO   && ts > new Date(toISO).getTime() + 86399999) return false; // включительно
  return true;
}

/* ---------------- Утилиты API --------------------------- */
function isLikelyHtml(s) {
  return typeof s === "string" && /<!doctype html>|<html[\s>]/i.test(s);
}
async function apiJSON(url, options = {}) {
  const res  = await fetch(url, options);
  const ctype = res.headers.get("content-type") || "";
  const text = await res.text();

  const parseJsonSafe = () => {
    try { return text ? JSON.parse(text) : {}; }
    catch { return {}; }
  };

  if (!res.ok) {
    // дружелюбное сообщение вместо «простыни» HTML
    if (isLikelyHtml(text)) throw new Error(`HTTP ${res.status} ${res.statusText || ""}`.trim());
    const data = parseJsonSafe();
    const msg = (data && (data.error || data.message)) || text || `HTTP ${res.status}`;
    throw new Error(msg);
  }

  if (ctype.includes("application/json")) return parseJsonSafe();
  // на всякий случай — если апи вернул не-json, но 200
  return text ? { raw: text } : {};
}
const apiUrl = (path) => `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
const photoUrl = (uuid) => apiUrl(`/photos/${uuid}`);

/* ---------------- Предпросмотр одиночного файла --------- */
let _filePreviewURL = null;
function updatePreview(file) {
  const wrap = $("#file_preview_wrap");
  const img  = $("#file_preview");
  if (_filePreviewURL) { try { URL.revokeObjectURL(_filePreviewURL); } catch {} _filePreviewURL = null; }
  if (!file || !file.type?.startsWith("image/")) {
    img?.removeAttribute("src"); show(wrap, false); return;
  }
  _filePreviewURL = URL.createObjectURL(file);
  if (img) {
    img.src = _filePreviewURL;
    img.loading = "lazy";
    img.decoding = "async";
    img.onerror = () => { img.alt = "Не удалось отобразить превью"; };
  }
  show(wrap, true);
  img?.addEventListener("load", () => {
    try { URL.revokeObjectURL(_filePreviewURL); } catch {}
    _filePreviewURL = null;
  }, { once: true });
}

/* ---------------- ZIP предпросмотр (с JSZip) -------------- */
const ZipState = { zipFile:null, entries:[], page:1, pageSize:12, total:0, urls:{} };

function resetZipPreview() {
  Object.values(ZipState.urls).forEach(u => { try { URL.revokeObjectURL(u); } catch {} });
  Object.assign(ZipState, { zipFile:null, entries:[], page:1, total:0, urls:{} });
  setText("#zip_parse_status", ""); setText("#zip_page_info", "стр. 1"); setText("#zip_count_info", "");
  const grid = $("#zip_grid"); if (grid) grid.innerHTML = "";
  show("#zip_preview_wrap", false);
}
function isImageName(name) { return !!name && /\.(jpe?g|png|webp|bmp|gif|tiff?)$/i.test(name); }

let _jszipPromise = null;
function ensureJSZip() {
  if (window.JSZip) return Promise.resolve(window.JSZip);
  if (_jszipPromise) return _jszipPromise;
  _jszipPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js";
    s.async = true;
    s.onload  = () => window.JSZip ? resolve(window.JSZip) : reject(new Error("JSZip не инициализировался"));
    s.onerror = () => reject(new Error("Не удалось загрузить JSZip с CDN"));
    document.head.appendChild(s);
  });
  return _jszipPromise;
}
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
  const prev = $("#btnPrevZip"), next = $("#btnNextZip");
  if (prev) prev.disabled = ZipState.page <= 1;
  if (next) next.disabled = ZipState.page >= totalPages;
  setText("#zip_count_info", `Изображений: ${ZipState.total}`);
}
async function renderZipPage(page = ZipState.page) {
  ZipState.page = Math.max(1, page);
  const start = (ZipState.page - 1) * ZipState.pageSize;
  const end   = Math.min(start + ZipState.pageSize, ZipState.total);
  const slice = ZipState.entries.slice(start, end);
  const grid  = $("#zip_grid"); if (!grid) return;
  grid.innerHTML = ""; setText("#zip_parse_status", slice.length ? "" : "Пусто");
  for (const item of slice) {
    const card = document.createElement("div"); card.className = "zip-thumb";
    const img  = document.createElement("img"); img.alt = item.name;
    img.loading = "lazy"; img.decoding = "async";
    try { img.src = await getEntryObjectURL(item.entry); } catch { continue; }
    const meta = document.createElement("div"); meta.className = "meta";
    meta.title = `${item.name} (${(item.size/1024).toFixed(1)} KB)`; meta.textContent = item.name;
    card.appendChild(img); card.appendChild(meta); grid.appendChild(card);
  }
  updateZipPagerUI();
}
async function loadZipPreview(file) {
  resetZipPreview(); if (!file) return; ZipState.zipFile = file;
  setText("#zip_parse_status", "Читаю ZIP…"); show("#zip_preview_wrap", true);
  try {
    await ensureJSZip();
    const zip = await JSZip.loadAsync(file);
    const entries = []; let idx = 0;
    zip.forEach((_, entry) => {
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
    ZipState.entries = entries; ZipState.total = entries.length;
    if (!ZipState.total) { setText("#zip_parse_status", "В ZIP не найдено изображений"); updateZipPagerUI(); return; }
    setText("#zip_parse_status", ""); await renderZipPage(1);
  } catch (e) {
    setText("#zip_parse_status", `Ошибка чтения ZIP: ${e.message || e}`);
  }
}

/* ---------------- Auth ----------------------------------- */
function saveUser(user) { localStorage.setItem("user", JSON.stringify(user || null)); }
function getUser() { try { return JSON.parse(localStorage.getItem("user")); } catch { return null; } }
function clearUser() { localStorage.removeItem("user"); }
function isAdminUser(user) { return !!(user && ["admin","Админ","administrator"].includes(user.role)); }

function renderAuthStatus() {
  const user = getUser();
  const statusEl = $("#authStatus");
  const logoutBtn = $("#logoutBtn");
  const isAdmin = isAdminUser(user);
  if (user && user.name) { statusEl && (statusEl.textContent = `Вы вошли как: ${user.name}${user.role ? ` (${user.role})` : ""}`); show(logoutBtn, true); }
  else { statusEl && (statusEl.textContent = "Гость"); show(logoutBtn, false); }
  show("#cardRegister", isAdmin);
  show("#cardUsers",    isAdmin);
  show("#cardCalc",     isAdmin);
  show("#cardExport",   isAdmin);
}
async function register() {
  const name = val("#reg_name");
  const password = $("#reg_pass")?.value ?? "";
  const allowedRoles = ["admin","uploader","runner","viewer","exporter"];
  const chosen = val("#reg_role") || "viewer";
  const role = allowedRoles.includes(chosen) ? chosen : "viewer";
  setText("#reg_out", "...");
  try {
    const data = await apiJSON(apiUrl("/register"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, password, role })
    });
    setText("#reg_out", JSON.stringify(data, null, 2));
  } catch (e) { setText("#reg_out", e.message); }
}
async function login() {
  const name = val("#login_name");
  const password = $("#login_pass")?.value ?? "";
  setText("#login_out", "...");
  try {
    const data = await apiJSON(apiUrl("/login"), {
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

/* ---------------- Photos (пагинация + фильтры) ----------- */
const PhotosState = { page:1, pageSize:5, gotCount:0, total:0 };

function getPhotosFilter() {
  const statusSel = $("#photos_filter_status");
  const df = $("#photos_date_from");
  const dt = $("#photos_date_to");
  const statusVal = statusSel ? statusSel.value : "all";
  return {
    has_coords: (statusVal === "with" ? "true" : statusVal === "without" ? "false" : "all"),
    date_from: df?.value || "",
    date_to:   dt?.value || ""
  };
}
function updatePhotosPagerUI() {
  const totalPages = Math.max(1, Math.ceil((PhotosState.total || 0) / PhotosState.pageSize));
  setText("#photos_page_info",
    `стр. ${PhotosState.page} из ${totalPages}` +
    (PhotosState.total ? `, всего: ${PhotosState.total}` : "") +
    (PhotosState.gotCount ? `, на странице: ${PhotosState.gotCount}` : "")
  );
  const prev = $("#btnPrevPhotos"), next = $("#btnNextPhotos");
  if (prev) prev.disabled = PhotosState.page <= 1;
  if (next) next.disabled = PhotosState.page >= totalPages;
}
async function loadPhotos(page = PhotosState.page, limit = PhotosState.pageSize) {
  PhotosState.page = Math.max(1, page);
  PhotosState.pageSize = limit;
  const box = $("#photos");
  if (box) box.textContent = "Загружаю…";
  const filter = getPhotosFilter();
  try {
    const offset = (PhotosState.page - 1) * PhotosState.pageSize;
    const q = buildQuery({
      limit: PhotosState.pageSize,
      offset,
      has_coords: filter.has_coords,
      date_from:  filter.date_from,
      date_to:    filter.date_to
    });
    const data = await apiJSON(apiUrl(`/photos${q}`));
    let photos = data.photos || [];
    PhotosState.total = Number(data.total || photos.length || 0);

    // Клиентские фильтры (подстраховка)
    if (filter.has_coords !== "all") {
      const need = (filter.has_coords === "true");
      photos = photos.filter(p => hasLatLon(p) === need);
    }
    if (filter.date_from || filter.date_to) photos = photos.filter(p => inDateRange(p, filter.date_from, filter.date_to));

    PhotosState.gotCount = photos.length;
    updatePhotosPagerUI();

    if (!photos.length) { box && (box.textContent = "Пусто"); return; }

    const rows = photos.map((p) => {
      const link = photoUrl(p.uuid);
      const size = p.width && p.height ? `${p.width}×${p.height}` : "-";
      const lat  = (p.shot_lat ?? "").toString();
      const lon  = (p.shot_lon ?? "").toString();
      const created = p.created || p.created_at || "-";
      const badge  = hasLatLon(p) ? '<span class="badge ok">coords</span>' : '<span class="badge warn">no coords</span>';
      return `<tr>
        <td>${p.id}</td>
        <td class="ellipsis" title="${p.name || "-"}">${p.name || "-"}</td>
        <td>${size}</td>
        <td>${lat}, ${lon}</td>
        <td>${created}</td>
        <td>${badge}</td>
        <td><a href="${link}" target="_blank" rel="noopener">open</a></td>
      </tr>`;
    }).join("");

    box && (box.innerHTML = `<table>
      <thead><tr><th>id</th><th>name</th><th>size</th><th>lat/lon</th><th>created</th><th>status</th><th>file</th></tr></thead>
      <tbody>${rows}</tbody></table>`);
  } catch (e) {
    // дружелюбное сообщение вместо HTML страницы ошибки
    box && (box.textContent = e.message || "Ошибка загрузки списка");
  }
}

/* ---------------- Upload (single) ------------------------ */
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
    const res  = await fetch(apiUrl("/upload"), { method: "POST", body: fd });
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

/* ---------------- Upload ZIP (bulk) ---------------------- */
async function uploadZip() {
  const zf = $("#zip")?.files?.[0];
  const out = $("#zip_out");
  if (!zf) { out && (out.textContent = "Выберите ZIP-архив"); return; }

  const fd = new FormData();
  // поддержим оба поля (на сервере тоже поддерживаются)
  fd.append("archive", zf, zf.name);
  fd.append("zip", zf, zf.name);

  const type = val("#type");
  const subtype = val("#subtype");
  if (type)   fd.append("type", type);
  if (subtype) fd.append("subtype", subtype);

  out && (out.textContent = "Импортирую ZIP...");
  try {
    const res  = await fetch(apiUrl("/upload_zip"), { method: "POST", body: fd });
    const text = await res.text();
    let msg = text;
    try {
      const data = text ? JSON.parse(text) : null;
      if (data?.imported != null) msg = `✅ Импортировано файлов: ${data.imported}` + (data.skipped ? `, пропущено: ${data.skipped}` : "");
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

/* ---------------- Users (admin) -------------------------- */
async function loadUsers() {
  const box = $("#users_out");
  if (box) box.textContent = "...";
  try {
    const data = await apiJSON(apiUrl("/users"));
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
    const msg = (e.message || "").includes("404")
      ? "Эндпоинт /api/users не найден (нужна поддержка в auth-service)"
      : e.message;
    box && (box.textContent = msg);
  }
}

/* ---------------- Map + поиски (fixed) ------------------- */
let _leafletMap = null;
let _leafletMarkers = [];

function ensureMap() {
  if (_leafletMap) return _leafletMap;
  const el = document.getElementById("map");
  if (!el) return null;
  _leafletMap = L.map(el, { attributionControl: false });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "" })
    .addTo(_leafletMap);
  L.control.attribution({ prefix: false })
    .addAttribution("© OpenStreetMap contributors")
    .addTo(_leafletMap);
  _leafletMap.setView([55.751244, 37.618423], 11);
  return _leafletMap;
}

function clearMarkers() {
  _leafletMarkers.forEach(m => m.remove());
  _leafletMarkers = [];
}

function addMarker(lat, lon, html) {
  const map = ensureMap();
  if (!map) return null;
  const marker = L.marker([lat, lon]).addTo(map);
  if (html) marker.bindPopup(html);
  _leafletMarkers.push(marker);
  return marker;
}

function showMap(on) {
  const el = document.getElementById("map");
  if (!el) return;
  el.style.display = on ? "" : "none";
  if (on) {
    const map = ensureMap();
    if (map) setTimeout(() => map.invalidateSize(), 0);
  }
}

async function searchAddress() {
  const q = val("#addr");
  const outJson = $("#search_out");
  const grid = $("#search_results");

  setText(outJson, "...");
  setText("#search_meta", "");
  if (grid) { grid.innerHTML = ""; show("#search_results", false); }
  showMap(false);

  try {
    const data = await apiJSON(apiUrl(`/search_address?q=${encodeURIComponent(q)}`));
    outJson && (outJson.textContent = JSON.stringify(data, null, 2));

    const results = Array.isArray(data.results) ? data.results : [];
    const hasAddr = (data.lat != null && data.lon != null);

    if (hasAddr || results.length) {
      // 1) Показать и создать карту
      showMap(true);
      const map = ensureMap();
      if (map) map.invalidateSize();

      // 2) Маркеры
      clearMarkers();
      if (hasAddr) {
        const lat = +data.lat, lon = +data.lon;
        setText("#search_meta", `Координаты адреса: ${lat.toFixed(6)}, ${lon.toFixed(6)}. Найдено фото: ${results.length}`);
        addMarker(lat, lon, `<b>Адрес</b><br>${lat.toFixed(6)}, ${lon.toFixed(6)}`);
        map && map.setView([lat, lon], 15);
      } else {
        setText("#search_meta", `Найдено фото: ${results.length}`);
      }

      // 3) Точки фото
      if (results.length && grid) {
        results.forEach((r) => {
          if (r.shot_lat != null && r.shot_lon != null) {
            const href = photoUrl(r.uuid);
            const title = `${r.name || r.uuid}`;
            const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
            const ll = `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}`;
            addMarker(+r.shot_lat, +r.shot_lon,
              `<div style="max-width:220px">
                 <div class="ellipsis" title="${title}"><b>${title}</b></div>
                 <div>${dist}${dist && ll ? " · " : ""}${ll}</div>
                 <div style="margin-top:6px"><a href="${href}" target="_blank" rel="noopener">open</a></div>
               </div>`);
          }
        });

        grid.innerHTML = results.map((r) => {
          const href = photoUrl(r.uuid);
          const title = `${r.name || r.uuid}`;
          const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
          const ll = (r.shot_lat != null && r.shot_lon != null)
            ? `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}`
            : "";
          return `
            <div class="card-photo">
              <a class="thumb" href="${href}" target="_blank" rel="noopener" title="${title}">
                <img src="${href}" alt="${title}" loading="lazy" decoding="async">
              </a>
              <div class="meta">
                <div class="ellipsis" title="${title}">${title}</div>
                <div style="color:#666;">${dist}${dist && ll ? " · " : ""}${ll}</div>
                <div><a href="${href}" target="_blank" rel="noopener">open</a></div>
              </div>
            </div>`;
        }).join("");
        show("#search_results", true);
      } else {
        show("#search_results", false);
      }
    } else {
      showMap(false);
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

  setText(meta, "");
  if (grid) { grid.innerHTML = ""; show("#coords_results", false); }
  showMap(false);

  if (Number.isNaN(lat) || Number.isNaN(lon)) {
    setText(meta, "Укажи корректные lat/lon");
    return;
  }

  try {
    const data = await apiJSON(apiUrl(`/search_coords?lat=${lat}&lon=${lon}&limit=${limit}`));
    const results = Array.isArray(data.results) ? data.results : [];
    setText(meta, `Найдено: ${results.length} (топ-${limit} ближайших)`);

    if (results.length) {
      // 1) Показать и создать карту
      showMap(true);
      const map = ensureMap();
      if (map) map.invalidateSize();

      // 2) Маркеры
      clearMarkers();
      addMarker(lat, lon, `<b>Центр</b><br>${lat.toFixed(6)}, ${lon.toFixed(6)}`);
      map && map.setView([lat, lon], 15);

      // 3) Точки фото
      if (grid) {
        results.forEach((r) => {
          if (r.shot_lat != null && r.shot_lon != null) {
            const href = photoUrl(r.uuid);
            const title = `${r.name || r.uuid}`;
            const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
            const ll = `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}`;
            addMarker(+r.shot_lat, +r.shot_lon,
              `<div style="max-width:220px">
                 <div class="ellipsis" title="${title}"><b>${title}</b></div>
                 <div>${dist}${dist && ll ? " · " : ""}${ll}</div>
                 <div style="margin-top:6px"><a href="${href}" target="_blank" rel="noopener">open</a></div>
               </div>`);
          }
        });

        grid.innerHTML = results.map((r) => {
          const href = photoUrl(r.uuid);
          const title = `${r.name || r.uuid}`;
          const dist = r.dist_m != null ? `${r.dist_m.toFixed(1)} м` : "";
          const ll = (r.shot_lat != null && r.shot_lon != null)
            ? `${(+r.shot_lat).toFixed(6)}, ${(+r.shot_lon).toFixed(6)}`
            : "";
          return `
            <div class="card-photo">
              <a class="thumb" href="${href}" target="_blank" rel="noopener" title="${title}">
                <img src="${href}" alt="${title}" loading="lazy" decoding="async">
              </a>
              <div class="meta">
                <div class="ellipsis" title="${title}">${title}</div>
                <div style="color:#666;">${dist}${dist && ll ? " · " : ""}${ll}</div>
                <div><a href="${href}" target="_blank" rel="noopener">open</a></div>
              </div>
            </div>`;
        }).join("");
        show("#coords_results", true);
      } else {
        show("#coords_results", false);
      }
    } else {
      showMap(false);
      show("#coords_results", false);
    }
  } catch (e) {
    setText(meta, e.message);
    showMap(false);
    show("#coords_results", false);
  }
}

/* ---------------- Admin: загрузки + расчёт --------------- */
const UploadsState = { page:1, pageSize:5, gotCount:0, total:0, selectedId:null };

function calcScope() {
  const card = $("#cardCalc");
  return {
    card,
    statusSel: card?.querySelector("#calc_filter_status") || null,
    dateFrom : card?.querySelector("#calc_date_from") || null,
    dateTo   : card?.querySelector("#calc_date_to") || null,
    applyBtn : card?.querySelector("#btnApplyUploadsFilter") || null
  };
}
function hideCalcFilterDuplicates() {
  const { card } = calcScope();
  const all = $$("#calc_filter_status, #calc_date_from, #calc_date_to, #btnApplyUploadsFilter");
  all.forEach(el => {
    if (!card) return;
    const inside = card.contains(el);
    if (!inside) el.style.display = "none";
  });
}

function getCalcFilter() {
  const { statusSel, dateFrom, dateTo } = calcScope();
  const st = statusSel ? statusSel.value : "all";
  return {
    has_coords: (st === "with" ? "true" : st === "without" ? "false" : "all"),
    date_from: dateFrom?.value || "",
    date_to:   dateTo?.value   || ""
  };
}
function updateUploadsPagerUI() {
  const totalPages = Math.max(1, Math.ceil((UploadsState.total || 0) / UploadsState.pageSize));
  setText("#uploads_page_info", `стр. ${UploadsState.page} из ${totalPages}`);
  const prev = $("#btnPrevUploads"), next = $("#btnNextUploads");
  if (prev) prev.disabled = UploadsState.page <= 1;
  if (next) next.disabled = UploadsState.page >= totalPages;
}
function selectUpload(id) {
  UploadsState.selectedId = id;
  const btn = $("#btnRunCalc");
  if (btn) btn.disabled = !id;
  $$('input[name="upload_pick"]').forEach(r => { r.checked = (String(r.value) === String(id)); });
}
async function loadUploads(page = UploadsState.page) {
  UploadsState.page = Math.max(1, page);
  const box = $("#uploads");
  if (box) box.textContent = "Загружаю…";
  const filter = getCalcFilter();
  try {
    const offset = (UploadsState.page - 1) * UploadsState.pageSize;
    const q = buildQuery({
      limit: UploadsState.pageSize,
      offset,
      has_coords: filter.has_coords,
      date_from:  filter.date_from,
      date_to:    filter.date_to
    });
    let data = await apiJSON(apiUrl(`/photos${q}`));
    let arr  = data.photos || [];
    UploadsState.total = Number(data.total || arr.length || 0);

    if (filter.has_coords !== "all") {
      const need = (filter.has_coords === "true");
      arr = arr.filter(p => hasLatLon(p) === need);
    }
    if (filter.date_from || filter.date_to) arr = arr.filter(p => inDateRange(p, filter.date_from, filter.date_to));

    UploadsState.gotCount = arr.length;
    updateUploadsPagerUI();

    if (!arr.length) { box && (box.textContent = "Пусто"); return; }

    const rows = arr.map((p, idx) => {
      const created = p.created || p.created_at || "-";
      const size = (p.width && p.height) ? `${p.width}×${p.height}` : "-";
      const radioId = `u_${p.id}`;
      const badge  = hasLatLon(p) ? '<span class="badge ok">coords</span>' : '<span class="badge warn">no coords</span>';
      return `<tr>
        <td style="width:34px;text-align:center;">
          <input type="radio" name="upload_pick" id="${radioId}" value="${p.id}" ${idx===0 && UploadsState.page===1 ? "checked" : ""} />
        </td>
        <td><label for="${radioId}" class="ellipsis" title="${p.name || "-"}">${p.name || "-"}</label></td>
        <td>${size}</td>
        <td>${created}</td>
        <td>${badge}</td>
        <td><a href="${photoUrl(p.uuid)}" target="_blank" rel="noopener">open</a></td>
      </tr>`;
    }).join("");

    box && (box.innerHTML = `<table>
      <thead><tr><th></th><th>name</th><th>size</th><th>created</th><th>status</th><th>file</th></tr></thead>
      <tbody>${rows}</tbody></table>`);

    $$('input[name="upload_pick"]').forEach(r => {
      r.addEventListener("change", (e) => selectUpload(e.target.value));
    });
    if (UploadsState.page === 1 && arr[0]) selectUpload(arr[0].id);
  } catch (e) { box && (box.textContent = e.message || "Ошибка загрузки"); }
}
async function runCalcForSelected() {
  const id = UploadsState.selectedId;
  const out = $("#calc_out");
  if (!id) { out && (out.textContent = "Выберите загрузку"); return; }
  out && (out.textContent = "Выполняю расчёт...");
  try {
    const data = await apiJSON(apiUrl("/calc_for_photo"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ photo_id: Number(id) })
    });
    out && (out.textContent = data?.message || "Готово");

    const wrap = $("#calc_preview_wrap");
    const img  = $("#calc_preview");
    const thumbs = $("#calc_preview_thumbs");

    if (data?.preview?.processed_image_url) {
      img.src = data.preview.processed_image_url;
      img.loading = "lazy"; img.decoding = "async";
      if (thumbs) {
        const singles = (data.preview.single_photos || []).filter(Boolean);
        thumbs.innerHTML = singles.map(u => `
          <a href="${u}" target="_blank" rel="noopener" style="display:block;border:1px solid #eee;border-radius:6px;overflow:hidden">
            <img src="${u}" alt="bbox" style="width:100%;display:block" loading="lazy" decoding="async">
          </a>`).join("");
      }
      show(wrap, true);
    } else show(wrap, false);
  } catch (e) {
    out && (out.textContent = e.message);
    show("#calc_preview_wrap", false);
  }
}

/* ---------------- Export (admin) ------------------------- */
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
    const res = await fetch(apiUrl("/export_xlsx"), {
      method: "POST", headers: { "Content-Type": "application/json" },
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

/* ---------------- Bind UI -------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  $("#logoutBtn")?.addEventListener("click", logout);
  renderAuthStatus();

  // Дефолт: последние 3 года
  setDefault3YearsRangeIn(document, "#photos_date_from", "#photos_date_to");
  setDefault3YearsRangeIn("#cardCalc", "#calc_date_from", "#calc_date_to");

  // Если в разметке случайно остались дубли элементов фильтра расчёта — прячем их
  hideCalcFilterDuplicates();

  // Фильтры: фото
  $("#btnApplyPhotosFilter")?.addEventListener("click", () => loadPhotos(1, PhotosState.pageSize));
  $("#photos_filter_status")?.addEventListener("change", () => loadPhotos(1, PhotosState.pageSize));
  $("#photos_date_from")?.addEventListener("change", () => loadPhotos(1, PhotosState.pageSize));
  $("#photos_date_to")?.addEventListener("change", () => loadPhotos(1, PhotosState.pageSize));

  // Фильтры: расчёт — в скоупе карточки
  const { applyBtn, statusSel, dateFrom, dateTo } = calcScope();
  applyBtn?.addEventListener("click", () => loadUploads(1));
  statusSel?.addEventListener("change", () => loadUploads(1));
  dateFrom?.addEventListener("change", () => loadUploads(1));
  dateTo?.addEventListener("change", () => loadUploads(1));

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

  // Export
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

  // Если уже админ — подгрузим список
  if (isAdminUser(getUser())) loadUploads(1);

  // Скрыть карты/превью до результатов
  show("#map", false);
  show("#search_results", false);
  show("#coords_results", false);
  show("#file_preview_wrap", false);
  show("#zip_preview_wrap", false);
});
