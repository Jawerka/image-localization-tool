// Короткие сигналы: моно WAV без внешних файлов. Громкость задаёт плеер.
(function () {
  "use strict";

  const RATE = 22050;
  const PEAK = 0.9;
  const OFF_ID = "off";
  const DEFAULT_VOLUME = 50;

  const SOUNDS = [
    { id: "drop", title: "Капля" },
    { id: "drops", title: "Две капли" },
    { id: "third", title: "Терция" },
    { id: "fifth", title: "Квинта вниз" },
    { id: "bell", title: "Колокольчик" },
    { id: "wood", title: "Дерево" },
    { id: "three", title: "Три ноты" },
    { id: "glass", title: "Стекло" },
    { id: "marimba", title: "Маримба" },
    { id: "chord", title: "Аккорд" },
  ];

  const LIST = SOUNDS.concat([{ id: OFF_ID, title: "Без звука" }]);

  const DEFAULT_ID = "drop";

  function isSound(id) {
    for (let i = 0; i < SOUNDS.length; i++) {
      if (SOUNDS[i].id === id) return true;
    }
    return false;
  }

  function known(id) {
    return id === OFF_ID || isSound(id);
  }

  function resolveId(id) {
    return isSound(id) ? id : DEFAULT_ID;
  }

  function clampVolume(value) {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return DEFAULT_VOLUME;
    return Math.max(0, Math.min(100, Math.round(n)));
  }

  function eventsFor(id) {
    const name = resolveId(id);
    if (name === "drop") {
      return { dur: 0.22, notes: [{ start: 0, dur: 0.22, f0: 880, f1: 660, amp: 1, decay: 7 }] };
    }
    if (name === "drops") {
      return {
        dur: 0.4,
        notes: [
          { start: 0, dur: 0.16, f0: 880, f1: 700, amp: 1, decay: 8 },
          { start: 0.22, dur: 0.18, f0: 740, f1: 560, amp: 0.85, decay: 8 },
        ],
      };
    }
    if (name === "third") {
      return {
        dur: 0.4,
        notes: [
          { start: 0, dur: 0.2, f0: 523.25, f1: 523.25, amp: 0.9, decay: 5 },
          { start: 0.18, dur: 0.22, f0: 659.25, f1: 659.25, amp: 0.85, decay: 5 },
        ],
      };
    }
    if (name === "fifth") {
      return {
        dur: 0.42,
        notes: [
          { start: 0, dur: 0.2, f0: 659.25, f1: 659.25, amp: 0.85, decay: 5 },
          { start: 0.2, dur: 0.22, f0: 440, f1: 440, amp: 0.9, decay: 4.5 },
        ],
      };
    }
    if (name === "bell") {
      return {
        dur: 0.5,
        notes: [{ start: 0, dur: 0.5, f0: 784, f1: 784, amp: 0.8, decay: 4.2, harm: 0.28, harmRatio: 2 }],
      };
    }
    if (name === "wood") {
      return {
        dur: 0.16,
        notes: [{ start: 0, dur: 0.16, f0: 520, f1: 480, amp: 1, decay: 12, attack: 0.004 }],
      };
    }
    if (name === "three") {
      return {
        dur: 0.42,
        notes: [
          { start: 0, dur: 0.14, f0: 783.99, f1: 783.99, amp: 0.7, decay: 7 },
          { start: 0.14, dur: 0.14, f0: 587.33, f1: 587.33, amp: 0.7, decay: 7 },
          { start: 0.28, dur: 0.14, f0: 440, f1: 440, amp: 0.75, decay: 6 },
        ],
      };
    }
    if (name === "glass") {
      return {
        dur: 0.15,
        notes: [{ start: 0, dur: 0.15, f0: 1568, f1: 1480, amp: 0.7, decay: 10, attack: 0.004 }],
      };
    }
    if (name === "marimba") {
      return {
        dur: 0.28,
        notes: [{ start: 0, dur: 0.28, f0: 784, f1: 690, amp: 1, decay: 6 }],
      };
    }
    return {
      dur: 0.4,
      notes: [
        { start: 0, dur: 0.4, f0: 261.63, f1: 261.63, amp: 0.55, decay: 4 },
        { start: 0, dur: 0.4, f0: 329.63, f1: 329.63, amp: 0.45, decay: 4.2 },
        { start: 0, dur: 0.4, f0: 392, f1: 392, amp: 0.4, decay: 4.4 },
      ],
    };
  }

  function addNote(samples, note) {
    const start = Math.round(note.start * RATE);
    const count = Math.max(1, Math.round(note.dur * RATE));
    const f0 = note.f0;
    const f1 = note.f1 == null ? note.f0 : note.f1;
    const attack = note.attack == null ? 0.012 : note.attack;
    const decay = note.decay == null ? 5.5 : note.decay;
    const harm = note.harm || 0;
    const harmRatio = note.harmRatio || 2;
    let phase = 0;
    let phase2 = 0;
    for (let i = 0; i < count; i++) {
      const idx = start + i;
      if (idx < 0 || idx >= samples.length) continue;
      const t = i / RATE;
      const u = count <= 1 ? 1 : i / (count - 1);
      const freq = f0 + (f1 - f0) * u;
      phase += (2 * Math.PI * freq) / RATE;
      let sample = Math.sin(phase);
      if (harm > 0) {
        phase2 += (2 * Math.PI * freq * harmRatio) / RATE;
        sample += harm * Math.sin(phase2);
      }
      const rise = t < attack ? t / attack : 1;
      const tail = Math.exp((-decay * t) / note.dur);
      samples[idx] += note.amp * rise * tail * sample;
    }
  }

  function render(id) {
    const spec = eventsFor(id);
    const count = Math.max(1, Math.round(spec.dur * RATE));
    const samples = new Float64Array(count);
    for (let i = 0; i < spec.notes.length; i++) addNote(samples, spec.notes[i]);
    let peak = 0;
    for (let i = 0; i < count; i++) {
      const value = Math.abs(samples[i]);
      if (value > peak) peak = value;
    }
    const gain = peak > 0 ? PEAK / peak : 0;
    const pcm = new Int16Array(count);
    for (let i = 0; i < count; i++) {
      let value = samples[i] * gain;
      if (value > PEAK) value = PEAK;
      if (value < -PEAK) value = -PEAK;
      pcm[i] = Math.round(value * 32767);
    }
    return pcm;
  }

  function writeAscii(view, offset, text) {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  }

  function wavBytes(id) {
    const pcm = render(id);
    const dataSize = pcm.length * 2;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);
    writeAscii(view, 0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    writeAscii(view, 8, "WAVE");
    writeAscii(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, RATE, true);
    view.setUint32(28, RATE * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, "data");
    view.setUint32(40, dataSize, true);
    let offset = 44;
    for (let i = 0; i < pcm.length; i++) {
      view.setInt16(offset, pcm[i], true);
      offset += 2;
    }
    return new Uint8Array(buffer);
  }

  function play(id, volume) {
    if (id === OFF_ID) return Promise.resolve();
    const bytes = wavBytes(id);
    if (typeof Audio === "undefined") return Promise.resolve();
    const blob = new Blob([bytes], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.volume = clampVolume(volume) / 100;
    const release = () => {
      try {
        URL.revokeObjectURL(url);
      } catch (_) {}
    };
    return new Promise((resolve, reject) => {
      audio.addEventListener(
        "ended",
        () => {
          release();
          resolve();
        },
        { once: true },
      );
      const started = audio.play();
      if (started && typeof started.then === "function") {
        started.catch((err) => {
          release();
          reject(err);
        });
      }
    });
  }

  globalThis.iltChime = {
    list: LIST,
    sounds: SOUNDS,
    defaultId: DEFAULT_ID,
    defaultVolume: DEFAULT_VOLUME,
    offId: OFF_ID,
    rate: RATE,
    peak: PEAK,
    known,
    clampVolume,
    wavBytes,
    play,
  };
})();
