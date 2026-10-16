'use strict';
'require view';
'require rpc';
'require ui';
'require poll';

var getStatus=rpc.declare({object:'cudy.webfiles',method:'status',expect:{'':{}}});
var actions={};
actions.public_access=rpc.declare({object:'cudy.webfiles',method:'public_access',params:['enabled','public_ip','listen_port','external_port'],expect:{'':{}}});
actions.zerotier=rpc.declare({object:'cudy.webfiles',method:'zerotier',params:['enabled','network'],expect:{'':{}}});
['start','stop','certificate','renew_certificate','public_certificate'].forEach(function(method){actions[method]=rpc.declare({object:'cudy.webfiles',method:method,expect:{'':{}}});});
actions.settings=rpc.declare({object:'cudy.webfiles',method:'settings',params:['volume','port','read_write'],expect:{'':{}}});
actions.user_save=rpc.declare({object:'cudy.webfiles',method:'user_save',params:['original_username','username','password','read_write'],expect:{'':{}}});
actions.user_delete=rpc.declare({object:'cudy.webfiles',method:'user_delete',params:['username'],expect:{'':{}}});
function unwrap(r){if(!r||r.ok!==true)throw new Error(r&&r.message||'操作失败，请稍后重试');return r.result;}
var fieldCount=0;
function row(label,field,help){field.id=field.id||('cudy-webfiles-field-'+(++fieldCount));return E('div',{'class':'cbi-value'},[E('label',{'class':'cbi-value-title','for':field.id},label),E('div',{'class':'cbi-value-field'},[field,help?E('div',{'class':'cbi-value-description'},help):''])]);}
return view.extend({
 load:function(){return getStatus().then(unwrap);},
 render:function(state){
  var self=this;this.state=state;this.busy=false;this.buttons=[];this.originalUsername='';this.editAdmin=false;
  this.userRows=E('tbody',{});this.userTable=E('table',{'class':'table'},[E('thead',{},E('tr',{},[E('th',{},'用户名'),E('th',{},'权限'),E('th',{},'操作')])),this.userRows]);
  this.userReadWrite=E('input',{'type':'checkbox'});
  this.summary=E('p',{'role':'status','aria-live':'polite'},'');
  this.publicDirty=false;
  function dirtyPublic(){self.publicDirty=true;}
  this.publicEnabled=E('input',{'type':'checkbox','change':dirtyPublic});
  this.publicIP=E('input',{'type':'text','class':'cbi-input-text','placeholder':'公网 IPv4 或 DDNS 域名','input':dirtyPublic});
  this.publicPort=E('input',{'type':'number','class':'cbi-input-text','min':1024,'max':65535,'value':8080,'input':dirtyPublic});
  this.externalPort=E('input',{'type':'number','class':'cbi-input-text','min':1,'max':65535,'value':8080,'input':dirtyPublic});
  this.publicNote=E('p',{'role':'status','aria-live':'polite'},'');
  this.zerotierDirty=false;
  this.zerotierEnabled=E('input',{'type':'checkbox','change':function(){self.zerotierDirty=true;}});
  this.zerotierNetwork=E('select',{'class':'cbi-input-select','change':function(){self.zerotierDirty=true;}});
  this.zerotierNote=E('p',{'role':'status','aria-live':'polite'},'');
  this.link=E('a',{'target':'_blank','rel':'noopener'},'打开网页');
  this.username=E('input',{'type':'text','class':'cbi-input-text','maxlength':32,'autocomplete':'off','value':state.account_set?'':'admin'});
  this.password=E('input',{'type':'password','class':'cbi-input-text','autocomplete':'new-password','maxlength':72});
  this.confirm=E('input',{'type':'password','class':'cbi-input-text','autocomplete':'new-password','maxlength':72});
  this.volume=E('select',{'class':'cbi-input-select'});(state.volumes||[]).forEach(function(v){if(v.ready)self.volume.appendChild(E('option',{'value':v.id},v.share+'（'+v.uuid+'）'+(v.readOnly?' · 原系统只读':'')));});
  if(!this.volume.options.length)this.volume.appendChild(E('option',{'value':state.settings.volume},'等待原系统挂载 USB'));
  this.volume.value=state.settings.volume;
  this.port=E('input',{'type':'number','class':'cbi-input-text','min':1024,'max':65535,'value':state.settings.port});
  this.readWrite=E('input',{'type':'checkbox'});this.readWrite.checked=state.settings.read_write===true;
  function button(label,fn,cls){var b=E('button',{'type':'button','class':'cbi-button '+(cls||'cbi-button-action'),'click':fn},label);self.buttons.push(b);return b;}
  this.startButton=button('开启',function(){return self.perform('start');},'cbi-button-apply');
  this.stopButton=button('关闭',function(){return self.perform('stop');},'cbi-button-reset');
  this.accountButton=button('保存用户',function(){
   var user=self.username.value,pwd=self.password.value;
   if(!/^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$/.test(user)){ui.addNotification(null,E('p',{},'用户名需为 3–32 位字母、数字、点、下划线或短横线。'),'error');return;}
   if((!self.originalUsername||pwd!=='')&&(Array.from(pwd).length<6||new TextEncoder().encode(pwd).length>72||pwd.trim()!==pwd||/[\r\n\x00]/.test(pwd))){ui.addNotification(null,E('p',{},'密码至少 6 个字符、最多 72 字节，不能有换行或首尾空格。'),'error');return;}
   if(pwd!==self.confirm.value){ui.addNotification(null,E('p',{},'两次输入的密码不一致。'),'error');return;}
   return self.perform('user_save',[self.originalUsername,user,pwd,self.userReadWrite.checked]).then(function(ok){if(ok)self.resetUserForm();});
  },'cbi-button-apply');
  var newUser=button('新增用户',function(){self.resetUserForm();});
  var saveSettings=button('保存服务设置',function(){return self.perform('settings',[self.volume.value,Number(self.port.value),self.readWrite.checked]);},'cbi-button-save');
  var saveZeroTier=button('保存访问方式',function(){return self.perform('zerotier',[self.zerotierEnabled.checked,self.zerotierNetwork.value]).then(function(ok){if(ok)self.zerotierDirty=false;});},'cbi-button-save');
  var savePublic=button('保存公网入口',function(){return self.perform('public_access',[self.publicEnabled.checked,self.publicIP.value,Number(self.publicPort.value),Number(self.externalPort.value)]).then(function(ok){if(ok)self.publicDirty=false;});},'cbi-button-save');
  var publicCertificate=button('下载公网 CA 证书',function(){return self.perform('public_certificate',[],function(result){var url=URL.createObjectURL(new Blob([result.certificate],{type:'application/x-x509-ca-cert'})),a=E('a',{'href':url,'download':'cudy-webpage-public-test-ca.crt'});document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);});});
  var certificate=button('下载本次 CA 证书',function(){return self.perform('certificate',[],function(result){var blob=new Blob([result.certificate],{type:'application/x-x509-ca-cert'});var url=URL.createObjectURL(blob),a=E('a',{'href':url,'download':'cudy-webpage-test-ca.crt'});document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);});});
  var renew=button('重新生成证书',function(){if(!window.confirm('重新生成后，手机和电脑需重新导入新 CA。继续吗？'))return;return self.perform('renew_certificate');});
  var root=E('div',{'class':'cbi-map'},[
   E('h2',{},'Cudy webpage'),E('div',{'class':'cbi-map-descr'},'管理 USB 网页文件服务。网页账号独立于路由器管理账号。'),
   E('div',{'class':'cbi-section'},[E('h3',{},'服务状态'),this.summary,this.link,E('p',{},[this.startButton,' ',this.stopButton])]),
   E('div',{'class':'cbi-section'},[E('h3',{},'服务设置'),row('USB 存储设备',this.volume,'只能访问原 USB 管理页面已挂载并授权的设备。'),row('HTTPS 端口',this.port,'可选 1024–65535；访问范围由下方设置控制。'),row('允许写入',this.readWrite,'默认只读。原系统授权只读时，本项不能扩大权限。'),E('p',{},saveSettings)]),
   E('div',{'class':'cbi-section'},[E('h3',{},'外出访问'),row('允许 ZeroTier 访问',this.zerotierEnabled,'外出设备需加入同一私有 ZeroTier 网络，并接受该网络的托管路由。'),row('ZeroTier 网络',this.zerotierNetwork,'仅可选择已授权且已有到本机 LAN 路由的网络。'),this.zerotierNote,E('p',{},saveZeroTier)]),
   E('div',{'class':'cbi-section'},[E('h3',{},'公网访问（上级路由器转发）'),row('启用公网 HTTPS 入口',this.publicEnabled,'开放给能够到达此端口的客户端，仍需网页账号登录。'),row('公网 IP／DDNS 域名',this.publicIP,'例如 files.example.net，不含 https:// 和端口。首次改用域名需导入域名 CA；其后公网 IP 变化由 DDNS 更新。原 LAN／ZeroTier 证书保留。'),row('TR3600 入口端口',this.publicPort,'仅绑定保存时的私有 WAN IPv4；与 LAN 使用相同端口也可以。'),row('上级外部端口',this.externalPort,'可选 1–65535；外部 443 可省略网址中的端口。上级 TCP 转发到 TR3600 入口端口。'),this.publicNote,E('p',{},[savePublic,' ',publicCertificate])]),
   E('div',{'class':'cbi-section'},[E('h3',{},'动态 DNS'),E('p',{},'动态 DNS 由独立服务把域名更新到真实公网 IPv4，账号与网页账号相互独立。'),E('a',{'href':L.url('admin','services','ddns'),'target':'_blank','rel':'noopener'},'打开动态 DNS 设置')]),
   E('div',{'class':'cbi-section'},[E('h3',{},'网页用户'),E('p',{},'每个用户有独立密码。原账号为网页管理员；新增用户可选只读或读写。保存或删除用户后，运行中的网页服务会重启，旧登录会话失效。'),this.userTable,E('p',{},newUser),row('用户名',this.username),row('新密码',this.password,'至少 6 个字符；编辑已有用户时留空可保留原密码。'),row('确认新密码',this.confirm),row('允许此用户写入',this.userReadWrite,'只读用户可浏览、下载；读写用户可上传、重命名和删除。全局只读仍优先。'),E('p',{},this.accountButton)]),
   E('div',{'class':'cbi-section'},[E('h3',{},'HTTPS 证书'),E('p',{},'普通服务重启会保留证书。测试证书有效期 30 天；更换管理地址或证书到期后，可以重新生成。'),E('p',{},[certificate,' ',renew])])
  ]);
  this.resetUserForm();this.update(state);poll.add(function(){if(self.busy)return;return getStatus().then(unwrap).then(function(s){self.update(s);});},5);return root;
 },
 resetUserForm:function(){this.originalUsername='';this.editAdmin=false;this.username.value=this.state.account_set?'':'admin';this.password.value='';this.confirm.value='';this.userReadWrite.checked=!this.state.account_set;this.userReadWrite.disabled=!this.state.account_set;},
 editUser:function(u){this.originalUsername=u.username;this.editAdmin=u.admin;this.username.value=u.username;this.password.value='';this.confirm.value='';this.userReadWrite.checked=u.read_write;this.userReadWrite.disabled=u.admin;},
 updateUserRows:function(state){var self=this;while(this.userRows.firstChild)this.userRows.removeChild(this.userRows.firstChild);(state.users||[]).forEach(function(u){var edit=E('button',{'type':'button','class':'cbi-button cbi-button-edit','click':function(){self.editUser(u);}},'编辑');var del=E('button',{'type':'button','class':'cbi-button cbi-button-remove','click':function(){if(window.confirm('删除用户 '+u.username+'？此操作只删除网页账号，不删除 USB 文件。'))return self.perform('user_delete',[u.username]).then(function(ok){if(ok&&self.originalUsername===u.username)self.resetUserForm();});}},'删除');edit.disabled=self.busy;del.disabled=self.busy||u.admin;self.userRows.appendChild(E('tr',{},[E('td',{},u.username),E('td',{},u.admin?'管理员':u.read_write?'读写':'只读'),E('td',{},[edit,' ',del])]));});},
 update:function(state){this.state=state;this.updateUserRows(state);var p=state.public_access||{},pc=p.config||{},candidate=state.public_candidate||{};
  if(!this.publicDirty){this.publicEnabled.checked=pc.enabled===true;this.publicIP.value=pc.public_ip||'';this.publicPort.value=pc.listen_port||8080;this.externalPort.value=pc.external_port||8080;}
  this.publicNote.textContent=p.active?'入口已就绪：'+p.url+'；上级 TCP '+pc.external_port+' → '+pc.listen_ip+':'+pc.listen_port+'。需在上级路由器保存转发规则后才能验证公网可达。':pc.enabled?(p.error||'等待公网 HTTPS 入口就绪。'):'公网入口已关闭。当前上级地址：'+(candidate.address||'未就绪')+'。';
  if(state.public_dns){var dns=state.public_dns;this.publicNote.textContent+=' 当前域名解析：'+(dns.ready?(dns.ipv4||[]).join('、'):'暂无公网 IPv4，等待 DDNS 同步')+'。';}
  var z=state.zerotier||{};
  if(!this.zerotierDirty){this.zerotierEnabled.checked=z.enabled===true;while(this.zerotierNetwork.firstChild)this.zerotierNetwork.removeChild(this.zerotierNetwork.firstChild);var seen=false;(state.zerotier_networks||[]).forEach(function(n){this.zerotierNetwork.appendChild(E('option',{'value':n.network},'现有网络 · 路由器 '+n.address));if(n.network===z.network)seen=true;},this);if(z.network&&!seen)this.zerotierNetwork.appendChild(E('option',{'value':z.network},'已保存网络（暂未就绪）'));if(!this.zerotierNetwork.options.length)this.zerotierNetwork.appendChild(E('option',{'value':''},'尚无可用的已授权网络或 LAN 路由'));if(z.network)this.zerotierNetwork.value=z.network;}
  this.zerotierNote.textContent=z.active?'已允许通过 ZeroTier 访问：'+(z.url||state.url)+'；继续使用原网页账号和证书。':z.enabled?(z.error||'等待 ZeroTier 网络和访问规则就绪。'):'ZeroTier 访问已关闭。开启后仍使用原网页地址和证书。';
  var text=state.running?'运行中':'已停止';text+=' · '+(state.account_set?'账号已设置':'请先设置账号')+' · '+(state.access||'仅 LAN')+' · '+(state.user_count||0)+' 个网页用户';if(!state.running&&state.stopReason)text+=' · 原因：'+state.stopReason;if(state.resourceWarning)text+=' · 内存偏低';if(state.memAvailableKiB)text+=' · '+(state.memorySampleIsLive===false?'上次采样内存 ':'当前可用内存 ')+(state.memAvailableKiB/1024).toFixed(1)+' MiB';if(state.error)text+=' · '+state.error;this.summary.textContent=text;this.link.href=state.url||('https://'+(state.lan||'192.168.9.1')+':'+state.settings.port);this.link.style.display=state.running?'':'none';this.buttons.forEach(function(b){b.disabled=this.busy;},this);this.startButton.disabled=this.busy||state.running||!state.account_set;this.stopButton.disabled=this.busy||(!state.running&&!state.enabled);this.accountButton.disabled=this.busy;},
 perform:function(method,args,callback){var self=this;this.busy=true;this.update(this.state);return actions[method].apply(null,args||[]).then(unwrap).then(function(result){if(callback)callback(result);else self.update(result);ui.addNotification(null,E('p',{},method==='user_save'?'用户已保存；请用对应账号密码登录网页。':'操作已完成。'),'info');return true;}).catch(function(e){ui.addNotification(null,E('p',{},e.message||'操作失败。'),'error');return false;}).finally(function(){self.busy=false;return getStatus().then(unwrap).then(function(s){self.update(s);});});},
 handleSave:null,handleSaveApply:null,handleReset:null
});
