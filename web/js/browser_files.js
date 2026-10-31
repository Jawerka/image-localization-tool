/* Файловый транспорт браузера. Секрет входа не сохраняется в Web Storage. */

import { accountSession, ApiError } from "./api.js";
import { getState } from "./state.js";

export function browserFiles() {
  return Boolean(getState().capabilities?.browser_files);
}

export function download(url) {
  if (!String(url).startsWith("/api/browser/")) return;
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

export function chooseFiles({ folder = false, project = false } = {}) {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = !project;
    input.accept = project ? ".zip,.ilt.zip" : ".png,.jpg,.jpeg,.bmp,.tif,.tiff,.zip,.cbz";
    input.hidden = true;
    if (folder) input.setAttribute("webkitdirectory", "");
    document.body.append(input);
    const finish = (files) => { input.remove(); resolve(files); };
    input.addEventListener("change", () => finish([...input.files]), { once: true });
    input.addEventListener("cancel", () => finish([]), { once: true });
    input.click();
  });
}

export async function uploadFiles(files, onProject) {
  let latest = null;
  const supported = [...files].filter((file) => /\.(png|jpe?g|bmp|tiff?|zip|cbz)$/i.test(file.name));
  if (!supported.length) return null;
  supported.sort((a, b) => (a.webkitRelativePath || a.name).localeCompare(b.webkitRelativePath || b.name, undefined, { numeric: true }));
  for (const file of supported) {
    if (file.size > 256 * 1024 * 1024) throw new Error(`Файл ${file.name} превышает 256 МиБ`);
    const relative = file.webkitRelativePath || "";
    const chapter = relative.includes("/") ? relative.slice(0, relative.lastIndexOf("/")) : "";
    const response = await fetch(`/api/browser/upload?name=${encodeURIComponent(file.name)}&chapter=${encodeURIComponent(chapter)}`, {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/octet-stream" }, body: file,
    });
    const data = await response.json();
    if (!response.ok) throw new ApiError(data.error || "Не удалось загрузить файл", response.status, data);
    latest = data;
    if (onProject) onProject(data);
  }
  return latest;
}

export async function saveBrowserProject(editor) {
  const response = await fetch("/api/browser/project", { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ editor }) });
  const data = await response.json();
  if (!response.ok) throw new ApiError(data.error || "Не удалось сохранить проект", response.status, data);
  download(data.download_url);
  return data;
}

export function showLogin(onSuccess) {
  document.querySelector("[data-role='shell']").hidden = true;
  const screen = document.querySelector("[data-role='screen-error']");
  screen.hidden = false;
  screen.querySelector("#error-title").textContent = "Вход в редактор";
  screen.querySelector("[data-role='error-log']").hidden = true;
  const host = screen.querySelector("[data-role='error-text']");
  host.replaceChildren();
  const form = document.createElement("form");
  form.className = "access-login";
  form.innerHTML = '<label class="field">Логин <input class="input" name="username" autocomplete="username" maxlength="64" required></label><label class="field">Пароль <input class="input" name="password" type="password" autocomplete="current-password" maxlength="256" required></label><button class="btn btn-primary" type="submit">Войти</button><p role="status" aria-live="polite"></p>';
  host.append(form);
  const input = form.elements.namedItem("password");
  const username = form.elements.namedItem("username");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    form.querySelector("button").disabled = true;
    try {
      await accountSession(username.value.trim(), input.value);
      input.value = "";
      await onSuccess();
      screen.hidden = true;
      document.querySelector("[data-role='shell']").hidden = false;
    } catch (error) {
      form.querySelector("[role='status']").textContent = error.message;
    } finally {
      form.querySelector("button").disabled = false;
    }
  });
  username.focus();
}
