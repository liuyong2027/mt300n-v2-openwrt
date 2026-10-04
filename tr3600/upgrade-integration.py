#!/usr/bin/env python3
"""Install a board-specific dual-slot dispatcher without altering other boards."""
from pathlib import Path
import sys

tree = Path(sys.argv[1])
p = tree/'target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh'
s = p.read_text()
anchor = 'platform_do_upgrade() {\n'
assert s.count(anchor) == 1
case = '''\tif [ "$(board_name)" = 'cudy,tr3600-v1' ]; then
\t\t. /lib/upgrade/cudy-tr3600.sh
\t\tcudy_tr3600_do_upgrade "$1"
\t\treturn $?
\tfi
'''
s = s.replace(anchor, anchor+case)
s = s.replace("RAMFS_COPY_BIN='fitblk fit_check_sign'", "RAMFS_COPY_BIN='fitblk fit_check_sign fw_printenv fw_setenv'")
assert "fw_setenv'" in s
s = "RAMFS_COPY_DATA=\"$RAMFS_COPY_DATA /etc/fw_env.config\"\n" + s
p.write_text(s, newline='\n')
