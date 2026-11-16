'use strict';

const $ = (selector) => document.querySelector(selector);

/* La sesión viaja en la cookie HttpOnly; si el navegador no la conserva, se reenvía este token
   firmado en la cabecera Authorization. Se guarda en sessionStorage y, si el navegador bloquea el
   almacenamiento del sitio, queda solo en memoria mientras dure la página. */
const CLAVE_TOKEN = 'czz_sesion';
let tokenMemoria = '';
function leerToken() {
  try {
    return sessionStorage.getItem(CLAVE_TOKEN) || tokenMemoria;
  } catch (error) {
    return tokenMemoria;
  }
}
function guardarToken(token) {
  tokenMemoria = token;
  try {
    sessionStorage.setItem(CLAVE_TOKEN, token);
  } catch (error) {
    /* almacenamiento bloqueado: basta con la copia en memoria */
  }
}
function borrarToken() {
  tokenMemoria = '';
  try {
    sessionStorage.removeItem(CLAVE_TOKEN);
  } catch (error) {
    /* nada que limpiar */
  }
}

/* Cada ejemplo muestra una capacidad distinta: tres del agente de acciones y dos abiertas al equipo. */
const EJEMPLOS = [
  'Analiza NVDA en US para un perfil moderado a 12 meses.',
  '¿Cuánto vale SQM-B en Chile?',
  '¿Qué agentes forman el equipo y qué hace cada uno?',
  '¿Quién del equipo puede ayudarme a automatizar un proceso?',
  '¿Cuánto impuesto pago por las ganancias de NVDA en Chile?',
];

const estado = {
  usuario: null,
  charlaId: null,
  charlas: [],
  equipo: { local: null, remotos: [], maximo: 4 },
  editandoClave: '',
  enviando: false,
};

/* ---------- transporte ---------- */

async function pedir(ruta, { metodo = 'GET', cuerpo = null, esLogin = false } = {}) {
  const opciones = {
    method: metodo,
    credentials: 'same-origin',
    headers: { 'X-Solicitado-Por': 'chat-web' },
  };
  const token = leerToken();
  if (token) opciones.headers.Authorization = `Bearer ${token}`;
  if (cuerpo !== null) {
    opciones.headers['Content-Type'] = 'application/json';
    opciones.body = JSON.stringify(cuerpo);
  }
  const respuesta = await fetch(ruta, opciones);
  const datos = await respuesta.json().catch(() => ({}));
  if (respuesta.status === 401 && esLogin) {
    // Credenciales rechazadas: no es un problema de cookie ni de almacenamiento.
    const error = new Error(datos.detail || 'Usuario o clave incorrectos.');
    error.status = 401;
    throw error;
  }
  if (respuesta.status === 401) {
    const aviso = estado.usuario ? 'La sesión terminó. Vuelve a entrar.' : '';
    estado.usuario = null;
    borrarToken();
    mostrarLogin(aviso);
    throw new Error('sin sesión');
  }
  if (!respuesta.ok) {
    const error = new Error(datos.detail || datos.error || `Error ${respuesta.status}`);
    error.datos = datos;
    throw error;
  }
  return datos;
}

/* ---------- utilidades de vista ---------- */

function escapar(texto) {
  return String(texto).replace(/[&<>"']/g, (caracter) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[caracter]);
}

function enfasis(texto) {
  return texto
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function markdown(texto) {
  const lineas = escapar(texto).split('\n');
  const trozos = [];
  let enLista = false;
  for (const linea of lineas) {
    const elemento = linea.match(/^\s*[-*]\s+(.*)$/);
    if (elemento) {
      if (!enLista) { trozos.push('<ul>'); enLista = true; }
      trozos.push(`<li>${enfasis(elemento[1])}</li>`);
      continue;
    }
    if (enLista) { trozos.push('</ul>'); enLista = false; }
    if (linea.trim()) trozos.push(`<p>${enfasis(linea)}</p>`);
  }
  if (enLista) trozos.push('</ul>');
  return trozos.join('');
}

function milisegundos(valor) {
  const ms = Number(valor) || 0;
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

function renderEjemplos() {
  const contenedor = $('#lista-ejemplos');
  contenedor.innerHTML = '';
  for (const pregunta of EJEMPLOS) {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.textContent = pregunta;
    boton.title = `Enviar: ${pregunta}`;
    boton.addEventListener('click', () => usarEjemplo(pregunta));
    contenedor.appendChild(boton);
  }
}

function usarEjemplo(pregunta) {
  if (estado.enviando || !estado.charlaId) return;
  $('#texto').value = pregunta;
  $('#form-mensaje').requestSubmit();
}

/* ---------- sesión ---------- */

function mostrarLogin(mensaje = '') {
  $('#app').hidden = true;
  $('#login').hidden = false;
  $('#login-error').textContent = mensaje;
  $('#login-clave').value = '';
  $('#login-usuario').focus();
}

async function entrar(sesion) {
  estado.usuario = sesion.usuario;
  $('#login').hidden = true;
  $('#app').hidden = false;
  $('#marca-agente').textContent = sesion.agente;
  $('#sesion-texto').textContent =
    `${sesion.usuario} · ${sesion.agente} en ${sesion.agente_url} · hasta ${sesion.maximo_agentes} agentes remotos`;
  // Un panel caído no debe impedir entrar al chat.
  await Promise.all([
    cargarCharlas().catch(() => {}),
    cargarEquipo().catch((error) => {
      $('#agente-error').textContent = error.message;
    }),
  ]);
  if (estado.charlas.length) {
    await abrirCharla(estado.charlas[0].id).catch(() => nuevaCharla().catch(() => {}));
  } else {
    await nuevaCharla().catch((error) => mostrarAviso(error.message));
  }
}

async function iniciar() {
  try {
    await entrar(await pedir('/api/sesion'));
  } catch (error) {
    if (error.message !== 'sin sesión') mostrarLogin('');
  }
}

/* ---------- conversaciones ---------- */

function renderCharlas() {
  const lista = $('#lista-charlas');
  lista.innerHTML = '';
  if (!estado.charlas.length) {
    const vacio = document.createElement('li');
    vacio.className = 'sutil';
    vacio.textContent = 'Todavía no hay conversaciones.';
    lista.appendChild(vacio);
    return;
  }
  for (const charla of estado.charlas) {
    const item = document.createElement('li');
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = `item${charla.id === estado.charlaId ? ' activo' : ''}`;

    const titulo = document.createElement('span');
    titulo.className = 'titulo-item';
    titulo.textContent = (charla.titulo || 'Conversación nueva').slice(0, 46);

    const detalle = document.createElement('span');
    detalle.className = 'sutil';
    detalle.textContent = `${charla.mensajes} mensaje(s) · ${new Date(charla.creada_en).toLocaleDateString()}`;

    boton.append(titulo, detalle);
    boton.addEventListener('click', () => abrirCharla(charla.id));
    item.appendChild(boton);
    lista.appendChild(item);
  }
}

async function cargarCharlas() {
  estado.charlas = await pedir('/api/charlas');
  renderCharlas();
}

async function nuevaCharla() {
  const { id } = await pedir('/api/charlas', { metodo: 'POST' });
  estado.charlaId = id;
  $('#hilo').innerHTML = '';
  mostrarVacio('Escribe la primera pregunta o toca un ejemplo. El agente local sintetiza lo que aporten sus colegas.');
  renderFlujo([]);
  await cargarCharlas();
  $('#texto').focus();
}

async function abrirCharla(id) {
  const charla = await pedir(`/api/charlas/${id}`);
  estado.charlaId = id;
  renderCharlas();

  const hilo = $('#hilo');
  hilo.innerHTML = '';
  if (!charla.mensajes.length) {
    mostrarVacio('Escribe la primera pregunta o toca un ejemplo. El agente local sintetiza lo que aporten sus colegas.');
    renderFlujo([]);
    return;
  }
  for (const mensaje of charla.mensajes) agregarMensaje(mensaje.rol, mensaje.texto);
  const ultimo = [...charla.mensajes].reverse().find((m) => m.rol === 'assistant' && m.flujo && m.flujo.length);
  renderFlujo(ultimo ? ultimo.flujo : []);
  hilo.scrollTop = hilo.scrollHeight;
}

function mostrarVacio(texto) {
  const vacio = document.createElement('p');
  vacio.className = 'vacio';
  vacio.textContent = texto;
  $('#hilo').appendChild(vacio);
}

function agregarMensaje(rol, texto) {
  const vacio = $('#hilo').querySelector('.vacio');
  if (vacio) vacio.remove();

  const contenedor = document.createElement('article');
  contenedor.className = `mensaje ${rol === 'user' ? 'user' : 'assistant'}`;

  const autor = document.createElement('span');
  autor.className = 'autor';
  autor.textContent = rol === 'user' ? 'Tú' : 'Equipo A2A';

  const burbuja = document.createElement('div');
  burbuja.className = 'burbuja';
  burbuja.innerHTML = markdown(texto || '');

  contenedor.append(autor, burbuja);
  $('#hilo').appendChild(contenedor);
  $('#hilo').scrollTop = $('#hilo').scrollHeight;
}

function mostrarAviso(texto) {
  const aviso = document.createElement('p');
  aviso.className = 'aviso';
  aviso.textContent = texto;
  $('#hilo').appendChild(aviso);
  $('#hilo').scrollTop = $('#hilo').scrollHeight;
}

function agregarPensando() {
  const contenedor = document.createElement('div');
  contenedor.className = 'pensando';
  contenedor.append(document.createTextNode('El equipo está trabajando'));
  for (let i = 0; i < 3; i += 1) contenedor.appendChild(document.createElement('span'));
  $('#hilo').appendChild(contenedor);
  $('#hilo').scrollTop = $('#hilo').scrollHeight;
  return contenedor;
}

async function enviarMensaje(evento) {
  evento.preventDefault();
  const caja = $('#texto');
  const texto = caja.value.trim();
  if (!texto || estado.enviando || !estado.charlaId) return;

  estado.enviando = true;
  alternarEnvio(true);
  agregarMensaje('user', texto);
  caja.value = '';
  const pensando = agregarPensando();

  try {
    const resultado = await pedir(`/api/charlas/${estado.charlaId}/mensaje`, {
      metodo: 'POST',
      cuerpo: { texto },
    });
    pensando.remove();
    agregarMensaje('assistant', resultado.respuesta);
    renderFlujo(resultado.flujo || []);
    if (resultado.error) mostrarAviso(resultado.error);
  } catch (error) {
    pensando.remove();
    if (error.datos && error.datos.flujo) renderFlujo(error.datos.flujo);
    mostrarAviso(error.message);
  } finally {
    estado.enviando = false;
    alternarEnvio(false);
    cargarCharlas().catch(() => {});
  }
}

function alternarEnvio(activo) {
  $('#texto').disabled = activo;
  $('#enviar').disabled = activo;
  for (const boton of document.querySelectorAll('#lista-ejemplos button')) boton.disabled = activo;
  if (!activo) $('#texto').focus();
}

/* ---------- equipo de agentes ---------- */

function itemAgente(agente, quitable) {
  const item = document.createElement('li');
  const caja = document.createElement('div');
  const clases = { disponible: 'disponible', 'requiere clave': 'requiere-clave' };
  caja.className = `agente ${clases[agente.estado] || 'no-disponible'}`;

  const faro = document.createElement('span');
  faro.className = 'faro';

  const datos = document.createElement('div');
  datos.className = 'datos';

  const nombre = document.createElement('span');
  nombre.className = 'nombre';
  nombre.textContent = agente.nombre || agente.url;

  const url = document.createElement('span');
  url.className = 'url';
  url.textContent = agente.url;
  url.title = agente.detalle || agente.url;

  datos.append(nombre);
  if (agente.rol) {
    const rol = document.createElement('span');
    rol.className = 'rol';
    rol.textContent = agente.rol;
    datos.appendChild(rol);
  }
  datos.appendChild(url);

  caja.append(faro, datos);

  if (quitable) {
    const acciones = document.createElement('div');
    acciones.className = 'acciones';

    if (agente.requiere_clave || agente.estado === 'requiere clave') {
      const clave = document.createElement('button');
      clave.type = 'button';
      clave.className = 'clave';
      clave.textContent = 'clave';
      clave.title = 'Escribir o cambiar la clave que pide este agente';
      clave.setAttribute('aria-label', `Cambiar la clave de ${agente.nombre || agente.url}`);
      clave.addEventListener('click', () => editarClave(agente.url));
      acciones.appendChild(clave);
    }

    const quitar = document.createElement('button');
    quitar.type = 'button';
    quitar.className = 'quitar';
    quitar.textContent = '×';
    quitar.title = 'Quitar del equipo';
    quitar.setAttribute('aria-label', `Quitar ${agente.nombre || agente.url}`);
    quitar.addEventListener('click', () => quitarAgente(agente.url));
    acciones.appendChild(quitar);

    caja.appendChild(acciones);
  }

  item.appendChild(caja);
  return item;
}

function renderEquipo() {
  const lista = $('#lista-agentes');
  const { local, remotos, maximo } = estado.equipo;
  lista.innerHTML = '';
  if (local) lista.appendChild(itemAgente({ ...local, rol: 'local · sintetiza' }, false));
  for (const remoto of remotos) lista.appendChild(itemAgente(remoto, true));

  $('#contador-equipo').textContent = `${remotos.length}/${maximo}`;
  // Con el equipo lleno el formulario se bloquea, salvo que se esté actualizando una clave.
  const lleno = remotos.length >= maximo && !estado.editandoClave;
  $('#url-agente').disabled = lleno;
  $('#clave-agente').disabled = lleno;
  $('#form-agente').querySelector('button').disabled = lleno;
  $('#url-agente').placeholder = lleno ? 'Equipo completo' : 'https://otro-agente/…';
}

async function cargarEquipo() {
  const equipo = await pedir('/api/agentes');
  estado.equipo = { local: equipo.local, remotos: equipo.remotos || [], maximo: equipo.maximo };
  renderEquipo();
}

/* Una clave nueva se envía con la URL del agente: la API la guarda en su ficha del equipo. */
function editarClave(url) {
  estado.editandoClave = url;
  $('#url-agente').value = url;
  $('#clave-agente').value = '';
  $('#agente-error').textContent = '';
  renderEquipo();
  $('#clave-agente').focus();
}

async function agregarAgente(evento) {
  evento.preventDefault();
  const entrada = $('#url-agente');
  const clave = $('#clave-agente');
  const url = entrada.value.trim();
  if (!url) return;
  $('#agente-error').textContent = '';
  const boton = $('#form-agente').querySelector('button');
  boton.disabled = true;
  try {
    const cuerpo = clave.value.trim() ? { url, clave: clave.value.trim() } : { url };
    await pedir('/api/agentes', { metodo: 'POST', cuerpo });
    entrada.value = '';
    clave.value = '';
    estado.editandoClave = '';
    await cargarEquipo();
  } catch (error) {
    $('#agente-error').textContent = error.message;
  } finally {
    renderEquipo();
  }
}

async function quitarAgente(url) {
  $('#agente-error').textContent = '';
  try {
    await pedir('/api/agentes', { metodo: 'DELETE', cuerpo: { url } });
    await cargarEquipo();
  } catch (error) {
    $('#agente-error').textContent = error.message;
  }
}

/* ---------- flujo A2A ---------- */

const ETIQUETAS = {
  descubrimiento: 'descubrimiento',
  consulta: 'consulta',
  sintesis: 'síntesis',
};

function renderFlujo(flujo) {
  const lista = $('#lista-flujo');
  lista.innerHTML = '';
  $('#flujo-vacio').hidden = flujo.length > 0;
  $('#flujo-resumen').textContent = flujo.length ? `${flujo.length} pasos` : 'sin turnos';
  if (!flujo.length) return;

  const paralelas = flujo.filter((paso) => paso.tipo === 'consulta').length;

  flujo.forEach((paso, indice) => {
    const item = document.createElement('li');
    item.className = `paso ${paso.estado === 'error' ? 'error' : ''} ${paso.rol === 'local' ? 'local' : ''}`;

    const cabecera = document.createElement('div');
    cabecera.className = 'cabecera';

    const tipo = document.createElement('span');
    tipo.className = 'tipo';
    tipo.textContent = `${indice + 1}. ${ETIQUETAS[paso.tipo] || paso.tipo}`;

    const nombre = document.createElement('span');
    nombre.className = 'nombre';
    nombre.textContent = paso.agente;

    const ms = document.createElement('span');
    ms.className = 'ms';
    ms.textContent = milisegundos(paso.ms);

    cabecera.append(tipo, nombre, ms);

    const url = document.createElement('span');
    url.className = 'url';
    url.textContent = paso.url;

    const detalle = document.createElement('p');
    detalle.className = 'detalle';
    detalle.textContent = paso.detalle;

    item.append(cabecera, url, detalle);

    if (paso.tipo === 'consulta' && paralelas > 1 && indice > 0) {
      const nota = document.createElement('span');
      nota.className = 'chip';
      nota.textContent = 'en paralelo';
      detalle.appendChild(nota);
    }

    if (paso.respuesta) {
      const detalles = document.createElement('details');
      const resumen = document.createElement('summary');
      resumen.textContent = 'ver respuesta del agente';
      const cuerpo = document.createElement('pre');
      cuerpo.textContent = paso.respuesta;
      detalles.append(resumen, cuerpo);
      item.appendChild(detalles);
    }

    lista.appendChild(item);
  });
}

/* ---------- eventos ---------- */

$('#form-login').addEventListener('submit', async (evento) => {
  evento.preventDefault();
  $('#login-error').textContent = '';
  const boton = $('#form-login').querySelector('button');
  boton.disabled = true;
  try {
    const sesion = await pedir('/api/login', {
      metodo: 'POST',
      cuerpo: { usuario: $('#login-usuario').value.trim(), clave: $('#login-clave').value },
      esLogin: true,
    });
    guardarToken(sesion.token || '');
    const completa = await pedir('/api/sesion');
    await entrar({ ...completa, usuario: sesion.usuario });
  } catch (error) {
    if (error.message === 'sin sesión') {
      $('#login-error').textContent =
        'Entraste, pero tu navegador no conservó la sesión. Prueba en una ventana normal (no incógnito) o permite el almacenamiento del sitio.';
    } else {
      $('#login-error').textContent = error.message;
    }
  } finally {
    boton.disabled = false;
  }
});

$('#salir').addEventListener('click', async () => {
  try {
    await pedir('/api/logout', { metodo: 'POST' });
  } catch (error) {
    /* la sesión ya no era válida */
  }
  borrarToken();
  estado.charlaId = null;
  estado.charlas = [];
  mostrarLogin('Sesión cerrada.');
});

$('#nueva-charla').addEventListener('click', () => nuevaCharla().catch((error) => mostrarAviso(error.message)));
$('#form-mensaje').addEventListener('submit', enviarMensaje);
$('#form-agente').addEventListener('submit', agregarAgente);
renderEjemplos();

$('#texto').addEventListener('keydown', (evento) => {
  if (evento.key === 'Enter' && !evento.shiftKey) {
    evento.preventDefault();
    $('#form-mensaje').requestSubmit();
  }
});

iniciar();
