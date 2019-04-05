from nimrod.tools.evosuite import Evosuite
from nimrod.tools.randoop import Randoop
from nimrod.tools.junit import JUnit

from collections import namedtuple

SuiteEnv = namedtuple('SuiteEnv', ['classes_dir', 'sut_class', 'tests_src'])

class SuiteFactory():

    def __init__(self, java, suite_env):
        self.suite_env = suite_env
        self.java = java

    def randoop_generate(self, tool_params=None):
        randoop = Randoop(
            java=self.java,
            classpath=self.suite_env.classes_dir,
            tests_src=self.suite_env.tests_src,
            sut_class=self.suite_env.sut_class,
            params=tool_params if tool_params else []
        )

        return SuiteRunner(self.java, randoop.generate(), self.suite_env)

    def evosuite_generate(self, tool_params=None):
        evosuite = Evosuite(
            java=self.java,
            classpath=self.suite_env.classes_dir,
            tests_src=self.suite_env.tests_src,
            sut_class=self.suite_env.sut_class,
            params=tool_params if tool_params else []
        )

        return SuiteRunner(self.java, evosuite.generate(), self.suite_env)

class SuiteRunner():

    def __init__(self, java, suite, suite_env):
        self.java = java
        self.suite = suite
        self.suite_env = suite_env
        self.junit = JUnit(java=self.java, classpath=suite_env.classes_dir)

    def run_with_mutant(self, mutant):
        return self.junit.run_with_mutant(self.suite, self.suite_env.sut_class, 
                                          mutant)

    def get_tool_name(self):
        return self.suite.tool_name
