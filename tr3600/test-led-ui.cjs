const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
async function main() {
    const source=fs.readFileSync(path.join(__dirname,'luci-app-cudy-led/htdocs/luci-static/resources/view/cudy-led.js'),'utf8');
    const options={},calls=[],messages=[];
    class Map {
        constructor(config) { assert.equal(config,'cudy_led'); }
        section(type,name) { assert.equal(name,'main'); return {option(type,name) {
            const option={name,map:this,values:[],value(v,label){this.values.push(v);},depends(){},formvalue(){return this.current;}};
            option.map={lookupOption:name=>[options[name]]}; options[name]=option; return option;
        }}; }
        save() {calls.push('save');return Promise.resolve();}
        render(){return {};}
    }
    let result={code:0,stdout:'指示灯设置已应用'};
    const context={view:{extend:v=>v},form:{Map,NamedSection:'named',ListValue:'list',Flag:'flag',Value:'value'},
        uci:{load:c=>{calls.push('load:'+c);return Promise.resolve();},apply:()=>{calls.push('apply');return Promise.resolve();}},
        fs:{exec:(file,args)=>{calls.push([file,...args]);return Promise.resolve(result);}},
        ui:{addNotification:(target,node,type)=>messages.push({node,type})},E:(tag,attrs,text)=>({tag,text}),Promise};
    const page=vm.runInNewContext('(function(){'+source+'})()',context);
    await page.load();page.render();
    assert.deepEqual(options.mode.values,['status','default','off']);
    assert.equal(options.mode.default,'status');assert.equal(options.night.default,'0');
    assert.equal(options.night_start.default,'23:00');assert.equal(options.night_end.default,'07:00');
    options.night_start.current='23:00';options.night_end.current='07:00';
    assert.equal(options.night_start.validate('main','23:00'),true);
    for (const bad of ['24:00','23:60','7:00','23:00;reboot','']) assert.notEqual(options.night_start.validate('main',bad),true);
    assert.notEqual(options.night_start.validate('main','07:00'),true);
    calls.length=0;await page.handleSaveApply();
    assert.deepEqual(JSON.parse(JSON.stringify(calls)),['save','apply',['/usr/libexec/cudy-led-apply']]);
    assert.equal(messages[0].type,'info');result={code:1,stderr:'升级期间指示灯由系统管理'};
    await page.handleSaveApply();assert.equal(messages[1].type,'error');
    console.log('LED LuCI defaults, time validation, fixed command and error feedback passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
