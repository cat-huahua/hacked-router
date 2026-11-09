"""Synthetic fixtures only: no firmware payload, credentials or target execution."""
import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('decode_web_assets', Path(__file__).with_name('decode_web_assets.py'))
WEB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WEB)

# Standard packer boilerplate; the test payload/dictionary are invented below.
BODY = r"""function(p,a,c,k,e,r){e=function(c){return c.toString(a)};if(!''.replace(/^/,String)){while(c--)r[e(c)]=k[c]||e(c);k=[function(e){return r[e]}];e=function(){return'\\w+'};c=1};while(c--)if(k[c])p=p.replace(new RegExp('\\b'+e(c)+'\\b','g'),k[c]);return p}"""


class WebDecodeTests(unittest.TestCase):
    def test_known_packer_and_nonrecursive_dictionary(self):
        wrapped = "eval(" + BODY + "('0 1=2;',10,3,'var|example|7'.split('|'),0,{}))"
        decoded, inline, blocks = WEB.decode_text(wrapped)
        self.assertEqual(decoded, 'var example=7;')
        self.assertIsNone(inline)
        self.assertEqual(blocks[0]['status'], 'decoded')
        self.assertEqual(WEB.unpack('0 1 00 _1', 10, 2, '1|word'), '1 word 00 _1')

    def test_unknown_body_is_preserved(self):
        wrapped = "eval(function(p,a,c,k,e,r){return p}('0',10,1,'example'.split('|'),0,{}))"
        decoded, inline, blocks = WEB.decode_text(wrapped)
        self.assertEqual(decoded, wrapped)
        self.assertIsNone(inline)
        self.assertEqual(blocks[0]['status'], 'unresolved')

    def test_string_literals_and_rejection(self):
        self.assertEqual(WEB.js_literal(r"'a\x20b\u0021\\c'"), 'a b!\\c')
        self.assertEqual(WEB.js_literal(r"'\uD83D\uDE00'"), '\U0001f600')
        with self.assertRaises(ValueError):
            WEB.js_literal(r"'\123'")
        with self.assertRaises(ValueError):
            WEB.js_literal("'x' + expression()")

    def test_global_byte_transform_and_js_unescape(self):
        escaped = 'x' * 19 + '%7Breturn%20%u0041;%7D'
        payload = base64.b64encode(bytes(ord(c) ^ 3 for c in escaped)).decode()
        self.assertEqual(WEB.decode_global_payload(payload), 'ArcBase._tt=function(){return A;}')
        with self.assertRaises(ValueError):
            WEB.decode_global_payload(base64.b64encode(b'\xff').decode())
        source = 'var enkripsi="' + payload + '";'
        decoded, inline, blocks = WEB.decode_text(source)
        self.assertEqual(decoded, source)
        self.assertIsNone(inline)
        self.assertEqual(blocks[0]['status'], 'unresolved')

    def test_manifest_and_output_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='web-static-test-') as temporary:
            root = Path(temporary) / 'input'
            root.mkdir()
            source = 'eval(unknownWrapper());'
            (root / 'unknown.js').write_text(source)
            output = Path(temporary) / 'output'
            manifest = WEB.run(root, output)
            self.assertEqual((output / 'unknown.js').read_text(), source)
            self.assertEqual(manifest['files'][0]['status'], 'unresolved_candidate')
            self.assertFalse(manifest['target_javascript_executed'])
            with self.assertRaises(ValueError):
                WEB.run(root, output)
            with self.assertRaises(ValueError):
                WEB.run(root, root / 'nested')
            repo = Path(temporary) / 'repository'
            repo.mkdir()
            (repo / '.git').mkdir()
            with self.assertRaises(ValueError):
                WEB.run(root, repo / 'output')


if __name__ == '__main__':
    unittest.main()
