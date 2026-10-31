'use strict';
'require view';
'require form';
'require uci';

return view.extend({
    load: function() {
        return uci.load('mango_ikev2');
    },
    render: function() {
        var m = new form.Map('mango_ikev2', 'IKEv2 客户端',
            '本镜像以 strongSwan 做路由器级 IKEv2 客户端。默认生产固件走 Xray，16 MiB 闪存放不下两套出口，因此 IKEv2 与 Xray 分属不同构建配置。split：国内 IP 直连，其余进隧道。中国 IP 列表：/usr/libexec/mango-ikev2-cn-update → /etc/mango-ikev2/cn-cidrs.txt。');

        var s = m.section(form.NamedSection, 'main', 'policy', '连接与分流');
        s.anonymous = true;

        var o = s.option(form.Flag, 'enabled', '启用 IKEv2 客户端');
        o.rmempty = false;

        o = s.option(form.ListValue, 'mode', '分流模式');
        o.value('direct', '全部直连（不经隧道）');
        o.value('split', '大陆分流（国内直连，境外 IKEv2）');
        o.value('global', '全局隧道');
        o.rmempty = false;

        o = s.option(form.Value, 'server', '服务器地址');
        o.datatype = 'host';
        o.rmempty = false;

        o = s.option(form.Value, 'remote_id', '远端 ID', '可留空，默认与服务器地址相同');
        o.placeholder = 'vpn.example.com';

        o = s.option(form.ListValue, 'auth', '认证方式');
        o.value('eap', 'EAP-MSCHAPv2（用户名密码）');
        o.value('psk', '预共享密钥 PSK');
        o.rmempty = false;

        o = s.option(form.Value, 'username', '用户名');
        o.depends('auth', 'eap');

        o = s.option(form.Value, 'password', '密码');
        o.password = true;
        o.depends('auth', 'eap');

        o = s.option(form.Value, 'psk', '预共享密钥');
        o.password = true;
        o.depends('auth', 'psk');

        o = s.option(form.Value, 'local_id', '本端 ID', 'EAP 默认同用户名；PSK 可填 %any');

        o = s.option(form.Value, 'lan_device', 'LAN 设备');
        o.default = 'br-lan';
        o.rmempty = false;

        o = s.option(form.Value, 'ifid', 'XFRM if_id');
        o.datatype = 'uinteger';
        o.default = '42';
        o.rmempty = false;

        o = s.option(form.Value, 'xfrm_mtu', 'XFRM MTU');
        o.datatype = 'range(1280,1500)';
        o.default = '1280';
        o.rmempty = false;

        return m.render();
    }
});
