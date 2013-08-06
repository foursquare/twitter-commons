import os
import shutil
import uuid

from twitter.common.dirutil import safe_mkdir, safe_rmtree, safe_mkdir_for
from twitter.pants.cache.artifact import TarballArtifact
from twitter.pants.cache.artifact_cache import ArtifactCache


class LocalArtifactCache(ArtifactCache):
  """An artifact cache that stores the artifacts in local files."""
  def __init__(self, log, artifact_root, cache_root, compress=True, copy_fn=None, read_only=False):
    """
    cache_root: The locally cached files are stored under this directory.
    copy_fn: An optional function with the signature copy_fn(absolute_src_path, relative_dst_path) that
        will copy cached files into the desired destination. If unspecified, a simple file copy is used.
    """
    ArtifactCache.__init__(self, log, artifact_root, read_only)
    self._cache_root = os.path.expanduser(cache_root)
    self._compress = compress

    def copy(src, rel_dst):
      dst = os.path.join(self.artifact_root, rel_dst)
      safe_mkdir_for(dst)
      shutil.copy(src, dst)

    self._copy_fn = copy_fn or copy
    safe_mkdir(self._cache_root)

  def try_insert(self, cache_key, paths):
    tarfile = self._cache_file_for_key(cache_key)
    safe_mkdir_for(tarfile)
    # Write to a temporary name (on the same filesystem), and move it atomically, so if we
    # crash in the middle we don't leave an incomplete or missing artifact.
    tarfile_tmp = tarfile + '.' + str(uuid.uuid4()) + '.tmp'
    if os.path.exists(tarfile_tmp):
      os.unlink(tarfile_tmp)

    artifact = TarballArtifact(self.artifact_root, tarfile_tmp, self._compress)
    artifact.collect(paths)
    # Note: Race condition here if multiple pants runs (in different workspaces)
    # try to write the same thing at the same time. However since rename is atomic,
    # this should not result in corruption. It may however result in a missing artifact
    # If we crash between the unlink and the rename. But that's OK.
    if os.path.exists(tarfile):
      os.unlink(tarfile)
    os.rename(tarfile_tmp, tarfile)

  def has(self, cache_key):
    return os.path.isdir(self._cache_dir_for_key(cache_key))

  def use_cached_files(self, cache_key):
    tarfile = self._cache_file_for_key(cache_key)
    if os.path.exists(tarfile):
      artifact = TarballArtifact(self.artifact_root, tarfile, self._compress)
      artifact.extract()
      return artifact
    else:
      return None

  def delete(self, cache_key):
    safe_rmtree(self._cache_dir_for_key(cache_key))

  def prune(self, age_hours):
    pass

  def _cache_dir_for_key(self, cache_key):
    # Note: it's important to use the id as well as the hash, because two different targets
    # may have the same hash if both have no sources, but we may still want to differentiate them.
    return os.path.join(self._cache_root, cache_key.id, cache_key.hash)

  def _cache_file_for_key(self, cache_key):
    # Note: it's important to use the id as well as the hash, because two different targets
    # may have the same hash if both have no sources, but we may still want to differentiate them.
    return os.path.join(self._cache_root, cache_key.id, cache_key.hash) + \
           '.tar.gz' if self._compress else '.tar'
