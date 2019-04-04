import os
import shutil
import time
import threading

from nimrod.tools.randoop import Randoop
from nimrod.tools.mujava import MuJava
from nimrod.mutant import Mutant
from nimrod.tools.safira import Safira
from nimrod.tools.junit import JUnit, JUnitResult, Coverage
from nimrod.tools.evosuite import Evosuite
from nimrod.utils import package_to_dir

from collections import namedtuple


OUTPUT_DIR = 'nimrod_output'


NimrodResult = namedtuple('NimrodResult', ['maybe_equivalent', 'not_equivalent',
                                           'coverage', 'differential',
                                           'timeout', 'test_tool', 'is_equal_coverage'])


class Nimrod:

    def __init__(self, java, maven):
        self.java = java
        self.maven = maven
        self.suite_evosuite_diff = None
        self.suite_evosuite = None
        self.suite_randoop = None

    def run(self, project_dir, mutants_dir, sut_class, randoop_params=None,
            evosuite_diff_params=None, evosuite_params=None, output_dir=None):

        results = {}

        _, classes_dir = self.maven.compile(project_dir, clean=True)
        output_dir = self.check_output_dir(output_dir if output_dir
                                           else os.path.join(project_dir,
                                                             OUTPUT_DIR))

        for mutant in self.get_mutants(classes_dir, mutants_dir):
            start_time = time.time()
            if self.check_mutant(mutant, sut_class):
                tests_src = os.path.join(output_dir, 'suites', mutant.mid)


                #Start Threads to generate the test suites
                thread_evosuite_diff = threading.Thread(target=self.gen_evosuite_diff, args=(classes_dir, evosuite_diff_params, mutant, sut_class, tests_src))
                thread_evosuite = threading.Thread(target=self.gen_evosuite, args=(classes_dir, evosuite_params, mutant, sut_class, tests_src))
                thread_randoop = threading.Thread(target=self.gen_randoop, args=(classes_dir, mutant, randoop_params, sut_class, tests_src))

                thread_evosuite_diff.start()

                # Wait the generation of the Suite in the thread
                thread_evosuite_diff.join()
                #Start to execute the test suites...
                test_result = self.try_evosuite_diff(classes_dir, tests_src,
                                                     sut_class, mutant,
                                                     evosuite_diff_params)
                
                
                if test_result.fail_tests > 0 or test_result.timeout:
                    results[mutant.mid] = self.create_nimrod_result(test_result,
                                                                    True, 'evosuite')
                else:
                    thread_evosuite.start()
                    thread_randoop.start()
                    # Wait the generation of the Suite in the thread
                    thread_evosuite.join()
                    evo_test_result = self.try_evosuite(classes_dir, tests_src,
                                                        sut_class, mutant,
                                                        evosuite_params)
                    if evo_test_result and (evo_test_result.fail_tests > 0
                                            or evo_test_result.timeout):
                        results[mutant.mid] = self.create_nimrod_result(
                            evo_test_result, False, 'evosuite')
                    else:
                        # Wait the generation of the Suite in the thread
                        thread_randoop.join()
                        ran_test_result = self.try_randoop(
                            classes_dir, tests_src, sut_class, mutant,
                            randoop_params)
                        if ran_test_result and (ran_test_result.fail_tests > 0
                                                or ran_test_result.timeout):
                            results[mutant.mid] = self.create_nimrod_result(
                                ran_test_result, False, 'randoop')
                        else:
                            # If no test kill, check coverage with original
                            is_equal_coverage = self.check_class_coverage(classes_dir,
                                                        sut_class, mutant, evo_test_result, ran_test_result)
                            results[mutant.mid] = self.sum_nimrod_result(
                                ran_test_result, evo_test_result, False, is_equal_coverage=is_equal_coverage)

                self.print_result(mutant, results[mutant.mid])
                exec_time = time.time() - start_time
                self.write_to_csv(results[mutant.mid], mutant, output_dir, exec_time=exec_time)
                if thread_evosuite_diff.is_alive():
                    thread_evosuite_diff.join()
                if thread_evosuite.is_alive():
                    thread_evosuite.join()
                if thread_randoop.is_alive():
                    thread_randoop.join()

        return results

    @staticmethod
    def print_result( mutant, result):
        if result.maybe_equivalent:
            print('{0} maybe equivalent, executions: {1}.'
                  .format(mutant.mid, result.coverage.executions))
        else:
            print('{0} is not equivalent. {1}'
                  .format(mutant.mid, 'Killed by differential test.' if
                          result.differential else ''))

    @staticmethod
    def check_mutant(mutant, sut_class):
        print("Analyzing mutant: {0}".format(mutant.mid))
        if os.path.exists(mutant.dir):
            class_file = os.path.join(mutant.dir, package_to_dir(sut_class) +
                                      '.class')
            if not os.path.exists(class_file):
                print("{0}: .class not found.".format(mutant.mid))
                return False
            else:
                return True
        else:
            print('{0}: directory not found.'.format(mutant.mid))
            return False

    def get_mutants(self, classpath, mutants_dir):
        mujava = MuJava(self.java, mutants_dir)
        mutants = mujava.read_log()
        mujava.compile_mutants(classpath, mutants)

        return mutants


    def check_class_coverage(self, classes_dir, sut_class, mutant, evo_test_result, ran_test_result):
        
        original_dir = os.path.join(
                            mutant.dir[:mutant.dir.rfind(os.sep)], 'ORIGINAL')
        original = Mutant(mid='ORIGINAL', operator=None, line_number=None,
                      method=None, transformation=None, dir=original_dir)

        junit = JUnit(java=self.java, classpath=classes_dir)
        orig_evosuite_result = (junit.run_with_mutant(self.suite_evosuite, sut_class, original)
                if self.suite_evosuite else None)
        orig_ran_result = (junit.run_with_mutant(self.suite_randoop, sut_class, original)
                if self.suite_randoop else None)        

        evosuite_coverage = (orig_evosuite_result.coverage.class_coverage == evo_test_result.coverage.class_coverage)
        randoop_coverage = (orig_ran_result.coverage.class_coverage == ran_test_result.coverage.class_coverage)
        return  (evosuite_coverage and randoop_coverage)


    def try_evosuite_diff(self, classes_dir, tests_src, sut_class, mutant,
                     evosuite_diff_params=None):
        junit = JUnit(java=self.java, classpath=classes_dir)
        return junit.run_with_mutant(self.suite_evosuite_diff, sut_class, mutant)


    def try_evosuite(self, classes_dir, tests_src, sut_class, mutant,
                     evosuite_params=None):
        junit = JUnit(java=self.java, classpath=classes_dir)
        return (junit.run_with_mutant(self.suite_evosuite, sut_class, mutant)
                if self.suite_evosuite else None)


    def try_randoop(self, classes_dir, tests_src, sut_class, mutant,
                    randoop_params=None):
        junit = JUnit(java=self.java, classpath=classes_dir)
        return (junit.run_with_mutant(self.suite_randoop, sut_class, mutant)
                if self.suite_randoop else None)

    def gen_evosuite_diff(self, classes_dir, evosuite_diff_params, mutant, sut_class, tests_src):
        evosuite = Evosuite(
            java=self.java,
            classpath=classes_dir,
            tests_src=tests_src,
            sut_class=sut_class,
            params=evosuite_diff_params
        )
        self.suite_evosuite_diff = evosuite.generate_differential(mutant.dir)
        return self.suite_evosuite_diff

    def gen_evosuite(self, classes_dir, evosuite_params, mutant, sut_class, tests_src):
        evosuite = Evosuite(
            java=self.java,
            classpath=classes_dir,
            tests_src=tests_src,
            sut_class=sut_class,
            params=evosuite_params
        )
        # suite = evosuite.generate()
        safira = Safira(java=self.java, classes_dir=classes_dir,
                        mutant_dir=mutant.dir)
        self.suite_evosuite = evosuite.generate_with_impact_analysis(safira)
        if "Simulator" in sut_class:
            import distutils.dir_util
            distutils.dir_util.copy_tree("./config/", evosuite.suite_dir + "/config/")

        return self.suite_evosuite

    def gen_randoop(self, classes_dir, mutant, randoop_params, sut_class, tests_src):
        randoop = Randoop(
            java=self.java,
            classpath=classes_dir,
            tests_src=tests_src,
            sut_class=sut_class,
            params=randoop_params
        )
        safira = Safira(java=self.java, classes_dir=classes_dir,
                        mutant_dir=mutant.dir)
        if "Bisect" in sut_class:
            self.suite_randoop = randoop.generate()
        else:
            self.suite_randoop = randoop.generate_with_impact_analysis(safira)
            if "Simulator" in sut_class:
                import distutils.dir_util
                distutils.dir_util.copy_tree("./config/", randoop.suite_dir + "/config/")
        return self.suite_randoop

    @staticmethod
    def check_output_dir(output_dir):
        output_dir = os.path.abspath(os.path.join('.', output_dir))
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir)

        return output_dir

    @staticmethod
    def create_nimrod_result(test_result, differential, test_tool, is_equal_coverage=False):
        return NimrodResult(
            test_result.fail_tests == 0 and not test_result.timeout,
            test_result.fail_tests > 0 or test_result.timeout,
            test_result.coverage, differential, test_result.timeout, test_tool, is_equal_coverage)

    @staticmethod
    def sum_nimrod_result(ran, evo, differential, is_equal_coverage):
        if ran and evo:
            return Nimrod.create_nimrod_result(
                JUnitResult(
                    ok_tests=ran.ok_tests + evo.ok_tests,
                    fail_tests=ran.fail_tests + evo.fail_tests,
                    fail_test_set=ran.fail_test_set.union(evo.fail_test_set),
                    run_time=ran.run_time + evo.run_time,
                    coverage=Coverage(
                        call_points=(ran.coverage.call_points
                                     .union(evo.coverage.call_points)),
                        test_cases=(ran.coverage.test_cases
                                    .union(evo.coverage.test_cases)),
                        executions=(ran.coverage.executions
                                    + evo.coverage.executions),
                        class_coverage=dict(evo.coverage.class_coverage, **ran.coverage.class_coverage),          
                    ),
                    timeout=ran.timeout or evo.timeout
                ),
                differential, 
                '',
                is_equal_coverage
            )
        elif ran:
            return Nimrod.create_nimrod_result(ran, differential, '', is_equal_coverage)
        elif evo:
            return Nimrod.create_nimrod_result(evo, differential, '', is_equal_coverage)

    @staticmethod
    def write_to_csv(result, mutant, output_dir='.', filename='nimrod.csv',
                     exclude_if_exists=False, exec_time=0):
        file = os.path.join(output_dir, filename)

        if exclude_if_exists:
            if os.path.exists(file):
                os.remove(file)

        if not os.path.exists(file):
            with open(file, 'w') as f:
                f.write('mutant,maybe_equivalent,not_equivalent,differential,' +
                        'timeout,killed_by,test_case,exec_time,call_points,test_cases,executions,equal_line_coverage\n')

        if result and mutant:
            killer_tests = []
            if(len(result.coverage.test_cases)>0):
                killer_tests = [t[0]+'#'+t[1] for t in result.coverage.test_cases if len(t)==2]

            with open(file, 'a') as f:
                f.write('{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11}\n'.format(
                    mutant.mid,
                    'x' if result.maybe_equivalent else '',
                    'x' if result.not_equivalent else '',
                    'x' if result.differential else '',
                    'x' if result.timeout else '',
                    result.test_tool,
                    '' if result.maybe_equivalent else str(killer_tests).replace(',', '|'), 
                    round(exec_time, 2),                    
                    len(result.coverage.call_points),
                    len(result.coverage.test_cases),
                    result.coverage.executions,
                    result.is_equal_coverage,
                ))
                f.close()



