// frontend/app.js
document.addEventListener("DOMContentLoaded", () => {
  // ====== БАЗОВЫЕ URL ЧЕРЕЗ API-GATEWAY ======
  const API    = "http://localhost:8080";
  const AUTH   = `${API}/auth`;
  const PHOTO  = `${API}/photo`;
  const COORDS = `${API}/coords`;
  const EXPORT = `${API}/export`;

  // ====== УТИЛИТЫ ======
  const j = (v) => JSON.stringify(v, null, 2);
  const $ = (id) => document.getElementById(id);

  function currentUser() {
    try { return JSON.parse(localStorage.getItem("user") || "{}"); }
    catch { return {}; }
  }
  function setCurrentUser(u) { localStorage.setItem("user", JSON.stringify(u || {})); }

  // ====== БАННЕР ПОЛЬЗОВАТЕЛЯ (Вы вошли как...) ======
  const banner      = $("user-banner");
  const bannerText  = $("user-banner-text");
  const logoutBtn   = $("logout-btn");
  const adminLink   = $("admin-link");
  const adminCard   = $("admin-card");
  const adminOut    = $("admin_out");

  function showUserBanner(user) {
    if (!banner) return;
    if (user && user.name) {
      bannerText && (bannerText.textContent = `Вы вошли как: ${user.name}`);
      banner.style.display = "block";
      if (adminLink) adminLink.style.display = (user.role === "admin") ? "inline" : "none";
    } else {
      hideUserBanner();
    }
  }
  function hideUserBanner() {
    if (!banner) return;
    if (bannerText) bannerText.textContent = "";
    if (adminLink)  adminLink.style.display = "none";
    banner.style.display = "none";
  }

  // восстановление пользователя при загрузке страницы
  (() => {
    const saved = currentUser();
    if (saved && saved.user_id) showUserBanner(saved);
  })();

  // кнопка Выйти
  logoutBtn?.addEventListener("click", () => {
    localStorage.removeItem("user");
    localStorage.removeItem("token");
    hideUserBanner();
    if (adminCard) adminCard.style.display = "none";
    alert("Вы вышли из системы");
  });

  // ====== ЛОГИН (экспортируем для onclick="login()") ======
  window.login = async function () {
    const name = $("login_name")?.value?.trim();
    const password = $("login_pass")?.value ?? "";
    const loginOut = $("login_out");

    if (!name || !password) {
      loginOut && (loginOut.textContent = "Укажите логин и пароль");
      return;
    }
    try {
      const r = await fetch(`${AUTH}/login`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ name, password })
      });
      const text = await r.text();
      let data; try { data = JSON.parse(text); } catch { throw new Error(text); }
      if (!r.ok || data.error) throw new Error(data.error || "Ошибка входа");

      const user = {
        user_id: data.user_id,
        name,
        role: data.role,
        email: data.email
      };
      setCurrentUser(user);
      showUserBanner(user);
      loginOut && (loginOut.textContent = j(user));
    } catch (e) {
      loginOut && (loginOut.textContent = "Ошибка: " + e.message);
      alert("Ошибка: " + e.message);
    }
  };

  // ====== АДМИН: ссылка и панель ======
  adminLink?.addEventListener("click", (e) => {
    e.preventDefault();
    if (adminCard) {
      adminCard.style.display = "block";
      adminListUsers(); // сразу загрузим список
    }
  });

  // отрисовка таблицы пользователей
  function renderUsersTable(list) {
    const wrap = $("users_table");
    if (!wrap) return;
    if (!list || !list.length) { wrap.textContent = "Нет пользователей"; return; }

    const table = document.createElement("table");
    table.style.width = "100%";
    table.style.borderCollapse = "collapse";
    table.innerHTML = `
      <thead>
        <tr>
          <th style="text-align:left;border-bottom:1px solid #ddd;padding:.25rem .4rem;">ID</th>
          <th style="text-align:left;border-bottom:1px solid #ddd;padding:.25rem .4rem;">Имя</th>
          <th style="text-align:left;border-bottom:1px solid #ddd;padding:.25rem .4rem;">Email</th>
          <th style="text-align:left;border-bottom:1px solid #ddd;padding:.25rem .4rem;">Роль</th>
          <th style="text-align:left;border-bottom:1px solid #ddd;padding:.25rem .4rem;">Создан</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector("tbody");
    for (const u of list) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="padding:.25rem .4rem;border-bottom:1px solid #f0f0f0;">${u.id}</td>
        <td style="padding:.25rem .4rem;border-bottom:1px solid #f0f0f0;">${u.name}</td>
        <td style="padding:.25rem .4rem;border-bottom:1px solid #f0f0f0;">${u.email || ""}</td>
        <td style="padding:.25rem .4rem;border-bottom:1px solid #f0f0f0;">${u.role}</td>
        <td style="padding:.25rem .4rem;border-bottom:1px solid #f0f0f0;">${u.created || ""}</td>
      `;
      tbody.appendChild(tr);
    }
    wrap.innerHTML = "";
    wrap.appendChild(table);
  }

  async function adminListUsers() {
    const u = currentUser();
    if (!u.user_id || u.role !== "admin") {
      adminOut && (adminOut.textContent = "Недостаточно прав (нужен admin)");
      return;
    }
    try {
      adminOut && (adminOut.textContent = "Загружаю список…");
      const r = await fetch(`${AUTH}/admin/users?admin_user_id=${encodeURIComponent(u.user_id)}`);
      const text = await r.text();
      let data; try { data = JSON.parse(text); } catch { throw new Error(text); }
      if (data.error) throw new Error(data.error);
      renderUsersTable(data.users || []);
      adminOut && (adminOut.textContent = "—");
    } catch (e) {
      adminOut && (adminOut.textContent = "Ошибка: " + e.message);
    }
  }

  $("btn-refresh-users")?.addEventListener("click", (e) => {
    e.preventDefault();
    adminListUsers();
  });

  $("admin-create-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const u = currentUser();
    if (!u.user_id || u.role !== "admin") {
      adminOut && (adminOut.textContent = "Недостаточно прав (нужен admin)");
      return;
    }
    const name  = $("new_name").value.trim();
    const pass  = $("new_pass").value;
    const email = $("new_email").value.trim() || `${name}@local`;
    const role  = $("new_role").value;

    if (!name || !pass) { adminOut && (adminOut.textContent = "Укажите имя и пароль"); return; }

    try {
      adminOut && (adminOut.textContent = "Создаю…");
      const r = await fetch(`${AUTH}/admin/create_user`, {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({
          admin_user_id: u.user_id,
          name, password: pass, role, email
        })
      });
      const text = await r.text();
      let data; try { data = JSON.parse(text); } catch { throw new Error(text); }
      if (data.error) throw new Error(data.error);
      adminOut && (adminOut.textContent = "Создан:\n" + j(data));

      // обновим таблицу
      adminListUsers();
    } catch (err) {
      adminOut && (adminOut.textContent = "Ошибка: " + err.message);
    }
  });

  // ====== МУЛЬТИЗАГРУЗКА ФОТО + ПРЕДПРОСМОТР ======
  const formMulti   = $("photoFormMulti");
  const filesInput  = $("files");
  const preview     = $("preview");
  const outMulti    = $("photo_multi_out");
  const lastLink    = $("last_photo_link");

  if (filesInput && preview) {
    filesInput.addEventListener("change", () => {
      preview.innerHTML = "";
      const files = Array.from(filesInput.files || []).slice(0, 50);
      for (const f of files) {
        const url = URL.createObjectURL(f);
        const img = document.createElement("img");
        img.src = url;
        img.className = "thumb";
        img.onload = () => URL.revokeObjectURL(url);
        preview.appendChild(img);
      }
    });
  }

  window.clearPreview = function () {
    if (filesInput) filesInput.value = "";
    if (preview) preview.innerHTML = "";
    if (outMulti) outMulti.textContent = "—";
  };

  if (formMulti) {
    formMulti.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!filesInput || !filesInput.files.length) {
        outMulti && (outMulti.textContent = "Не выбраны файлы");
        return;
      }
      const fd = new FormData();
      for (const f of filesInput.files) fd.append("files", f);

      fd.append("type1",   $("type1_m")?.value || "мусор");
      fd.append("type2",   $("type2_m")?.value || "ИНС");
      fd.append("building",$("building_m")?.value || "");
      fd.append("address", $("address_m")?.value  || "");

      try {
        outMulti && (outMulti.textContent = "Загружаю…");
        const r = await fetch(`${PHOTO}/upload_photos`, { method: "POST", body: fd });
        const text = await r.text();
        let data; try { data = JSON.parse(text); } catch { throw new Error(text); }
        outMulti && (outMulti.textContent = j(data));

        if (data.items && data.items.length > 0 && lastLink) {
          const last = data.items[data.items.length - 1];
          if (last.url) {
            lastLink.href = `${PHOTO}${last.url}`;
            lastLink.textContent = "последнее фото";
          }
        }
      } catch (err) {
        outMulti && (outMulti.textContent = "Ошибка: " + err.message);
      }
    });
  }

  // ====== СПИСОК ФОТО ======
  window.listPhotos = async function () {
    const out = outMulti || $("photo_out");
    try {
      out && (out.textContent = "Загружаю список…");
      const r = await fetch(`${PHOTO}/list`);
      const text = await r.text();
      let data; try { data = JSON.parse(text); } catch { throw new Error(text); }
      out && (out.textContent = j(data));
    } catch (e) {
      out && (out.textContent = "Ошибка: " + e.message);
    }
  };

  // ====== ЗАГРУЗКА КООРДИНАТ ======
  const coordsOut = $("coords_out");
  window.uploadCoords = async function () {
    const lat = parseFloat($("lat")?.value ?? "");
    const lon = parseFloat($("lon")?.value ?? "");
    const type1 = $("c_type1")?.value || "мусор";
    const type2 = $("c_type2")?.value || "ИНС";
    const building = $("c_building")?.value || null;
    const address  = $("c_address")?.value || null;

    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      coordsOut && (coordsOut.textContent = "Укажите числовые lat/lon");
      return;
    }
    try {
      coordsOut && (coordsOut.textContent = "Сохраняю координаты…");
      const r = await fetch(`${COORDS}/upload_coords`, {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ lat, lon, type1, type2, building, address })
      });
      const text = await r.text();
      let data; try { data = JSON.parse(text); } catch { throw new Error(text); }
      coordsOut && (coordsOut.textContent = j(data));
    } catch (e) {
      coordsOut && (coordsOut.textContent = "Ошибка: " + e.message);
    }
  };

  // ====== ПОИСК ПО АДРЕСУ ======
  window.searchByAddr = async function () {
    const addr = $("c_address")?.value || "";
    try {
      coordsOut && (coordsOut.textContent = "Ищу…");
      const r = await fetch(`${COORDS}/search_by_addr?q=${encodeURIComponent(addr)}`);
      const text = await r.text();
      let data; try { data = JSON.parse(text); } catch { throw new Error(text); }
      coordsOut && (coordsOut.textContent = j(data));
    } catch (e) {
      coordsOut && (coordsOut.textContent = "Ошибка: " + e.message);
    }
  };

  // ====== ЭКСПОРТ В XLSX ======
  window.exportXlsx = async function () {
    const idsRaw = $("ids")?.value?.trim() || "";
    const ids = idsRaw
      ? idsRaw.split(",").map(x => parseInt(x.trim(), 10)).filter(Number.isInteger)
      : undefined;

    try {
      const r = await fetch(`${EXPORT}/export`, {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ ids })
      });
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "export.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("Ошибка экспорта: " + e.message);
    }
  };
});
