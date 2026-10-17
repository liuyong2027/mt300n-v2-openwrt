"""Set the published filename before building source/checksum release assets."""
import hashlib
import json
from pathlib import Path
import re

def version_image(assets, version):
    assets = Path(assets)
    assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-rc[1-9][0-9]*)?', version)
    report_path = assets / 'tr3600-verification.json'
    proof = json.loads(report_path.read_text())
    assert proof['device'] == 'cudy,tr3600-v1'
    assert proof['version'] == 'tr3600-' + version
    original = proof['image']
    assert Path(original).name == original and '/' not in original and '\\' not in original
    source = assets / original
    assert source.is_file() and not source.is_symlink()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == proof['image_sha256']
    target = assets / ('cudy-tr3600-v1-' + version + '-sysupgrade.bin')
    if source != target:
        assert not target.exists(), 'Versioned asset already exists; do not overwrite it'
        source.rename(target)
    proof['image'] = target.name
    proof['download_filename_versioned'] = True
    report_path.write_text(json.dumps(proof, indent=2) + '\n')
    return target
