import unittest
from check_runtime_dependencies import check_dependencies


class DependencyFailures(unittest.TestCase):
    def check(self, *, websocket=True, packages=None, version='24.19.0'):
        contract = {'runtime': {'node': {'observedVersion': '24.19.0'},
                    'python': {'observedVersion': '3.12.13',
                               'observedBusinessDependencyClosure': {'openpyxl': '3.1.5'}}},
                    'browserComponents': [], 'hostNodeLibraries': {'observed': {}, 'currentRoot': '/unused'}}
        def fake(argv):
            if '--eval' in argv:
                return {'version': version, 'webSocket': websocket}
            return {'version': '3.12.13', 'packages': {'openpyxl': '3.1.5'} if packages is None else packages}
        return check_dependencies(contract, {'interpreters': {'node': 'node', 'python': 'python'}}, fake)

    def test_node_twenty_without_websocket_cannot_pass(self):
        self.assertFalse(self.check(websocket=False, version='20.20.0')['ok'])

    def test_missing_business_package_cannot_pass(self):
        self.assertFalse(self.check(packages={})['ok'])

    def test_different_package_version_cannot_pass(self):
        self.assertFalse(self.check(packages={'openpyxl': '3.0.0'})['ok'])

    def test_complete_baseline_passes_without_business_actions(self):
        result = self.check()
        self.assertTrue(result['ok'])
        self.assertEqual(result['productionActions'], 0)


if __name__ == '__main__':
    unittest.main()
