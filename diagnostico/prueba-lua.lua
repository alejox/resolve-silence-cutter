-- Prueba de qué permite el Lua de tu Resolve, paso a paso. Cada comprobación crea una timeline con un
-- nombre corto (solo letras, números y _): si el script se detiene, la última que aparezca dice dónde.
-- Las comprobaciones que podrían bloquearse (ejecutar comandos) van al final.
--   SC_a_inicio ........ el script corre
--   SC_b_io_<tipo> ..... ¿existe io?
--   SC_c_open_<tipo> ... ¿existe io.open?
--   SC_d_popen_<tipo> .. ¿existe io.popen?
--   SC_e_exec_<tipo> ... ¿existe os.execute?
--   SC_f_escribe_<r> ... ¿se puede escribir un archivo?  (si / nil / err)
--   SC_g_popenrun_<r> .. ¿io.popen ejecuta un comando?   (si / vacio / err)
--   SC_h_execrun_<r> ... ¿os.execute ejecuta un comando? (ok / falla / err)

local stamp = tostring(os.time() % 10000)
local r = resolve or (fu and fu.GetResolve and fu:GetResolve())
local pool
if r then
  local ok, p = pcall(function() return r:GetProjectManager():GetCurrentProject():GetMediaPool() end)
  if ok then pool = p end
end

local function mk(stage, value)
  local name = "SC_" .. stage .. (value and ("_" .. value) or "") .. "_" .. stamp
  print(name)
  if pool then pcall(function() return pool:CreateEmptyTimeline(name) end) end
end

local function clean(s) return (tostring(s):gsub("[^%w]", "")):sub(1, 12) end

mk("a_inicio")
mk("b_io", type(io))
mk("c_open", type(io and io.open))
mk("d_popen", type(io and io.popen))
mk("e_exec", type(os and os.execute))

local ok1, f = pcall(function() return io.open("/tmp/silence-cutter-prueba.txt", "w") end)
if ok1 and f then f:write("hola"); f:close(); mk("f_escribe", "si") else mk("f_escribe", ok1 and "nil" or "err") end

local ok2, res = pcall(function()
  local p = io.popen("echo hola")
  local o = p:read("*a")
  p:close()
  return o
end)
if ok2 then mk("g_popenrun", (res or ""):find("hola") and "si" or "vacio") else mk("g_popenrun", "err") end

local ok3, rc = pcall(function() return os.execute("touch /tmp/silence-cutter-os-execute") end)
mk("h_execrun", ok3 and ("ok" .. clean(rc)) or "err")
