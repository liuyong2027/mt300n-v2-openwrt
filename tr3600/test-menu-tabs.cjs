const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const kit=__dirname;
// Locked LuCI 128a7812 parent entries. The dispatcher merges glob-sorted
// files; Bootstrap renders children of the third route segment as tabs.
const stock={
 'luci-app-samba4.json':{'admin/services/samba4':{title:'Network Shares',action:{type:'view',path:'samba4'},depends:{acl:['luci-app-samba4'],uci:{samba4:true}}}},
 'luci-mod-network.json':{'admin/network/wireless':{title:'Wireless',order:15,action:{type:'view',path:'network/wireless'},depends:{acl:['luci-mod-network-config'],uci:{wireless:{'@wifi-device':true}}}}}
};
let files={...stock};
for(const pkg of ['usb','wifi']) {
 const dir=path.join(kit,`luci-app-cudy-${pkg}/root/usr/share/luci/menu.d`);
 for(const name of fs.readdirSync(dir))files[name]=JSON.parse(fs.readFileSync(path.join(dir,name),'utf8'));
}
let menu={};
for(const name of Object.keys(files).sort())for(const [route,spec] of Object.entries(files[name]))menu[route]={...menu[route],...spec};
for(const [parent,children,view,old,acl] of [
 ['admin/services/samba4',['settings','usb'],'samba4','admin/services/cudy-usb','luci-app-samba4'],
 ['admin/network/wireless',['settings','unified'],'network/wireless','admin/network/cudy-wifi','luci-mod-network-config']
]) {
 assert.equal(menu[parent].action.type,'firstchild','custom menu must override stock after sorted loading');
 assert.deepEqual(menu[parent].depends.acl,[acl],'parent must retain stock ACL');
 const tabs=Object.keys(menu).filter(r=>r.startsWith(parent+'/') && r.split('/').length===4).sort((a,b)=>menu[a].order-menu[b].order);
 assert.deepEqual(tabs,children.map(c=>parent+'/'+c));
 assert.equal(menu[tabs[0]].action.path,view,'default tab preserves original settings');
 assert.equal(menu[tabs[0]].action.type,'view');
 assert.equal(menu[tabs[1]].action.type,'view');
 assert.equal(menu[old].title,undefined,'old sidebar entry must be hidden');
 assert.deepEqual(menu[old].action,{type:'alias',path:tabs[1]},'old bookmarks must resolve');
 assert(menu[tabs[1]].depends.acl.length,'feature tab retains its ACL');
}
assert.equal(menu['admin/network/wireless'].title,'Wireless');
assert.equal(menu['admin/network/wireless'].order,15);
assert.equal(menu['admin/services/samba4'].title,'Network Shares');
console.log('PASS sorted LuCI menus, default tabs, feature tabs, ACLs and legacy URL aliases');
