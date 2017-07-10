import click
from click.testing import CliRunner
from bin.go_tropo import deploy
from nose.tools import assert_equal


class run_tests():

    def go_tropo_dry_run(self, options):
        runner = CliRunner()
        result = runner.invoke(deploy,['--stack',options['stack_type'],'--dry-run',options['config_file']])
        return result

    def test_dry_run_phpinfo_app(self):
        stack_type = 'app'
        config_file = 'examples/phpinfo.yaml'
        output_file = 'tests/outputs/phpinfo.json'

        result = self.go_tropo_dry_run(dict(stack_type=stack_type, config_file = config_file))
        expected_output = open(output_file).read()
        assert_equal(result.output, expected_output)
