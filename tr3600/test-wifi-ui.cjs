const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'luci-app-cudy-wifi/htdocs/luci-static/resources/view/cudy-wifi.js'),'utf8');

async function main() {
    const options = {}, calls = [], messages = [];
    const aps = [
        {'.name':'ap2',device:'r2',mode:'ap',network:'lan',ssid:'Separate-2G'},
        {'.name':'ap5',device:'r5',mode:'ap',network:['lan'],ssid:'Separate-5G',key:'NeverExposeThisPassword'},
        {'.name':'guest',device:'r5',mode:'ap',network:'guest',ssid:'Guest'},
        {'.name':'uplink',device:'r2',mode:'sta',network:'wwan',ssid:'Upstream'}
    ];
    class Map {
        constructor(config) { assert.equal(config,'cudy_wifi'); }
        section(type,name) {
            assert.equal(name,'main');
            return {option(type,name,title,description) {
                const o = {type,name,title,description,values:[],dependencies:[],
                    value(value,label) { this.values.push([value,label]); },
                    depends(name,value) { this.dependencies.push([name,value]); }};
                options[name]=o; return o;
            }};
        }
        save() { calls.push('save'); return Promise.resolve(); }
        render() { return {}; }
    }
    let result = {code:0,stdout:'双频合一和频段引导已启用'};
    const context = {
        view:{extend:v=>v},form:{Map,NamedSection:'named',Flag:'flag',Value:'value',ListValue:'list'},
        uci:{
            load:name=>{ calls.push('load:'+name); return Promise.resolve(); },
            sections:(config,kind,cb)=>aps.forEach(cb),
            get:(config,name,option)=>name==='r2'?'2g':'5g',
            apply:()=>{ calls.push('apply'); return Promise.resolve(); }
        },
        fs:{exec:(file,args)=>{ calls.push([file,...args]); return Promise.resolve(result); }},
        ui:{addNotification:(target,node,type)=>messages.push({node,type})},
        E:(tag,attrs,text)=>({tag,attrs,text}),Promise,Array,encodeURIComponent,unescape
    };
    const page = vm.runInNewContext('(function(){'+source+'})()',context);
    await page.load(); page.render();
    assert.deepEqual(options.ap2g.values.map(x=>x[0]),['ap2']);
    assert.deepEqual(options.ap5g.values.map(x=>x[0]),['ap5']);
    assert.equal(options.ssid.default,'Separate-5G');
    assert.equal(options.key.password,true);
    assert.equal(options.key.default,undefined);
    assert.equal(options.steering.default,'1');
    assert.equal(options.ssid.validate('main','中'.repeat(10)),true);
    assert.notEqual(options.ssid.validate('main','中'.repeat(11)),true);
    assert.notEqual(options.ssid.validate('main','bad\nssid'),true);
    assert.equal(options.key.validate('main',''),true);
    assert.equal(options.key.validate('main','valid"Pass\\123'),true);
    assert.notEqual(options.key.validate('main','short'),true);
    assert.notEqual(options.key.validate('main','x'.repeat(64)),true);
    assert.notEqual(options.key.validate('main','invalid\nPass'),true);
    calls.length=0; await page.handleSaveApply();
    assert.deepEqual(JSON.parse(JSON.stringify(calls)),['save','apply',['/usr/libexec/cudy-wifi-apply','apply']]);
    assert.equal(messages[0].type,'info');
    assert.equal(messages[0].node.text,result.stdout);
    result={code:1,stderr:'无法保存原无线配置，未修改网络'};
    await page.handleSaveApply();
    assert.equal(messages[1].type,'error'); assert.equal(messages[1].node.text,result.stderr);
    console.log('Wi-Fi LuCI: LAN AP selection, UTF-8 bounds, masked password, fixed apply command and error feedback passed');
}
main().catch(error=>{ console.error(error); process.exitCode=1; });
