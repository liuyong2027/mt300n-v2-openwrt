const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function E(tag,attrs={},children=[]) {
	if (attrs==null) attrs={};
	// LuCI accepts a flat children list; nested arrays become text, not DOM rows.
	const flat=(Array.isArray(children) ? children : [children]).filter(x=>x!=null).map(x=>Array.isArray(x) ? String(x) : x);
	const node={tag,attrs,children:flat,value:attrs.value || '',appendChild(x){this.children.push(x);if(this.tag==='select' && !this.value && !x.attrs.disabled)this.value=x.attrs.value;},replaceChildren(...xs){this.children=xs;}};
	Object.defineProperty(node,'firstChild',{get(){return this.children[0];}});
	if (tag==='select') { const x=flat.find(x=>!x.attrs.disabled);if(x)node.value=x.attrs.value; }
	return node;
}
function nodes(x) { if(!x || typeof x!=='object')return [];return [x,...(x.children || []).flatMap(nodes)]; }
function text(x) {return typeof x==='string' ? x : (x.children || []).map(text).join('');}
function button(x,label) {return nodes(x).find(n=>n.tag==='button' && text(n)===label);}
let modal,calls=[],messages=[],data={devices:[{device:'/dev/sda1',uuid:'abcd-1234',fstype:'vfat',label:'<img onerror=alert(1)>'}],volumes:{}};
let failure=false;
const ui={showModal(title,children){modal=E('div',{},children);},hideModal(){modal=null;},addNotification(_,node,kind){messages.push({text:text(node),kind});}};
const backend={exec:async(path,args)=>{
	assert.equal(path,'/usr/libexec/cudy-usb');calls.push(args);
	if(failure)return {code:1,stdout:JSON.stringify({ok:false,message:'分区仍在使用'})};
	if(args[0]!=='status')data.volumes=[{id:'usb_abcd_1234',uuid:'abcd-1234',share:'USB',target:'/mnt/cudy-usb/usb_abcd_1234',ready:true}];
	return {code:0,stdout:JSON.stringify({ok:true,result:args[0]==='status' ? data : {message:'完成'}})};
}};
const source=fs.readFileSync(process.argv[2] || 'tr3600/luci-app-cudy-usb/htdocs/luci-static/resources/view/cudy-usb.js','utf8');
const view=vm.runInNewContext('(function(){'+source+'})()', {view:{extend:x=>x},fs:backend,ui,E,window:{location:{hostname:'192.168.9.1'}},Array,Promise,JSON,Error});
(async()=>{
	let initial=await view.load();let container=view.render(initial);
	assert.equal(calls.length,1);
	assert(text(container).includes('尚未启用任何磁盘共享'));
	assert(text(container).includes('<img onerror=alert(1)>'));
	assert(!nodes(container).some(n=>n.tag==='img'));
	button(container,'启用共享').attrs.click();assert.equal(calls.length,1,'no mutation before explicit confirmation');
	await button(modal,'启用共享').attrs.click();
	assert.deepEqual(Array.from(calls[1]),['enable','abcd-1234','USB','0']);
	assert.equal(view.container,container,'refresh preserves the existing DOM holder');
	assert(text(container).includes('共享就绪'));
	assert(nodes(container).some(n=>n.tag==='tr' && text(n).includes('USB')),'authorized volume must be a DOM table row');
	await view.refresh();assert.equal(view.container,container);
	button(container,'安全卸载').attrs.click();assert(modal);
	failure=true;await button(modal,'确认').attrs.click();
	assert.equal(messages.at(-1).kind,'error');assert.equal(messages.at(-1).text,'分区仍在使用');
	failure=false;button(container,'取消授权').attrs.click();await button(modal,'确认').attrs.click();
	assert(calls.some(x=>x[0]==='forget'));
	const empty=view.render({devices:{},volumes:{}});assert(button(empty,'启用共享').attrs.disabled);
	const duplicate=view.render({devices:[{uuid:'abcd-1234',device:'/dev/sda1',fstype:'vfat',duplicate:true}],volumes:[]});assert(button(duplicate,'启用共享').attrs.disabled);
	console.log('PASS USB LuCI consent, JSON empty sets, safe text, persistent refresh, error and eject/forget actions');
})().catch(e=>{console.error(e);process.exit(1);});
