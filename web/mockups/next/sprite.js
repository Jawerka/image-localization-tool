(function () {
  "use strict";
  /* Встроенный спрайт: внешние <use> блокируются на file://. Канонический источник: icons-v2.svg */
  var sprite = `
<svg xmlns="http://www.w3.org/2000/svg" style="display:none">
  <!-- v2: базовый набор (совместим с ../icons/icons.svg) + новые символы.
       Правило: контурные иконки stroke 1.75, круглые окончания, viewBox 24. -->
  <symbol id="folder" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3.5 7.2V6.4A1.4 1.4 0 0 1 4.9 5h4.2l1.6 2h8.4A1.4 1.4 0 0 1 20.5 8.4V18a1.4 1.4 0 0 1-1.4 1.4H4.9A1.4 1.4 0 0 1 3.5 18V7.2z"/>
    </g>
  </symbol>
  <symbol id="file" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M7 3.5h6.2L19 9.2V20.5H7z"/>
      <path d="M13.2 3.5V9.2H19"/>
    </g>
  </symbol>
  <symbol id="play" viewBox="0 0 24 24">
    <path fill="currentColor" d="M8 5.2v13.6l11-6.8z"/>
  </symbol>
  <symbol id="pause" viewBox="0 0 24 24">
    <g fill="currentColor">
      <rect x="7.6" y="6" width="3.2" height="12" rx="1.2"/>
      <rect x="13.2" y="6" width="3.2" height="12" rx="1.2"/>
    </g>
  </symbol>
  <symbol id="stop" viewBox="0 0 24 24">
    <rect fill="currentColor" x="6.5" y="6.5" width="11" height="11" rx="2"/>
  </symbol>
  <symbol id="settings" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M12 3.2v2.3M12 18.5V20.8M3.2 12h2.3M18.5 12h2.3M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6"/>
    </g>
  </symbol>
  <symbol id="export" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 3.5v10"/>
      <path d="M8 10.5 12 14.5l4-4"/>
      <path d="M5 15.5V20h14v-4.5"/>
    </g>
  </symbol>
  <symbol id="download" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 3.5v10"/>
      <path d="M8 10.2 12 14.2l4-4"/>
      <path d="M5 19.5h14"/>
    </g>
  </symbol>
  <symbol id="translate" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3.5 6h7"/>
      <path d="M7 6c.2 3.2-1.4 5.4-3.6 6.4"/>
      <path d="M4.6 9h4.2"/>
      <path d="M13 19.2 15.3 12h1.2l2.3 7.2"/>
      <path d="M13.8 16.6h3.6"/>
      <path d="M18.2 5.2h3.2"/>
      <path d="M19.8 3.6v3.2"/>
    </g>
  </symbol>
  <symbol id="globe" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8"/>
      <path d="M4 12h16"/>
      <path d="M12 4c2.4 2.3 3.7 5 3.7 8s-1.3 5.7-3.7 8c-2.4-2.3-3.7-5-3.7-8S9.6 6.3 12 4z"/>
    </g>
  </symbol>
  <symbol id="brush" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14.2 4.2 19.8 9.8 10.2 19.4H5.2v-5z"/>
      <path d="M12.8 5.6 18.4 11.2"/>
      <path d="M4.8 20.6c1.3-.9 2.1-.7 2.8 0 .8.8 1.7.2 2.8-.6"/>
    </g>
  </symbol>
  <symbol id="polyline" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 18 9 8 14 14 20 5"/>
      <circle cx="4" cy="18" r="1.4" fill="currentColor" stroke="none"/>
      <circle cx="9" cy="8" r="1.4" fill="currentColor" stroke="none"/>
      <circle cx="14" cy="14" r="1.4" fill="currentColor" stroke="none"/>
      <circle cx="20" cy="5" r="1.4" fill="currentColor" stroke="none"/>
    </g>
  </symbol>
  <symbol id="eraser" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14 4.8 20.2 11 12.6 18.6H8.2L3.6 14 10.6 7z"/>
      <path d="M9.4 9.6 15.2 15.4"/>
      <path d="M8 20.5h12"/>
    </g>
  </symbol>
  <symbol id="select" viewBox="0 0 24 24">
    <path fill="currentColor" d="M5.2 3.2 5.2 17.2 9.6 13.2 13.8 20.2 16.2 19 12.1 12.1 18 11.4z"/>
  </symbol>
  <symbol id="region" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M9 4H5.5A1.5 1.5 0 0 0 4 5.5V9"/>
      <path d="M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9"/>
      <path d="M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15"/>
      <path d="M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15"/>
      <rect x="8" y="8" width="8" height="8" stroke-dasharray="2 1.6"/>
    </g>
  </symbol>
  <symbol id="compare" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2"/>
      <path d="M12 4.5v15"/>
      <path d="M8.2 9.2 6.2 12l2 2.8"/>
      <path d="M15.8 9.2 17.8 12l-2 2.8"/>
    </g>
  </symbol>
  <symbol id="original" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2"/>
      <circle cx="8.5" cy="9" r="1.4"/>
      <path d="M3.5 16.2 8.4 12.2 12 15.2 15.2 12.4 20.5 16.8"/>
    </g>
  </symbol>
  <symbol id="mask" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="4" y="4" width="16" height="16" rx="2"/>
      <path d="M4 12h16M12 4v16"/>
    </g>
  </symbol>
  <symbol id="layers" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 3.5 21 8.2 12 12.9 3 8.2z"/>
      <path d="M3 12.2 12 16.9 21 12.2"/>
      <path d="M3 16.2 12 20.9 21 16.2"/>
    </g>
  </symbol>
  <symbol id="undo" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M9 7H4.8V11"/>
      <path d="M5.4 8.2A7 7 0 1 1 6.6 16.5"/>
    </g>
  </symbol>
  <symbol id="redo" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M15 7h4.2V11"/>
      <path d="M18.6 8.2A7 7 0 1 0 17.4 16.5"/>
    </g>
  </symbol>
  <symbol id="zoom" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="10.5" cy="10.5" r="5.75"/>
      <path d="M14.8 14.8 20 20"/>
    </g>
  </symbol>
  <symbol id="search" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="10.7" cy="10.7" r="5.6"/>
      <path d="M14.9 14.9 20 20"/>
    </g>
  </symbol>
  <symbol id="minus" viewBox="0 0 24 24">
    <path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" d="M6 12h12"/>
  </symbol>
  <symbol id="add" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 5v14M5 12h14"/>
    </g>
  </symbol>
  <symbol id="warning" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 3.8 21.4 20.2H2.6z"/>
      <path d="M12 9.2v4.4"/>
      <path d="M12 16.8h.01"/>
    </g>
  </symbol>
  <symbol id="error" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8"/>
      <path d="M9 9l6 6M15 9l-6 6"/>
    </g>
  </symbol>
  <symbol id="check" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 12.5 9.2 17.2 19.5 6.8"/>
    </g>
  </symbol>
  <symbol id="info" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8"/>
      <path d="M12 11v5"/>
      <path d="M12 8h.01"/>
    </g>
  </symbol>
  <symbol id="ban" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8"/>
      <path d="M6.6 6.6l10.8 10.8"/>
    </g>
  </symbol>
  <symbol id="refresh" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M19.4 9.2A7.6 7.6 0 1 0 19.6 14"/>
      <path d="M19.6 4.8v4.4h-4.4"/>
    </g>
  </symbol>
  <symbol id="compress" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 12h5.3M14.2 12h5.3"/>
      <path d="M9.8 8.7 6.2 12l3.6 3.3"/>
      <path d="M14.2 8.7 17.8 12l-3.6 3.3"/>
    </g>
  </symbol>
  <symbol id="copy" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="9" y="9" width="10.5" height="10.5" rx="2"/>
      <path d="M15 9V6.5a2 2 0 0 0-2-2H6.5a2 2 0 0 0-2 2V13a2 2 0 0 0 2 2H9"/>
    </g>
  </symbol>
  <symbol id="delete" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 7h15"/>
      <path d="M9 7V4.8h6V7"/>
      <path d="M7.4 7.2 8.2 19.5h7.6l.8-12.3"/>
      <path d="M10 11v5M14 11v5"/>
    </g>
  </symbol>
  <symbol id="hand" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M8 11.2V6.2a1.35 1.35 0 0 1 2.7 0v5"/>
      <path d="M10.7 10.2V5.2a1.35 1.35 0 0 1 2.7 0V11"/>
      <path d="M13.4 11V7.4a1.35 1.35 0 0 1 2.7 0V13"/>
      <path d="M8 12.2V11c0-.9-.6-1.6-1.45-1.6S5.1 10.2 5.1 11.6c0 2.3 1.3 4.5 3.4 6.2 1.4 1.1 3.1 1.9 4.9 1.9 2.9 0 5.1-1.9 5.1-4.5V13"/>
    </g>
  </symbol>
  <symbol id="move" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 4.5v15M4.5 12h15"/>
      <path d="M9.3 7.2 12 4.5l2.7 2.7M9.3 16.8 12 19.5l2.7-2.7M7.2 9.3 4.5 12l2.7 2.7M16.8 9.3 19.5 12l-2.7 2.7"/>
    </g>
  </symbol>
  <symbol id="type" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5 6.2V4.8h14v1.4"/>
      <path d="M12 4.8v14.4"/>
      <path d="M9.4 19.2h5.2"/>
    </g>
  </symbol>
  <symbol id="sliders" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 7.5h16M4 12h16M4 16.5h16"/>
      <circle cx="9.5" cy="7.5" r="2.1"/>
      <circle cx="15" cy="12" r="2.1"/>
      <circle cx="7.5" cy="16.5" r="2.1"/>
    </g>
  </symbol>
  <symbol id="palette" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 20.2c-4.6 0-8.3-3.7-8.3-8.2C3.7 7.3 7.4 3.8 12 3.8c4.4 0 8.3 3 8.3 6.9 0 2.4-1.9 3.9-4.1 3.9h-1.6c-1 0-1.8.8-1.8 1.7 0 .4.1.8.4 1.1.2.3.4.7.4 1.1 0 .9-.8 1.7-1.6 1.7z"/>
      <circle cx="8.3" cy="9.4" r="1.1" fill="currentColor" stroke="none"/>
      <circle cx="12.3" cy="7.5" r="1.1" fill="currentColor" stroke="none"/>
      <circle cx="16.1" cy="9.5" r="1.1" fill="currentColor" stroke="none"/>
    </g>
  </symbol>
  <symbol id="eye" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3.6 12S6.8 6.3 12 6.3 20.4 12 20.4 12 17.2 17.7 12 17.7 3.6 12 3.6 12z"/>
      <circle cx="12" cy="12" r="2.6"/>
    </g>
  </symbol>
  <symbol id="target" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8"/>
      <circle cx="12" cy="12" r="3"/>
      <path d="M12 4v2.6M12 17.4V20M4 12h2.6M17.4 12H20"/>
    </g>
  </symbol>
  <symbol id="clock" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8"/>
      <path d="M12 7.5V12l3.2 2"/>
    </g>
  </symbol>
  <symbol id="llm" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="7" y="7" width="10" height="10" rx="2"/>
      <path d="M12 7V3.5M12 20.5V17M7 12H3.5M20.5 12H17"/>
      <path d="M8.2 8.2 5.8 5.8M15.8 15.8l2.4 2.4M15.8 8.2l2.4-2.4M8.2 15.8 5.8 18.2"/>
    </g>
  </symbol>
  <symbol id="gpu" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="7" width="18" height="10" rx="2"/>
      <circle cx="8" cy="12" r="1.35"/>
      <circle cx="12" cy="12" r="1.35"/>
      <circle cx="16" cy="12" r="1.35"/>
      <path d="M7 7V4.8M12 7V4.8M17 7V4.8"/>
    </g>
  </symbol>
  <symbol id="panel-left" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/>
      <path d="M9.7 4.5v15"/>
    </g>
  </symbol>
  <symbol id="panel-right" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/>
      <path d="M14.3 4.5v15"/>
    </g>
  </symbol>
  <symbol id="grip" viewBox="0 0 24 24">
    <g fill="currentColor">
      <circle cx="9.4" cy="7.4" r="1.25"/><circle cx="14.6" cy="7.4" r="1.25"/>
      <circle cx="9.4" cy="12" r="1.25"/><circle cx="14.6" cy="12" r="1.25"/>
      <circle cx="9.4" cy="16.6" r="1.25"/><circle cx="14.6" cy="16.6" r="1.25"/>
    </g>
  </symbol>
  <symbol id="more-h" viewBox="0 0 24 24">
    <g fill="currentColor">
      <circle cx="5.8" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="18.2" cy="12" r="1.5"/>
    </g>
  </symbol>
  <symbol id="fit-width" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 12h15"/>
      <path d="M8 8.5 4.5 12 8 15.5"/>
      <path d="M16 8.5 19.5 12 16 15.5"/>
    </g>
  </symbol>
  <symbol id="fit" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 9V6.8a2.3 2.3 0 0 1 2.3-2.3H9"/>
      <path d="M15 4.5h2.2a2.3 2.3 0 0 1 2.3 2.3V9"/>
      <path d="M19.5 15v2.2a2.3 2.3 0 0 1-2.3 2.3H15"/>
      <path d="M9 19.5H6.8a2.3 2.3 0 0 1-2.3-2.3V15"/>
    </g>
  </symbol>
  <symbol id="chevron" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M6 9l6 6 6-6"/>
    </g>
  </symbol>
  <symbol id="close" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <path d="M6 6l12 12M18 6 6 18"/>
    </g>
  </symbol>
  <symbol id="keyboard" viewBox="0 0 24 24">
    <g fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="6.5" width="18" height="11" rx="2.5"/>
      <path d="M6.6 10h.01M9.8 10h.01M13 10h.01M16.2 10h.01M8 13.6h8"/>
    </g>
  </symbol>
</svg>

`;
  document.write(sprite);
})();
