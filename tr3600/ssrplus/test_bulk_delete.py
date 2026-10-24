"""Bulk deletion uses only a synthetic cursor; never create a production cursor."""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

HERE = Path(__file__).resolve().parent

class BulkDeleteTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.helper = self.lua.execute((HERE / 'bulk_delete.lua').read_text(encoding='utf-8'))
        self.lua.execute('''
local function copy(v) if type(v)~='table' then return v end local r={};for k,x in pairs(v)do r[k]=copy(x)end;return r end
rows={a={['.type']='servers'},b={['.type']='servers'},c={['.type']='servers'},d={['.type']='servers'},
 global={['.type']='global',global_server='a'}, server={['.type']='server_config',enable='0'}}
committed=copy(rows);deletes=0;commits=0;unloads=0;pending=false;fail_delete=nil;fail_commit=false
cursor={}
function cursor:get(pkg,sid)assert(pkg=='shadowsocksr');return rows[sid]and rows[sid]['.type']end
function cursor:foreach(pkg,kind,fn)assert(pkg=='shadowsocksr');for sid,row in pairs(rows)do if row['.type']==kind then fn(row)end end end
function cursor:changes(pkg)assert(pkg=='shadowsocksr');return pending and {shadowsocksr={synthetic=true}}or{}end
function cursor:delete(pkg,sid)assert(pkg=='shadowsocksr');deletes=deletes+1;if sid==fail_delete then return false end;rows[sid]=nil;return true end
function cursor:commit(pkg)assert(pkg=='shadowsocksr');commits=commits+1;if fail_commit then return false end;committed=copy(rows);return true end
function cursor:unload(pkg)assert(pkg=='shadowsocksr');unloads=unloads+1;rows=copy(committed)end
''')

    def delete(self, *ids):
        return self.helper.delete(self.lua.globals().cursor, self.lua.table_from(ids))

    def test_selected_nodes_only_and_single_commit(self):
        self.assertEqual(self.delete('b', 'c', 'b'), 2)
        g = self.lua.globals()
        self.assertEqual((g.deletes, g.commits), (2, 1))
        self.assertIsNotNone(g.rows.a); self.assertIsNotNone(g.rows.d)
        self.assertIsNotNone(g.rows.server); self.assertEqual(g.rows['global'].global_server, 'a')

    def test_configured_main_udp_socks_http_nodes_are_protected(self):
        self.lua.execute("rows.global.udp_relay_server='b'; rows.socks={['.type']='socks5_proxy',server='c'}; rows.http={['.type']='http_proxy',server='d'}")
        for sid in ('a', 'b', 'c', 'd'):
            self.assertEqual(self.delete(sid), (None, 'node_in_use'))
        self.assertEqual(self.lua.globals().deletes, 0)

    def test_entire_selection_validates_before_any_deletion(self):
        for sid, expected in [('a', 'node_in_use'), ('missing', 'stale_selection'),
                              ('server', 'stale_selection'), ('b;touch /tmp/unsafe', 'invalid_selection')]:
            self.assertEqual(self.delete('b', sid), (None, expected))
        self.assertEqual(self.lua.globals().deletes, 0)

    def test_invalid_array_shape_and_limit(self):
        values = [None, 'b', self.lua.table(), self.lua.table_from({'sid': 'b'}),
                  self.lua.table_from({1: 'b', 3: 'c'}), self.lua.table_from(['b'] * 4097)]
        for value in values:
            self.assertEqual(self.helper.delete(self.lua.globals().cursor, value), (None, 'invalid_selection'))
        self.assertEqual(self.lua.globals().deletes, 0)

    def test_pending_edits_are_not_committed_or_discarded(self):
        self.lua.globals().pending = True
        self.assertEqual(self.delete('b'), (None, 'pending_changes'))
        g = self.lua.globals(); self.assertEqual((g.deletes, g.commits, g.unloads), (0, 0, 0))

    def test_delete_failure_discards_only_unsaved_cursor_changes(self):
        self.lua.globals().fail_delete = 'c'
        self.assertEqual(self.delete('b', 'c'), (None, 'delete_failed'))
        g = self.lua.globals(); self.assertEqual(g.commits, 0)
        self.assertIsNotNone(g.rows.b); self.assertIsNotNone(g.rows.c)

    def test_commit_failure_restores_cursor_and_reports_failure(self):
        self.lua.globals().fail_commit = True
        self.assertEqual(self.delete('b'), (None, 'commit_failed'))
        self.assertIsNotNone(self.lua.globals().rows.b)

    def test_controller_rejects_get_and_never_calls_a_shell(self):
        self.lua.globals().bulk_helper = self.helper
        self.lua.execute('''
method='GET';payload='synthetic';parsed_ids={'b'};removed=0
json={parse=function(v)return parsed_ids end}
luci={http={status=function(v)http_status=v end,prepare_content=function()end,
 write_json=function(v)response=v end,getenv=function()return method end,formvalue=function()return payload end}}
nixio={fs={remove=function()removed=removed+1 end}};SERVER_DETECT_CACHE='synthetic-cache'
package.loaded['luci.model.uci']={cursor=function()return cursor end}
dofile=function(path)assert(path=='/usr/share/shadowsocksr/bulk_delete.lua');return bulk_helper end
''')
        self.lua.execute((HERE / 'bulk-delete-controller.lua').read_text(encoding='utf-8'))
        g = self.lua.globals(); g.act_delete_nodes()
        self.assertEqual((g.http_status, g.deletes), (405, 0))
        g.method = 'POST'; g.act_delete_nodes()
        self.assertEqual((g.http_status, g.response.ret, g.response.deleted, g.commits, g.removed), (200, 1, 1, 1, 1))

if __name__ == '__main__':
    unittest.main(verbosity=2)
