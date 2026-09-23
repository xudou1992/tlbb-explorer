// Minimal WebGL mesh viewer for M2-2: gray model + mouse rotation + zoom.
// No dependencies, ~300 lines, pure WebGL 1.0.

export class MeshViewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!this.gl) {
      throw new Error('WebGL not supported');
    }

    this.camera = {
      distance: 3,
      rotationX: -0.3,
      rotationY: 0.5,
      targetDistance: 3,
      targetRotationX: -0.3,
      targetRotationY: 0.5,
    };

    this.mouse = { down: false, lastX: 0, lastY: 0 };
    this.mesh = null;
    this.program = null;
    this.animationId = null;

    this.initShaders();
    this.initEvents();
    this.resize();
  }

  initShaders() {
    const gl = this.gl;

    const vsSource = `
      attribute vec3 aPosition;
      attribute vec3 aNormal;
      uniform mat4 uModelView;
      uniform mat4 uProjection;
      varying vec3 vNormal;
      varying vec3 vPosition;
      void main() {
        vec4 pos = uModelView * vec4(aPosition, 1.0);
        vPosition = pos.xyz;
        vNormal = mat3(uModelView) * aNormal;
        gl_Position = uProjection * pos;
      }
    `;

    const fsSource = `
      precision mediump float;
      varying vec3 vNormal;
      varying vec3 vPosition;
      void main() {
        vec3 normal = normalize(vNormal);
        vec3 lightDir = normalize(vec3(0.5, 1.0, 0.8));
        float diff = max(dot(normal, lightDir), 0.0);
        vec3 ambient = vec3(0.15);
        vec3 diffuse = vec3(0.7) * diff;
        vec3 color = ambient + diffuse;
        gl_FragColor = vec4(color, 1.0);
      }
    `;

    const vs = this.compileShader(gl.VERTEX_SHADER, vsSource);
    const fs = this.compileShader(gl.FRAGMENT_SHADER, fsSource);

    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);

    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error('Shader program link failed: ' + gl.getProgramInfoLog(program));
    }

    this.program = program;
    this.attribs = {
      position: gl.getAttribLocation(program, 'aPosition'),
      normal: gl.getAttribLocation(program, 'aNormal'),
    };
    this.uniforms = {
      modelView: gl.getUniformLocation(program, 'uModelView'),
      projection: gl.getUniformLocation(program, 'uProjection'),
    };
  }

  compileShader(type, source) {
    const gl = this.gl;
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error('Shader compile failed: ' + gl.getShaderInfoLog(shader));
    }
    return shader;
  }

  initEvents() {
    this.canvas.addEventListener('mousedown', (e) => {
      this.mouse.down = true;
      this.mouse.lastX = e.clientX;
      this.mouse.lastY = e.clientY;
    });

    this.canvas.addEventListener('mousemove', (e) => {
      if (!this.mouse.down) return;
      const dx = e.clientX - this.mouse.lastX;
      const dy = e.clientY - this.mouse.lastY;
      this.mouse.lastX = e.clientX;
      this.mouse.lastY = e.clientY;
      this.camera.targetRotationY += dx * 0.01;
      this.camera.targetRotationX += dy * 0.01;
      this.camera.targetRotationX = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, this.camera.targetRotationX));
    });

    this.canvas.addEventListener('mouseup', () => {
      this.mouse.down = false;
    });

    this.canvas.addEventListener('mouseleave', () => {
      this.mouse.down = false;
    });

    this.canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 1.1 : 0.9;
      this.camera.targetDistance *= delta;
      this.camera.targetDistance = Math.max(0.5, Math.min(50, this.camera.targetDistance));
    });

    this.canvas.addEventListener('dblclick', () => {
      this.resetCamera();
    });

    window.addEventListener('resize', () => this.resize());
  }

  resetCamera() {
    this.camera.targetDistance = 3;
    this.camera.targetRotationX = -0.3;
    this.camera.targetRotationY = 0.5;
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
  }

  loadMesh(data) {
    const gl = this.gl;

    if (!data.positions || !data.indices) {
      throw new Error('Mesh data missing positions or indices');
    }

    // Flatten positions
    const positions = new Float32Array(data.positions.flat());
    const indices = new Uint16Array(data.indices);

    // Compute normals if not provided
    let normals;
    if (data.normals && data.normals.length > 0) {
      normals = new Float32Array(data.normals.flat());
    } else {
      normals = this.computeNormals(positions, indices);
    }

    // Compute bounding box for auto-centering
    const bbox = this.computeBBox(positions);
    const center = [
      (bbox.min[0] + bbox.max[0]) / 2,
      (bbox.min[1] + bbox.max[1]) / 2,
      (bbox.min[2] + bbox.max[2]) / 2,
    ];
    const size = Math.max(
      bbox.max[0] - bbox.min[0],
      bbox.max[1] - bbox.min[1],
      bbox.max[2] - bbox.min[2]
    );

    // Create buffers
    const posBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);

    const normalBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, normalBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, normals, gl.STATIC_DRAW);

    const indexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);

    this.mesh = {
      posBuffer,
      normalBuffer,
      indexBuffer,
      indexCount: indices.length,
      center,
      size,
    };

    // Auto-fit camera
    this.camera.targetDistance = size * 1.5;
    this.camera.distance = this.camera.targetDistance;
  }

  computeNormals(positions, indices) {
    const normals = new Float32Array(positions.length);
    const counts = new Float32Array(positions.length / 3);

    // Accumulate face normals
    for (let i = 0; i < indices.length; i += 3) {
      const i0 = indices[i] * 3;
      const i1 = indices[i + 1] * 3;
      const i2 = indices[i + 2] * 3;

      const v0 = [positions[i0], positions[i0 + 1], positions[i0 + 2]];
      const v1 = [positions[i1], positions[i1 + 1], positions[i1 + 2]];
      const v2 = [positions[i2], positions[i2 + 1], positions[i2 + 2]];

      const e1 = [v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]];
      const e2 = [v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]];

      const n = [
        e1[1] * e2[2] - e1[2] * e2[1],
        e1[2] * e2[0] - e1[0] * e2[2],
        e1[0] * e2[1] - e1[1] * e2[0],
      ];

      for (let j = 0; j < 3; j++) {
        const idx = indices[i + j];
        normals[idx * 3] += n[0];
        normals[idx * 3 + 1] += n[1];
        normals[idx * 3 + 2] += n[2];
        counts[idx]++;
      }
    }

    // Normalize
    for (let i = 0; i < normals.length; i += 3) {
      const len = Math.sqrt(normals[i] * normals[i] + normals[i + 1] * normals[i + 1] + normals[i + 2] * normals[i + 2]);
      if (len > 0.0001) {
        normals[i] /= len;
        normals[i + 1] /= len;
        normals[i + 2] /= len;
      } else {
        normals[i + 1] = 1; // default up
      }
    }

    return normals;
  }

  computeBBox(positions) {
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < positions.length; i += 3) {
      for (let j = 0; j < 3; j++) {
        min[j] = Math.min(min[j], positions[i + j]);
        max[j] = Math.max(max[j], positions[i + j]);
      }
    }
    return { min, max };
  }

  start() {
    if (this.animationId) return;
    const frame = () => {
      this.render();
      this.animationId = requestAnimationFrame(frame);
    };
    frame();
  }

  stop() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
  }

  render() {
    if (!this.mesh) return;

    const gl = this.gl;

    // Smooth camera
    this.camera.distance += (this.camera.targetDistance - this.camera.distance) * 0.1;
    this.camera.rotationX += (this.camera.targetRotationX - this.camera.rotationX) * 0.15;
    this.camera.rotationY += (this.camera.targetRotationY - this.camera.rotationY) * 0.15;

    gl.clearColor(0.09, 0.1, 0.12, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);

    gl.useProgram(this.program);

    // Model-view matrix
    const mv = this.mat4Identity();
    this.mat4Translate(mv, 0, 0, -this.camera.distance);
    this.mat4RotateX(mv, this.camera.rotationX);
    this.mat4RotateY(mv, this.camera.rotationY);
    this.mat4Translate(mv, -this.mesh.center[0], -this.mesh.center[1], -this.mesh.center[2]);

    // Projection matrix
    const aspect = this.canvas.width / this.canvas.height;
    const proj = this.mat4Perspective(Math.PI / 4, aspect, 0.1, 100);

    gl.uniformMatrix4fv(this.uniforms.modelView, false, mv);
    gl.uniformMatrix4fv(this.uniforms.projection, false, proj);

    gl.bindBuffer(gl.ARRAY_BUFFER, this.mesh.posBuffer);
    gl.enableVertexAttribArray(this.attribs.position);
    gl.vertexAttribPointer(this.attribs.position, 3, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ARRAY_BUFFER, this.mesh.normalBuffer);
    gl.enableVertexAttribArray(this.attribs.normal);
    gl.vertexAttribPointer(this.attribs.normal, 3, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.mesh.indexBuffer);
    gl.drawElements(gl.TRIANGLES, this.mesh.indexCount, gl.UNSIGNED_SHORT, 0);
  }

  // Minimal matrix math
  mat4Identity() {
    return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);
  }

  mat4Translate(m, x, y, z) {
    m[12] += m[0]*x + m[4]*y + m[8]*z;
    m[13] += m[1]*x + m[5]*y + m[9]*z;
    m[14] += m[2]*x + m[6]*y + m[10]*z;
    m[15] += m[3]*x + m[7]*y + m[11]*z;
  }

  mat4RotateX(m, rad) {
    const c = Math.cos(rad), s = Math.sin(rad);
    const m4=m[4], m5=m[5], m6=m[6], m7=m[7];
    const m8=m[8], m9=m[9], m10=m[10], m11=m[11];
    m[4]=m4*c+m8*s; m[5]=m5*c+m9*s; m[6]=m6*c+m10*s; m[7]=m7*c+m11*s;
    m[8]=m8*c-m4*s; m[9]=m9*c-m5*s; m[10]=m10*c-m6*s; m[11]=m11*c-m7*s;
  }

  mat4RotateY(m, rad) {
    const c = Math.cos(rad), s = Math.sin(rad);
    const m0=m[0], m1=m[1], m2=m[2], m3=m[3];
    const m8=m[8], m9=m[9], m10=m[10], m11=m[11];
    m[0]=m0*c-m8*s; m[1]=m1*c-m9*s; m[2]=m2*c-m10*s; m[3]=m3*c-m11*s;
    m[8]=m0*s+m8*c; m[9]=m1*s+m9*c; m[10]=m2*s+m10*c; m[11]=m3*s+m11*c;
  }

  mat4Perspective(fov, aspect, near, far) {
    const f = 1 / Math.tan(fov / 2);
    const nf = 1 / (near - far);
    return new Float32Array([
      f/aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far+near)*nf, -1,
      0, 0, 2*far*near*nf, 0
    ]);
  }

  dispose() {
    this.stop();
    const gl = this.gl;
    if (this.mesh) {
      gl.deleteBuffer(this.mesh.posBuffer);
      gl.deleteBuffer(this.mesh.normalBuffer);
      gl.deleteBuffer(this.mesh.indexBuffer);
      this.mesh = null;
    }
    if (this.program) {
      gl.deleteProgram(this.program);
      this.program = null;
    }
  }
}
