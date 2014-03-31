# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
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
# ==================================================================================================

from __future__ import print_function

from twitter.common.collections import OrderedSet
from twitter.pants.base.build_file import BuildFile
from twitter.pants.base.build_file_parser import BuildFileParser
from twitter.pants.base.config import Config
from twitter.pants.base.target import Target
from twitter.pants.graph.build_graph import BuildGraph


class Command(object):
  """Baseclass for all pants subcommands."""

  @staticmethod
  def get_command(name):
    return Command._commands.get(name, None)

  @staticmethod
  def all_commands():
    return Command._commands.keys()

  _commands = {}

  @classmethod
  def _register(cls):
    """Register a command class."""
    command_name = cls.__dict__.get('__command__', None)
    if command_name:
      Command._commands[command_name] = cls

  @staticmethod
  def scan_addresses(root_dir, base_path=None):
    """Parses all targets available in BUILD files under base_path and
    returns their addresses.  If no base_path is specified, root_dir is
    assumed to be the base_path"""

    addresses = OrderedSet()
    for buildfile in BuildFile.scan_buildfiles(root_dir, base_path):
      addresses.update(Target.get_all_addresses(buildfile))
    return addresses

  @classmethod
  def serialized(cls):
    return False

  def __init__(self, run_tracker, root_dir, parser, args):
    """run_tracker: The (already opened) RunTracker to track this run with
    root_dir: The root directory of the pants workspace
    parser: an OptionParser
    args: the subcommand arguments to parse"""
    self.run_tracker = run_tracker
    self.root_dir = root_dir

    # TODO(pl): Gross that we're doing a local import here, but this has dependendencies
    # way down into specific Target subclasses, and I'd prefer to make it explicit that this
    # import is in many ways similar to to third party plugin imports below.
    from twitter.pants.base.build_file_aliases import (target_aliases, object_aliases,
                                                       applicative_path_relative_util_aliases,
                                                       partial_path_relative_util_aliases)
    for alias, target_type in target_aliases.items():
      BuildFileParser.register_target_alias(alias, target_type)

    for alias, obj in object_aliases.items():
      BuildFileParser.register_exposed_object(alias, obj)

    for alias, util in applicative_path_relative_util_aliases.items():
      BuildFileParser.register_applicative_path_relative_util(alias, util)

    for alias, util in partial_path_relative_util_aliases.items():
      BuildFileParser.register_partial_path_relative_util(alias, util)

    config = Config.load()

    # TODO(pl): This is awful but I need something quick and dirty to support
    # injection of third party Targets and tools into BUILD file context
    plugins = config.getlist('plugins', 'entry_points', default=[])
    for entry_point_spec in plugins:
      module, entry_point = entry_point_spec.split(':')
      plugin_module = __import__(module, globals(), locals(), [entry_point], 0)
      getattr(plugin_module, entry_point)(config)

    self.build_file_parser = BuildFileParser(root_dir=self.root_dir, run_tracker=self.run_tracker)
    self.build_graph = BuildGraph(run_tracker=self.run_tracker)

    # Override the OptionParser's error with more useful output
    def error(message=None, show_help=True):
      if message:
        print(message + '\n')
      if show_help:
        parser.print_help()
      parser.exit(status=1)
    parser.error = error
    self.error = error

    self.setup_parser(parser, args)
    self.options, self.args = parser.parse_args(args)
    self.parser = parser

  def setup_parser(self, parser, args):
    """Subclasses should override and confiure the OptionParser to reflect
    the subcommand option and argument requirements.  Upon successful
    construction, subcommands will be able to access self.options and
    self.args."""

    pass

  def error(self, message=None, show_help=True):
    """Reports the error message, optionally followed by pants help, and then exits."""

  def run(self, lock):
    """Subcommands that are serialized() should override if they need the ability to interact with
    the global command lock.
    The value returned should be an int, 0 indicating success and any other value indicating
    failure."""
    return self.execute()

  def execute(self):
    """Subcommands that do not require serialization should override to perform the command action.
    The value returned should be an int, 0 indicating success and any other value indicating
    failure."""
    raise NotImplementedError('Either run(lock) or execute() must be over-ridden.')

  def cleanup(self):
    """Called on SIGINT (e.g., when the user hits ctrl-c).
    Subcommands may override to perform cleanup before exit."""
    pass
