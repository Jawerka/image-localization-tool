const WIDTH = 800;
const HEIGHT = 400;
const GRID_X = 16;
const GRID_Y = 12;
const SUBDIVISIONS = 4;
const FRAME_COUNT = 180;
const WARMUP = 15;

function percentile(values, ratio) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * ratio))];
}

function summary(values) {
  return Object.fromEntries([["p50", 0.5], ["p95", 0.95], ["max", 1]].map(([key, ratio]) => [
    key,
    Number((ratio === 1 ? Math.max(...values) : percentile(values, ratio)).toFixed(3)),
  ]));
}

function makeLayer() {
  const layer = document.createElement("canvas");
  layer.width = WIDTH;
  layer.height = HEIGHT;
  const context = layer.getContext("2d");
  context.font = "bold 76px Arial";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineJoin = "round";
  context.lineWidth = 9;
  context.strokeStyle = "rgba(0,0,0,.92)";
  context.fillStyle = "white";
  context.strokeText("Привет, мир! Ёжик 123", WIDTH / 2, HEIGHT / 2);
  context.fillText("Привет, мир! Ёжик 123", WIDTH / 2, HEIGHT / 2);
  return layer;
}

function makeGeometry() {
  const columns = GRID_X * SUBDIVISIONS;
  const rows = GRID_Y * SUBDIVISIONS;
  const base = [];
  const indices = [];
  for (let y = 0; y <= rows; y += 1) {
    for (let x = 0; x <= columns; x += 1) {
      base.push((x / columns) * WIDTH, (y / rows) * HEIGHT);
    }
  }
  const stride = columns + 1;
  for (let y = 0; y < rows; y += 1) {
    for (let x = 0; x < columns; x += 1) {
      const a = y * stride + x;
      const b = a + 1;
      const d = a + stride;
      const e = d + 1;
      indices.push(a, d, b, b, d, e);
    }
  }
  return { base, indices };
}

function makeWebGL(canvas, layer, base, indices) {
  const gl = canvas.getContext("webgl", {
    alpha: true,
    antialias: true,
    premultipliedAlpha: true,
    preserveDrawingBuffer: true,
  });
  if (!gl) throw new Error("WebGL недоступен");
  const shader = (type, source) => {
    const value = gl.createShader(type);
    gl.shaderSource(value, source);
    gl.compileShader(value);
    if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(value));
    return value;
  };
  const program = gl.createProgram();
  gl.attachShader(program, shader(gl.VERTEX_SHADER,
    "attribute vec2 p;attribute vec2 uv;varying vec2 v;void main(){gl_Position=vec4(p.x/400.0-1.0,1.0-p.y/200.0,0.0,1.0);v=uv;}"));
  gl.attachShader(program, shader(gl.FRAGMENT_SHADER,
    "precision mediump float;uniform sampler2D tex;varying vec2 v;void main(){gl_FragColor=texture2D(tex,v);}"));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
  gl.useProgram(program);
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, layer);
  const positions = new Float32Array(base);
  const uvs = new Float32Array(base.length);
  for (let i = 0; i < base.length; i += 2) {
    uvs[i] = base[i] / WIDTH;
    uvs[i + 1] = 1 - base[i + 1] / HEIGHT;
  }
  const positionBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, positions, gl.DYNAMIC_DRAW);
  const positionLocation = gl.getAttribLocation(program, "p");
  gl.enableVertexAttribArray(positionLocation);
  gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
  const uvBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, uvBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, uvs, gl.STATIC_DRAW);
  const uvLocation = gl.getAttribLocation(program, "uv");
  gl.enableVertexAttribArray(uvLocation);
  gl.vertexAttribPointer(uvLocation, 2, gl.FLOAT, false, 0, 0);
  const indexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);
  gl.viewport(0, 0, WIDTH, HEIGHT);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  return { gl, positions, positionBuffer };
}

function deform(target, base, frame) {
  for (let i = 0; i < base.length; i += 2) {
    const x = base[i];
    const y = base[i + 1];
    target[i] = x;
    target[i + 1] = y + Math.sin((x / WIDTH) * Math.PI * 2 + frame * 0.04) * Math.sin((y / HEIGHT) * Math.PI) * 8;
  }
}

async function run() {
  const layer = makeLayer();
  const { base, indices } = makeGeometry();
  const { gl, positions, positionBuffer } = makeWebGL(document.querySelector("#plain"), layer, base, indices);
  const pixiApp = new PIXI.Application();
  await pixiApp.init({ width: WIDTH, height: HEIGHT, preference: "webgl", antialias: true, backgroundAlpha: 0, autoStart: false, preserveDrawingBuffer: true });
  document.querySelector("#pixi").replaceChildren(pixiApp.canvas);
  const mesh = new PIXI.MeshPlane({ texture: PIXI.Texture.from(layer), verticesX: GRID_X * SUBDIVISIONS + 1, verticesY: GRID_Y * SUBDIVISIONS + 1 });
  pixiApp.stage.addChild(mesh);
  const buffer = mesh.geometry.getAttribute("aPosition").buffer;
  const pixiPositions = buffer.data;
  const pixiBase = pixiPositions.slice();
  async function record(draw) {
    const drawTimes = [];
    const intervals = [];
    let previous = 0;
    for (let frame = 0; frame < FRAME_COUNT; frame += 1) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const frameStart = performance.now();
      if (previous) intervals.push(frameStart - previous);
      previous = frameStart;
      draw(frame);
      if (frame >= WARMUP) drawTimes.push(performance.now() - frameStart);
    }
    return { updateAndSubmit: summary(drawTimes), rafInterval: summary(intervals.slice(WARMUP)) };
  }
  const plainWebGL = await record((frame) => {
    deform(positions, base, frame);
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, positions);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawElements(gl.TRIANGLES, indices.length, gl.UNSIGNED_SHORT, 0);
  });
  const pixiMeshPlane = await record((frame) => {
    deform(pixiPositions, pixiBase, frame);
    buffer.update();
    pixiApp.renderer.render(pixiApp.stage);
  });
  const result = {
    browser: navigator.userAgent,
    pixiVersion: PIXI.VERSION,
    layer: `${WIDTH}x${HEIGHT} RGBA, Cyrillic, white fill + dark outline`,
    mesh: `${GRID_X}x${GRID_Y} cells subdivided ${SUBDIVISIONS}x${SUBDIVISIONS}; ${base.length / 2} vertices`,
    frames: FRAME_COUNT,
    plainWebGL,
    pixiMeshPlane,
    jsHeapBytes: performance.memory?.usedJSHeapSize ?? null,
    renderer: pixiApp.renderer.type,
  };
  document.querySelector("#result").textContent = JSON.stringify(result, null, 2);
  pixiApp.destroy(true);
}

document.querySelector("#run").addEventListener("click", () => run().catch((error) => {
  document.querySelector("#result").textContent = String(error.stack || error);
}));
