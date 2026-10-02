-- Diagnóstico de Silence Cutter (Lua): ¿está todo listo? Escribe `Silence Cutter Check.log` y lo
-- imprime en la Consola de comandos (F6).

local REPO = ""            -- `install-resolve.sh` escribe aquí la ruta del repo
local PYTHON = ""          -- "" = busca uno solo
local EXTRA_PATH = "/opt/homebrew/bin:/usr/local/bin"

if REPO == "" then REPO = os.getenv("SILENCE_CUTTER_HOME") or "" end
local lines = {}
local function add(ok, name, detail)
  lines[#lines + 1] = (ok and "OK    " or "FALTA ") .. name .. (detail and detail ~= "" and ("  -> " .. detail) or "")
end
local function q(s) return "'" .. (tostring(s):gsub("'", "'\\''")) .. "'" end
local function run(cmd)
  local p = io.popen("PATH=" .. q(EXTRA_PATH .. ":" .. (os.getenv("PATH") or "")) .. " " .. cmd .. " 2>&1; echo __EXIT:$?")
  if not p then return nil, -1 end
  local out = p:read("*a") or ""
  p:close()
  return (out:gsub("__EXIT:%d+%s*$", "")), tonumber(out:match("__EXIT:(%d+)%s*$")) or -1
end

local function check()
  add(io.popen ~= nil, "Ejecutar comandos desde Lua (io.popen)")
  add(REPO ~= "", "Carpeta del repo", REPO ~= "" and REPO or "instala con ./install-resolve.sh")

  local py, pyver
  local candidates = { PYTHON, "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
    "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3", "python3" }
  for _, c in ipairs(candidates) do
    if c ~= "" then
      local out, code = run(q(c) .. " --version")
      if code == 0 and out:find("Python 3") then py, pyver = c, out:gsub("%s+$", ""); break end
    end
  end
  add(py ~= nil, "Python 3 (fuera de Resolve)", py and (pyver .. "  (" .. py .. ")") or "instala Python 3")

  local _, ffm = run("ffmpeg -version")
  add(ffm == 0, "ffmpeg", ffm == 0 and "" or "instala con: brew install ffmpeg")
  local _, ffp = run("ffprobe -version")
  add(ffp == 0, "ffprobe", ffp == 0 and "" or "viene con ffmpeg")

  if py and REPO ~= "" then
    local out, code = run("cd " .. q(REPO) .. " && " .. q(py) .. " -c " .. q("import silence_cutter"))
    add(code == 0, "Paquete silence_cutter", code == 0 and "" or out)
    local _, w = run(q(py) .. " -c " .. q("import faster_whisper"))
    add(w == 0, "faster-whisper (transcripción)", w == 0 and "" or ("instala con: " .. py .. " -m pip install faster-whisper"))
    local keyfile = (os.getenv("HOME") or "") .. "/.config/silence-cutter/anthropic_key"
    local kf = io.open(keyfile, "r")
    if kf then kf:close() end
    add(kf ~= nil or (os.getenv("ANTHROPIC_API_KEY") or "") ~= "", "API key de Anthropic (cortes y planos con Claude)",
      "opcional; guárdala en " .. keyfile)
  end

  local r = resolve or (fu and fu.GetResolve and fu:GetResolve()) or nil
  if r then
    local project = r:GetProjectManager():GetCurrentProject()
    add(project ~= nil, "Conexión con Resolve", project and ("proyecto: " .. project:GetName()) or "abre un proyecto")
  else
    lines[#lines + 1] = "(sin objeto 'resolve': no se comprueba la conexión)"
  end
end

local ok, err = pcall(check)
if not ok then lines[#lines + 1] = "Error inesperado: " .. tostring(err) end
local text = table.concat(lines, "\n")
local base = (REPO ~= "" and REPO) or os.getenv("HOME") or "."
local f = io.open(base .. "/Silence Cutter Check.log", "w")
if f then f:write(text .. "\n"); f:close() end
print(text)

-- Los scripts del menú no muestran ventanas: abre el resultado en tu editor de texto (Mac).
if not os.getenv("SILENCE_CUTTER_NO_OPEN") then
  pcall(run, "open -t " .. q(base .. "/Silence Cutter Check.log"))
end
