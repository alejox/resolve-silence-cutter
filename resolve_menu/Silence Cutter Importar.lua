-- Silence Cutter Importar (Lua): importa en Resolve la última timeline recortada.
--
-- En Resolve 21 el Lua de los scripts corre en un entorno cerrado: no hay `io` ni `os.execute`, así que un
-- script NO puede leer archivos, escribirlos ni ejecutar comandos (se comprobó en una instalación gratuita).
-- Lo que sí puede es llamar a la API de Resolve. Por eso la herramienta de la terminal genera el archivo y
-- este script solo lo importa:
--
--   1) En la terminal:  python3 -m silence_cutter mi_video.mov --fcpxml
--   2) En Resolve:      Área de trabajo > Secuencias de comandos > Silence Cutter Importar
--
-- (Alternativa sin script: Archivo > Importar > Timeline... y elige el .fcpxml que dejó junto al video.)
-- Si algo falla aparece una timeline vacía llamada "SC_ERROR_<motivo>" (el menú no muestra ventanas).

local REPO = ""            -- `install-resolve.sh` escribe aquí la ruta del repo
local FILE_NAME = "ultimo.fcpxml"

local function get_pool()
  local r = resolve or (fu and fu.GetResolve and fu:GetResolve())
  if not r then return nil end
  local project = r:GetProjectManager():GetCurrentProject()
  if not project then return nil end
  return project:GetMediaPool(), project
end

-- Devuelve (true, "ok") o (false, motivo).
local function main()
  local pool, project = get_pool()
  if not pool then return false, "sin_proyecto_abierto" end
  if REPO == "" then return false, "sin_ruta_del_repo" end
  local timeline = pool:ImportTimelineFromFile(REPO .. "/" .. FILE_NAME, { importSourceClips = true })
  if not timeline then return false, "no_pude_importar" end
  project:SetCurrentTimeline(timeline)
  return true, "ok"
end

local pcall_ok, ok, reason = pcall(main)
if not pcall_ok then ok, reason = false, "error_inesperado" end

if ok then
  print("Silence Cutter: timeline importada.")
else
  print("Silence Cutter: no se pudo importar (" .. tostring(reason) .. ").")
  local pool = select(1, pcall(get_pool)) and select(2, pcall(get_pool)) or nil
  if pool then
    pcall(function() return pool:CreateEmptyTimeline("SC_ERROR_" .. reason .. "_" .. tostring(os.time() % 10000)) end)
  end
end
