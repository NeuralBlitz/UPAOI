"""CI schema regression: catch YAML parse errors before pushing GitHub workflows."""
import unittest
from pathlib import Path
try:
    import yaml
except ImportError:
    yaml = None


@unittest.skipIf(yaml is None, "Install the CI extras: pip install -e '.[ci]'")
class GithubActionsConfigTests(unittest.TestCase):
    def test_workflow_is_valid_yaml_with_expected_jobs(self):
        path=Path(__file__).resolve().parent.parent/'.github'/'workflows'/'ci.yml'
        with path.open(encoding='utf8') as f:
            spec=yaml.safe_load(f)
        self.assertIsInstance(spec,dict)
        self.assertIn('jobs',spec)
        self.assertIn('unit-tests',spec['jobs'])
        job=spec['jobs']['unit-tests']
        versions=job['strategy']['matrix']['python-version']
        self.assertEqual(set(versions),{'3.10','3.12','3.13'})
        steps=job['steps']
        self.assertIn('Local specialist demo smoke test',{x.get('name') for x in steps})
        run=next(x['run'] for x in steps if x.get('name')=='Local specialist demo smoke test')
        self.assertIn('nb_orchestrator.cli agents',run)


if __name__=='__main__':unittest.main()
