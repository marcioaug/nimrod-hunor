import os
import shutil
import subprocess

from unittest import TestCase

from nimrod.tests.utils import calculator_project_dir
from nimrod.tests.utils import get_config

from nimrod.tools.suite_generator import SuiteGenerator
from nimrod.tools.java import Java


class ToolSuiteGenerator(SuiteGenerator):

    def _get_tool_name(self):
        return 'test'

    def _exec_tool(self):
        return self._exec('-version')

    def _test_classes(self):
        return []

    def _get_timeout(self):
        return 0


class TestSuiteGenerator(TestCase):

    def setUp(self):
        self.java = Java(get_config()['java_home'])

        self.tests_src = os.path.join(calculator_project_dir(), 'test_tool')
        self.suite_tool = ToolSuiteGenerator(self.java, '', self.tests_src, '')

    def test_get_tool_name(self):
        self.assertEqual('test', self.suite_tool._get_tool_name())

    def test_generate_timeout(self):
        with self.assertRaises(subprocess.TimeoutException):
            self.suite_tool.generate()

    def tearDown(self):
        shutil.rmtree(self.tests_src)
