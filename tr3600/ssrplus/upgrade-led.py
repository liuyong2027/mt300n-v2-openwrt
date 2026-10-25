from pathlib import Path
import importlib.util
import sys
root=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('led',root/'tr3600/led-integration.py')
led=importlib.util.module_from_spec(spec);spec.loader.exec_module(led)
p=Path(sys.argv[1])/'package/base-files/files/sbin/sysupgrade'
p.write_text(led.patch_upgrade(p.read_text()),newline='\n')

