/* Учётная запись владельца браузерного редактора; секреты живут только в полях. */
import { browserAccess, logoutBrowser, saveBrowserAccess } from "./api.js";
import { getState } from "./state.js";

let revision = 0;
const field = (name) => document.getElementById(`access-${name}`);

export function clearAccessSecrets() {
  revision++;
  for (const name of ["password", "confirm", "current"]) field(name).value = "";
}

function paint(status) {
  field("enabled").checked = status.enabled;
  field("username").value = status.username || "";
  field("current-row").hidden = !status.configured;
  field("logout").hidden = !status.enabled;
  field("password").placeholder = status.configured ? "Оставьте пустым, чтобы сохранить пароль" : "Не менее 10 символов";
  field("summary").textContent = status.enabled
    ? "Вход по логину и паролю включён."
    : "Защита выключена. Редактор доступен всем, кто может открыть его адрес.";
}

export function initAccessSettings() {
  field("logout").addEventListener("click", async () => {
    field("logout").disabled = true;
    try {
      await logoutBrowser();
      clearAccessSecrets();
      window.location.reload();
    } catch (error) {
      field("message").textContent = error.message;
    } finally {
      field("logout").disabled = false;
    }
  });
  field("save").addEventListener("click", async () => {
    const message = field("message");
    message.textContent = "";
    if (field("password").value !== field("confirm").value) {
      message.textContent = "Пароли не совпадают";
      field("confirm").focus();
      return;
    }
    const requestRevision = revision;
    field("save").disabled = true;
    try {
      const status = await saveBrowserAccess({
        enabled: field("enabled").checked,
        username: field("username").value.trim(),
        password: field("password").value,
        current_password: field("current").value,
      });
      if (revision !== requestRevision) return;
      clearAccessSecrets();
      paint(status);
      message.textContent = "Настройки доступа сохранены";
    } catch (error) {
      if (revision === requestRevision) message.textContent = error.message;
    } finally {
      if (revision === requestRevision || revision === requestRevision + 1) field("save").disabled = false;
    }
  });
}

export async function refreshAccessSettings() {
  clearAccessSecrets();
  const available = Boolean(getState().capabilities?.browser_files);
  document.getElementById("nav-access").hidden = !available;
  if (!available) return;
  const requestRevision = revision;
  field("save").disabled = true;
  field("message").textContent = "Загрузка настроек доступа…";
  try {
    const status = await browserAccess();
    if (revision !== requestRevision) return;
    paint(status);
    field("message").textContent = "";
    field("save").disabled = false;
  } catch (error) {
    if (revision === requestRevision) field("message").textContent = error.message;
  }
}
