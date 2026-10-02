-- Silence Cutter para DaVinci Resolve (Lua).
--
-- Resolve no ejecuta Python en todas las instalaciones, pero Lua siempre funciona. Este script no
-- necesita Python DENTRO de Resolve: le pide el trabajo pesado (cortar silencios, transcribir) a la
-- herramienta por la terminal y arma la timeline con la API de Lua.
--
-- Uso: abre una timeline con el clip en la pista V1 y ejecuta Área de trabajo > Secuencias de comandos >
-- Silence Cutter. Crea una timeline nueva "<clip> - sin silencios". Mientras trabaja (sobre todo si
-- transcribes) Resolve parece congelado: es normal. El resultado queda en `Silence Cutter.log`.

local REPO = ""            -- `install-resolve.sh` escribe aquí la ruta del repo
local PYTHON = ""          -- "" = busca uno solo; o la ruta de tu python3
local NOISE = "auto"       -- "auto" (del ruido de fondo del clip) o un nivel fijo en dB, ej. "-35"
local MIN_SILENCE = 0.5    -- pausa mínima a cortar, en segundos
local PADDING = 0.1        -- holgura que se conserva junto al habla
local MIN_SPEECH = 0.15    -- descarta ruidos más cortos que esto
local TRANSCRIBE = false   -- true = también guión (.guion.md y .srt); necesita faster-whisper
local LANGUAGE = ""        -- ej. "es"; "" = autodetectar

local OPEN_LOG = "error"   -- cuándo abrir el .log en tu editor de texto (Mac): "error", "always" o "never"
local EXTRA_PATH = "/opt/homebrew/bin:/usr/local/bin"  -- Resolve no hereda el PATH de la terminal en macOS

if REPO == "" then REPO = os.getenv("SILENCE_CUTTER_HOME") or "" end

local function q(s) return "'" .. (tostring(s):gsub("'", "'\\''")) .. "'" end

local function logpath()
  local base = (REPO ~= "" and REPO) or os.getenv("HOME") or "."
  return base .. "/Silence Cutter.log"
end

local function write_log(text)
  local f = io.open(logpath(), "w")
  if f then f:write(text .. "\n"); f:close() end
  print(text)
end

-- Ejecuta un comando de shell. Devuelve (salida, código). El código se lee de un marcador porque
-- close() de io.popen no devuelve lo mismo en todas las versiones de Lua.
local function run(cmd)
  local p = io.popen("PATH=" .. q(EXTRA_PATH .. ":" .. (os.getenv("PATH") or "")) .. " " .. cmd .. " 2>&1; echo __EXIT:$?")
  if not p then return nil, -1 end
  local out = p:read("*a") or ""
  p:close()
  local code = tonumber(out:match("__EXIT:(%d+)%s*$")) or -1
  return (out:gsub("__EXIT:%d+%s*$", "")), code
end

local function find_python()
  if PYTHON ~= "" then return PYTHON end
  local candidates = {
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
    "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3", "python3",
  }
  for _, c in ipairs(candidates) do
    local out, code = run(q(c) .. " --version")
    if code == 0 and out:find("Python 3") then return c end
  end
  return nil
end

local function get_resolve()
  if resolve then return resolve end
  if fu and fu.GetResolve then return fu:GetResolve() end
  return nil
end

local function main()
  if REPO == "" then
    return "No sé dónde está el repo: instala con ./install-resolve.sh o escribe su ruta en REPO arriba."
  end
  local r = get_resolve()
  if not r then return "No pude conectar con Resolve desde este script." end
  local project = r:GetProjectManager():GetCurrentProject()
  if not project then return "Abre un proyecto primero." end
  local timeline = project:GetCurrentTimeline()
  if not timeline then return "Abre una timeline primero." end
  local items = timeline:GetItemListInTrack("video", 1)
  if not items or #items == 0 then return "La pista V1 está vacía." end
  local clip = items[1]:GetMediaPoolItem()
  local media = clip and clip:GetClipProperty("File Path")
  if not media or media == "" then return "No encuentro el archivo del primer clip de V1." end

  local py = find_python()
  if not py then return "No encuentro python3. Instala Python 3 o escribe su ruta en PYTHON arriba." end

  local cmd = "cd " .. q(REPO) .. " && " .. q(py) .. " -m silence_cutter " .. q(media)
    .. " --noise " .. q(NOISE) .. " --min-silence " .. MIN_SILENCE
    .. " --padding " .. PADDING .. " --min-speech " .. MIN_SPEECH
  if not TRANSCRIBE then cmd = cmd .. " --no-transcribe" end
  if LANGUAGE ~= "" then cmd = cmd .. " --language " .. q(LANGUAGE) end
  local out, code = run(cmd)
  if code ~= 0 then
    return "La herramienta falló (código " .. tostring(code) .. ") con " .. py .. ":\n" .. (out or "")
  end

  local dir, file = media:match("^(.*)/([^/]+)$")
  local stem = (file or media):gsub("%.[^%.]+$", "")
  local f = io.open((dir or ".") .. "/" .. stem .. ".segments.tsv", "r")
  if not f then return "La herramienta no dejó los tramos (.segments.tsv).\n" .. (out or "") end
  local content = f:read("*a"); f:close()

  local fps = tonumber(clip:GetClipProperty("FPS")) or 24
  local infos = {}
  for a, b in content:gmatch("([%d%.eE%+%-]+)\t([%d%.eE%+%-]+)") do
    local s = math.floor(tonumber(a) * fps + 0.5)
    local e = math.max(s, math.floor(tonumber(b) * fps + 0.5) - 1)  -- endFrame es inclusivo
    infos[#infos + 1] = { mediaPoolItem = clip, startFrame = s, endFrame = e }
  end
  if #infos == 0 then return "No quedó ningún tramo hablado: nada que armar." end

  local pool = project:GetMediaPool()
  local name = stem .. " - sin silencios"
  local tl = pool:CreateEmptyTimeline(name)
  if not tl then return "No pude crear la timeline '" .. name .. "' (¿ya existe una con ese nombre?)." end
  project:SetCurrentTimeline(tl)
  if not pool:AppendToTimeline(infos) then return "Resolve rechazó los recortes al armar la timeline." end

  local summary = (out:match("Duración:[^\n]*") or "")
  return "Listo: " .. #infos .. " tramos en la timeline '" .. name .. "'. " .. summary
end

local ok, result = pcall(main)
local text = ok and tostring(result) or ("Error inesperado: " .. tostring(result))
write_log(text)

-- Los scripts del menú no muestran ventanas: si algo salió mal, abre el log para que se vea el motivo.
local failed = not text:find("^Listo")
if (OPEN_LOG == "always" or (OPEN_LOG == "error" and failed)) and not os.getenv("SILENCE_CUTTER_NO_OPEN") then
  pcall(run, "open -t " .. q(logpath()))
end
