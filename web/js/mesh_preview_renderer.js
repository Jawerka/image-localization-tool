import { isValidMesh, mapMeshForward } from "./text_mesh.js";

const GRID_X = 16;
const GRID_Y = 12;
const SUBDIVISIONS = 4;

/** Локальный RGBA mesh renderer; текстура не меняется в течение жеста. */
export class MeshPreviewRenderer {
  constructor(canvas, onUnavailable = () => {}) {
    this.canvas = canvas;
    this.onUnavailable = onUnavailable;
    this.image = null;
    this.texture = null;
    this.gl = canvas.getContext("webgl", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: true,
      preserveDrawingBuffer: true,
    });
    this.ready = Boolean(this.gl && this._initialize());
    if (this.gl) {
      canvas.addEventListener("webglcontextlost", (event) => {
        event.preventDefault();
        this.ready = false;
        canvas.hidden = true;
        this.onUnavailable("Локальный предпросмотр отключён: WebGL-контекст потерян.");
      });
    }
    if (!this.ready) this.onUnavailable("Локальный предпросмотр недоступен; остаётся точный серверный результат.");
  }

  _initialize() {
    const gl = this.gl;
    const vertex = this._shader(gl.VERTEX_SHADER,
      "attribute vec2 aPosition;attribute vec2 aUv;uniform vec2 uSize;varying vec2 vUv;void main(){gl_Position=vec4(aPosition.x/uSize.x*2.0-1.0,1.0-aPosition.y/uSize.y*2.0,0.0,1.0);vUv=aUv;}");
    const fragment = this._shader(gl.FRAGMENT_SHADER,
      "precision mediump float;uniform sampler2D uTexture;varying vec2 vUv;void main(){gl_FragColor=texture2D(uTexture,vUv);}");
    if (!vertex || !fragment) return false;
    const program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return false;
    this.program = program;
    this.positionBuffer = gl.createBuffer();
    this.uvBuffer = gl.createBuffer();
    this.indexBuffer = gl.createBuffer();
    this.texture = gl.createTexture();
    this.positionLocation = gl.getAttribLocation(program, "aPosition");
    this.uvLocation = gl.getAttribLocation(program, "aUv");
    this.sizeLocation = gl.getUniformLocation(program, "uSize");
    this._createIndices();
    gl.useProgram(program);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    return true;
  }

  _shader(kind, source) {
    const shader = this.gl.createShader(kind);
    this.gl.shaderSource(shader, source);
    this.gl.compileShader(shader);
    if (!this.gl.getShaderParameter(shader, this.gl.COMPILE_STATUS)) return null;
    return shader;
  }

  _createIndices() {
    const columns = GRID_X * SUBDIVISIONS;
    const rows = GRID_Y * SUBDIVISIONS;
    const indices = [];
    for (let y = 0; y < rows; y += 1) {
      for (let x = 0; x < columns; x += 1) {
        const a = y * (columns + 1) + x;
        const b = a + 1;
        const d = a + columns + 1;
        const e = d + 1;
        indices.push(a, d, b, b, d, e);
      }
    }
    this.indices = new Uint16Array(indices);
    this.gl.bindBuffer(this.gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    this.gl.bufferData(this.gl.ELEMENT_ARRAY_BUFFER, this.indices, this.gl.STATIC_DRAW);
  }

  setLayer(image) {
    if (!this.ready || !image || !image.complete) return false;
    this.image = image;
    this.canvas.dataset.ready = "true";
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.uvBuffer);
    const uvs = this._uvs();
    gl.bufferData(gl.ARRAY_BUFFER, uvs, gl.STATIC_DRAW);
    return true;
  }

  _uvs() {
    const columns = GRID_X * SUBDIVISIONS;
    const rows = GRID_Y * SUBDIVISIONS;
    const values = new Float32Array((columns + 1) * (rows + 1) * 2);
    let index = 0;
    for (let y = 0; y <= rows; y += 1) {
      for (let x = 0; x <= columns; x += 1) {
        values[index++] = x / columns;
        values[index++] = 1 - y / rows;
      }
    }
    return values;
  }

  render({ mesh, bbox, origin, rotation = 0, textPosition = null, anchor = null, pageSize }) {
    if (!this.ready || !this.image || !isValidMesh(mesh)) return false;
    const [bx, by, bw, bh] = bbox.map(Number);
    if (!(bw > 1 && bh > 1)) return false;
    const pivot = anchor || [bx + bw / 2, by + bh / 2];
    const target = textPosition || pivot;
    const delta = [Number(target[0]) - pivot[0], Number(target[1]) - pivot[1]];
    const radians = (Number(rotation) * Math.PI) / 180;
    const cos = Math.cos(radians);
    const sin = Math.sin(radians);
    const columns = GRID_X * SUBDIVISIONS;
    const rows = GRID_Y * SUBDIVISIONS;
    const points = new Float32Array((columns + 1) * (rows + 1) * 2);
    let index = 0;
    let left = Infinity;
    let top = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    for (let y = 0; y <= rows; y += 1) {
      for (let x = 0; x <= columns; x += 1) {
        const sourceX = Number(origin[0]) + (x / columns) * this.image.naturalWidth;
        const sourceY = Number(origin[1]) + (y / rows) * this.image.naturalHeight;
        const dx = sourceX - pivot[0];
        const dy = sourceY - pivot[1];
        const rotatedX = pivot[0] + cos * dx - sin * dy;
        const rotatedY = pivot[1] + sin * dx + cos * dy;
        const warped = mapMeshForward([rotatedX - bx, rotatedY - by], mesh, bw, bh);
        const outputX = warped ? bx + warped[0] + delta[0] : NaN;
        const outputY = warped ? by + warped[1] + delta[1] : NaN;
        points[index++] = outputX;
        points[index++] = outputY;
        if (Number.isFinite(outputX) && Number.isFinite(outputY)) {
          left = Math.min(left, outputX);
          top = Math.min(top, outputY);
          right = Math.max(right, outputX);
          bottom = Math.max(bottom, outputY);
        }
      }
    }
    if (!Number.isFinite(left) || !Number.isFinite(top) || !Number.isFinite(right) || !Number.isFinite(bottom)) return false;
    left = Math.max(0, Math.floor(left));
    top = Math.max(0, Math.floor(top));
    right = Math.min(Number(pageSize[0]), Math.ceil(right));
    bottom = Math.min(Number(pageSize[1]), Math.ceil(bottom));
    const width = Math.max(1, right - left);
    const height = Math.max(1, bottom - top);
    this.canvas.width = width;
    this.canvas.height = height;
    this.canvas.style.left = `${(left / pageSize[0]) * 100}%`;
    this.canvas.style.top = `${(top / pageSize[1]) * 100}%`;
    this.canvas.style.width = `${(width / pageSize[0]) * 100}%`;
    this.canvas.style.height = `${(height / pageSize[1]) * 100}%`;
    const localPositions = new Float32Array(points.length);
    for (let i = 0; i < points.length; i += 2) {
      localPositions[i] = Number.isFinite(points[i]) ? points[i] - left : -10000;
      localPositions[i + 1] = Number.isFinite(points[i + 1]) ? points[i + 1] - top : -10000;
    }
    const gl = this.gl;
    gl.viewport(0, 0, width, height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.program);
    gl.uniform2f(this.sizeLocation, width, height);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, localPositions, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(this.positionLocation);
    gl.vertexAttribPointer(this.positionLocation, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.uvBuffer);
    gl.enableVertexAttribArray(this.uvLocation);
    gl.vertexAttribPointer(this.uvLocation, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.drawElements(gl.TRIANGLES, this.indices.length, gl.UNSIGNED_SHORT, 0);
    this.canvas.hidden = false;
    return true;
  }

  hide() {
    this.canvas.hidden = true;
  }
}
