import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class DraftResponseTest(unittest.TestCase):
    def test_publish_uses_created_draft_id_without_relisting(self):
        spec=importlib.util.spec_from_file_location('publisher',ROOT/'scripts/publish-release.py')
        publisher=importlib.util.module_from_spec(spec); spec.loader.exec_module(publisher)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); assets=folder/'release-assets'; assets.mkdir()
            for name in publisher.ASSETS | {'SHA256SUMS'}:
                (assets/name).write_text('fixture')
            commit='a'*40
            calls=[]
            def gh(*args,input_text=None):
                calls.append(args)
                if args[0]=='api' and 'matching-refs' in args[1]: return '[]'
                if args==('api','repos/liuyong2027/mt300n-v2-openwrt/releases?per_page=100'):
                    assert calls.count(args)==1, 'Draft list is deliberately stale'
                    return '[]'
                if args[:3]==('api','--method','POST'):
                    body=json.loads(input_text)
                    assert body['draft'] and body['target_commitish']==commit
                    return json.dumps({'id':123,'draft':True,'target_commitish':commit})
                if args==('api','repos/liuyong2027/mt300n-v2-openwrt/releases/123'):
                    uploaded=[{'name':p.name,'size':p.stat().st_size,'state':'uploaded',
                               'digest':'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()} for p in assets.iterdir()]
                    return json.dumps({'assets':uploaded,'draft':calls.count(args)==1,'prerelease':False,'html_url':'fixture'})
                if args==('api','repos/liuyong2027/mt300n-v2-openwrt/git/ref/tags/v23.0.0'):
                    return json.dumps({'object':{'type':'commit','sha':commit}})
                if args[:2] in [('release','upload'),('release','edit')]: return ''
                raise AssertionError(args)
            old=Path.cwd()
            try:
                os.chdir(folder)
                with patch.object(publisher,'gh',gh), patch.object(publisher,'verify_assets',return_value={}), patch.dict(os.environ,{
                    'GITHUB_REPOSITORY':'liuyong2027/mt300n-v2-openwrt','GITHUB_SHA':commit,
                    'GITHUB_REF':'refs/heads/codex/mt300n-v2-release23','GITHUB_RUN_ID':'123'}), contextlib.redirect_stdout(io.StringIO()):
                    publisher.main()
            finally:
                os.chdir(old)
            self.assertTrue(any(c[:3]==('api','--method','POST') for c in calls))


if __name__=='__main__': unittest.main()
