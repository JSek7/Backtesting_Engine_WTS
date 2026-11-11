"""Check retained execution methods against the organiser-core release fingerprint."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

def canonical(node):
    if isinstance(node, ast.AST):
        return [type(node).__name__, [(name, canonical(value)) for name, value in ast.iter_fields(node) if name != "type_params"]]
    if isinstance(node, list):
        return [canonical(value) for value in node]
    return node

EXPECTED = {'submit_bot_quotes': '13c2210ae224a676c753a36b523601c6c7ce662d2a955f5db63f773c5866e80a', 'submit_order': '72bffe06469e161d9fd246bbc1879d53580b5d30389f2d81e00b20f411f8f1de', '_match': '6dbc170a74440ffeb21a5278b4c2b207e469fb58eca5c50f8a2f7aa2aea3c8a8', 'cancel_order': '44fe96f11d28fdcdda29abd6b1eebc3868f40cf469bb9d83a4dcc074bc1d58a5', 'cancel_bot_quotes': 'a49bdde6f9c43e68a7136993b5c47a1ed12d95b9f6c69ca31b27c4cb01b85236', 'get_best_bid': 'd292bddd86d3942c9764f8e3a0b18cba3708347ed7e29b9c454661b66daa4eab', 'get_best_ask': 'f996ebf997690ef0f00d42fcae63a15c266da30a1428582476265697f08c65c1', 'get_book_snapshot': '6fe18501b87b990fc3763284577b711bb2adb9bb4773554ef7bf6a632188d3b0', '_next_sequence': 'e824f01ca3148935087eb82f2c2df97571ecd2e738fae443681a927c0defad7e'}

class CoreCompatibilityTests(unittest.TestCase):
    def test_execution_methods_match_release_fingerprints(self):
        path = Path(__file__).resolve().parents[1] / "engine/matching.py"
        cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef))
        got = {n.name: hashlib.sha256(json.dumps(canonical(n), separators=(",", ":")).encode()).hexdigest()
               for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in EXPECTED}
        self.assertEqual(got, EXPECTED)
