import os
import subprocess
import tempfile
import unittest
from pathlib import Path

try:  # LuaJIT es el motor de Resolve: si lupa lo trae, se prueba con ese (Lua 5.1)
    from lupa.luajit21 import LuaRuntime
except ImportError:
    try:
        from lupa import LuaRuntime
    except ImportError:  # pip install lupa
        LuaRuntime = None

REPO = Path(__file__).resolve().parent.parent
MENU = REPO / "resolve_menu"

FAKE_RESOLVE = """
captured, created, messages = nil, nil, {}
local function tl() return {
  GetItemListInTrack = function(self, kind, idx) return ITEMS end,
} end
local pool = {
  CreateEmptyTimeline = function(self, name) created = name; return {} end,
  AppendToTimeline = function(self, infos) captured = infos; return true end,
}
local project = {
  GetMediaPool = function(self) return pool end,
  GetCurrentTimeline = function(self) return HAS_TIMELINE and tl() or nil end,
  SetCurrentTimeline = function(self, t) end,
  GetName = function(self) return "proyecto-demo" end,
}
resolve = { GetProjectManager = function(self) return { GetCurrentProject = function(self) return project end } end }
"""


def clip_item(lua, path, fps="30"):
    clip = lua.eval(
        "function(path, fps) return { GetClipProperty = function(self, k) "
        "if k == 'File Path' then return path elseif k == 'FPS' then return fps end end } end"
    )(path, fps)
    return lua.eval("function(c) return { GetMediaPoolItem = function(self) return c end } end")(clip)


def set_items(lua, *items):
    lua.globals().ITEMS = lua.eval("function(...) return { ... } end")(*items)


def py_popen(cmd):
    """El Lua de lupa viene sin io.popen: se emula con bash real, que es lo que hace Resolve."""
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True).stdout


def run_script(name, items_builder, env=None, has_timeline=True, log_dir=REPO):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("HAS_TIMELINE = " + ("true" if has_timeline else "false"))
    lua.execute("ITEMS = nil")
    lua.execute(FAKE_RESOLVE)
    lua.globals().py_popen = py_popen
    lua.execute(
        "io.popen = function(cmd) local out = py_popen(cmd) "
        "return { read = function(self, f) return out end, close = function(self) return true end } end"
    )
    items_builder(lua)
    for k, v in (env or {}).items():
        os.environ[k] = v
    log = Path(log_dir) / (name.replace(".lua", "") + ".log")
    log.unlink(missing_ok=True)
    lua.execute((MENU / name).read_text(encoding="utf-8"))
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    log.unlink(missing_ok=True)
    return lua, text


@unittest.skipIf(LuaRuntime is None, "falta lupa (pip install lupa)")
class LuaLauncherTests(unittest.TestCase):
    def setUp(self):
        self._home = os.environ.get("HOME", "")
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.env = {"SILENCE_CUTTER_HOME": str(REPO), "SILENCE_CUTTER_NO_OPEN": "1"}

    def tearDown(self):
        os.environ["HOME"] = self._home
        self.tmp.cleanup()

    def make_audio(self):
        wav = self.d / "clip.wav"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=7",
             "-f", "lavfi", "-i", "anullsrc=d=2", "-f", "lavfi", "-i", "sine=f=660:d=6",
             "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(wav)], check=True)
        return wav

    def test_cuts_run_through_the_cli_and_become_timeline_ranges(self):
        wav = self.make_audio()

        lua, log = run_script("Silence Cutter.lua", lambda l: set_items(l, clip_item(l, str(wav))), self.env)
        self.assertIn("Listo: 2 tramos", log)
        self.assertEqual(str(lua.globals().created), "clip - sin silencios")
        got = [(int(i["startFrame"]), int(i["endFrame"])) for i in lua.globals().captured.values()]
        # 0-7.1 s y 8.9-15 s a 30 fps, endFrame inclusivo. El nivel se mide en ventanas de 50 ms, así que
        # un borde puede correrse hasta ~3 fotogramas; el padding de 0.1 s (3 fotogramas) lo absorbe.
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0][0], 0)
        self.assertAlmostEqual(got[0][1], 212, delta=4)
        self.assertAlmostEqual(got[1][0], 267, delta=4)
        self.assertEqual(got[1][1], 449)  # el final del archivo (15 s)
        self.assertGreater(got[1][0], got[0][1])  # los tramos no se pisan
        self.assertTrue((self.d / "clip.segments.tsv").is_file())

    def test_empty_v1_is_explained(self):
        lua, log = run_script("Silence Cutter.lua", lambda l: set_items(l), self.env)
        self.assertIn("La pista V1 está vacía", log)

    def test_no_timeline_is_explained(self):
        _, log = run_script("Silence Cutter.lua", lambda l: None, self.env, has_timeline=False)
        self.assertIn("Abre una timeline primero", log)

    def test_missing_repo_is_explained(self):
        home = self.d / "home"
        home.mkdir()
        env = {"SILENCE_CUTTER_HOME": "", "HOME": str(home), "SILENCE_CUTTER_NO_OPEN": "1"}  # sin repo, el log va a la carpeta personal
        try:
            _, log = run_script("Silence Cutter.lua", lambda l: None, env, log_dir=home)
        finally:
            os.environ["HOME"] = self._home
        self.assertIn("No sé dónde está el repo", log)

    def test_cli_failure_is_reported_with_its_output(self):
        _, log = run_script("Silence Cutter.lua", lambda l: set_items(l, clip_item(l, "/no/existe.mov")), self.env)
        self.assertIn("La herramienta falló", log)
        self.assertIn("No existe", log)

    def test_log_is_opened_in_the_editor_on_error_but_not_on_success(self):
        """Los scripts del menú no muestran ventanas: ante un error el log se abre con `open -t`."""
        opened = []
        wav = self.make_audio()

        def run(items_builder, open_env):
            lua = LuaRuntime(unpack_returned_tuples=True)
            lua.execute("HAS_TIMELINE = true; ITEMS = nil")
            lua.execute(FAKE_RESOLVE)
            lua.globals().py_popen = lambda cmd: (opened.append(cmd) if "open -t" in cmd else None) or py_popen(
                cmd if "open -t" not in cmd else "true")
            lua.execute("io.popen = function(cmd) local out = py_popen(cmd) or '' "
                        "return { read = function(self, f) return out end, close = function(self) return true end } end")
            items_builder(lua)
            os.environ.pop("SILENCE_CUTTER_NO_OPEN", None)
            os.environ["SILENCE_CUTTER_HOME"] = str(REPO)
            lua.execute((MENU / "Silence Cutter.lua").read_text(encoding="utf-8"))
            (REPO / "Silence Cutter.log").unlink(missing_ok=True)

        run(lambda l: set_items(l), None)  # V1 vacía -> error
        self.assertTrue(any("open -t" in c and "Silence Cutter.log" in c for c in opened), opened)
        opened.clear()
        run(lambda l: set_items(l, clip_item(l, str(wav))), None)  # éxito
        self.assertEqual(opened, [])

    def test_check_script_reports_each_requirement(self):
        _, log = run_script("Silence Cutter Check.lua", lambda l: None, self.env)
        self.assertIn("Ejecutar comandos desde Lua", log)
        self.assertRegex(log, r"OK\s+ffmpeg")
        self.assertRegex(log, r"OK\s+Paquete silence_cutter")
        self.assertRegex(log, r"OK\s+Conexión con Resolve\s+->\s+proyecto: proyecto-demo")


if __name__ == "__main__":
    unittest.main()
