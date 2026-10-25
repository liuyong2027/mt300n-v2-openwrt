"""Test-only forwarding of Linux IPv4 transparent socket APIs in pinned QEMU.

These are real host syscalls and sockaddr/CMSG translations. No destination,
result or permission is fabricated. This code never enters the router image.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1])/'linux-user/syscall.c'
s=p.read_text()
anchor='        case IP_RECVTOS:\n'
assert s.count(anchor)==2
s=s.replace(anchor,anchor+'''#ifdef IP_TRANSPARENT
        case IP_TRANSPARENT:
#endif
#ifdef IP_RECVORIGDSTADDR
        case IP_RECVORIGDSTADDR:
#endif
''')
a=s.index('static abi_long do_getsockopt(')
before,after=s[:a],s[a:]
anchor='    case SOL_IP:\n        switch(optname) {\n'
assert after.count(anchor)==1
after=after.replace(anchor,anchor+'''        case 80: /* Linux SO_ORIGINAL_DST returns sockaddr, never an int. */
        {
            struct sockaddr_storage addr;
            socklen_t addrlen = sizeof(addr);
            if (get_user_u32(len, optlen)) {
                return -TARGET_EFAULT;
            }
            if (len < 0) {
                return -TARGET_EINVAL;
            }
            memset(&addr, 0, sizeof(addr));
            ret = get_errno(getsockopt(sockfd, level, optname, &addr, &addrlen));
            if (ret < 0) {
                return ret;
            }
            len = MIN(len, addrlen);
            ret = host_to_target_sockaddr(optval_addr, (struct sockaddr *)&addr, len);
            if (ret < 0) {
                return ret;
            }
            if (put_user_u32(len, optlen)) {
                return -TARGET_EFAULT;
            }
            break;
        }
''',1)
s=before+after
a=s.index('host_to_target_cmsg(');b=s.index('/* do_setsockopt()',a)
before,body,after=s[:a],s[a:b],s[b:]
anchor='        case SOL_IP:\n            switch (cmsg->cmsg_type) {\n'
assert body.count(anchor)==1
body=body.replace(anchor,anchor+'''#ifdef IP_ORIGDSTADDR
            case IP_ORIGDSTADDR:
            {
                struct sockaddr_in *src = (struct sockaddr_in *)data;
                struct sockaddr_in *dst = (struct sockaddr_in *)target_data;
                if (len != sizeof(*src) || tgt_len != sizeof(*dst)) {
                    goto unimplemented;
                }
                /* Port/address are already network-order; only family is native. */
                memcpy(dst, src, sizeof(*dst));
                __put_user(src->sin_family, &dst->sin_family);
                break;
            }
#endif
''',1)
p.write_text(before+body+after,newline='\n')
