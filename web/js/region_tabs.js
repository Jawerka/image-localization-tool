/** Чистая логика вкладок карточки региона: выбор живёт в UI-состоянии. */

export const REGION_TABS = [
  ["text", "Текст"],
  ["font", "Шрифт"],
  ["transform", "Трансформация"],
];

export function regionTabKey(state, regionId) {
  const project = state && state.project && state.project.id ? String(state.project.id) : "";
  return `${project}/${(state && state.activePageId) || ""}/${regionId}`;
}

export function regionTabFor(map, state, regionId, fallback = "text") {
  return map.get(regionTabKey(state, regionId)) || fallback;
}

export function setRegionTab(map, state, regionId, tab) {
  if (!REGION_TABS.some(([id]) => id === tab)) return;
  map.set(regionTabKey(state, regionId), tab);
}
