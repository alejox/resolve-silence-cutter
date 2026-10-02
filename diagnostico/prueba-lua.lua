-- Prueba de qué permite el Lua de tu Resolve. El resultado va en el NOMBRE de timelines nuevas
-- (los scripts del menú no muestran ventanas, y los archivos pueden estar bloqueados).
--   SC0 ...  se crea lo primero: prueba que ESTE script corre.
--   SC1 ...  trae el resultado de las comprobaciones.

local function timeline_maker()
  local r = resolve or (fu and fu.GetResolve and fu:GetResolve())
  if not r then return nil end
  local ok, pool = pcall(function() return r:GetProjectManager():GetCurrentProject():GetMediaPool() end)
  if not ok or not pool then return nil end
  return function(name)
    local ok2, t = pcall(function() return pool:CreateEmptyTimeline(name) end)
    return ok2 and t ~= nil
  end
end

local stamp = tostring(os.time() % 10000)
local mk = timeline_maker()
if mk then mk("SC0 corre #" .. stamp) end

local parts = {}
local function add(s) parts[#parts + 1] = s end
add("io=" .. type(io))
add("open=" .. type(io and io.open))
add("popen=" .. type(io and io.popen))
add("exec=" .. type(os and os.execute))

local ok1, f = pcall(function() return io.open("/tmp/silence-cutter-prueba.txt", "w") end)
if ok1 and f then f:write("hola"); f:close(); add("escribe=si") else add("escribe=" .. (ok1 and "nil" or "err")) end

local ok2, res = pcall(function()
  local p = io.popen("echo hola")
  local o = p:read("*a")
  p:close()
  return o
end)
if ok2 then add("popen_run=" .. ((res or ""):find("hola") and "si" or "vacio"))
else add("popen_run=err[" .. tostring(res):sub(1, 40) .. "]") end

local ok3, rc = pcall(function() return os.execute("touch /tmp/silence-cutter-os-execute") end)
add("exec_run=" .. tostring(ok3) .. "/" .. tostring(rc))

local name = "SC1 " .. table.concat(parts, " ") .. " #" .. stamp
if mk then print(name .. " -> timeline: " .. tostring(mk(name))) else print(name .. " -> sin resolve") end
