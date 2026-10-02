import unittest
from pathlib import Path

try:  # LuaJIT es el motor de Resolve: si lupa lo trae, se prueba con ese (Lua 5.1)
    from lupa.luajit21 import LuaRuntime
except ImportError:
    try:
        from lupa import LuaRuntime
    except ImportError:  # pip install lupa
        LuaRuntime = None

SRC = (Path(__file__).resolve().parent.parent / "resolve_menu" / "Silence Cutter Importar.lua").read_text(encoding="utf-8")


def run(repo="/Users/x/resolve-silence-cutter", imports=True, project=True, sandbox=True):
    """Ejecuta el script con un Resolve simulado. Devuelve lo que hizo y lo que imprimió."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("calls, created, printed = {}, {}, {}; _print = print; print = function(...) table.insert(printed, table.concat({...}, ' ')) end")
    if sandbox:  # el Lua de Resolve 21: sin io ni os.execute
        lua.execute("io = nil; os.execute = nil")
    lua.execute(f"""
local pool = {{
  ImportTimelineFromFile = function(self, path, opts)
    table.insert(calls, {{ path = path, importSourceClips = opts.importSourceClips }})
    return {'{}' if imports else 'nil'}
  end,
  CreateEmptyTimeline = function(self, name) table.insert(created, name); return {{}} end,
}}
local proj = {{ GetMediaPool = function(self) return pool end, SetCurrentTimeline = function(self, t) current_set = true end }}
resolve = {{ GetProjectManager = function(self) return {{ GetCurrentProject = function(self) return {'proj' if project else 'nil'} end }} end }}
""")
    lua.execute(SRC.replace('local REPO = ""', f'local REPO = "{repo}"'))
    g = lua.globals()
    return (
        [dict(path=str(c["path"]), imp=bool(c["importSourceClips"])) for c in g.calls.values()],
        [str(n) for n in g.created.values()],
        [str(p) for p in g.printed.values()],
        bool(g.current_set),
    )


@unittest.skipIf(LuaRuntime is None, "falta lupa (pip install lupa)")
class ImportScriptTests(unittest.TestCase):
    def test_imports_the_latest_fcpxml_without_needing_io_or_os_execute(self):
        calls, created, printed, current = run()
        self.assertEqual(calls, [{"path": "/Users/x/resolve-silence-cutter/ultimo.fcpxml", "imp": True}])
        self.assertEqual(created, [])
        self.assertTrue(current)  # la timeline importada queda abierta
        self.assertIn("importada", printed[0])

    def test_failed_import_leaves_a_visible_error_timeline(self):
        _, created, printed, current = run(imports=False)
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].startswith("SC_ERROR_no_pude_importar_"), created)
        self.assertFalse(current)

    def test_missing_repo_path_is_reported_without_importing(self):
        calls, created, _, _ = run(repo="")
        self.assertEqual(calls, [])
        self.assertTrue(created[0].startswith("SC_ERROR_sin_ruta_del_repo_"), created)

    def test_no_open_project_does_not_crash(self):
        calls, created, printed, _ = run(project=False)
        self.assertEqual((calls, created), ([], []))
        self.assertIn("sin_proyecto_abierto", printed[0])


if __name__ == "__main__":
    unittest.main()
