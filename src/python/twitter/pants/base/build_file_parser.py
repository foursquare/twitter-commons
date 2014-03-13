from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
from copy import deepcopy
from functools import partial
import os.path

from twitter.common.python import compatibility

from twitter.pants.base.address import BuildFileAddress, parse_spec, SyntheticAddress
from twitter.pants.base.build_file import BuildFile

import logging
logger = logging.getLogger(__name__)


class TargetProxy(object):
  def __init__(self, target_type, build_file, args, kwargs):
    # Deep copy in case someone is being too tricky for their own good in their BUILD files.
    # kwargs = deepcopy(kwargs)

    assert 'name' in kwargs, (
      'name is a required parameter to all Target objects specified within a BUILD file.'
      '  Target type was: {target_type}.'
      '  Current BUILD file is: {build_file}.'
      .format(target_type=target_type,
              build_file=build_file))

    assert not args, (
      'All arguments passed to Targets within BUILD files should use explicit keyword syntax.'
      '  Target type was: {target_type}.'
      '  Current BUILD file is: {build_file}.'
      '  Arguments passed were: {args}'
      .format(target_type=target_type,
              build_file=build_file,
              args=args))

    assert 'build_file' not in kwargs, (
      'build_file cannot be passed as an explicit argument to a target within a BUILD file.'
      '  Target type was: {target_type}.'
      '  Current BUILD file is: {build_file}.'
      '  build_file argument passed was: {build_file_arg}'
      .format(target_type=target_type,
              build_file=build_file,
              build_file_arg=kwargs.get('build_file')))

    self.target_type = target_type
    self.build_file = build_file
    self.kwargs = kwargs
    self.dependencies = self.kwargs.pop('dependencies', [])
    self.name = kwargs['name']
    self.address = BuildFileAddress(build_file, self.name)

  def to_target(self, build_graph):
    return self.target_type(build_graph=build_graph, address=self.address, **self.kwargs)

  def __str__(self):
    format_str = ('<TargetProxy(target_type={target_type}, build_file={build_file})'
                  ' [name={name}, address={address}]>')
    return format_str.format(target_type=self.target_type,
                             build_file=self.build_file,
                             name=self.name,
                             address=self.address)

  def __repr__(self):
    format_str = 'TargetProxy(target_type={target_type}, build_file={build_file}, kwargs={kwargs})'
    return format_str.format(target_type=self.target_type,
                             build_file=self.build_file,
                             kwargs=self.kwargs)


class TargetCallProxy(object):
  def __init__(self, target_type, build_file, registered_target_proxies):
    self._target_type = target_type
    self._build_file = build_file
    self._registered_target_proxies = registered_target_proxies

  def __call__(self, *args, **kwargs):
    target_proxy = TargetProxy(self._target_type, self._build_file, args, kwargs)
    self._registered_target_proxies.add(target_proxy)

  def __repr__(self):
    return ('<TargetCallProxy(target_type={target_type}, build_file={build_file},'
            ' registered_target_proxies=<dict with id: {registered_target_proxies_id}>)>'
            .format(target_type=self._target_type,
                    build_file=self._build_file,
                    registered_target_proxies=id(self._registered_target_proxies)))


class BuildFileParser(object):
  _exposed_objects = {}
  _partial_path_relative_utils = {}
  _applicative_path_relative_utils = {}
  _target_alias_map = {}

  @classmethod
  def register_exposed_object(cls, alias, obj):
    if alias in cls._exposed_objects:
      logger.warn('Object alias {alias} has already been registered.  Overwriting!'
                  .format(alias=alias))
    cls._exposed_objects[alias] = obj

  @classmethod
  def register_applicative_path_relative_util(cls, alias, obj):
    if alias in cls._applicative_path_relative_utils:
      logger.warn('Applicative path relative util alias {alias} has already been registered.'
                  '  Overwriting!'
                  .format(alias=alias))
    cls._applicative_path_relative_utils[alias] = obj

  @classmethod
  def register_partial_path_relative_util(cls, alias, obj):
    if alias in cls._partial_path_relative_utils:
      logger.warn('Partial path relative util alias {alias} has already been registered.'
                  '  Overwriting!'
                  .format(alias=alias))
    cls._partial_path_relative_utils[alias] = obj

  @classmethod
  def register_target_alias(cls, alias, obj):
    if alias in cls._target_alias_map:
      logger.warn('Target alias {alias} has already been registered.  Overwriting!'
                  .format(alias=alias))
    cls._target_alias_map[alias] = obj

  def __init__(self, root_dir):
    self._root_dir = root_dir

    self._target_proxy_by_address = {}
    self._target_proxies_by_build_file = defaultdict(set)
    self._addresses_by_build_file = defaultdict(set)
    self._added_build_files = set()

  def inject_spec_closure_into_build_graph(self, spec, build_graph, addresses_already_closed=None):
    addresses_already_closed = addresses_already_closed or set()

    spec_path, target_name = parse_spec(spec)
    build_file = BuildFile(self._root_dir, spec_path)
    address = BuildFileAddress(build_file, target_name)

    self.populate_target_proxy_transitive_closure_for_spec(spec)
    target_proxy = self._target_proxy_by_address[address]

    def dependency_iter():
      for dep_spec in target_proxy.dependencies:
        dep_spec_path, dep_target_name = parse_spec(dep_spec,
                                                    relative_to=target_proxy.build_file.spec_path)
        dep_build_file = BuildFile(self._root_dir, dep_spec_path)
        dep_address = BuildFileAddress(dep_build_file, dep_target_name)
        yield dep_address

    if not build_graph.contains_address(address) and address not in addresses_already_closed:
      addresses_already_closed.add(address)
      dependency_addresses = frozenset(dependency_iter())
      for dep_address in dependency_addresses:
        self.inject_spec_closure_into_build_graph(dep_address.spec,
                                                  build_graph,
                                                  addresses_already_closed)
      target = target_proxy.to_target(build_graph)
      build_graph.inject_target(target, dependencies=dependency_addresses)

  def populate_target_proxy_transitive_closure_for_spec(self, spec, addresses_already_closed=None):
    '''
    Translates a spec into a BuildFileAddress, parses the BUILD file, then recurses over the
     dependency specs of the TargetProxy referred to by the caller.  This method is immune to
     cycles between either BUILD files or individual Targets, but it is also incapable of
     detecting them.
    '''

    addresses_already_closed = addresses_already_closed or set()

    spec_path, target_name = parse_spec(spec)
    build_file = BuildFile(self._root_dir, spec_path)
    address = BuildFileAddress(build_file, target_name)

    self.parse_build_file_family(build_file)

    addresses_already_closed.add(address)

    assert address in self._target_proxy_by_address, (
        '{address} from spec {spec} was not found in BUILD file {build_file}.'
        .format(address=address,
                spec=spec,
                build_file=build_file))

    target_proxy = self._target_proxy_by_address[address]
    for dependency_spec in target_proxy.dependencies:
      dep_spec_path, dep_target_name = parse_spec(dependency_spec,
                                                  relative_to=build_file.spec_path)
      dep_build_file = BuildFile(self._root_dir, dep_spec_path)
      dep_address = BuildFileAddress(dep_build_file, dep_target_name)
      if dep_address not in addresses_already_closed:
        self.populate_target_proxy_transitive_closure_for_spec(dep_address.spec,
                                                               addresses_already_closed)

  def parse_build_file_family(self, build_file):
    for bf in build_file.family():
      self.parse_build_file(bf)

  def parse_build_file(self, build_file): 
    '''
    Prepares a context for parsing, reads a BUILD file from the filesystem, and records the
     TargetProxies generated by executing the code.
    '''

    if build_file in self._added_build_files:
      logger.debug('BuildFile %s has already been parsed.' % build_file)
      return

    logger.debug("Parsing BUILD file %s." % build_file)
    with open(build_file.full_path, 'r') as build_file_fp:
      build_file_bytes = build_file_fp.read()

    parse_context = {}
    parse_context.update(self._exposed_objects)
    parse_context.update(dict((
      (key, partial(util, rel_path=build_file.spec_path)) for 
      key, util in self._partial_path_relative_utils.items()
    )))
    parse_context.update(dict((
      (key, util(rel_path=build_file.spec_path)) for 
      key, util in self._applicative_path_relative_utils.items()
    )))
    registered_target_proxies = set()
    parse_context.update(dict((
      (alias, TargetCallProxy(target_type=target_type,
                              build_file=build_file,
                              registered_target_proxies=registered_target_proxies)) for
      alias, target_type in self._target_alias_map.items()
    )))

    try:
      build_file_code = build_file.code()
    except Exception as e:
      logger.error("Error parsing {build_file}.  Exception was:\n {exception}"
                   .format(build_file=build_file, exception=e))
      raise e

    try:
      compatibility.exec_function(build_file_code, parse_context)
    except Exception as e:
      logger.error("Error running {build_file}.  Exception was:\n {exception}"
                   .format(build_file=build_file, exception=e))
      raise e

    for target_proxy in registered_target_proxies:
      logger.debug('Adding {target_proxy} to the proxy build graph with {address}'
                   .format(target_proxy=target_proxy,
                           address=target_proxy.address))

      assert target_proxy.address not in self._target_proxy_by_address, (
        '{address} already in BuildGraph._target_proxy_by_address even though this BUILD file has'
        ' not yet been added to the BuildGraph.  The target type is: {target_type}'
        .format(address=target_proxy.address,
                target_type=target_proxy.target_type))

      assert target_proxy.address not in self._addresses_by_build_file[build_file], (
        '{address} has already been associated with {build_file} in the build graph.'
        .format(address=target_proxy.address,
                build_file=self._addresses_by_build_file[build_file])
      )

      self._target_proxy_by_address[target_proxy.address] = target_proxy
      self._addresses_by_build_file[build_file].add(target_proxy.address)
      self._target_proxies_by_build_file[build_file].add(target_proxy)
    self._added_build_files.add(build_file)

    logger.debug("{build_file} produced the following TargetProxies:"
                 .format(build_file=build_file))
    for target_proxy in registered_target_proxies:
      logger.debug("  * {target_proxy}".format(target_proxy=target_proxy))

