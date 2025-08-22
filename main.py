"""
Laboratorio 1 - TA proyecto 3

Paula Sanchez U - 202123678
Esteban Ricaurte E - 202123468
Sebastian Amaya A - 201911141

El siguiente codigo es para el funcionamiento de un sistema de paso para vehiculos
en espacios reducidos, donde solo puede pasar un vheiculo a la vez

El codigo se divide en las siguientes partes:
- Definicion de pines y parametros 
- Definicion de funciones para el funcionamiento
- Conexcion a internet 
- Codigo HTML para la pagina web
- Lazo para funcionamiento continuo

"""

# Librerias necesitadas para el proyecto
import network
import socket
import ujson as json
import utime as time
from machine import Pin

# Red WIFI y constraseña para la conexion
SSID = 'TP-Link_9A7A'
PASSWORD = '19908588'

# Definicion de pines segun el semaforo
PIN_VERDE_INF = 15
PIN_ROJO_INF  = 2

PIN_VERDE_SUP = 4
PIN_ROJO_SUP  = 5

# Definicion de pines para los dos ultra sonidos 
PIN_TRIG_INF, PIN_ECHO_INF = 18, 19   
PIN_TRIG_SUP, PIN_ECHO_SUP = 21, 22   

# Definicion de los pines como variables 
verde_inf = Pin(PIN_VERDE_INF, Pin.OUT)
rojo_inf  = Pin(PIN_ROJO_INF,  Pin.OUT)
verde_sup = Pin(PIN_VERDE_SUP, Pin.OUT)
rojo_sup  = Pin(PIN_ROJO_SUP,  Pin.OUT)

trig_inf = Pin(PIN_TRIG_INF, Pin.OUT)
echo_inf = Pin(PIN_ECHO_INF, Pin.IN)
trig_sup = Pin(PIN_TRIG_SUP, Pin.OUT)
echo_sup = Pin(PIN_ECHO_SUP, Pin.IN)

# Parametros a utilizar durante el programa
# Se pueden camibar dependiendo del uso
UMBRAL_CM        = 10      # distancia para la detección del vehículo 
PING_TIMEOUT_US  = 30000   # timeout por medición
N_MEDIDAS        = 3       # cantidad de medidas
MIN_GREEN_MS     = 4000    # minimo timepo que dura el led verde prendido
AUSENCIA_MS      = 1500    # si no hay detección en este tiempo, se libera el led

CLEAR_MS         = 6000    # tiempo extra antes de cambiar 


# Estados inciales
estado = "ALL_RED"
t_estado_ms = time.ticks_ms()
sistema_activo = True

# Parametros de los sensores
dist_inf = 999.0
dist_sup = 999.0
pres_inf = False
pres_sup = False

# Definicion para prioridad
arribo_inf_ms = None
arribo_sup_ms = None

# Ultima vez que se detecto algo 
last_seen_inf_ms = 0
last_seen_sup_ms = 0

# Variable de despeje 
clearing_side = None             
clear_hold_until_ms = 0          

# Funciones para los LED dependiendo del estado
def set_inf_go():
    verde_inf.value(1); rojo_inf.value(0)
    verde_sup.value(0); rojo_sup.value(1)

def set_sup_go():
    verde_inf.value(0); rojo_inf.value(1)
    verde_sup.value(1); rojo_sup.value(0)

def set_all_red():
    verde_inf.value(0); rojo_inf.value(1)
    verde_sup.value(0); rojo_sup.value(1)

def parpadear_todos(veces, delay=0.22):
    leds = [verde_inf, rojo_inf, verde_sup, rojo_sup]
    for _ in range(veces):
        for led in leds: led.value(1)
        time.sleep(delay)
        for led in leds: led.value(0)
        time.sleep(delay)
    if estado == "INF_GO":
        set_inf_go()
    elif estado == "SUP_GO":
        set_sup_go()
    else:
        set_all_red()

# Medicion de la distancia de ambos ultra sonidos 
def ping_cm(trig, echo):
    trig.value(0); time.sleep_us(2)
    trig.value(1); time.sleep_us(10)
    trig.value(0)

    t0 = time.ticks_us()
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), t0) > PING_TIMEOUT_US:
            return None
    start = time.ticks_us()

    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), start) > PING_TIMEOUT_US:
            return None
    end = time.ticks_us()

    dur = time.ticks_diff(end, start)
    return (dur / 2) / 29.1 

def medir_estable(trig, echo, n=N_MEDIDAS):
    vals = []
    for _ in range(n):
        v = ping_cm(trig, echo)
        if v is not None:
            vals.append(v)
        time.sleep_ms(20)
    if not vals:
        return 999.0
    vals.sort()
    return vals[len(vals)//2]  

# Funciones de logica de estado
def puede_cambiar():
    return time.ticks_diff(time.ticks_ms(), t_estado_ms) >= MIN_GREEN_MS

def aplicar_estado(nuevo):
    global estado, t_estado_ms, clearing_side
    if nuevo == estado:
        return
    if not puede_cambiar():
        return
    estado = nuevo
    t_estado_ms = time.ticks_ms()
    clearing_side = None
    if estado == "INF_GO":
        set_inf_go()
    elif estado == "SUP_GO":
        set_sup_go()
    else:
        set_all_red()

def actualizar_presencias():
    """Actualiza distancias, presencias y llegada inicial (para prioridad)."""
    global dist_inf, dist_sup, pres_inf, pres_sup
    global arribo_inf_ms, arribo_sup_ms, last_seen_inf_ms, last_seen_sup_ms

    now = time.ticks_ms()

    di = medir_estable(trig_inf, echo_inf)
    ds = medir_estable(trig_sup, echo_sup)
    dist_inf, dist_sup = di, ds

    pi = di < UMBRAL_CM
    ps = ds < UMBRAL_CM

    if pi:
        last_seen_inf_ms = now
        if not pres_inf:         
            arribo_inf_ms = now
    else:
        if arribo_inf_ms is not None and time.ticks_diff(now, last_seen_inf_ms) > AUSENCIA_MS:
            arribo_inf_ms = None

    if ps:
        last_seen_sup_ms = now
        if not pres_sup:
            arribo_sup_ms = now
    else:
        if arribo_sup_ms is not None and time.ticks_diff(now, last_seen_sup_ms) > AUSENCIA_MS:
            arribo_sup_ms = None

    pres_inf, pres_sup = pi, ps

def decidir_transicion():
    """Decide a qué estado ir según prioridad por llegada, con ventana de despeje."""
    global clearing_side, clear_hold_until_ms, arribo_inf_ms, arribo_sup_ms

    now = time.ticks_ms()

    if not sistema_activo:
        if estado != "ALL_RED":
            aplicar_estado("ALL_RED")
        clearing_side = None
        return

    if estado == "INF_GO":
        if not pres_inf:
            if clearing_side != "INF":
                clearing_side = "INF"
                clear_hold_until_ms = time.ticks_add(now, CLEAR_MS)
            
            if time.ticks_diff(clear_hold_until_ms, now) > 0:
                set_inf_go()  
                return
            clearing_side = None
            arribo_inf_ms = None  
            if pres_sup:
                aplicar_estado("SUP_GO")
            else:
                aplicar_estado("ALL_RED")
            return
        else:
            clearing_side = None

    if estado == "SUP_GO":
        if not pres_sup:
            if clearing_side != "SUP":
                clearing_side = "SUP"
                clear_hold_until_ms = time.ticks_add(now, CLEAR_MS)
            if time.ticks_diff(clear_hold_until_ms, now) > 0:
                set_sup_go()
                return
            clearing_side = None
            arribo_sup_ms = None
            if pres_inf:
                aplicar_estado("INF_GO")
            else:
                aplicar_estado("ALL_RED")
            return
        else:
            clearing_side = None

    if not pres_inf and not pres_sup:
        if puede_cambiar():
            aplicar_estado("ALL_RED")
        return

    if pres_inf and not pres_sup:
        aplicar_estado("INF_GO")
        return
    if pres_sup and not pres_inf:
        aplicar_estado("SUP_GO")
        return

    if arribo_inf_ms is not None and arribo_sup_ms is not None:
        if time.ticks_diff(arribo_inf_ms, arribo_sup_ms) <= 0:
            aplicar_estado("INF_GO")
        else:
            aplicar_estado("SUP_GO")
    else:
        if dist_inf <= dist_sup:
            aplicar_estado("INF_GO")
        else:
            aplicar_estado("SUP_GO")

# Conexion a WIFI 
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(SSID, PASSWORD)
while not wlan.isconnected():
    time.sleep_ms(100)
print("WiFi OK:", wlan.ifconfig())

# Codigo para la pagina web en HTML
HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Semáforos Rampa</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 560px; margin: 24px auto; }
    .row { display: flex; gap: 12px; margin: 8px 0; align-items: center; }
    .badge { padding: 4px 8px; border-radius: 6px; background:#efefef; }
    .ok { background:#d1ffd1; }
    .warn { background:#ffe6cc; }
    button { padding: 10px 16px; margin-right: 8px; }
    .led { width:12px; height:12px; border-radius:50%; display:inline-block; margin-left:6px; }
    .red { background:#c62828; } .green { background:#2e7d32; } .off { background:#555; }
    .state { font-weight:bold; }
  </style>
</head>
<body>
  <h1>Semáforos Rampa (ESP32)</h1>
  <div class="row">
    <button onclick="accion('on')">ENCENDER</button>
    <button onclick="accion('off')">APAGAR</button>
    <span id="sys" class="badge"></span>
  </div>
  <div class="row">
    <div>Estado: <span id="estado" class="state"></span></div>
  </div>
  <div class="row">
    <div>Inferior: <span id="dinf" class="badge"></span> <span id="pinf" class="badge"></span></div>
  </div>
  <div class="row">
    <div>Superior: <span id="dsup" class="badge"></span> <span id="psup" class="badge"></span></div>
  </div>
  <div class="row">
    <div>Leds INF: R<span id="lrinf" class="led off"></span> V<span id="lvinf" class="led off"></span></div>
  </div>
  <div class="row">
    <div>Leds SUP: R<span id="lrsup" class="led off"></span> V<span id="lvsup" class="led off"></span></div>
  </div>

<script>

# En este puento se define la funcion para la actualizacion automatica 
# Esto permite que la pagina web funcione sin tener que estar recargandose constantemente

async function actualizar(){
  try{
    const r = await fetch('/data', {cache:'no-store'});
    const j = await r.json();
    // sistema
    const sys = document.getElementById('sys');
    sys.textContent = j.sistema_activo ? 'ENCENDIDO' : 'APAGADO';
    sys.className = 'badge ' + (j.sistema_activo ? 'ok' : 'warn');

    // estado
    document.getElementById('estado').textContent = j.estado;

    // distancias y presencia
    document.getElementById('dinf').textContent = 'Dist: ' + j.dist_inf.toFixed(1) + ' cm';
    document.getElementById('dsup').textContent = 'Dist: ' + j.dist_sup.toFixed(1) + ' cm';
    const pinf = document.getElementById('pinf');
    const psup = document.getElementById('psup');
    pinf.textContent = j.pres_inf ? 'Vehículo: SÍ' : 'Vehículo: NO';
    psup.textContent = j.pres_sup ? 'Vehículo: SÍ' : 'Vehículo: NO';
    pinf.className = 'badge ' + (j.pres_inf ? 'ok' : '');
    psup.className = 'badge ' + (j.pres_sup ? 'ok' : '');

    // leds (simples, desde estado)
    const lrinf = document.getElementById('lrinf');
    const lvinf = document.getElementById('lvinf');
    const lrsup = document.getElementById('lrsup');
    const lvsup = document.getElementById('lvsup');

    if(j.estado === 'INF_GO'){
      lrinf.className='led off'; lvinf.className='led green';
      lrsup.className='led red'; lvsup.className='led off';
    } else if(j.estado === 'SUP_GO'){
      lrinf.className='led red'; lvinf.className='led off';
      lrsup.className='led off'; lvsup.className='led green';
    } else {
      lrinf.className='led red'; lvinf.className='led off';
      lrsup.className='led red'; lvsup.className='led off';
    }
  }catch(e){ console.log(e); }
}
async function accion(kind){
  try{
    await fetch('/'+kind, {cache:'no-store'});
  }catch(e){}
}
setInterval(actualizar, 500);
actualizar();
</script>
</body>
</html>
"""

# configuracion del servidor HTTP
# Aca la ESP abre un serivdor en el puerto 80
def start_server():

    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(addr)
    srv.listen(2)
    srv.settimeout(0.03)
    print("HTTP en:", wlan.ifconfig()[0])
    return srv

srv = start_server()
set_all_red()  # arranque seguro

# Loop principal del sistema
while True:
    # actualiza el sistema
    if sistema_activo:
        actualizar_presencias()
        decidir_transicion()
    else:
        # apagado: todo rojo 
        pass

    # Atiende las peticiones del HTTP
    try:
        cl, a = srv.accept()
    except OSError:
        continue

    req = cl.recv(1024)
    if not req:
        cl.close()
        continue

    req = req.decode()
    if req.startswith('GET / '):
        cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nCache-Control: no-store\r\n\r\n")
        cl.send(HTML) #Devuelve a la pagina web
    elif req.startswith('GET /data'): # La funcion /data obtiene la informacion de los sensores y los estados de los leds
        payload = {
            "sistema_activo": sistema_activo,
            "estado": estado,
            "dist_inf": float(dist_inf),
            "dist_sup": float(dist_sup),  #Genera la variables con la informacion de sensores y estados 
            "pres_inf": bool(pres_inf),
            "pres_sup": bool(pres_sup),
            "umbral_cm": UMBRAL_CM
        }
        body = json.dumps(payload)
        cl.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n")
        cl.send(body)
    elif req.startswith('GET /on'): #Funcion para prender el sistema
        # solo si hay cambio
        if not sistema_activo:
            sistema_activo = True
            # limpiar marcas de llegada para un arranque justo
            arribo_inf_ms = None
            arribo_sup_ms = None
            aplicar_estado("ALL_RED")
            parpadear_todos(2) #SE maneja el parpadeo LEED
        cl.send("HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n")
    elif req.startswith('GET /off'): # Funcion para apagar el sistema
        if sistema_activo:
            sistema_activo = False
            aplicar_estado("ALL_RED")
            parpadear_todos(3)
        cl.send("HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n")
    else:
        cl.send("HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n\r\nNot found")

    cl.close()
