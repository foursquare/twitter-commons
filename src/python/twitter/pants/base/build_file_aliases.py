# =================================================================================================
# Copyright 2011 Twitter, Inc.
# -------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =================================================================================================

import os

from twitter.pants.targets.annotation_processor import AnnotationProcessor
from twitter.pants.targets.artifact import Artifact
from twitter.pants.targets.benchmark import Benchmark
from twitter.pants.targets.credentials import Credentials
from twitter.pants.targets.doc import Page, Wiki
from twitter.pants.targets.jar_dependency import JarDependency
from twitter.pants.targets.jar_library import JarLibrary
from twitter.pants.targets.java_agent import JavaAgent
from twitter.pants.targets.java_antlr_library import JavaAntlrLibrary
from twitter.pants.targets.java_library import JavaLibrary
from twitter.pants.targets.java_protobuf_library import JavaProtobufLibrary
from twitter.pants.targets.java_tests import JavaTests
from twitter.pants.targets.java_thrift_library import JavaThriftLibrary
from twitter.pants.targets.jvm_binary import JvmApp, JvmBinary
from twitter.pants.targets.pants_target import Pants
from twitter.pants.targets.python_antlr_library import PythonAntlrLibrary
from twitter.pants.targets.python_artifact import PythonArtifact
from twitter.pants.targets.python_binary import PythonBinary
from twitter.pants.targets.python_egg import PythonEgg
from twitter.pants.targets.python_library import PythonLibrary
from twitter.pants.targets.python_requirement import PythonRequirement
from twitter.pants.targets.python_requirement_library import PythonRequirementLibrary
from twitter.pants.targets.python_tests import PythonTests, PythonTestSuite
from twitter.pants.targets.python_thrift_library import PythonThriftLibrary
from twitter.pants.targets.repository import Repository
from twitter.pants.targets.resources import Resources
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.targets.scalac_plugin import ScalacPlugin


# aliases
target_aliases = {
  'annotation_processor': AnnotationProcessor,
  'benchmark': Benchmark,
  'credentials': Credentials,
  'dependencies': JarLibrary,
  'jar_library': JarLibrary,
  'egg': PythonEgg,
  'fancy_pants': Pants,
  'java_agent': JavaAgent,
  'java_library': JavaLibrary,
  'java_antlr_library': JavaAntlrLibrary,
  'java_protobuf_library': JavaProtobufLibrary,
  'junit_tests': JavaTests,
  'java_tests': JavaTests,
  'java_thrift_library': JavaThriftLibrary,
  'jvm_binary': JvmBinary,
  'jvm_app': JvmApp,
  'page': Page,
  'python_binary': PythonBinary,
  'python_library': PythonLibrary,
  'python_requirement_library': PythonRequirementLibrary,
  'python_antlr_library': PythonAntlrLibrary,
  'python_thrift_library': PythonThriftLibrary,
  'python_tests': PythonTests,
  'python_test_suite': PythonTestSuite,
  'repo': Repository,
  'resources': Resources,
  'scala_library': ScalaLibrary,
  'scala_specs': ScalaTests,
  'scala_tests': ScalaTests,
  'scalac_plugin': ScalacPlugin,
  'wiki': Wiki,
}

from twitter.common.quantity import Amount, Time
from twitter.pants.goal import Context, Goal, Group, Phase
from twitter.pants.targets.exclude import Exclude
from twitter.pants.tasks import Task, TaskError
from .build_environment import get_buildroot, get_version, set_buildroot, get_scm, set_scm
from .config import Config

object_aliases = {
  'artifact': Artifact,
  'goal': Goal,
  'group': Group,
  'phase': Phase,
  'config': Config,
  'get_version': get_version,
  'get_buildroot': get_buildroot,
  'set_buildroot': set_buildroot,
  'get_scm': get_scm,
  'set_scm': set_scm,
  'jar': JarDependency,
  'python_requirement': PythonRequirement,
  'exclude': Exclude,
  'python_artifact': PythonArtifact,
  'setup_py': PythonArtifact,
  'Amount': Amount,
  'Time': Time,
}


from twitter.common.dirutil.fileset import Fileset
from twitter.pants.targets.jvm_binary import Bundle
from twitter.pants.base.source_root import SourceRoot

def maven_layout(basedir='', rel_path=None):
  """Sets up typical maven project source roots for all built-in pants target types.

  Shortcut for ``source_root('src/main/java', *java targets*)``,
  ``source_root('src/main/python', *python targets*)``, ...

  :param string basedir: Instead of using this BUILD file's directory as
    the base of the source tree, use a subdirectory. E.g., instead of
    expecting to find java files in ``src/main/java``, expect them in
    ``**basedir**/src/main/java``.
  """

  def root(path, *types):
    SourceRoot.register(os.path.join(rel_path, basedir, path), *types)

  root('src/main/antlr', JavaAntlrLibrary, Page, PythonAntlrLibrary)
  root('src/main/java', AnnotationProcessor, JavaAgent, JavaLibrary, JvmBinary, Page)
  root('src/main/protobuf', JavaProtobufLibrary, Page)
  root('src/main/python', Page, PythonBinary, PythonLibrary)
  root('src/main/resources', Page, Resources)
  root('src/main/scala', JvmBinary, Page, ScalaLibrary)
  root('src/main/thrift', JavaThriftLibrary, Page, PythonThriftLibrary)

  root('src/test/java', JavaLibrary, JavaTests, Page)
  root('src/test/python', Page, PythonLibrary, PythonTests, PythonTestSuite)
  root('src/test/resources', Page, Resources)
  root('src/test/scala', JavaTests, Page, ScalaLibrary, ScalaTests)


applicative_path_relative_util_aliases = {
  'source_root': SourceRoot,
  'bundle': Bundle,
}

partial_path_relative_util_aliases = {
  'globs': Fileset.globs,
  'rglobs': Fileset.rglobs,
  'zglobs': Fileset.zglobs,
  'maven_layout': maven_layout,
}
