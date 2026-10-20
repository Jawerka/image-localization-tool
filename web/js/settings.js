/* Настройки и мастер первого запуска. Тема на экране живая, в файл — по ОК и Применить. */

import { dialogLog, dialogReveal, downloadModel, llmCheck, models, pausePreparation, preparationCurrent, preparationPlan, putSecret, putSettings, remotePair, remoteRevoke, resumePreparation, startPreparation, verifyPreparation } from "./api.js";
import { openModelPick } from "./dialogs.js";
import { clone, getState, patch, setBanner, settingsForSave, subscribe } from "./state.js";

const LABELS = {
  detector: "Детектор RT-DETR",
  lama: "LaMa",
  font: "Шрифт Heroika",
};
const REQUIRED = ["detector", "lama", "font"];

let screen;
let wizardScreen;
let opened = false;
let wizard = false;
let wizardStep = 1;
let previewing = false;
let secretDirty = false;
let modelItems = [];
let modelProgress = {};
let downloading = false;
let modelError = "";
let remoteActionError = "";
let prepPlanResult = null;
let prepCurrent = null;
let prepError = "";
let prepTimer = 0;
let prepLoading = false;
let settingsPrepPlan = null;
let settingsPrepCurrent = null;
let settingsPrepError = "";
let settingsPrepLoading = false;
let settingsPrepTimer = 0;

export function isOpen() {
  return opened;
}

export function isWizard() {
  return wizard;
}

export function isPreviewing() {
  return previewing;
}

export function init() {
  screen = document.querySelector("[data-role='screen-settings']");
  wizardScreen = document.querySelector("[data-role='screen-wizard']");
  bindTabs(screen);
  screen.querySelectorAll("input[name='set-theme']").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) applyAppearance(input.value, Number(document.getElementById("set-scale").value));
    });
  });
  document.getElementById("set-scale").addEventListener("input", () => {
    const value = Number(document.getElementById("set-scale").value);
    document.getElementById("set-scale-value").textContent = `${value} %`;
    const theme = screen.querySelector("input[name='set-theme']:checked")?.value || "system";
    applyAppearance(theme, value);
  });
  document.querySelector("[data-role='settings-ok']").addEventListener("click", () => apply(true));
  document.querySelector("[data-role='settings-apply']").addEventListener("click", () => apply(false));
  document.querySelector("[data-role='settings-cancel']").addEventListener("click", cancel);
  document.querySelector("[data-role='settings-close']")?.addEventListener("click", cancel);
  document.querySelector("[data-role='api-key-edit']").addEventListener("click", () => {
    const input = document.getElementById("set-api-key");
    input.readOnly = false;
    input.placeholder = "";
    input.focus();
  });
  document.getElementById("set-api-key").addEventListener("input", () => {
    secretDirty = true;
  });
  document.querySelector("[data-role='llm-check']").addEventListener("click", () => checkLlm(
    document.getElementById("set-llm-url").value,
    document.getElementById("set-llm-model").value,
    document.querySelector("[data-role='llm-check-result']"),
    document.getElementById("set-llm-model"),
  ));
  document.querySelector("[data-role='llm-models']").addEventListener("click", () => pickModel(document.getElementById("set-llm-model")));
  document.querySelector("[data-role='open-log']").addEventListener("click", () => {
    dialogLog().catch((error) => notify(error.message));
  });
  document.querySelector("[data-role='open-components-dir']")?.addEventListener("click", () => {
    dialogReveal({ kind: "components" }).catch((error) => notify(error.message));
  });
  document.querySelectorAll("[data-role='models-download']").forEach((button) => {
    button.addEventListener("click", () => downloadMissing());
  });
  document.getElementById("wizard-prev").addEventListener("click", () => showWizardStep(wizardStep - 1));
  document.getElementById("wizard-next").addEventListener("click", onWizardNext);
  wizardScreen.querySelectorAll("[data-step-btn]").forEach((button) => {
    button.addEventListener("click", () => showWizardStep(Number(button.dataset.stepBtn)));
  });
  wizardScreen.querySelectorAll("input[name='wiz-theme']").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) applyAppearance(input.value, getState().settings.ui_scale);
    });
  });
  wizardScreen.querySelectorAll("input[name='wiz-profile']").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked && wizardStep === 3) refreshPreparationPlan();
    });
  });
  document.querySelector("[data-role='preparation-start']")?.addEventListener("click", startWizardPreparation);
  document.querySelector("[data-role='preparation-pause']")?.addEventListener("click", pauseWizardPreparation);
  document.querySelector("[data-role='preparation-resume']")?.addEventListener("click", resumeWizardPreparation);
  document.querySelector("[data-role='settings-preparation-start']")?.addEventListener("click", startSettingsPreparation);
  document.querySelector("[data-role='settings-preparation-pause']")?.addEventListener("click", pauseSettingsPreparation);
  document.querySelector("[data-role='settings-preparation-resume']")?.addEventListener("click", resumeSettingsPreparation);
  document.querySelector("[data-role='settings-preparation-refresh']")?.addEventListener("click", verifySettingsPreparation);
  document.querySelector("[data-role='wiz-check']").addEventListener("click", () => checkLlm(
    document.getElementById("wiz-url").value,
    document.getElementById("wiz-model").value,
    document.querySelector("[data-role='wiz-check-result']"),
    document.getElementById("wiz-model"),
  ));
  document.querySelector("[data-role='remote-live']")?.addEventListener("click", onRemoteClick);
  subscribe(() => {
    if (!opened) return;
    syncLang("set-target", "target_lang");
    const panel = screen.querySelector("[data-tabpanel='network']");
    if (panel && !panel.hidden) paintRemote();
  });
}

export function open(tab) {
  opened = true;
  previewing = true;
  secretDirty = false;
  fill(getState().settings);
  screen.hidden = false;
  document.querySelector("[data-role='shell']")?.setAttribute("inert", "");
  showSettingsTab(tab || "appearance");
  refreshModels();
  screen.querySelector("[role='tab']")?.focus();
}

export function cancel() {
  if (!opened) return;
  const settings = getState().settings;
  applyAppearance(settings.theme, settings.ui_scale);
  closeScreen();
}

export function openWizard() {
  wizard = true;
  previewing = true;
  wizardStep = 1;
  prepPlanResult = null;
  prepCurrent = null;
  prepError = "";
  prepLoading = false;
  const settings = getState().settings;
  checkRadio("wiz-theme", settings.theme || "system");
  checkRadio("wiz-profile", settings.translator_backend === "argos" ? "offline" : "llm");
  document.getElementById("wiz-url").value = settings.llm_base_url || "";
  document.getElementById("wiz-model").value = settings.llm_model || "";
  document.getElementById("wiz-dst").value = settings.target_lang || "ru";
  wizardScreen.hidden = false;
  document.querySelector("[data-role='shell']")?.setAttribute("inert", "");
  showWizardStep(1);
  if (prepTimer) window.clearInterval(prepTimer);
  prepTimer = 0;
}

export function noteModelProgress(payload) {
  const kind = payload.kind || payload.name;
  if (!kind) return;
  const value = percentOf(payload);
  if (value == null) return;
  modelProgress[kind] = value;
  renderModelLists();
  if (value >= 100 || payload.finished || payload.present) refreshModels();
}

export function applyAppearance(theme, scale) {
  const root = document.documentElement;
  if (theme === "dark" || theme === "light") root.setAttribute("data-theme", theme);
  else root.removeAttribute("data-theme");
  const value = Math.min(150, Math.max(100, Number(scale) || 100));
  root.style.setProperty("--ui-scale", String(value / 100));
}

async function apply(close) {
  const body = readForm();
  try {
    const saved = await putSettings(settingsForSave(body));
    const settings = mergeSettings(body, saved);
    patch({ settings, hasApiKey: secretDirty && document.getElementById("set-api-key").value ? true : getState().hasApiKey });
    const secret = document.getElementById("set-api-key").value;
    if (secretDirty && secret) {
      await putSecret(secret);
      patch({ hasApiKey: true });
      secretDirty = false;
      document.getElementById("set-api-key").value = "";
      document.getElementById("set-api-key").placeholder = "задан";
      document.getElementById("set-api-key").readOnly = true;
    }
    if (close) closeScreen();
    else refreshSettingsPreparation();
  } catch (error) {
    notify(error.message || "Не удалось сохранить настройки");
  }
}

function closeScreen() {
  opened = false;
  previewing = wizard;
  screen.hidden = true;
  if (!wizard && prepTimer) {
    window.clearInterval(prepTimer);
    prepTimer = 0;
  }
  if (settingsPrepTimer) {
    window.clearInterval(settingsPrepTimer);
    settingsPrepTimer = 0;
  }
  const modal = document.querySelector("[data-role='modals']");
  const modalOpen = Boolean(modal && !modal.hidden);
  if (!wizard && !modalOpen) document.querySelector("[data-role='shell']")?.removeAttribute("inert");
}

function readForm() {
  const next = clone(getState().settings);
  next.theme = checked("set-theme") || "system";
  next.ui_scale = clampScale(document.getElementById("set-scale").value);
  next.single_key_shortcuts = document.getElementById("set-single").checked;
  next.source_lang = "auto";
  next.target_lang = document.getElementById("set-target").value;
  next.reading_order = document.getElementById("set-reading").value;
  next.translate_sfx = document.getElementById("set-sfx").checked;
  next.sfx_mode = next.translate_sfx ? "replace" : "skip";
  next.auto_stylized_fonts = document.getElementById("set-auto-fonts").checked;
  next.remote_enabled = document.getElementById("set-remote").checked;
  next.remote_bind = document.getElementById("set-remote-bind").value.trim() || "0.0.0.0";
  next.remote_port = Math.max(1, Math.min(65535, Math.round(numberValue("set-remote-port", 8765))));
  next.glossary_path = document.getElementById("set-glossary").value.trim();
  next.llm_base_url = document.getElementById("set-llm-url").value.trim();
  next.llm_model = document.getElementById("set-llm-model").value.trim();
  next.llm_timeout = numberValue("set-llm-timeout", 300);
  next.llm_thinking = document.getElementById("set-llm-think").checked;
  next.ocr_backend = document.getElementById("set-ocr").value;
  next.translator_backend = document.getElementById("set-translator").value;
  next.inpainter_backend = document.getElementById("set-clean").value === "fill" ? "opencv" : document.getElementById("set-clean").value;
  next.device = document.getElementById("set-device").value;
  next.detector_conf = numberValue("set-conf", 0.3);
  next.ort_intra_op_threads = numberValue("set-ort-threads", 0);
  next.min_font_size = numberValue("set-font-min", 10);
  next.max_font_size = numberValue("set-font-max", 128);
  next.text_stroke_ratio = numberValue("set-stroke", 0.08);
  next.text_margin = numberValue("set-margin", 0.08);
  next.font_path = document.getElementById("set-font-path").value.trim();
  next.export_subdir = document.getElementById("set-export-sub").value.trim() || "translated";
  next.export_format = document.getElementById("set-export-format").value;
  next.export_jpeg_quality = numberValue("set-jpeg", 90);
  next.export_conflict = document.getElementById("set-conflict").value;
  return next;
}

function fill(settings) {
  checkRadio("set-theme", settings.theme || "system");
  const scale = clampScale(settings.ui_scale);
  document.getElementById("set-scale").value = String(scale);
  document.getElementById("set-scale-value").textContent = `${scale} %`;
  document.getElementById("set-single").checked = settings.single_key_shortcuts !== false;
  document.getElementById("set-target").value = settings.target_lang || "ru";
  document.getElementById("set-reading").value = settings.reading_order || "auto";
  document.getElementById("set-sfx").checked = Boolean(settings.translate_sfx);
  document.getElementById("set-auto-fonts").checked = settings.auto_stylized_fonts !== false;
  document.getElementById("set-remote").checked = Boolean(settings.remote_enabled);
  document.getElementById("set-remote-bind").value = settings.remote_bind || "0.0.0.0";
  document.getElementById("set-remote-port").value = String(settings.remote_port || 8765);
  paintRemote();
  document.getElementById("set-glossary").value = settings.glossary_path || "";
  document.getElementById("set-llm-url").value = settings.llm_base_url || "";
  document.getElementById("set-llm-model").value = settings.llm_model || "";
  const secret = document.getElementById("set-api-key");
  secret.value = "";
  secret.readOnly = true;
  secret.placeholder = getState().hasApiKey ? "задан" : "не задан";
  document.getElementById("set-llm-timeout").value = String(settings.llm_timeout || 300);
  document.getElementById("set-llm-think").checked = Boolean(settings.llm_thinking);
  document.getElementById("set-ocr").value = settings.ocr_backend || "vlm";
  document.getElementById("set-translator").value = settings.translator_backend || "llm";
  const clean = settings.inpainter_backend === "opencv" ? "opencv" : "lama";
  document.getElementById("set-clean").value = clean;
  document.getElementById("set-device").value = settings.device || "auto";
  document.getElementById("set-conf").value = String(settings.detector_conf ?? 0.3);
  document.getElementById("set-ort-threads").value = String(settings.ort_intra_op_threads ?? 0);
  document.getElementById("set-font-min").value = String(settings.min_font_size ?? 10);
  document.getElementById("set-font-max").value = String(settings.max_font_size ?? 128);
  document.getElementById("set-stroke").value = String(settings.text_stroke_ratio ?? 0.08);
  document.getElementById("set-margin").value = String(settings.text_margin ?? 0.08);
  document.getElementById("set-font-path").value = settings.font_path || "";
  document.getElementById("set-export-sub").value = settings.export_subdir || "translated";
  document.getElementById("set-export-format").value = settings.export_format === "jpg" ? "jpg" : "png";
  document.getElementById("set-jpeg").value = String(settings.export_jpeg_quality || 90);
  document.getElementById("set-conflict").value = settings.export_conflict || "rename";
  const state = getState();
  document.getElementById("set-version").textContent = state.version || "1.0.0";
  document.getElementById("set-settings-path").textContent = state.paths?.settings || "%APPDATA%\\ImageLocalizationTool\\settings.json";
  document.getElementById("set-data-path").textContent = state.paths?.data || "%LOCALAPPDATA%\\ImageLocalizationTool\\";
  const componentsPath = document.querySelector("[data-role='components-path']");
  if (componentsPath) componentsPath.textContent = state.paths?.components || "папка программы";
  applyAppearance(settings.theme, scale);
}

async function checkLlm(url, model, output, field) {
  output.textContent = "Проверяем…";
  try {
    const current = settingsForSave(getState().settings);
    current.llm_base_url = url.trim();
    current.llm_model = model.trim();
    const saved = await putSettings(current);
    patch({ settings: mergeSettings({ ...getState().settings, llm_base_url: current.llm_base_url, llm_model: current.llm_model }, saved) });
    const result = await llmCheck();
    patch({ llm: { ok: Boolean(result?.ok), models: result?.models || [], vision: Boolean(result?.vision), reason: result?.reason || "" } });
    if (result?.ok && result?.vision) output.textContent = "Связь есть, модель принимает картинки.";
    else if (result?.ok) output.textContent = "Связь есть. Приём картинок не подтверждён.";
    else output.textContent = result?.reason ? `Нет связи: ${result.reason}` : "Нет связи с сервером LLM.";
    if (result?.ok && Array.isArray(result.models) && result.models.length && !field.value) {
      const picked = await choose(result.models);
      if (picked) field.value = picked;
    }
  } catch (error) {
    output.textContent = error.message || "Не удалось проверить сервер";
  }
}

function pickModel(field) {
  const known = getState().llm?.models || [];
  choose(known).then((value) => {
    if (value) field.value = value;
  });
}

function choose(list) {
  return new Promise((resolve) => {
    openModelPick(list, (value) => resolve(value || ""));
  });
}

async function onWizardNext() {
  if (wizardStep === 3 && !preparationReady()) return;
  if (wizardStep < 4) {
    showWizardStep(wizardStep + 1);
    return;
  }
  const current = settingsForSave(getState().settings);
  current.theme = checked("wiz-theme") || "system";
  current.llm_base_url = document.getElementById("wiz-url").value.trim();
  current.llm_model = document.getElementById("wiz-model").value.trim();
  current.source_lang = "auto";
  current.target_lang = document.getElementById("wiz-dst").value;
  const offline = checked("wiz-profile") === "offline";
  current.translator_backend = offline ? "argos" : "llm";
  current.ocr_backend = offline ? "rapid" : "vlm";
  current.first_run_complete = true;
  try {
    const saved = await putSettings(current);
    const settings = mergeSettings(current, saved);
    patch({ settings });
    applyAppearance(settings.theme, settings.ui_scale);
    wizard = false;
    previewing = opened;
    wizardScreen.hidden = true;
    if (prepTimer) window.clearInterval(prepTimer);
    prepTimer = 0;
    if (!opened) document.querySelector("[data-role='shell']")?.removeAttribute("inert");
  } catch (error) {
    notify(error.message || "Не удалось сохранить настройки");
  }
}

function showWizardStep(step) {
  const target = Math.min(4, Math.max(1, step));
  if (target > 3 && !preparationReady()) return;
  wizardStep = target;
  wizardScreen.querySelectorAll("[data-step]").forEach((panel) => {
    panel.hidden = Number(panel.dataset.step) !== wizardStep;
  });
  wizardScreen.querySelectorAll("[data-step-btn]").forEach((button) => {
    const number = Number(button.dataset.stepBtn);
    const on = number === wizardStep;
    button.classList.toggle("is-active", on);
    button.classList.toggle("is-done", number < wizardStep);
    if (on) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
  document.getElementById("wizard-prev").disabled = wizardStep === 1;
  document.getElementById("wizard-next").textContent = wizardStep === 4 ? "Готово" : "Далее";
  paintModelGate();
  if (wizardStep === 3) {
    refreshPreparationPlan();
    refreshPreparationState();
    if (!prepTimer) prepTimer = window.setInterval(refreshPreparationState, 1200);
  }
}

function preparationSelection() {
  const settings = getState().settings || {};
  return {
    source_lang: "en",
    target_lang: document.getElementById("wiz-dst").value || "ru",
    translator_backend: checked("wiz-profile") === "offline" ? "argos" : "llm",
    inpainter_backend: settings.inpainter_backend || "lama",
    device: settings.device || "auto",
    models_dir: settings.models_dir || "",
  };
}

function preparationReady() {
  const items = prepPlanResult?.items;
  return Boolean(Array.isArray(items) && items.length && items.every((item) => item.ready));
}

async function refreshPreparationPlan() {
  prepLoading = true;
  prepError = "";
  paintPreparation();
  try {
    prepPlanResult = await preparationPlan(preparationSelection());
  } catch (error) {
    prepPlanResult = null;
    prepError = error.message || "Не удалось составить план подготовки";
  } finally {
    prepLoading = false;
    paintPreparation();
  }
}

async function refreshPreparationState() {
  if (!wizard || wizardStep !== 3) return;
  const previousState = prepCurrent?.state;
  try {
    prepCurrent = await preparationCurrent();
    if (prepCurrent?.state === "ready" && previousState !== "ready") {
      await refreshPreparationPlan();
    }
  } catch (error) {
    prepError = error.message || "Не удалось проверить состояние подготовки";
  }
  paintPreparation();
}

async function startWizardPreparation() {
  if (prepLoading || preparationReady()) return;
  prepLoading = true;
  prepError = "";
  paintPreparation();
  try {
    prepPlanResult = await preparationPlan(preparationSelection());
    if (prepPlanResult.items?.every((item) => item.ready)) {
      prepCurrent = { state: "ready" };
    } else {
      prepCurrent = await startPreparation(preparationSelection());
    }
  } catch (error) {
    prepError = error.message || "Не удалось начать подготовку";
  } finally {
    prepLoading = false;
    paintPreparation();
  }
}

async function pauseWizardPreparation() {
  try { prepCurrent = await pausePreparation(); }
  catch (error) { prepError = error.message || "Не удалось приостановить подготовку"; }
  paintPreparation();
}

async function resumeWizardPreparation() {
  try { prepCurrent = await resumePreparation(); }
  catch (error) { prepError = error.message || "Не удалось продолжить подготовку"; }
  paintPreparation();
}

function paintPreparation() {
  const note = document.querySelector("[data-role='preparation-note']");
  const host = document.querySelector("[data-role='wizard-models']");
  const start = document.querySelector("[data-role='preparation-start']");
  const pause = document.querySelector("[data-role='preparation-pause']");
  const resume = document.querySelector("[data-role='preparation-resume']");
  if (!note || !host || !start) return;
  const plan = prepPlanResult;
  const current = prepCurrent || {};
  const active = ["planning", "downloading", "installing", "checking"].includes(current.state);
  const selected = preparationSelection();
  const savedSelection = current.selection || {};
  const matchesCurrent = ["source_lang", "target_lang", "translator_backend", "inpainter_backend", "device", "models_dir"]
    .every((key) => String(savedSelection[key] || "") === String(selected[key] || ""));
  const paused = current.state === "paused" && matchesCurrent;
  const pausedOther = current.state === "paused" && !matchesCurrent;
  const ready = preparationReady();
  const total = Number(plan?.total || 0);
  const required = Number(plan?.required_space || 0);
  start.textContent = total > 0 ? "Подготовить компоненты" : "Проверить и активировать";
  if (prepError) note.textContent = prepError;
  else if (prepLoading) note.textContent = "Считаем объём загрузки и место установки…";
  else if (ready) note.textContent = "Компоненты готовы. Можно продолжить настройку.";
  else if (current.state === "error") note.textContent = current.error || "Не удалось подготовить компоненты.";
  else if (paused) note.textContent = `Подготовка приостановлена: ${formatBytes(current.done)} из ${formatBytes(current.total)}.`;
  else if (pausedOther) note.textContent = "Приостановлена подготовка другого профиля. Запуск ниже создаст план для выбранного профиля.";
  else if (active) note.textContent = preparationStatusText(current);
  else note.textContent = total === 0
    ? "Компоненты уже скачаны. Нужна только проверка и активация."
    : `Потребуется скачать ${formatBytes(total)} и иметь ${formatBytes(required)} свободного места.`;

  const items = Array.isArray(plan?.items) ? plan.items : [];
  host.innerHTML = items.map((item) => `<div class="model-row"><span class="model-row__name">${escapeText(item.title || item.id)}</span><span class="badge ${item.ready ? "badge--ok" : "badge--warn"}">${escapeText(preparationBadge(item))}</span></div>`).join("");
  if (Array.isArray(plan?.warnings) && plan.warnings.length) {
    host.insertAdjacentHTML("beforeend", `<p class="field-hint">${plan.warnings.map(escapeText).join(" ")}</p>`);
  }
  start.hidden = ready || active || paused || prepLoading;
  start.disabled = !plan || Boolean(prepError);
  if (pause) pause.hidden = !active;
  if (resume) resume.hidden = !paused;
  const next = document.getElementById("wizard-next");
  if (next && wizard && wizardStep === 3) next.disabled = !ready;
}

function preparationStatusText(current) {
  const title = current.current || "Проверка компонентов";
  return Number(current.total) > 0
    ? `${title}: ${formatBytes(current.done)} из ${formatBytes(current.total)}.`
    : title;
}

function formatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} КБ`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} ГБ`;
}

function preparationBadge(item) {
  if (item.ready) return "готово";
  return Number(item.download_bytes) > 0 ? formatBytes(item.download_bytes) : "проверить";
}

function settingsPreparationSelection() {
  const form = readForm();
  return {
    source_lang: "en",
    target_lang: form.target_lang || "ru",
    translator_backend: form.translator_backend || "llm",
    inpainter_backend: form.inpainter_backend || "lama",
    device: form.device || "auto",
    models_dir: form.models_dir || "",
  };
}

function settingsPreparationActive(current = settingsPrepCurrent) {
  return ["planning", "downloading", "installing", "checking"].includes(String(current?.state || ""));
}

function settingsPreparationMatches(current, selected) {
  const saved = current?.selection || {};
  return ["source_lang", "target_lang", "translator_backend", "inpainter_backend", "device", "models_dir"]
    .every((key) => String(saved[key] || "") === String(selected[key] || ""));
}

function settingsPreparationReady() {
  const items = settingsPrepPlan?.items;
  return Boolean(Array.isArray(items) && items.length && items.every((item) => item.ready));
}

async function refreshSettingsPreparation() {
  if (!opened || !document.querySelector("[data-role='settings-preparation-note']")) return;
  settingsPrepLoading = true;
  settingsPrepError = "";
  paintSettingsPreparation();
  try {
    const selection = settingsPreparationSelection();
    const [plan, current] = await Promise.all([preparationPlan(selection), preparationCurrent()]);
    settingsPrepPlan = plan;
    settingsPrepCurrent = current;
  } catch (error) {
    settingsPrepPlan = null;
    settingsPrepError = error.message || "Не удалось проверить компоненты";
  } finally {
    settingsPrepLoading = false;
    paintSettingsPreparation();
    syncSettingsPreparationPoll();
  }
}

async function verifySettingsPreparation() {
  if (settingsPrepLoading) return;
  settingsPrepLoading = true;
  settingsPrepError = "";
  paintSettingsPreparation();
  try {
    const selection = settingsPreparationSelection();
    settingsPrepPlan = await preparationPlan(selection);
    settingsPrepCurrent = await verifyPreparation(selection);
  } catch (error) {
    settingsPrepError = error.message || "Не удалось проверить компоненты";
  } finally {
    settingsPrepLoading = false;
    paintSettingsPreparation();
    syncSettingsPreparationPoll();
  }
}

function syncSettingsPreparationPoll() {
  if (settingsPreparationActive()) {
    if (!settingsPrepTimer) settingsPrepTimer = window.setInterval(refreshSettingsPreparationState, 1200);
    return;
  }
  if (settingsPrepTimer) {
    window.clearInterval(settingsPrepTimer);
    settingsPrepTimer = 0;
  }
}

async function refreshSettingsPreparationState() {
  if (!opened) {
    if (settingsPrepTimer) {
      window.clearInterval(settingsPrepTimer);
      settingsPrepTimer = 0;
    }
    return;
  }
  const previous = settingsPrepCurrent?.state;
  try {
    settingsPrepCurrent = await preparationCurrent();
    if (settingsPrepCurrent?.state === "ready" && previous !== "ready") {
      settingsPrepPlan = await preparationPlan(settingsPreparationSelection());
    }
  } catch (error) {
    settingsPrepError = error.message || "Не удалось проверить состояние подготовки";
  }
  paintSettingsPreparation();
  syncSettingsPreparationPoll();
}

async function startSettingsPreparation() {
  if (settingsPrepLoading) return;
  settingsPrepLoading = true;
  settingsPrepError = "";
  paintSettingsPreparation();
  try {
    const selection = settingsPreparationSelection();
    settingsPrepPlan = await preparationPlan(selection);
    if (settingsPrepPlan?.items?.every((item) => item.ready)) {
      settingsPrepCurrent = await preparationCurrent();
    } else {
      settingsPrepCurrent = await startPreparation(selection);
    }
  } catch (error) {
    settingsPrepError = error.message || "Не удалось начать подготовку";
  } finally {
    settingsPrepLoading = false;
    paintSettingsPreparation();
    syncSettingsPreparationPoll();
  }
}

async function pauseSettingsPreparation() {
  try {
    settingsPrepCurrent = await pausePreparation();
    settingsPrepError = "";
  } catch (error) {
    settingsPrepError = error.message || "Не удалось приостановить подготовку";
  }
  paintSettingsPreparation();
  syncSettingsPreparationPoll();
}

async function resumeSettingsPreparation() {
  try {
    settingsPrepCurrent = await resumePreparation();
    settingsPrepError = "";
  } catch (error) {
    settingsPrepError = error.message || "Не удалось продолжить подготовку";
  }
  paintSettingsPreparation();
  syncSettingsPreparationPoll();
}

function paintSettingsPreparation() {
  const note = document.querySelector("[data-role='settings-preparation-note']");
  const host = document.querySelector("[data-role='settings-preparation-list']");
  const start = document.querySelector("[data-role='settings-preparation-start']");
  const pause = document.querySelector("[data-role='settings-preparation-pause']");
  const resume = document.querySelector("[data-role='settings-preparation-resume']");
  if (!note || !host || !start) return;
  const plan = settingsPrepPlan;
  const current = settingsPrepCurrent || {};
  const active = settingsPreparationActive(current);
  const selected = settingsPreparationSelection();
  const paused = current.state === "paused" && settingsPreparationMatches(current, selected);
  const pausedOther = current.state === "paused" && !settingsPreparationMatches(current, selected);
  const ready = settingsPreparationReady();
  const total = Number(plan?.total || 0);
  const required = Number(plan?.required_space || 0);
  start.textContent = total > 0 ? "Подготовить компоненты" : "Проверить и активировать";
  if (settingsPrepError) note.textContent = settingsPrepError;
  else if (settingsPrepLoading) note.textContent = "Считаем объём загрузки и проверяем компоненты…";
  else if (ready) note.textContent = "Компоненты готовы. Перевод можно запускать.";
  else if (current.state === "error") note.textContent = current.error || "Не удалось подготовить компоненты.";
  else if (paused) note.textContent = `Подготовка приостановлена: ${formatBytes(current.done)} из ${formatBytes(current.total)}.`;
  else if (pausedOther) note.textContent = "Приостановлена подготовка другого профиля. Новый запуск создаст план для текущих настроек.";
  else if (active) note.textContent = preparationStatusText(current);
  else if (plan) note.textContent = total === 0
    ? "Компоненты уже скачаны. Нужна только проверка и активация."
    : `Потребуется скачать ${formatBytes(total)} и иметь ${formatBytes(required)} свободного места.`;
  else note.textContent = "Не удалось получить план подготовки.";

  const items = Array.isArray(plan?.items) ? plan.items : [];
  host.innerHTML = items.map((item) => `<div class="model-row"><span class="model-row__name">${escapeText(item.title || item.id)}</span><span class="badge ${item.ready ? "badge--ok" : "badge--warn"}">${escapeText(preparationBadge(item))}</span></div>`).join("");
  if (Array.isArray(plan?.warnings) && plan.warnings.length) {
    host.insertAdjacentHTML("beforeend", `<p class="field-hint">${plan.warnings.map(escapeText).join(" ")}</p>`);
  }
  start.hidden = ready || active || paused || settingsPrepLoading;
  start.disabled = !plan || Boolean(settingsPrepError);
  if (pause) pause.hidden = !active;
  if (resume) resume.hidden = !paused;
  const refresh = document.querySelector("[data-role='settings-preparation-refresh']");
  if (refresh) refresh.disabled = active || settingsPrepLoading;
}

async function refreshModels() {
  try {
    const data = await models();
    modelItems = normalizeModels(data);
    renderModelLists();
  } catch (error) {
    notify(error.message || "Не удалось прочитать модели");
  }
}

function renderModelLists() {
  const settingsHost = document.querySelector("[data-role='model-list']");
  if (settingsHost) settingsHost.innerHTML = modelItems.map((item) => modelRow(item, "settings")).join("");
  paintModelGate();
}

function modelRow(model, place) {
  const percent = modelProgress[model.kind];
  const ready = model.present ? (place === "wizard" ? "готово" : "установлена") : "";
  let badge = `<span class="badge badge--warn">${icon("warning")} не установлена</span>`;
  if (model.present) badge = `<span class="badge badge--ok">${icon("check")} ${ready}</span>`;
  else if (percent != null) badge = `<span class="badge">${icon("play")} ${Math.round(percent)} %</span>`;
  const name = percent != null && !model.present
    ? `<span class="model-row__main"><span class="model-row__name">${escapeText(model.name)}</span><progress max="100" value="${Math.round(percent)}" aria-label="Загрузка ${escapeAttr(model.name)}">${Math.round(percent)} %</progress></span>`
    : `<span class="model-row__name">${escapeText(model.name)}</span>`;
  return `<div class="model-row">${name}${badge}<span></span></div>`;
}

function requiredKinds() {
  const settings = getState().settings || {};
  return settings.inpainter_backend === "opencv" ? ["detector", "font"] : REQUIRED;
}

function requiredReady() {
  return requiredKinds().every((kind) => modelItems.some((item) => item.kind === kind && item.present));
}

function missingKinds() {
  return requiredKinds().filter((kind) => !modelItems.some((item) => item.kind === kind && item.present));
}

function modelNote() {
  if (downloading) return "Скачиваем недостающие файлы…";
  if (modelError) return modelError;
  if (!modelItems.length) return "Проверяем файлы…";
  if (requiredReady()) return "Модели готовы.";
  const names = missingKinds().map((kind) => LABELS[kind] || kind).join(", ");
  return `Нужно скачать: ${names}. Без них глава не обработается.`;
}

function paintModelGate() {
  const text = modelNote();
  document.querySelectorAll("[data-role='models-note']").forEach((node) => {
    node.textContent = text;
  });
  const ready = requiredReady();
  document.querySelectorAll("[data-role='models-download']").forEach((button) => {
    button.hidden = ready;
    button.disabled = downloading;
  });
  const next = document.getElementById("wizard-next");
  if (next && wizard && wizardStep !== 3) next.disabled = false;
  if (modelItems.length && getState().modelsReady !== ready) patch({ modelsReady: ready });
}

async function downloadMissing() {
  if (downloading) return;
  await refreshModels();
  const missing = missingKinds();
  if (!missing.length) {
    modelError = "";
    paintModelGate();
    return;
  }
  downloading = true;
  modelError = "";
  paintModelGate();
  try {
    for (const kind of missing) {
      modelProgress[kind] = 0;
      renderModelLists();
      await downloadModel(kind);
      await refreshModels();
      const item = modelItems.find((entry) => entry.kind === kind);
      if (!item || !item.present) {
        throw new Error(`${LABELS[kind] || kind} скачан, но проверка его не видит.`);
      }
      delete modelProgress[kind];
    }
    modelError = "";
  } catch (error) {
    modelError = error.message || "Не удалось скачать модели";
    notify(modelError);
  } finally {
    downloading = false;
    renderModelLists();
  }
}

function normalizeModels(data) {
  const root = data && data.models && !data.detector && !data.lama ? data.models : (data || {});
  if (Array.isArray(root)) {
    return root.map((item) => ({
      kind: item.kind || item.id,
      name: item.name || LABELS[item.kind] || item.kind || "Модель",
      present: Boolean(item.present ?? item.ready ?? item.ok),
    })).filter((item) => item.kind);
  }
  const keys = ["detector", "lama", "font"].concat(Object.keys(root));
  const seen = new Set();
  const list = [];
  keys.forEach((kind) => {
    if (seen.has(kind)) return;
    const entry = root[kind];
    if (!entry || typeof entry !== "object") return;
    seen.add(kind);
    list.push({
      kind,
      name: LABELS[kind] || kind,
      present: Boolean(entry.present ?? entry.ready),
    });
  });
  return list;
}

function percentOf(payload) {
  if (payload.finished || payload.done === true) return 100;
  const done = payload.done_bytes ?? payload.loaded ?? (typeof payload.done === "number" ? payload.done : undefined);
  const total = payload.total_bytes ?? payload.total;
  if (typeof done === "number" && typeof total === "number" && total > 0) return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
  const raw = payload.percent ?? payload.progress;
  if (typeof raw !== "number") return null;
  const value = raw <= 1 ? raw * 100 : raw;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function mergeSettings(body, response) {
  if (response && response.settings && typeof response.settings === "object") return { ...body, ...response.settings };
  if (response && typeof response === "object" && response.theme) return { ...body, ...response };
  return body;
}

function bindTabs(root) {
  root.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => showSettingsTab(button.dataset.tab));
  });
  root.querySelector("[role='tablist']").addEventListener("keydown", (event) => {
    const tabs = [...root.querySelectorAll("[role='tab']")];
    const index = tabs.indexOf(document.activeElement);
    if (index < 0) return;
    let next = -1;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next < 0) return;
    event.preventDefault();
    tabs[next].focus();
    showSettingsTab(tabs[next].dataset.tab);
  });
}

function showSettingsTab(name) {
  screen.querySelectorAll("[data-tab]").forEach((button) => {
    const on = button.dataset.tab === name;
    button.setAttribute("aria-selected", on ? "true" : "false");
    button.tabIndex = on ? 0 : -1;
  });
  screen.querySelectorAll("[data-tabpanel]").forEach((panel) => {
    panel.hidden = panel.dataset.tabpanel !== name;
  });
  if (name === "models") {
    refreshModels();
    refreshSettingsPreparation();
  } else if (settingsPrepTimer) {
    window.clearInterval(settingsPrepTimer);
    settingsPrepTimer = 0;
  }
  if (name === "network") paintRemote();
}

function syncLang(id, key) {
  const input = document.getElementById(id);
  if (!input || document.activeElement === input) return;
  const value = getState().settings[key] || "";
  if (input.value !== value) input.value = value;
}

function checked(name) {
  return document.querySelector(`input[name='${name}']:checked`)?.value || "";
}

function checkRadio(name, value) {
  const input = document.querySelector(`input[name='${name}'][value='${value}']`) || document.querySelector(`input[name='${name}'][value='system']`);
  if (input) input.checked = true;
}

function clampScale(value) {
  return Math.min(150, Math.max(100, Math.round(Number(value) || 100)));
}

function numberValue(id, fallback) {
  const value = Number(document.getElementById(id).value);
  return Number.isFinite(value) ? value : fallback;
}

function notify(text) {
  if (!text) return;
  setBanner("settings-error", { text });
}

function icon(id) {
  return `<svg class="icon" aria-hidden="true"><use href="icons/icons.svg#${id}"></use></svg>`;
}

function escapeText(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function escapeAttr(value) {
  return escapeText(value);
}

function onRemoteClick(event) {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.role === "pair-code") issuePairCode();
  if (button.dataset.role === "revoke-device") revokeDevice(button.dataset.deviceId);
}

async function issuePairCode() {
  remoteActionError = "";
  paintRemote();
  try {
    const data = await remotePair();
    remoteActionError = "";
    patch({ remote: remoteView(data) });
  } catch (error) {
    remoteActionError = error.message || "Не удалось выдать код";
    paintRemote();
  }
}

async function revokeDevice(id) {
  if (!id) return;
  remoteActionError = "";
  try {
    const data = await remoteRevoke(id);
    patch({ remote: remoteView(data) });
  } catch (error) {
    remoteActionError = error.message || "Не удалось отозвать доступ";
    paintRemote();
  }
}

function remoteView(data) {
  return {
    enabled: Boolean(data && data.enabled),
    clients: Number(data && data.clients) || 0,
    addresses: (data && data.addresses) || [],
    pairing_code: (data && data.pairing_code) || "",
    devices: (data && data.devices) || [],
    recent: (data && data.recent) || [],
    loaded: true,
    error: "",
  };
}

function paintRemote() {
  const root = document.querySelector("[data-role='remote-live']");
  if (!root) return;
  const remote = getState().remote || {};
  const loaded = Boolean(remote.loaded);
  let name = "loading";
  const problem = remoteActionError || remote.error || "";
  if (problem) name = "error";
  else if (!loaded) name = "loading";
  else if (!remote.enabled) name = "empty";
  else name = "ready";
  root.innerHTML = remoteHtml(name, remote);
}

function remoteHtml(name, remote) {
  const code = remote.pairing_code ? `<p class="pair-code" aria-live="polite">${escapeText(remote.pairing_code)}</p>` : `<p class="muted">Код ещё не выдан</p>`;
  const devices = Array.isArray(remote.devices) ? remote.devices : [];
  const recent = Array.isArray(remote.recent) ? remote.recent : [];
  const deviceList = devices.length
    ? `<ul class="remote-devices">${devices.map((device) => {
      const id = String(device.id || device.device_id || "");
      const label = device.name || device.label || id || "Устройство";
      return `<li><span>${escapeText(label)}</span><button type="button" class="btn btn-ghost" data-role="revoke-device" data-device-id="${escapeAttr(id)}">Отозвать</button></li>`;
    }).join("")}</ul>`
    : `<p class="muted">Подключённых устройств нет</p>`;
  const log = recent.length
    ? `<ul class="remote-log">${recent.map((item) => `<li>${escapeText(typeof item === "string" ? item : (item.text || item.message || JSON.stringify(item)))}</li>`).join("")}</ul>`
    : `<p class="muted">Журнал пуст</p>`;
  const pair = `<button type="button" class="btn btn-accent" data-role="pair-code">Новый код подключения</button>`;
  if (name === "loading") {
    return `<div class="remote-state" data-state="loading" aria-busy="true"><h3>Читаем состояние сети</h3><p role="status">Читаем состояние сети</p></div>`;
  }
  if (name === "error") {
    return `<div class="remote-state" data-state="error"><h3>Сеть недоступна</h3><p class="style-fail" role="alert">${icon("error")}<span>${escapeText(remoteActionError || remote.error || "Нет ответа")}</span></p>${pair}</div>`;
  }
  if (name === "empty") {
    return `<div class="remote-state" data-state="empty"><h3>Доступ по сети выключен</h3><p class="muted">Включите доступ и нажмите ОК или Применить. Код можно запросить и до включения: сервер ответит, если сеть ещё не запущена.</p>${pair}${code}</div>`;
  }
  const addresses = (remote.addresses || []).map((item) => escapeText(typeof item === "string" ? item : (item.url || item.host || ""))).filter(Boolean);
  return `<div class="remote-state" data-state="ready"><h3>Сеть включена</h3>${addresses.length ? `<p>${addresses.join(", ")}</p>` : ""}${pair}${code}<h3>Устройства</h3>${deviceList}<h3>Недавние</h3>${log}</div>`;
}
