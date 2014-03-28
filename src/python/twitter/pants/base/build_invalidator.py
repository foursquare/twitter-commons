# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

import errno
import hashlib
import itertools
import os

from abc import abstractmethod
from collections import namedtuple

from twitter.common.dirutil import safe_mkdir
from twitter.common.lang import Compatibility, Interface

from twitter.pants.base.hash_utils import hash_all
from twitter.pants.fs.fs import safe_filename
from twitter.pants.base.target import Target


# A CacheKey represents some version of a set of targets.
#  - id identifies the set of targets.
#  - hash is a fingerprint of all invalidating inputs to the build step, i.e., it uniquely
#    determines a given version of the artifacts created when building the target set.
#  - payloads is the list of Target Payloads used to compute this key

CacheKey = namedtuple('CacheKey', ['id', 'hash', 'payloads'])



# Bump this to invalidate all existing keys in artifact caches across all pants deployments in the world.
# Do this if you've made a change that invalidates existing artifacts, e.g.,  fixed a bug that
# caused bad artifacts to be cached.
GLOBAL_CACHE_KEY_GEN_VERSION = '6'

class CacheKeyGenerator(object):
  """Generates cache keys for versions of target sets."""

  @staticmethod
  def combine_cache_keys(cache_keys):
    """Returns a cache key for a list of target sets that already have cache keys.

    This operation is 'idempotent' in the sense that if cache_keys contains a single key
    then that key is returned.

    Note that this operation is commutative but not associative.  We use the term 'combine' rather
    than 'merge' or 'union' to remind the user of this. Associativity is not a necessary property,
    in practice.
    """
    if len(cache_keys) == 1:
      return cache_keys[0]
    else:
      combined_id = Target.maybe_readable_combine_ids(cache_key.id for cache_key in cache_keys)
      combined_hash = hash_all(sorted(cache_key.hash for cache_key in cache_keys))
      combined_payloads = sorted(list(itertools.chain(*[cache_key.payloads 
                                                        for cache_key in cache_keys])))
      return CacheKey(combined_id, combined_hash, combined_payloads)

  def __init__(self, cache_key_gen_version=None):
    """cache_key_gen_version - If provided, added to all cache keys. Allows you to invalidate all cache
                               keys in a single pants repo, by changing this value in config.
    """
    self._cache_key_gen_version = (cache_key_gen_version or '') + '_' + GLOBAL_CACHE_KEY_GEN_VERSION

  def key_for_target(self, target, transitive=False):
    """Get a key representing the given target and its sources.

    A key for a set of targets can be created by calling combine_cache_keys()
    on the target's individual cache keys.

    :target: The target to create a CacheKey for.
    :fingerprint_extra: A function that accepts a sha hash and updates it with extra fprint data.
    """

    hasher = hashlib.sha1()
    hasher.update(self._cache_key_gen_version)
    target.payload.invalidation_hash(hasher)
    if transitive:
      dep_hashes = [self.key_for_target(dep, transitive=True).hash
                    for dep in target.dependencies]
      for dep_hash in sorted(dep_hashes):
        hasher.update(dep_hash)
    return CacheKey(target.id, hasher.hexdigest(), (target.payload,))


# A persistent map from target set to cache key, which is a fingerprint of all
# the inputs to the current version of that target set. That cache key can then be used
# to look up build artifacts in an artifact cache.
class BuildInvalidator(object):
  """Invalidates build targets based on the SHA1 hash of source files and other inputs."""

  def __init__(self, root):
    self._root = os.path.join(root, GLOBAL_CACHE_KEY_GEN_VERSION)
    safe_mkdir(self._root)

  def needs_update(self, cache_key):
    """Check if the given cached item is invalid.

    :param cache_key: A CacheKey object (as returned by BuildInvalidator.key_for().
    :returns: True if the cached version of the item is out of date.
    """
    return self._read_sha(cache_key) != cache_key.hash

  def update(self, cache_key):
    """Makes cache_key the valid version of the corresponding target set.

    :param cache_key: A CacheKey object (typically returned by BuildInvalidator.key_for()).
    """
    self._write_sha(cache_key)

  def force_invalidate_all(self):
    """Force-invalidates all cached items."""
    safe_mkdir(self._root, clean=True)

  def force_invalidate(self, cache_key):
    """Force-invalidate the cached item."""
    try:
      os.unlink(self._sha_file(cache_key))
    except OSError as e:
      if e.errno != errno.ENOENT:
        raise

  def existing_hash(self, id):
    """Returns the existing hash for the specified id.

    Returns None if there is no existing hash for this id.
    """
    return self._read_sha_by_id(id)

  def _sha_file(self, cache_key):
    return self._sha_file_by_id(cache_key.id)

  def _sha_file_by_id(self, id):
    return os.path.join(self._root, safe_filename(id, extension='.hash'))

  def _write_sha(self, cache_key):
    with open(self._sha_file(cache_key), 'w') as fd:
      fd.write(cache_key.hash)

  def _read_sha(self, cache_key):
    return self._read_sha_by_id(cache_key.id)

  def _read_sha_by_id(self, id):
    try:
      with open(self._sha_file_by_id(id), 'rb') as fd:
        return fd.read().strip()
    except IOError as e:
      if e.errno != errno.ENOENT:
        raise
      return None  # File doesn't exist.
